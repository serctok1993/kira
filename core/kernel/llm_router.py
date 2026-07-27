"""LLM-Router: ein Gateway fuer alle Modelle (Claude / DeepSeek / Ollama).

Cloud-first: Standard ist das in config.yaml gesetzte Modell pro Task-Typ.
Fehlt der noetige API-Key, faellt der Router automatisch auf das lokale
Ollama-Modell zurueck (0 EUR). Jeder Call wird als Event protokolliert
(Grundlage fuer den spaeteren ROI-Tracker).
"""
from __future__ import annotations

import concurrent.futures as _futures
import datetime
import json
import os
import re
import time

import httpx
import litellm

from core.config import CONFIG, outbound_blocked
from core.kernel import events

# Modellspezifisch nicht unterstuetzte Parameter still ignorieren (z.B. bei Ollama).
litellm.drop_params = True
litellm.suppress_debug_info = True  # kein "Provider List"-Rauschen

# --- Harte Wall-Clock-Wache um jeden LLM-Call ---------------------------------
# litellm's eigenes `timeout` beisst bei haengenden Provider-Sockets nicht immer
# hart (beobachtet: ein Cloud-Call hing ~8 Min, num_retries*timeout half nicht).
# Diese Wache fuehrt den Call in einem Thread aus und gibt nach einer harten
# Grenze die Kontrolle zurueck -> der Turn friert NICHT ein, sondern degradiert
# sauber. Der Turn-Watchdog bleibt nur letzter Rettungsanker.
_LLM_POOL = _futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="llm")


def _hard_cap_seconds() -> float:
    base = float(CONFIG["models"].get("request_timeout", 120))
    return float(CONFIG["models"].get("hard_call_timeout", base + 30))


def _completion(**kwargs):
    """litellm.completion mit harter Wall-Clock-Grenze. Wirft TimeoutError statt
    einen Turn minutenlang einzufrieren (der aufgegebene Call laeuft ggf. im
    Hintergrund aus, blockiert aber den Turn nicht mehr)."""
    cap = _hard_cap_seconds()
    fut = _LLM_POOL.submit(litellm.completion, **kwargs)
    try:
        return fut.result(timeout=cap)
    except _futures.TimeoutError:
        fut.cancel()
        raise TimeoutError(f"LLM-Call ueberschritt harte Wall-Clock-Grenze ({cap:.0f}s)") from None

# Reasoning-Modelle (Qwythos, Qwen3) denken in <think>...</think>. Das gehoert
# nicht in die sichtbare Antwort -> wir parsen es raus (Rohtext bleibt im Log).
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    if "<think>" in cleaned:  # offenes Tag ohne Abschluss
        cleaned = cleaned.split("<think>")[0].strip()
    cleaned = cleaned.replace("</think>", "").strip()
    return cleaned or text.strip()


_THINK_INNER_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _think_content(text: str) -> str:
    """Inverses zu _strip_think: liefert den INHALT der <think>-Bloecke — den Denk-Strom
    selbst, fuer ein SICHTBARES Reasoning (Cockpit + Telegram). Bei einem offenen Tag ohne
    Abschluss den Rest ab <think>. Modelle, die statt Inline-Tags ein dediziertes Feld
    (reasoning_content) liefern, werden separat in complete() gelesen."""
    inner = "\n".join(m.group(1).strip() for m in _THINK_INNER_RE.finditer(text))
    if not inner and "<think>" in text:
        inner = text.split("<think>", 1)[1].replace("</think>", "").strip()
    return inner.strip()


