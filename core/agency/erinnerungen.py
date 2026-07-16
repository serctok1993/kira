"""Einmal-Wecker (data/erinnerungen.json): zur Zeit X EINE aktive Nachricht, dann weg.

Schliesst die Luecke aus dem c4-Vorfall (16.07.): "Weck mich heute um 15 Uhr per
Telegram" hatte kein Werkzeug — termin_add ist passiv (Radar/Briefing), cron_add
wiederkehrend. Das Modell erfand daraufhin 'telegram_add_reminder'.

Zusteller ist der Telegram-Bot (Poll-Runde ~60s, _maybe_erinnerungen); ohne
konfiguriertes Telegram stellt der Runner ins Cockpit zu (Event-only) — genau
EINER von beiden, damit kein Prozess-Rennen um die Datei entsteht.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from core.config import CONFIG, DATA_DIR
from core.kernel.fs import atomic_write

_PATH = DATA_DIR / "erinnerungen.json"
_MAX = 50


def _melden(typ: str, payload: dict) -> None:
    try:
        from core.kernel import events

        events.emit(typ, payload)
    except Exception:  # noqa: BLE001
        pass


def _laden() -> list[dict]:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def _speichern(liste: list[dict]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(_PATH, json.dumps(liste, ensure_ascii=False, indent=1))


def telegram_konfiguriert() -> bool:
    try:
        return bool(CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id"))
    except Exception:  # noqa: BLE001
        return False


def add(text: str, datum: str, zeit: str) -> tuple[dict | None, str]:
    """Anlegen mit lehrenden Fehlern. Liefert (eintrag, '') oder (None, fehler)."""
    jetzt = time.strftime("%d.%m.%Y %H:%M")
    if not (text or "").strip():
        return None, ('text fehlt. Beispiel: erinnerung("Aufstehen — Termin um 16 Uhr", '
                      '"16.07.2026", "15:00").')
    try:
        wann = datetime.strptime(f"{(datum or '').strip()} {(zeit or '').strip()}",
                                 "%d.%m.%Y %H:%M")
    except ValueError:
        return None, (f"datum braucht TT.MM.JJJJ und zeit HH:MM (bekam datum='{datum}', "
                      f"zeit='{zeit}'). Heute ist {jetzt.split()[0]} — steht auch in deiner "
                      'JETZT-Zeile. Beispiel: erinnerung("Anruf Mama", "16.07.2026", "15:00").')
    ts = wann.timestamp()
    if ts < time.time() - 60:
        return None, (f"{datum} {zeit} liegt in der Vergangenheit (JETZT: {jetzt}). "
                      "Nimm den naechsten passenden Zeitpunkt.")
    liste = _laden()
    if len(liste) >= _MAX:
        return None, f"Schon {_MAX} offene Erinnerungen — erst welche zustellen lassen oder aufraeumen."
    e = {"id": uuid.uuid4().hex[:8], "ts": ts, "wann": f"{datum.strip()} {zeit.strip()}",
         "text": text.strip()[:300], "angelegt": time.time()}
    liste.append(e)
    _speichern(liste)
    _melden("erinnerung_gestellt", {"wann": e["wann"], "text": e["text"][:200]})
    return e, ""


def alle() -> list[dict]:
    return sorted(_laden(), key=lambda e: e.get("ts", 0))


def faellige(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    return [e for e in _laden() if float(e.get("ts", 0)) <= now]


def zustellen(sender=None, now: float | None = None) -> int:
    """Faellige Erinnerungen ausliefern und austragen. sender(text) schickt (Telegram);
    None = nur Cockpit-Event. Scheitert der Versand, bleibt der Eintrag fuer die
    naechste Runde liegen. Gibt die Anzahl zugestellter Erinnerungen zurueck."""
    f = faellige(now)
    if not f:
        return 0
    weg: set[str] = set()
    for e in f:
        try:
            if sender is not None:
                sender(f"⏰ Erinnerung: {e['text']}")
            _melden("erinnerung_zugestellt", {"wann": e.get("wann", ""), "text": e["text"][:200]})
            weg.add(e["id"])
        except Exception:  # noqa: BLE001 — naechste Runde erneut
            pass
    if weg:
        _speichern([e for e in _laden() if e.get("id") not in weg])
    return len(weg)
