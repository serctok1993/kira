"""LLM-Router: ein Gateway fuer alle Modelle (Claude / DeepSeek / Ollama).

Cloud-first: Standard ist das in config.yaml gesetzte Modell pro Task-Typ.
Fehlt der noetige API-Key, faellt der Router automatisch auf das lokale
Ollama-Modell zurueck (0 EUR). Jeder Call wird als Event protokolliert
(Grundlage fuer den spaeteren ROI-Tracker).
"""
from __future__ import annotations

import datetime
import os
import re
import time

import litellm

from core.config import CONFIG
from core.kernel import events

# Modellspezifisch nicht unterstuetzte Parameter still ignorieren (z.B. bei Ollama).
litellm.drop_params = True

# Reasoning-Modelle (Qwythos, Qwen3) denken in <think>...</think>. Das gehoert
# nicht in die sichtbare Antwort -> wir parsen es raus (Rohtext bleibt im Log).
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    if "<think>" in cleaned:  # offenes Tag ohne Abschluss
        cleaned = cleaned.split("<think>")[0].strip()
    cleaned = cleaned.replace("</think>", "").strip()
    return cleaned or text.strip()


def _visible_from_raw(raw: str) -> str:
    """Fuer Streaming: sichtbarer Teil aus dem bisherigen Rohtext.

    Vollstaendige <think>-Bloecke werden entfernt; ein noch offenes <think>
    unterdrueckt alles ab dort (waehrend Kyros 'denkt'). Monoton -> als Prefix
    nutzbar, um nur das jeweils Neue auszugeben.
    """
    s = _THINK_RE.sub("", raw)
    idx = s.find("<think>")
    if idx != -1:
        s = s[:idx]
    return s


def _think_portion(raw: str) -> str:
    """Fuer das Dashboard: der bisherige DENK-Anteil (Inhalt der <think>-Bloecke).

    Konkateniert abgeschlossene Bloecke + einen evtl. offenen. Waechst monoton.
    """
    parts = re.findall(r"<think>(.*?)</think>", raw, re.DOTALL)
    s = "".join(parts)
    open_idx = raw.rfind("<think>")
    close_idx = raw.rfind("</think>")
    if open_idx != -1 and open_idx > close_idx:
        s += raw[open_idx + len("<think>"):]
    return s

# Bekannte Anbieter -> Name der Env-Variable mit dem Key.
# OpenRouter ist der "universelle" Anbieter: EIN Key, hunderte Modelle aller Firmen.
_PROVIDER_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",   # universell, kein Lock-in
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _provider_config(model_id: str) -> tuple[str, str | None, str | None]:
    """Loest einen eigenen Provider-Alias auf.

    Rueckgabe: (litellm_modell, api_base, api_key_env). Fuer Standardmodelle
    (ollama/anthropic/...) bleibt es (model_id, None, None).
    """
    providers = CONFIG["models"].get("providers", {})
    if model_id in providers:
        p = providers[model_id]
        return p.get("model", model_id), p.get("api_base"), p.get("api_key_env")
    return model_id, None, None


def _has_key(model: str) -> bool:
    real, _api_base, key_env = _provider_config(model)
    if key_env:  # eigener Provider -> dessen Env-Variable
        return bool(os.getenv(key_env))
    provider = real.split("/", 1)[0]
    if provider.startswith("ollama"):
        return True  # lokal, kein Key noetig
    env = _PROVIDER_KEYS.get(provider)
    return bool(env and os.getenv(env))


def resolve_model(task_type: str = "default", escalate: bool = False) -> tuple[str, bool]:
    """Gibt (modell_id, fell_back) zurueck.

    escalate=True -> der Agent haelt die Aufgabe fuer wuerdig: Cloud-Modell, sofern
    ein Key vorhanden ist. Ohne Key faellt es sauber auf lokal zurueck.
    """
    models = CONFIG["models"]
    if escalate:
        target = models.get("escalation_model")
        if target and _has_key(target):
            return target, False
        return models["local_fallback"], True
    routing = models.get("routing", {})
    chosen = routing.get(task_type, models["default"])
    if _has_key(chosen):
        return chosen, False
    return models["local_fallback"], True


