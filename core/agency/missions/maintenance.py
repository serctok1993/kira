"""Wartungs-Gates: persistente "hoechstens 1x pro Intervall"-Schalter fuer Pflege-Jobs.

cron.py ist prompt-getrieben (act auf einen Text) — fuer direkte Python-Calls wie
curator.curate_skills() das falsche Vehikel. Dieses Gate speichert Zeitstempel in
data/maintenance.json: ueberlebt Neustarts, feuert nach einem Crash nicht doppelt.
"""
from __future__ import annotations

import json
import time

from core.config import DATA_DIR

_STATE_PATH = DATA_DIR / "maintenance.json"


def _load() -> dict:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def maybe_run(name: str, interval_s: int = 86400) -> bool:
    """True genau dann, wenn der Job 'name' laenger als interval_s nicht lief.

    Der Zeitstempel wird SOFORT gesetzt (nicht erst nach Erfolg): ein crashender
    Pflege-Job darf nicht bei jedem Tick erneut Kosten verursachen."""
    now = time.time()
    state = _load()
    last = float(state.get(name) or 0)
    if now - last < interval_s:
        return False
    state[name] = now
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return True
