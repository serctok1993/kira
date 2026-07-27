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


def normtext(s: str | None) -> str:
    """Text auf seinen Kern reduzieren: Gross/klein, Satzzeichen und Umlaut-Schreibweise
    egal. "Müll rausbringen!" und "muell rausbringen" sind derselbe Wecker."""
    import re as _re

    t = (s or "").lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(alt, neu)
    return _re.sub(r"[^a-z0-9]+", "", t)


def _gleich(a: str | None, b: str | None) -> bool:
    return bool(normtext(a)) and normtext(a) == normtext(b)


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
    from core.agency import termine as _termine

    datum = _termine.datum_aufloesen(datum)     # "heute"/"morgen" direkt annehmen (Live-Fund 17.07.)
    try:
        wann = datetime.strptime(f"{(datum or '').strip()} {(zeit or '').strip()}",
                                 "%d.%m.%Y %H:%M")
    except ValueError:
        morgen = time.strftime("%d.%m.%Y", time.localtime(time.time() + 86400))
        return None, (f"datum braucht TT.MM.JJJJ und zeit HH:MM (bekam datum='{datum}', "
                      f"zeit='{zeit}'). Heute ist der {jetzt.split()[0]}, morgen der {morgen} "
                      '— siehe auch deine JETZT-Zeile. Beispiel: '
                      'erinnerung("Anruf Mama", "16.07.2026", "15:00").')
    ts = wann.timestamp()
    if ts < time.time() - 60:
        return None, (f"{datum} {zeit} liegt in der Vergangenheit (JETZT: {jetzt}). "
                      "Nimm den naechsten passenden Zeitpunkt.")
    liste = _laden()
    doppelt = next((a for a in liste if _gleich(a.get("text"), text)
                    and abs(float(a.get("ts", 0)) - ts) < 60), None)
    if doppelt:
        # Live-Fund 27.07.: "Muell rausbringen" fuer 18:00 wurde zweimal angelegt
        # (23:54 und 00:21) — der Nutzer bekam den Wecker doppelt und hielt es fuer
        # einen Zustell-Bug. Es war ein Anlege-Bug: nichts prueft auf Doppelung.
        return None, (f"Diesen Wecker gibt es schon: „{doppelt['text']}“ am {doppelt['wann']} "
                      f"(id {doppelt['id']}). Sag es dem Nutzer, statt einen zweiten zu stellen — "
                      "sonst klingelt es doppelt.")
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


def entfernen(kennung: str) -> dict | None:
    """Wecker absagen — per id (auch Kurzform) oder per Text. Liefert den entfernten.

    Bis 27.07. konnte man Wecker nur STELLEN: "Welche Wecker hab ich?" und "sag den
    9-Uhr-Wecker wieder ab" waren unbeantwortbar, ein falsch gestellter Wecker klingelte
    zwangslaeufig."""
    k = (kennung or "").strip()
    if not k:
        return None
    liste = _laden()
    treffer = next((e for e in liste if e.get("id") == k), None)
    if treffer is None:
        treffer = next((e for e in liste if str(e.get("id", "")).startswith(k)), None)
    if treffer is None:
        treffer = next((e for e in liste if _gleich(e.get("text"), k)), None)
    if treffer is None:
        return None
    _speichern([e for e in liste if e.get("id") != treffer["id"]])
    _melden("erinnerung_abgesagt", {"wann": treffer.get("wann", ""),
                                    "text": str(treffer.get("text", ""))[:200]})
    return treffer


def faellige(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    return [e for e in _laden() if float(e.get("ts", 0)) <= now]


def zustellen(sender=None, now: float | None = None) -> int:
    """Faellige Erinnerungen ausliefern und austragen. sender(text) schickt (Telegram);
    None = nur Cockpit-Event. Scheitert der Versand, bleibt der Eintrag fuer die
    naechste Runde liegen. Gibt die Anzahl zugestellter Erinnerungen zurueck.

    Dieses Versprechen war auf dem Telegram-Pfad lange gebrochen (Fund 27.07.): der
    Sender dort schluckte jeden Fehler und warf nie, also galt jeder Wecker als
    zugestellt und wurde ausgetragen — auch wenn er nie ankam. Ein sender, der
    ausdruecklich False liefert, laesst den Wecker jetzt stehen; None/True gelten
    weiter als zugestellt (Cockpit-Pfad und Alt-Aufrufer bleiben unveraendert)."""
    f = faellige(now)
    if not f:
        return 0
    weg: set[str] = set()
    for e in f:
        try:
            if sender is not None and sender(f"⏰ Erinnerung: {e['text']}") is False:
                _melden("erinnerung_unzustellbar", {"wann": e.get("wann", ""),
                                                    "text": e["text"][:200]})
                continue
            _melden("erinnerung_zugestellt", {"wann": e.get("wann", ""), "text": e["text"][:200]})
            weg.add(e["id"])
        except Exception:  # noqa: BLE001 — naechste Runde erneut
            pass
    if weg:
        _speichern([e for e in _laden() if e.get("id") not in weg])
    return len(weg)
