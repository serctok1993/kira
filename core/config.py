"""Zentrale Konfiguration: laedt config.yaml + .env + Zugangs-Tresor, definiert Pfade."""
from __future__ import annotations

import os

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


def _load_vault_secrets() -> None:
    """Zugaenge aus dem Tresor (data/secrets.json) in die Umgebung laden — damit JEDER
    Prozess (Cockpit, Telegram-Bot, Supervisor, Runner), der core.config importiert, sie
    sieht. Ohne das lebte ein im Cockpit eingegebener Key nur im Cockpit-Prozess und war
    beim Neustart weg — der separate Bot sah ihn NIE (ELEVENLABS/TTS blieb stumm).
    .env hat Vorrang (setdefault): explizit gesetzte Werte werden nicht ueberschrieben.
    Direkt hier statt via core.governance.secrets, um einen Import-Zyklus zu vermeiden."""
    try:
        import json as _j

        f = DATA_DIR / "secrets.json"
        if not f.exists():
            return
        data = _j.loads(f.read_text(encoding="utf-8"))
        for k, v in (data.get("secrets") or {}).items():
            if v and str(k) not in os.environ:
                os.environ[str(k)] = str(v)
    except Exception:  # noqa: BLE001 — fehlender/kaputter Tresor darf den Start nie brechen
        pass


_load_vault_secrets()


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
    if "escalation_model" in d:
        m["escalation_model"] = d["escalation_model"]
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


# Allgemeine Laufzeit-Overrides (data/overrides.json) ueber config.yaml legen -> config.yaml
# bleibt mit Kommentaren unangetastet, Aenderungen ueberleben Neustarts.
_OVERRIDE_FILE = DATA_DIR / "overrides.json"


def _apply_overrides(cfg: dict, ov: dict) -> None:
    for path, val in ov.items():
        keys = str(path).split(".")
        d = cfg
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = val


def set_override(path: str, value) -> None:
    """Einen Config-Pfad (z.B. 'mission.goal') zur Laufzeit setzen + persistieren."""
    import json as _jo

    ov: dict = {}
    if _OVERRIDE_FILE.exists():
        try:
            ov = _jo.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        except Exception:
            ov = {}
    ov[path] = value
    from core.kernel.fs import atomic_write as _aw
    _aw(_OVERRIDE_FILE, _jo.dumps(ov, indent=2, ensure_ascii=False))
    _apply_overrides(CONFIG, {path: value})


if _OVERRIDE_FILE.exists():
    import json as _json3

    try:
        _apply_overrides(CONFIG, _json3.loads(_OVERRIDE_FILE.read_text(encoding="utf-8")))
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
