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
    OVERRIDE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def ollama_models() -> list[str]:
    """Lokal in Ollama verfuegbare Modelle (best effort)."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


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


def set_params(num_ctx: int | None = None, max_tokens: int | None = None) -> dict:
    """Kontextfenster / max. Ausgabetokens zur Laufzeit setzen (persistiert, sofort live)."""
    d = _load()
    if num_ctx is not None:
        d["num_ctx"] = int(num_ctx)
    if max_tokens is not None:
        d["max_tokens"] = int(max_tokens)
    _save(d)
    apply_model_overrides(d)
    return {"num_ctx": CONFIG["models"].get("num_ctx"), "max_tokens": CONFIG["models"].get("max_tokens")}


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