def today_spend_usd() -> float:
    """Summe der LLM-Kosten seit lokaler Mitternacht (Grundlage der Budget-Bremse)."""
    start = (
        datetime.datetime.now()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    total = 0.0
    for e in events.recent(2000):
        if e["ts"] >= start and e["type"] == "llm_call":
            total += float(e["payload"].get("cost_usd") or 0.0)
    return total


def complete(
    messages: list[dict],
    system: str | None = None,
    task_type: str = "chat",
    session_id: str | None = None,
    escalate: bool = False,
) -> dict:
    """Fuehrt einen Chat-Completion-Call aus und protokolliert ihn.

    escalate=True bittet um das Cloud-Modell. Eine harte Tagesbudget-Bremse
    setzt die Eskalation zurueck auf lokal, sobald das Limit erreicht ist.

    Rueckgabe: {text, model, cost_usd, fell_back, latency_s, escalated}
    """
    if escalate:
        from core.governance import treasury  # lazy -> kein Import-Zyklus

        ok, why = treasury.can_spend(0.0)  # schon am Limit? -> keine Cloud mehr
        if not ok:
            events.emit("budget_block", {"reason": why, "spent_usd": round(treasury.today_spend(), 4)}, session_id=session_id)
            escalate = False  # zurueck auf lokal -> 0 EUR

    model, fell_back = resolve_model(task_type, escalate=escalate)
    real, api_base, key_env = _provider_config(model)

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    extra: dict = {}
    if real.startswith("ollama"):
        keep_alive = CONFIG["models"].get("keep_alive")
        if keep_alive is not None:
            extra["keep_alive"] = keep_alive  # Modell im VRAM halten (Ollama)
        num_ctx = CONFIG["models"].get("num_ctx")
        if num_ctx is not None:
            extra["num_ctx"] = num_ctx  # groesseres Kontextfenster (Ollama)
    if api_base:
        extra["api_base"] = api_base
    if key_env:
        extra["api_key"] = os.getenv(key_env)

    t0 = time.time()
    resp = litellm.completion(
        model=real,
        messages=msgs,
        temperature=CONFIG["models"].get("temperature", 0.7),
        max_tokens=CONFIG["models"].get("max_tokens", 2048),
        num_retries=2,
        **extra,
    )
    latency = time.time() - t0

    raw_text = resp.choices[0].message.content or ""
    text = _strip_think(raw_text)
    had_think = text != raw_text

    try:
        cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
    except Exception:
        cost = 0.0

    usage = getattr(resp, "usage", None)
    tokens = None
    if usage is not None:
        tokens = {
            "prompt": getattr(usage, "prompt_tokens", None),
            "completion": getattr(usage, "completion_tokens", None),
        }

    events.emit(
        "llm_call",
        {
            "model": model,
            "task_type": task_type,
            "escalated": escalate,
            "fell_back": fell_back,
            "had_think": had_think,
            "cost_usd": round(cost, 6),
            "latency_s": round(latency, 2),
            "tokens": tokens,
        },
        session_id=session_id,
    )

    return {
        "text": text,
        "model": model,
        "cost_usd": cost,
        "fell_back": fell_back,
        "latency_s": latency,
        "escalated": escalate,
    }


def stream(messages, system=None, task_type="chat", session_id=None, escalate=False):
    """Streamt die sichtbare Antwort als Text-Deltas (Generator).

    Lokale Modelle werden tokenweise gestreamt, mit Live-<think>-Filter.
    Cloud-Calls laufen ueber complete() (sauberes Kosten-Logging) und werden als
    ein Block ausgegeben.
    """
    model, fell_back = resolve_model(task_type, escalate=escalate)
    real, _api_base, _key_env = _provider_config(model)

    if not real.startswith("ollama"):
        # Cloud/eigener Provider -> ueber complete() (sauberes Kosten-Logging), als ein Block
        res = complete(messages, system=system, task_type=task_type, session_id=session_id, escalate=escalate)
        yield res["text"]
        return

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    extra: dict = {}
    if CONFIG["models"].get("keep_alive") is not None:
        extra["keep_alive"] = CONFIG["models"]["keep_alive"]
    if CONFIG["models"].get("num_ctx") is not None:
        extra["num_ctx"] = CONFIG["models"]["num_ctx"]

    t0 = time.time()
    resp = litellm.completion(
        model=real,
        messages=msgs,
        temperature=CONFIG["models"].get("temperature", 0.7),
        max_tokens=CONFIG["models"].get("max_tokens", 2048),
        stream=True,
        **extra,
    )

    raw = ""
    shown = ""
    for chunk in resp:
        try:
            delta = chunk.choices[0].delta.content or ""
        except (AttributeError, IndexError):
            delta = ""
        if not delta:
            continue
        raw += delta
        vis = _visible_from_raw(raw)
        if len(vis) > len(shown) and vis.startswith(shown):
            new = vis[len(shown):]
            shown = vis
            yield new
        elif vis != shown:
            shown = vis  # seltene Divergenz -> still resynchronisieren

    if not shown.strip():  # nur <think> kam, keine Antwort -> Fallback
        fb = raw.strip()
        if fb:
            yield fb

    events.emit(
        "llm_call",
        {
            "model": model,
            "task_type": task_type,
            "escalated": False,
            "fell_back": fell_back,
            "had_think": "<think>" in raw,
            "cost_usd": 0.0,
            "latency_s": round(time.time() - t0, 2),
            "streamed": True,
        },
        session_id=session_id,
    )


def stream_tagged(messages, system=None, task_type="chat", session_id=None, escalate=False):
    """Wie stream(), aber getaggt: yields {"kind": "think"|"answer", "text": delta}.

    Fuer das Dashboard, das Kyros' Denken live sichtbar machen soll. Lokale Modelle
    werden tokenweise getaggt; Cloud/Provider laufen ueber complete() (ein answer-Block).
    """
    model, fell_back = resolve_model(task_type, escalate=escalate)
    real, _api_base, _key_env = _provider_config(model)

    if not real.startswith("ollama"):
        res = complete(messages, system=system, task_type=task_type, session_id=session_id, escalate=escalate)
        yield {"kind": "answer", "text": res["text"]}
        return

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    extra: dict = {}
    if CONFIG["models"].get("keep_alive") is not None:
        extra["keep_alive"] = CONFIG["models"]["keep_alive"]
    if CONFIG["models"].get("num_ctx") is not None:
        extra["num_ctx"] = CONFIG["models"]["num_ctx"]

    t0 = time.time()
    resp = litellm.completion(
        model=real,
        messages=msgs,
        temperature=CONFIG["models"].get("temperature", 0.7),
        max_tokens=CONFIG["models"].get("max_tokens", 2048),
        stream=True,
        **extra,
    )

    raw = ""
    shown_think = ""
    shown_answer = ""
    for chunk in resp:
        try:
            delta = chunk.choices[0].delta.content or ""
        except (AttributeError, IndexError):
            delta = ""
        if not delta:
            continue
        raw += delta
        think_part = _think_portion(raw)
        answer_part = _visible_from_raw(raw)
        if len(think_part) > len(shown_think) and think_part.startswith(shown_think):
            yield {"kind": "think", "text": think_part[len(shown_think):]}
            shown_think = think_part
        if len(answer_part) > len(shown_answer) and answer_part.startswith(shown_answer):
            yield {"kind": "answer", "text": answer_part[len(shown_answer):]}
            shown_answer = answer_part

    if not shown_answer.strip():  # nur <think> kam -> Fallback
        fb = raw.strip()
        if fb:
            yield {"kind": "answer", "text": fb}

    events.emit(
        "llm_call",
        {"model": model, "task_type": task_type, "fell_back": fell_back,
         "had_think": "<think>" in raw, "cost_usd": 0.0,
         "latency_s": round(time.time() - t0, 2), "streamed": True},
        session_id=session_id,
    )
