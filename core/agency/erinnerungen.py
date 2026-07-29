"""Einmal-Wecker (data/erinnerungen.json): zur Zeit X EINE aktive Nachricht, dann weg.

Schliesst die Luecke aus dem c4-Vorfall (16.07.): "Weck mich heute um 15 Uhr per
Telegram" hatte kein Werkzeug — termin_add ist passiv (Radar/Briefing), cron_add
wiederkehrend. Das Modell erfand daraufhin 'telegram_add_reminder'.

Zusteller ist der Telegram-Bot (Poll-Runde ~60s, _maybe_erinnerungen); ohne
konfiguriertes Telegram stellt der Runner ins Cockpit zu (Event-only) — genau
EINER von beiden, damit kein Prozess-Rennen um die Datei entsteht.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from datetime import datetime

from core.config import CONFIG, DATA_DIR
from core.kernel.fs import atomic_write

_PATH = DATA_DIR / "erinnerungen.json"
_MAX = 50

# Lebenszeichen des Bots: er stempelt hier bei jeder Poll-Runde (~alle 30 s).
ALIVE_FILE = DATA_DIR / "telegram_alive.json"
BOT_STUMM_S = 300        # so lange darf der Stempel alt sein, bevor er als stumm gilt
VERTRETUNG_AB_S = 600    # erst SO ueberfaellige Wecker uebernimmt der Runner


def bot_pollt(now: float | None = None) -> bool:
    """Pollt der Telegram-Bot gerade wirklich?

    Nicht zu verwechseln mit telegram_konfiguriert(): ein Bot ohne Token schlaeft in
    einer Endlosschleife, ein zweiter Start beendet sich am Instanz-Lock, und die
    getMe-Wache kann das Polling verweigern. In all diesen Faellen ist Telegram
    eingerichtet — und trotzdem stellt niemand zu."""
    try:
        d = json.loads(ALIVE_FILE.read_text(encoding="utf-8"))
        return (now or time.time()) - float(d.get("ts") or 0) < BOT_STUMM_S
    except Exception:  # noqa: BLE001 — kein Stempel = kein Lebenszeichen
        return False


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
    """Kann ueber Telegram ueberhaupt zugestellt werden? Token UND Chat noetig.

    Die Pruefung sah frueher nur nach der chat_id. Fehlte das TOKEN, galt Telegram als
    eingerichtet, der Bot schlief in seiner Endlosschleife, und der Runner schickte
    seine Wecker in denselben tokenlosen Kanal — sie blieben liegen, Tick fuer Tick,
    ohne dass je etwas beim Nutzer ankam."""
    try:
        from core import config as _cfg

        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        return bool(chat and _cfg.telegram_token())
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
        return None, (f"datum braucht TT.MM.JJJJ und zeit HH:MM (bekam datum='{datum}', "
                      f"zeit='{zeit}'). {_termine.datums_hilfe()} Beispiel: "
                      'erinnerung("Anruf Mama", "Donnerstag", "15:00").')
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


_LOCK_FILE = DATA_DIR / "erinnerungen.zustellung.lock"
_LOCK_MAX_S = 120   # danach gilt ein Lock als verwaist (Prozess starb beim Zustellen)


@contextlib.contextmanager
def _zustell_lock():
    """Genau EIN Prozess stellt Wecker zu — liefert True, wenn wir dran sind.

    Ohne diese Sperre koennen Bot und Runner sich ueberlappen: beide lesen dieselbe
    Liste, beide senden, und der Nutzer hoert denselben Wecker zweimal. Das Fenster ist
    schmal (der Runner springt erst nach 5 Minuten Funkstille ein), aber es existiert —
    kehrt der Bot genau waehrend der Vertretung zurueck, klingelt es doppelt.
    os.O_CREAT|os.O_EXCL ist auf beiden Plattformen atomar."""
    fd = None
    try:
        try:
            fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:    # verwaister Lock (Absturz mitten in der Zustellung)?
                alt = time.time() - _LOCK_FILE.stat().st_mtime > _LOCK_MAX_S
            except Exception:  # noqa: BLE001
                alt = False
            if not alt:
                yield False
                return
            _LOCK_FILE.unlink(missing_ok=True)
            fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except Exception:  # noqa: BLE001 — im Zweifel lieber zustellen als schweigen
            yield True
            return
        try:
            os.write(fd, str(os.getpid()).encode())
        except Exception:  # noqa: BLE001
            pass
        yield True
    finally:
        if fd is not None:
            with contextlib.suppress(Exception):
                os.close(fd)
            with contextlib.suppress(Exception):
                _LOCK_FILE.unlink(missing_ok=True)


def vertretung_zustellen(now: float | None = None) -> int:
    """Der Runner springt ein, wenn der Bot stumm ist. Gibt die Anzahl zurueck.

    Uebernimmt bewusst NUR Wecker, die schon VERTRETUNG_AB_S ueberfaellig sind: kommt
    der Bot in derselben Minute zurueck, sollen nicht beide klingeln. Die Karenz macht
    ein Doppel-Klingeln praktisch unmoeglich und kostet nichts — ein Wecker, der zehn
    Minuten liegt, ist ohnehin zu spaet. Umgesetzt ueber ein zurueckdatiertes `now`:
    damit gelten genau die laengst faelligen als faellig."""
    from core.kernel import zustellung

    jetzt = now if now is not None else time.time()
    abgelehnt = False

    def _sender(text: str):
        nonlocal abgelehnt
        r = zustellung.an_nutzer(text, quelle="wecker-vertretung")
        if r is False:
            abgelehnt = True
        return r

    n = zustellen(_sender, now=jetzt - VERTRETUNG_AB_S)
    if abgelehnt:
        # Telegram hat ausdruecklich abgelehnt (kein Token, Bot blockiert, chat weg).
        # Ohne diesen Rueckfall blieben die Wecker liegen, Tick fuer Tick, fuer immer —
        # ausgerechnet in dem Fall, fuer den die Vertretung gebaut wurde.
        n += zustellen(None, now=jetzt - VERTRETUNG_AB_S)
        _melden("erinnerung_nur_cockpit",
                {"grund": "Telegram lehnt ab — im Cockpit zugestellt"})
    if n:
        _melden("erinnerung_vertretung", {"anzahl": n, "grund": "Bot stumm"})
    return n


def zustellen(sender=None, now: float | None = None) -> int:
    """Faellige Erinnerungen ausliefern und austragen. sender(text) schickt (Telegram);
    None = nur Cockpit-Event. Scheitert der Versand, bleibt der Eintrag fuer die
    naechste Runde liegen. Gibt die Anzahl zugestellter Erinnerungen zurueck.

    Dieses Versprechen war auf dem Telegram-Pfad lange gebrochen (Fund 27.07.): der
    Sender dort schluckte jeden Fehler und warf nie, also galt jeder Wecker als
    zugestellt und wurde ausgetragen — auch wenn er nie ankam.

    Der sender ist dreiwertig, und die Unterscheidung entscheidet ueber Klingeln oder
    Schweigen:
      True  -> zugestellt, austragen.
      False -> AUSDRUECKLICH abgelehnt: liegen lassen, naechste Runde erneut.
      None  -> Ausgang unbekannt (Timeout): austragen. Die Nachricht kann angekommen
               sein; ein zweites Klingeln waere der schlimmere Fehler — der Nutzer hat
               genau diese Doppelung beklagt. Der Zweifel wird als Event protokolliert.
    Alt-Aufrufer und der Cockpit-Pfad geben None zurueck und bleiben damit unveraendert."""
    f = faellige(now)
    if not f:
        return 0
    with _zustell_lock() as dran:
        if not dran:
            return 0   # ein anderer Prozess stellt gerade zu
        return _zustellen_gesperrt(f, sender, now)


def _zustellen_gesperrt(f: list[dict], sender, now: float | None) -> int:
    weg: set[str] = set()
    jetzt = now if now is not None else time.time()
    for e in f:
        try:
            # Ueberfaellige Wecker haben den Nutzer ratlos gelassen ("⏰ Erinnerung:
            # Aufstehen" um 15:21, gestellt fuer 09:00). Steht die Verspaetung dabei,
            # ergibt die Nachricht wieder Sinn.
            spaet = jetzt - float(e.get("ts", 0))
            nachtrag = (f"\n(war fuer {e.get('wann', '?')} gestellt — "
                        f"{round(spaet / 3600)} h zu spaet)") if spaet > 3600 else ""
            r = sender(f"⏰ Erinnerung: {e['text']}{nachtrag}") if sender is not None else True
            if r is False:
                # Eindeutige Absage: der Wecker bleibt fuer die naechste Runde liegen.
                _melden("erinnerung_unzustellbar", {"wann": e.get("wann", ""),
                                                    "text": e["text"][:200]})
                continue
            if r is None:
                # Ausgang unbekannt (Zeitueberschreitung). Wir tragen ihn AUS: er kann
                # angekommen sein, und ein zweites Klingeln waere der schlimmere Fehler.
                _melden("erinnerung_ausgang_unklar", {"wann": e.get("wann", ""),
                                                      "text": e["text"][:200]})
            else:
                _melden("erinnerung_zugestellt", {"wann": e.get("wann", ""),
                                                  "text": e["text"][:200]})
            weg.add(e["id"])
        except Exception:  # noqa: BLE001 — naechste Runde erneut
            pass
    if weg:
        _speichern([e for e in _laden() if e.get("id") not in weg])
    return len(weg)
