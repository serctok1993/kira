"""Modell-Verwaltung: LLMs zur Laufzeit austauschen + eigene API-Provider anlegen.

Vorstufe zum Ziel "eigenes LLM trainieren": ein selbst trainiertes Modell haengst
du spaeter einfach als weiteres Ollama-Modell oder als API-Provider hier ein.

Aenderungen landen in data/models.json (Laufzeit-Override) und werden sofort
auf die laufende CONFIG angewendet. config.yaml (mit Kommentaren) bleibt unberuehrt.

CLI:
  uv run python -m core.kernel.models list
  uv run python -m core.kernel.models use <modell-id-oder-alias>
  uv run python -m core.kernel.models add <alias> <litellm-modell> <api_base> <API_KEY_ENV>
"""
from __future__ import annotations

import json
import os
import sys

import httpx

from core.config import CONFIG, DATA_DIR, apply_model_overrides
from core.kernel.llm_router import _PROVIDER_KEYS
from core.kernel.fs import atomic_write

OVERRIDE = DATA_DIR / "models.json"
_MAIN_SCOPES = ("chat", "reason", "bulk")  # diese Routing-Pfade folgen dem Default


def _load() -> dict:
    if OVERRIDE.exists():
        try:
            return json.loads(OVERRIDE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(d: dict) -> None:
    atomic_write(OVERRIDE, json.dumps(d, indent=2, ensure_ascii=False))


def ollama_models() -> list[str]:
    """Lokal in Ollama verfuegbare Modelle (best effort)."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def aimlapi_models() -> list[dict]:
    """Modelle von AIMLAPI (https://aimlapi.com) – nur Chat-Modelle, ohne Key.

    Der /v1/models-Endpoint ist public; Antwort-Layout (Verkürzt):
    {
      "data": [
        {
          "id": "openai/gpt-4o",
          "info": {
            "name": "GPT-4o",
            "contextLength": 128000,
            "features": ["openai/chat-completion", ...]
          },
          "type": "openai/chat-completions"
        }
      ]
    }
    """
    try:
        r = httpx.get("https://api.aimlapi.com/v1/models", timeout=5)
        data = r.json().get("data", []) if isinstance(r.json(), dict) else []
    except Exception:
        return []
    models = []
    for m in data:
        m_type = (m.get("type") or "").lower()
        if not m_type.endswith("chat-completions"):
            continue
        info = m.get("info") or {}
        models.append({
            "id": "aimlapi/" + (m.get("id") or ""),
            "name": info.get("name") or m.get("id") or "",
            "in": 0,
            "out": 0,
            "ctx": info.get("contextLength"),
        })
    return models


def set_model(model_id: str, scope: str = "default") -> str:
    """Aktives Modell setzen. scope='default' setzt auch chat/reason/bulk."""
    d = _load()
    if scope == "default":
        d["default"] = model_id
        routing = d.setdefault("routing", {})
        for s in _MAIN_SCOPES:
            routing[s] = model_id
    else:
        d.setdefault("routing", {})[scope] = model_id
    _save(d)
    apply_model_overrides(d)  # sofort live
    _history_merken(model_id)
    return model_id


def add_openrouter(model_id: str) -> str:
    """OpenRouter = universeller Anbieter: EIN Key (OPENROUTER_API_KEY) -> jedes Modell.

    Beispiel model_id: 'anthropic/claude-opus-4-8', 'google/gemini-2.5-pro',
    'meta-llama/llama-3.1-70b-instruct', 'deepseek/deepseek-chat'.
    Setzt das aktive Modell auf 'openrouter/<model_id>'.
    """
    return set_model(f"openrouter/{model_id.lstrip('/')}")


def add_provider(alias: str, model: str, api_base: str, api_key_env: str) -> dict:
    """Eigenen API-Provider registrieren (OpenAI-kompatibel via litellm).

    alias         : Kurzname, den du danach mit 'use' setzen kannst
    model         : litellm-Modell-ID, z.B. 'openai/gpt-4o' oder 'openai/mein-modell'
    api_base      : Basis-URL der API (z.B. https://api.xyz.com/v1)
    api_key_env   : Name der Env-Variable in .env mit dem Schluessel (z.B. XYZ_API_KEY)
    """
    d = _load()
    d.setdefault("providers", {})[alias] = {
        "model": model,
        "api_base": api_base,
        "api_key_env": api_key_env,
    }
    _save(d)
    apply_model_overrides(d)
    return d["providers"][alias]


def set_params(num_ctx: int | None = None, max_tokens: int | None = None,
               temperature: float | None = None, keep_alive: str | None = None) -> dict:
    """Kontext / max. Tokens / Temperatur / keep_alive zur Laufzeit setzen (persistiert, sofort live)."""
    d = _load()
    if num_ctx is not None:
        d["num_ctx"] = int(num_ctx)
    if max_tokens is not None:
        d["max_tokens"] = int(max_tokens)
    if temperature is not None:
        d["temperature"] = float(temperature)
    if keep_alive is not None:
        d["keep_alive"] = str(keep_alive)
    _save(d)
    apply_model_overrides(d)
    mm = CONFIG["models"]
    return {"num_ctx": mm.get("num_ctx"), "max_tokens": mm.get("max_tokens"),
            "temperature": mm.get("temperature"), "keep_alive": mm.get("keep_alive")}


_CATALOG_CACHE = {"ts": 0.0, "data": None}
_CATALOG_FILE = DATA_DIR / "openrouter_models.json"   # Datei-Cache: ueberlebt Neustarts, traegt offline
_CATALOG_FRISCH_S = 6 * 3600
_HISTORY_FILE = DATA_DIR / "model_history.json"       # Zuletzt-genutzt: oben im Picker statt 300er-Scroll
_HISTORY_MAX = 8
# Kuratierte Vorauswahl (Praefixe der OpenRouter-IDs): das Steuerpult zeigt diese
# zuerst, ALLES andere findet die Suche — Neuerscheinungen (Kimi K3 & Co.) sind
# damit sofort zuweisbar, ohne dass je ein Katalog-PR noetig wird.
_KURATIERT_PRAEFIXE = ("deepseek/", "z-ai/", "moonshotai/", "anthropic/",
                       "qwen/", "google/gemini")


def _local_catalog() -> list[dict]:
    """Lokale Ollama-Modelle — IMMER frisch abgefragt (Abfrage kostet ~ms), damit ein
    frisch gezogenes Modell (ollama pull) sofort im Dropdown steht, ohne 10-min-Cache."""
    return [{"id": "ollama_chat/" + n.replace(":latest", ""),
             "name": n.replace(":latest", "") + " (lokal)", "in": 0, "out": 0}
            for n in ollama_models() if not any(x in n.lower() for x in ("embed", "hf.co", "gguf"))]


def _openrouter_fetch() -> list[dict] | None:
    """Live-Liste von OpenRouter (IDs + Preise pro Token, in/out) — None bei Netzfehler.

    'rc' (reasoning-capable) ist ein KATALOG-FAKT: OpenRouter meldet die Denk-Faehigkeit
    pro Modell live mit (Top-Level 'reasoning'-Objekt bzw. 'reasoning' in
    supported_parameters) — keine Marker-Rateliste noetig."""
    try:
        data = httpx.get("https://openrouter.ai/api/v1/models", timeout=15).json().get("data", [])
    except Exception:  # noqa: BLE001
        return None
    ors = []
    for m in data:
        pr = m.get("pricing", {})
        ors.append({"id": "openrouter/" + (m.get("id") or ""), "name": m.get("name") or m.get("id"),
                    "in": pr.get("prompt"), "out": pr.get("completion"), "ctx": m.get("context_length"),
                    "rc": bool(m.get("reasoning")
                               or "reasoning" in (m.get("supported_parameters") or []))})
    return sorted(ors, key=lambda x: x["id"])


def _openrouter_liste(force: bool = False) -> list[dict]:
    """OpenRouter-Katalog mit Datei-Cache (Config-Muster: Frische per mtime).

    Frische Datei (< 6h) -> lesen, kein Netz. Sonst live holen und wegschreiben.
    Netzfehler -> Datei-Fallback egal wie alt (offline bleibt der Katalog nutzbar)."""
    import time as _t

    try:
        frisch = _CATALOG_FILE.exists() and (_t.time() - _CATALOG_FILE.stat().st_mtime) < _CATALOG_FRISCH_S
    except OSError:
        frisch = False
    if frisch and not force:
        try:
            alt = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
            if not alt or "rc" in alt[0]:
                return alt
            # Schema von vor der Reasoning-Runde (ohne 'rc') -> einmal live auffrischen
        except Exception:  # noqa: BLE001
            pass
    live = _openrouter_fetch()
    if live is not None:
        try:
            atomic_write(_CATALOG_FILE, json.dumps(live, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        return live
    try:
        return json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _kuratiert(ors: list[dict]) -> list[dict]:
    praefixe = tuple(CONFIG.get("models", {}).get("kuratiert") or _KURATIERT_PRAEFIXE)
    return [m for m in ors
            if str(m.get("id", "")).removeprefix("openrouter/").startswith(praefixe)]


_RC_MEMO = {"mtime": -1.0, "ids": frozenset()}


def reasoning_ids() -> frozenset:
    """IDs aller denk-faehigen Katalog-Modelle — aus dem Datei-Cache, NIE uebers Netz
    (steht im heissen Pfad jedes LLM-Aufrufs und in Langlaeufern wie dem Telegram-Bot).
    Memo per mtime nach dem Config-Muster; fehlende/alte Datei -> leer (Marker greifen)."""
    try:
        mt = _CATALOG_FILE.stat().st_mtime
    except OSError:
        return frozenset()
    if mt != _RC_MEMO["mtime"]:
        try:
            ors = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            ors = []
        _RC_MEMO.update(mtime=mt,
                        ids=frozenset(m.get("id", "") for m in ors if m.get("rc")))
    return _RC_MEMO["ids"]


def _history_merken(model_id: str) -> None:
    """Zuletzt-genutzt pflegen (juengstes zuerst, dedupliziert) — best effort,
    darf das Setzen nie brechen."""
    mid = (model_id or "").strip()
    if not mid:
        return
    try:
        alt = json.loads(_HISTORY_FILE.read_text(encoding="utf-8")) if _HISTORY_FILE.exists() else []
    except Exception:  # noqa: BLE001
        alt = []
    neu = [mid] + [m for m in alt if isinstance(m, str) and m != mid]
    try:
        atomic_write(_HISTORY_FILE, json.dumps(neu[:_HISTORY_MAX], ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


def _zuletzt(voll: dict) -> list[dict]:
    """Zuletzt-genutzt-Eintraege, gegen den Katalog aufgeloest (Preis/Denk-Badge inklusive)."""
    try:
        hist = json.loads(_HISTORY_FILE.read_text(encoding="utf-8")) if _HISTORY_FILE.exists() else []
    except Exception:  # noqa: BLE001
        hist = []
    px = {m.get("id"): m for liste in voll.values() if isinstance(liste, list) for m in liste}
    return [px.get(mid) or {"id": mid, "name": mid}
            for mid in hist if isinstance(mid, str) and mid]


def catalog(force: bool = False) -> dict:
    """Alle verfuegbaren Modelle: OpenRouter (live, Datei-Cache 6h + offline-Fallback),
    AIML, lokal (Ollama, ungecacht — neue Downloads erscheinen sofort). 'kuratiert'
    ist die Vorauswahl fuers Steuerpult; 'zuletzt' die Zuletzt-genutzt-Reihe (beide
    stehen im Picker OBEN); die Suche sieht weiterhin alles."""
    import time as _t

    if not force and _CATALOG_CACHE["data"] and (_t.time() - _CATALOG_CACHE["ts"]) < 600:
        voll = {**_CATALOG_CACHE["data"], "local": _local_catalog()}
        return {**voll, "zuletzt": _zuletzt(voll)}
    ors = _openrouter_liste(force=force)
    aimlapi_list = sorted(aimlapi_models(), key=lambda x: x["id"])
    out = {"openrouter": ors, "aimlapi": aimlapi_list, "kuratiert": _kuratiert(ors)}
    _CATALOG_CACHE.update(ts=_t.time(), data=out)
    voll = {**out, "local": _local_catalog()}
    return {**voll, "zuletzt": _zuletzt(voll)}


def roles() -> dict:
    """Aktuelle Rollen-Zuordnung (welches Modell fuer welche Aufgabe)."""
    m = CONFIG["models"]
    rt = m.get("routing", {})
    return {
        "chat": rt.get("chat", m.get("default")),
        "reason": rt.get("reason", m.get("default")),
        "bulk": rt.get("bulk", m.get("default")),
        "classify": rt.get("classify", m.get("local_fallback")),
        "worker": rt.get("worker", m.get("default")),
        "escalation": m.get("escalation_model"),
        "default": m.get("default"),
    }


def set_role(role: str, model: str) -> str:
    """Weist einer Rolle (chat/reason/bulk/escalation/default) ein Modell zu — sofort live + persistent."""
    role = (role or "").strip().lower()
    model = (model or "").strip()
    d = _load()
    if role in ("escalation", "escalation_model", "esk", "eskalation"):
        d["escalation_model"] = model
    elif role == "default":
        d["default"] = model
        routing = d.setdefault("routing", {})
        for s in _MAIN_SCOPES:
            routing[s] = model
    else:
        d.setdefault("routing", {})[role] = model
    _save(d)
    apply_model_overrides(d)
    _history_merken(model)
    return model


def loaded() -> dict:
    """Was Ollama gerade geladen hat: Kontext + VRAM-Anteil (best effort, fuer 'passt auf GPU?')."""
    try:
        r = httpx.get("http://localhost:11434/api/ps", timeout=5).json()
        for m in r.get("models", []):
            size = m.get("size") or 0
            vram = m.get("size_vram") or 0
            return {
                "name": m.get("name"),
                "context": m.get("context_length") or m.get("context"),
                "size_gb": round(size / 1e9, 2),
                "vram_gb": round(vram / 1e9, 2),
                "gpu_pct": round(vram / size * 100) if size else None,
            }
    except Exception:
        pass
    return {}


def status() -> dict:
    m = CONFIG["models"]
    providers = m.get("providers", {})
    return {
        "default": m.get("default"),
        "routing": m.get("routing", {}),
        "escalation_model": m.get("escalation_model"),
        "num_ctx": m.get("num_ctx"),
        "max_tokens": m.get("max_tokens"),
        "providers": {a: {**p, "key_set": bool(os.getenv(p.get("api_key_env", "")))} for a, p in providers.items()},
        "api_keys": {prov: bool(os.getenv(env)) for prov, env in _PROVIDER_KEYS.items()},
        "ollama_local": ollama_models(),
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "list"

    if cmd in ("list", "status"):
        s = status()
        print("Aktives Default-Modell:", s["default"])
        print("Routing:", s["routing"])
        print("Eskalation (Cloud):", s["escalation_model"])
        print("Eigene Provider:", s["providers"] or "(keine)")
        print("Lokal in Ollama:", s["ollama_local"] or "(keine/Service aus)")
    elif cmd == "use" and len(args) >= 2:
        print("Default-Modell gesetzt auf:", set_model(args[1]))
    elif cmd == "openrouter" and len(args) >= 2:
        print("Aktiv ueber OpenRouter:", add_openrouter(args[1]))
    elif cmd == "add" and len(args) >= 5:
        print("Provider angelegt:", add_provider(args[1], args[2], args[3], args[4]))
    else:
        print(__doc__)
