"""Melde-Puffer (Fix 09.07.): Missions-Meldungen buendeln statt fluten.

10 Einzelmeldungen in 3 Stunden sind nicht verarbeitbar — jetzt sammeln sich
Schritt-Meldungen als Einzeiler in data/melde_puffer.json und der Telegram-Bot
schickt sie alle N Stunden (mission.buendel_stunden, Default 3) als EIN Buendel.
Wichtiges (endgueltig gescheitert, Freigaben) geht weiter SOFORT raus.
"""
from __future__ import annotations

import json
import time

from core.config import DATA_DIR

_PATH = DATA_DIR / "melde_puffer.json"
MAX_ZEILEN = 40


def _load() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 — Puffer ist best effort, nie kritisch
        pass


def merken(zeile: str) -> None:
    """Eine Einzeiler-Meldung in den Puffer legen (aeltestes faellt bei Ueberlauf raus)."""
    zeile = " ".join((zeile or "").split())[:160]
    if not zeile:
        return
    d = _load()
    items = d.get("items") or []
    items.append({"ts": time.time(), "zeile": zeile})
    d["items"] = items[-MAX_ZEILEN:]
    _save(d)


def faellig(stunden: float = 3.0) -> bool:
    """Buendel faellig? (Puffer nicht leer UND letzter Versand >= N Stunden her)."""
    d = _load()
    if not (d.get("items") or []):
        return False
    return time.time() - float(d.get("last_flush") or 0) >= max(0.25, float(stunden)) * 3600


def leeren() -> list[str]:
    """Puffer entnehmen (chronologisch) und Flush-Zeit stempeln."""
    d = _load()
    items = [str(i.get("zeile") or "") for i in (d.get("items") or []) if i.get("zeile")]
    _save({"items": [], "last_flush": time.time()})
    return items
