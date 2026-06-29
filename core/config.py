"""Zentrale Konfiguration: laedt config.yaml + .env, definiert Pfade."""
from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent      # prometheus/
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
