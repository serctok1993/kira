"""Zentrale Konfiguration: laedt config.yaml + .env, definiert Pfade."""
from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent      # kira/
DATA_DIR = ROOT / "data"
MIND_DIR = ROOT / "core" / "mind"
DB_PATH = DATA_DIR / "state.db"
CONFIG_PATH = ROOT / "config.yaml"

# .env laden (still, falls nicht vorhanden)
load_dotenv(ROOT / ".env")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()

# Datenverzeichnis sicherstellen
DATA_DIR.mkdir(parents=True, exist_ok=True)


def apply_model_overrides(d: dict) -> None:
    """Laufzeit-Overrides ueber die models-Sektion legen (Modellwahl, Provider).

    So bleibt config.yaml (mit Kommentaren) unangetastet; geaendert wird nur
    data/models.json zur Laufzeit.
    """
    m = CONFIG.setdefault("models", {})
    if "default" in d:
        m["default"] = d["default"]
    if "routing" in d:
        m.setdefault("routing", {}).update(d["routing"])
    if "providers" in d:
        m.setdefault("providers", {}).update(d["providers"])
    for key in ("num_ctx", "max_tokens", "temperature", "keep_alive"):
        if key in d:
            m[key] = d[key]


# Beim Start vorhandene Overrides einspielen
_MODEL_OVERRIDE = DATA_DIR / "models.json"
if _MODEL_OVERRIDE.exists():
    import json as _json

    try:
        apply_model_overrides(_json.loads(_MODEL_OVERRIDE.read_text(encoding="utf-8")))
    except Exception:
        pass

# Zugaenge/Secrets aus data/secrets.json in die Umgebung laden (write-only, gitignored)
_SECRETS_FILE = DATA_DIR / "secrets.json"
if _SECRETS_FILE.exists():
    import json as _json2
    import os as _os

    try:
        for _k, _v in (_json2.loads(_SECRETS_FILE.read_text(encoding="utf-8")).get("secrets") or {}).items():
            if _v:
                _os.environ[_k] = str(_v)
    except Exception:
        pass