def _visible_from_raw(raw: str) -> str:
    """Fuer Streaming: sichtbarer Teil aus dem bisherigen Rohtext.

    Vollstaendige <think>-Bloecke werden entfernt; ein noch offenes <think>
    unterdrueckt alles ab dort (waehrend Kira 'denkt'). Monoton -> als Prefix
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
    "aimlapi": "AIMLAPI_API_KEY",
}

_PROVIDER_META = {
    "aimlapi": {"api_base": "https://api.aimlapi.com/v1", "key_env": "AIMLAPI_API_KEY"},
}

# Erkennt OpenRouter-402-Antworten wegen zu wenig Guthaben fuer die angeforderte
# max_tokens-Menge, z.B.: "...but can only afford 3035. To increase, visit..."
_AFFORD_RE = re.compile(r"can only afford (\d+)", re.IGNORECASE)


def _provider_config(model_id: str) -> tuple[str, str | None, str | None]:
    """Loest einen eigenen Provider-Alias auf.

    Rueckgabe: (litellm_modell, api_base, api_key_env). Fuer Standardmodelle
    (ollama/anthropic/...) bleibt es (model_id, None, None).
    """
    providers = CONFIG["models"].get("providers", {})
    if model_id in providers:
        p = providers[model_id]
        return p.get("model", model_id), p.get("api_base"), p.get("api_key_env")
    for prefix, meta in _PROVIDER_META.items():
        if model_id.startswith(prefix + "/"):
            stripped = model_id[len(prefix)+1:]
            return f"openai/{stripped}", meta["api_base"], meta["key_env"]
    return model_id, None, None


def _has_key(model: str) -> bool:
    real, _api_base, key_env = _provider_config(model)
    if key_env:  # eigener Provider -> dessen Env-Variable
        return bool(os.getenv(key_env))
    if model in CONFIG["models"].get("providers", {}):
        return True  # registrierter Endpunkt OHNE api_key_env = bewusst keyless (llama.cpp & Co.)
    provider = real.split("/", 1)[0]
    if provider.startswith("ollama"):
        return True  # lokal, kein Key noetig
    env = _PROVIDER_KEYS.get(provider)
    return bool(env and os.getenv(env))


# Oeffentlicher Alias, damit Chat-Befehl + API denselben Key-Check nutzen (nicht neu bauen).
def has_key(model: str) -> bool:
    """True, wenn fuer dieses Modell ein Provider-Key vorhanden ist (lokal immer True)."""
    return _has_key(model)


def _lokal_extra(real: str, api_base: str | None, key_env: str | None) -> dict:
    """litellm-Zusatzargumente fuer LOKALE Modelle im Streaming-Pfad: Ollama bekommt
    keep_alive/num_ctx, ein eigener Endpunkt (llama.cpp) api_base + (Dummy-)Key."""
    extra: dict = {}
    if real.startswith("ollama"):
        if CONFIG["models"].get("keep_alive") is not None:
            extra["keep_alive"] = CONFIG["models"]["keep_alive"]
        if CONFIG["models"].get("num_ctx") is not None:
            extra["num_ctx"] = CONFIG["models"]["num_ctx"]
    if api_base:
        extra["api_base"] = api_base
        extra["api_key"] = os.getenv(key_env) if key_env else "sk-lokal"
    return extra


def ist_lokal(model_id: str) -> bool:
    """Laeuft dieses Modell auf DIESEM Rechner? (Ollama ODER registrierter Endpunkt
    auf 127.0.0.1/localhost — z.B. der llama.cpp-Nachtdenker.)

    Steuert die Chat-Weiche: lokale Modelle fahren den ACT-Pfad mit dem schlanken
    haupt-Manifest. 35B-Premiere 22.07.: der Cloud-Pfad schickte dem lokalen
    Endpunkt 17,7k Token (volle Schema-Flotte) — Prefill riss die 150s-Wall-Clock;
    dasselbe Modell antwortete roh in 7s."""
    real, api_base, _ke = _provider_config(model_id)
    if real.startswith("ollama"):
        return True
    return bool(api_base and ("127.0.0.1" in api_base or "localhost" in api_base))


# Sichtbarkeit statt stillem Fallback: EIN Event pro (task, gewuenscht), gedrosselt,
# damit der heisse Pfad (jeder complete/stream) nicht spammt.
_FALLBACK_SEEN: dict[tuple[str, str], float] = {}
_FALLBACK_THROTTLE_S = 300.0


def _note_fallback(task_type: str, wanted: str | None, used: str) -> None:
    key = (task_type, str(wanted))
    now = time.time()
    if now - _FALLBACK_SEEN.get(key, 0.0) > _FALLBACK_THROTTLE_S:
        _FALLBACK_SEEN[key] = now
        try:
            events.emit("model_fallback",
                        {"task_type": task_type, "wanted": wanted, "used": used, "reason": "missing_key"})
        except Exception:  # noqa: BLE001 — Sichtbarkeit darf den Aufruf nie brechen
            pass


_REASON_MARKERS = [str(m).lower() for m in
                   (CONFIG.get("models", {}).get("reasoning_markers")
                    or ["glm", "anthropic", "claude", "fable", "qwen3"])]
_REASON_EFFORT = {"aus": "minimal", "off": "minimal", "niedrig": "low", "low": "low",
                  "mittel": "medium", "medium": "medium", "hoch": "high", "high": "high"}


def is_reasoning_model(model_id: str) -> bool:
    """Kann dieses Modell 'denken' (extended reasoning)? Katalog-Fakt zuerst (OpenRouter
    meldet die Faehigkeit pro Modell live mit, siehe models.reasoning_ids), Marker nur
    noch als Fallback fuer lokale/Provider-Modelle ausserhalb des Katalogs.
    Live-Fund 20.07.: DeepSeek R1 stand als 'kein Reasoning' im Picker — die alte
    Marker-Liste kannte nur glm/anthropic/claude/fable/qwen3."""
    m = (model_id or "").lower()
    if any(mk in m for mk in _REASON_MARKERS):
        return True
    try:
        from core.kernel import models as _models
        return model_id in _models.reasoning_ids()
    except Exception:  # noqa: BLE001 — Katalog-Luecke darf keinen LLM-Call brechen
        return False


def _reasoning_extra(model_id: str, level: str | None) -> dict:
    """OpenRouter/litellm-Reasoning-Parameter — NUR fuer denk-faehige Modelle, sonst leer.
    litellm.drop_params=True verwirft ihn ohnehin still bei Modellen ohne Reasoning."""
    if not level:
        return {}
    eff = _REASON_EFFORT.get(str(level).strip().lower())
    if not eff or not is_reasoning_model(model_id):
        return {}
    return {"reasoning_effort": eff}


def resolve_model(task_type: str = "default", escalate: bool = False) -> tuple[str, bool]:
    """Gibt (modell_id, fell_back) zurueck.

    escalate=True -> der Agent haelt die Aufgabe fuer wuerdig: Cloud-Modell, sofern
    ein Key vorhanden ist. Ohne Key faellt es sauber auf lokal zurueck (und meldet das,
    damit der Wechsel nie STILL verpufft — siehe model_fallback-Event).
    """
    models = CONFIG["models"]
    # Benchmark-Direktwahl: KIRA_FORCE_MODEL (nur in Bench-Subprozessen gesetzt) schlaegt
    # ALLE Rollen — so testet der Nutzer jedes beliebige Modell (auch kuenftige OpenRouter-IDs)
    # auf dem Harness, ohne die Live-Rollen zu verstellen. Budget/Firewall greifen weiter.
    forced = os.getenv("KIRA_FORCE_MODEL")
    if forced:
        return forced, False
    if escalate:
        target = models.get("escalation_model")
        if target and _has_key(target):
            return target, False
        _note_fallback(task_type, target, models["local_fallback"])
        return models["local_fallback"], True
    routing = models.get("routing", {})
    chosen = routing.get(task_type, models["default"])
    if _has_key(chosen):
        return chosen, False
    _note_fallback(task_type, chosen, models["local_fallback"])
    return models["local_fallback"], True


_OR_PRICES: dict | None = None


def _openrouter_prices() -> dict:
    """OpenRouter-Preise (USD pro Token) je Modell, einmal gecacht."""
    global _OR_PRICES
    if _OR_PRICES is None:
        _OR_PRICES = {}
        try:
            data = httpx.get("https://openrouter.ai/api/v1/models", timeout=15).json().get("data", [])
            for m in data:
                pr = m.get("pricing") or {}
                _OR_PRICES[m["id"]] = (float(pr.get("prompt", 0) or 0), float(pr.get("completion", 0) or 0))
        except Exception:
            _OR_PRICES = {}
    return _OR_PRICES


def _estimate_or_cost(real_model: str, tokens: dict | None) -> float:
    if not real_model.startswith("openrouter/") or not tokens:
        return 0.0
    mid = real_model.split("/", 1)[1]
    p_in, p_out = _openrouter_prices().get(mid, (0.0, 0.0))
    return (tokens.get("prompt") or 0) * p_in + (tokens.get("completion") or 0) * p_out


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
    tools: list | None = None,
    reasoning: str | None = None,
    model: str | None = None,
) -> dict:
    """Fuehrt einen Chat-Completion-Call aus und protokolliert ihn.

    escalate=True bittet um das Cloud-Modell. Eine harte Tagesbudget-Bremse
    setzt die Eskalation zurueck auf lokal, sobald das Limit erreicht ist.
    model=... (Benchmark-Direktwahl) schlaegt die Rollen-Aufloesung — Budget-
    Bremse und Firewall gelten trotzdem.

    Rueckgabe: {text, model, cost_usd, fell_back, latency_s, escalated}
    """
    if escalate:
        from core.governance import treasury  # lazy -> kein Import-Zyklus

        ok, why = treasury.can_spend(0.0)  # schon am Limit? -> keine Cloud mehr
        if not ok:
            events.emit("budget_block", {"reason": why, "spent_usd": round(treasury.today_spend(), 4)}, session_id=session_id)
            escalate = False  # zurueck auf lokal -> 0 EUR

    if model:
        fell_back = False
    else:
        model, fell_back = resolve_model(task_type, escalate=escalate)
    # Firewall (Benchmark/Sandbox): kein Cloud-Spend. Erzwinge das lokale 0-EUR-Modell (liefert
    # trotzdem Output), ausser KIRA_ALLOW_LLM ist bewusst gesetzt. Standard aus -> Live unveraendert.
    if outbound_blocked() and not os.getenv("KIRA_ALLOW_LLM") and not model.startswith("ollama"):
        model = CONFIG["models"]["local_fallback"]
        fell_back = True
    real, api_base, key_env = _provider_config(model)

    # Budget-Bremse fuer ALLE Cloud-Calls (nicht nur eskalierte) -> 24/7 kann nie ueberziehen.
    if not real.startswith("ollama"):
        from core.governance import treasury

        ok, why = treasury.can_spend(0.0)
        if not ok:
            events.emit("budget_block", {"reason": why, "model": model,
                        "spent_usd": round(treasury.today_spend(), 4)}, session_id=session_id)
            model = CONFIG["models"]["local_fallback"]  # -> lokal, 0 EUR, laeuft weiter
            real, api_base, key_env = _provider_config(model)
            fell_back = True

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
    elif api_base:
        # Registrierter keyless Endpunkt (llama.cpp & Co.): der Server verlangt keinen
        # Key, aber litellm besteht bei openai/-Modellen auf einem -> Platzhalter.
        extra["api_key"] = "sk-lokal"
    if tools:
        extra["tools"] = tools
    extra.update(_reasoning_extra(real, reasoning))   # Denk-Tiefe -> nur bei denk-faehigen Modellen

    want_max_tokens = CONFIG["models"].get("max_tokens", 2048)

    t0 = time.time()
    try:
        resp = _completion(
            model=real,
            messages=msgs,
            temperature=CONFIG["models"].get("temperature", 0.7),
            max_tokens=want_max_tokens,
            num_retries=2,
            timeout=CONFIG["models"].get("request_timeout", 120),  # hartes Timeout -> kein Einfrieren
            **extra,
        )
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        # OpenRouter-402: zu wenig Guthaben fuer die angeforderte max_tokens-Menge.
        # Statt hart zu crashen (das reisst z.B. den Heartbeat in eine Fehler-Schleife):
        # EINMAL automatisch mit der leistbaren Tokenzahl erneut versuchen.
        m = _AFFORD_RE.search(msg)
        if "credits" in msg.lower() and "afford" in msg.lower() and m:
            affordable = max(256, int(m.group(1)) - 50)
            retry_max_tokens = min(want_max_tokens, affordable)
            try:
                resp = _completion(
                    model=real,
                    messages=msgs,
                    temperature=CONFIG["models"].get("temperature", 0.7),
                    max_tokens=retry_max_tokens,
                    num_retries=2,
                    timeout=CONFIG["models"].get("request_timeout", 120),
                    **extra,
                )
                events.emit("llm_call_retry", {"model": model, "reason": "credits",
                            "orig_max_tokens": want_max_tokens, "retry_max_tokens": retry_max_tokens},
                            session_id=session_id)
            except Exception as e2:  # noqa: BLE001
                events.emit("llm_call_error", {"error": str(e2)[:300], "model": model}, session_id=session_id)
                raise
        elif (("not a valid model" in msg.lower() or "no endpoints found" in msg.lower())
              and not real.startswith("ollama")):
            # Vertipptes/ungueltiges Cloud-Modell (z.B. 400 "glm/glm-5.2 is not a valid model ID"):
            # EINMAL aufs lokale Fallback ausweichen, statt den ganzen Chat abzuschiessen — sonst
            # tickt JEDER Aufruf einen harten Fehler hoch (hunderte 400er) und der Chat bleibt tot.
            fb = CONFIG["models"]["local_fallback"]
            fb_real, fb_base, fb_key = _provider_config(fb)
            fb_extra: dict = {}
            if fb_real.startswith("ollama"):
                if CONFIG["models"].get("keep_alive") is not None:
                    fb_extra["keep_alive"] = CONFIG["models"]["keep_alive"]
                if CONFIG["models"].get("num_ctx") is not None:
                    fb_extra["num_ctx"] = CONFIG["models"]["num_ctx"]
            if fb_base:
                fb_extra["api_base"] = fb_base
            if fb_key:
                fb_extra["api_key"] = os.getenv(fb_key)
            if tools:
                fb_extra["tools"] = tools
            events.emit("model_invalid_fallback", {"bad_model": model, "used": fb, "error": msg[:200]},
                        session_id=session_id)
            try:
                resp = _completion(model=fb_real, messages=msgs,
                                   temperature=CONFIG["models"].get("temperature", 0.7),
                                   max_tokens=want_max_tokens, num_retries=1,
                                   timeout=CONFIG["models"].get("request_timeout", 120), **fb_extra)
                model, real, fell_back = fb, fb_real, True
            except Exception as e2:  # noqa: BLE001
                events.emit("llm_call_error", {"error": str(e2)[:300], "model": fb}, session_id=session_id)
                raise
        else:
            kind = "llm_call_timeout" if isinstance(e, TimeoutError) else "llm_call_error"
            events.emit(kind, {"error": msg[:300], "model": model}, session_id=session_id)
            raise
    latency = time.time() - t0

    message = resp.choices[0].message
    raw_text = message.content or ""
    text = _strip_think(raw_text)
    had_think = text != raw_text

    # Sichtbares Reasoning: Denk-Modelle liefern ihren Gedankenstrom entweder im dedizierten
    # Feld (reasoning_content — so normalisiert litellm OpenRouter/GLM) ODER inline als
    # <think>...</think> im content. Beides einfangen -> Cockpit und Telegram koennen das
    # echte Denken zeigen, statt eines leeren „nachdenken…"-Pulses.
    reasoning = (getattr(message, "reasoning_content", None)
                 or getattr(message, "reasoning", None) or "")
    if not reasoning and had_think:
        reasoning = _think_content(raw_text)
    reasoning = reasoning.strip() or None

    tool_calls: list[dict] = []
    for c in (getattr(message, "tool_calls", None) or []):
        try:
            args = json.loads(c.function.arguments or "{}")
        except Exception:  # noqa: BLE001
            args = {}
        tool_calls.append({"id": getattr(c, "id", None), "name": c.function.name,
                           "args": args if isinstance(args, dict) else {}})

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

    if cost == 0.0:  # litellm kennt z.B. OpenRouter-Preise oft nicht -> selbst schaetzen
        cost = _estimate_or_cost(real, tokens)

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
        "tool_calls": tool_calls,
        "reasoning": reasoning,
    }


def stream(messages, system=None, task_type="chat", session_id=None, escalate=False,
           reasoning=None, model=None):
    """Streamt die sichtbare Antwort als Text-Deltas (Generator).

    Lokale Modelle werden tokenweise gestreamt, mit Live-<think>-Filter.
    Cloud-Calls laufen ueber complete() (sauberes Kosten-Logging) und werden als
    ein Block ausgegeben.

    `model` fehlte in der Signatur, obwohl die erste Zeile des Rumpfs es abfragt —
    jeder Aufruf endete mit UnboundLocalError (Befund 27.07.). stream_tagged hat den
    Parameter seit jeher; hier war er beim Angleichen verlorengegangen.
    """
    if model:
        fell_back = False
    else:
        model, fell_back = resolve_model(task_type, escalate=escalate)
    real, api_base, key_env = _provider_config(model)

    if not ist_lokal(model):
        # Cloud -> ueber complete() (sauberes Kosten-Logging), als ein Block
        res = complete(messages, system=system, task_type=task_type, session_id=session_id,
                       escalate=escalate, reasoning=reasoning)
        yield res["text"]
        return

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    extra: dict = _lokal_extra(real, api_base, key_env)

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


def stream_tagged(messages, system=None, task_type="chat", session_id=None, escalate=False,
                  reasoning=None, model=None):
    """Wie stream(), aber getaggt: yields {"kind": "think"|"answer", "text": delta}.

    Fuer das Dashboard, das Kiras Denken live sichtbar machen soll. Lokale Modelle
    werden tokenweise getaggt; Cloud/Provider laufen ueber complete() (ein answer-Block).
    model: optionale Direktwahl (Benchmark/Chat-Chip) — sonst entscheidet der Router.
    Fix 09.07.: 'model' fehlte in der Signatur (Benchmark-Commit) -> UnboundLocalError,
    JEDER lokale Chat brach mit '(Fehler: cannot access local variable model)' ab."""
    if model:
        fell_back = False
    else:
        model, fell_back = resolve_model(task_type, escalate=escalate)
    real, api_base, key_env = _provider_config(model)

    if not ist_lokal(model):
        res = complete(messages, system=system, task_type=task_type, session_id=session_id,
                       escalate=escalate, reasoning=reasoning)
        yield {"kind": "answer", "text": res["text"]}
        return

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    extra: dict = _lokal_extra(real, api_base, key_env)

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
