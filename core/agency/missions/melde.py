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


def lesen() -> list[str]:
    """Puffer ansehen, OHNE ihn zu leeren — erst nach erfolgreicher Zustellung bestaetigen."""
    return [str(i.get("zeile") or "") for i in (_load().get("items") or []) if i.get("zeile")]


def bestaetigen(zeilen: list[str]) -> None:
    """Diese Zeilen sind beim Nutzer angekommen: raus aus dem Puffer, Flush-Zeit stempeln.

    Alles, was waehrend des Sendens dazukam, bleibt liegen und geht beim naechsten
    Buendel raus."""
    rest = [i for i in (_load().get("items") or [])
            if str(i.get("zeile") or "") not in set(zeilen)]
    _save({"items": rest[-MAX_ZEILEN:], "last_flush": time.time()})


def leeren() -> list[str]:
    """Puffer entnehmen und Flush-Zeit stempeln.

    ACHTUNG (Fund 27.07.): Das leert den Puffer, BEVOR die Zeilen zugestellt sind —
    scheiterte der Versand danach, waren bis zu 40 gesammelte Meldungen dauerhaft weg,
    ohne Event und ohne Log. Fuer Zustellwege stattdessen lesen() + bestaetigen()."""
    items = lesen()
    _save({"items": [], "last_flush": time.time()})
    return items
