"""Termine/Kalender (Phase 2 Alltags-Kern): minimaler JSON-Kalender fuer den Nutzers Alltag.

data/kalender.json haelt eine Liste von Eintraegen
  {id, datum: "TT.MM.JJJJ", zeit: "HH:MM"|"", titel, jaehrlich: bool, quelle}
— atomar geschrieben (atomic_write), bewusst OHNE DB: klein, lesbar, von Hand reparierbar.
Geburtstage aus dem Stammbaum kommen NICHT hier hinein — die liest standup._termin_radar
direkt aus den .md-Blaettern; naechste() liefert dasselbe (tage_bis, zeile)-Format,
damit beide Quellen im Briefing zu EINEM TERMIN-RADAR-Block gemergt werden.
"""
from __future__ import annotations

import datetime
import json
import re
import uuid

from core.config import DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write

_PATH = DATA_DIR / "kalender.json"


def _load() -> list[dict]:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 — fehlende/kaputte Datei = leerer Kalender
        return []


def _save(items: list[dict]) -> None:
    atomic_write(_PATH, json.dumps(items, indent=2, ensure_ascii=False))


_RELATIV = {"heute": 0, "morgen": 1, "uebermorgen": 2, "übermorgen": 2}

# Wochentage — die haeufigste Datumsangabe des Alltags ("Trag mir Donnerstag 14 Uhr ein").
_WOCHENTAGE = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
    "samstag": 5, "sonnabend": 5, "sonntag": 6,
    "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6,
}
# Fuellwoerter, die vor dem Wochentag stehen duerfen. "naechsten"/"kommenden" heben
# einen Treffer auf HEUTE auf die kommende Woche — sonst sind sie bedeutungsgleich.
_VORSATZ = re.compile(r"^(am|diesen|diesem|kommenden|kommende[nrs]?|naechsten|nächsten|"
                      r"naechste[nrs]?|nächste[nrs]?)\s+", re.IGNORECASE)
_NAECHSTEN = re.compile(r"^(kommend|naechst|nächst)", re.IGNORECASE)


def _wochentag_aufloesen(t: str, heute: datetime.date) -> str | None:
    """'Donnerstag' / 'am Montag' / 'naechsten Freitag' -> TT.MM.JJJJ, sonst None.

    Regel: die NAECHSTE Gelegenheit, heute eingeschlossen. Wer die Woche darauf meint,
    sagt "naechsten Donnerstag" — dann wird ein Treffer auf heute um sieben Tage
    geschoben. Das ist die Lesart, die im Alltag gemeint ist, und sie ist vorhersagbar."""
    rest = t
    vorsatz = ""
    m = _VORSATZ.match(rest)
    if m:
        vorsatz = m.group(1)
        rest = rest[m.end():].strip()
    tag = _WOCHENTAGE.get(rest.rstrip("."))
    if tag is None:
        return None
    abstand = (tag - heute.weekday()) % 7
    if abstand == 0 and _NAECHSTEN.match(vorsatz):
        abstand = 7
    return (heute + datetime.timedelta(days=abstand)).strftime("%d.%m.%Y")


def datum_aufloesen(s: str) -> str:
    """Eindeutige Relativ-Angaben -> TT.MM.JJJJ, alles andere unveraendert.

    'heute'/'morgen'/'uebermorgen' seit dem 17.07.; Wochentage seit dem 28.07.
    Live-Fund 17.07.: Modelle rechnen Relativdaten selbst — und verrechnen sich
    (Erinnerung einen Tag zu spaet). Katalog-Lauf 28.07., Aufgabe 001: auf "Trag mir
    Donnerstag 14 Uhr ein" antwortete das Modell, es gebe "zwei Donnerstage im Juli
    (30. und 6. August)" — und fragte zurueck, statt einzutragen.

    Eindeutiges loest der Harness auf. Das ist billiger und zuverlaessiger, als es
    einem 9B beizubringen."""
    t = str(s or "").strip().lower()
    if t in _RELATIV:
        return (datetime.date.today() + datetime.timedelta(days=_RELATIV[t])).strftime("%d.%m.%Y")
    tag = _wochentag_aufloesen(t, datetime.date.today())
    return tag if tag else str(s or "").strip()


def datums_hilfe() -> str:
    """Konkrete Datumshilfe fuer Fehlertexte — mit den ECHTEN Tagen, nicht der Regel.

    Ein kleines Modell, dem man "Format TT.MM.JJJJ" sagt, rechnet weiter selbst. Eines,
    das "Donnerstag = 30.07.2026" liest, schreibt beim naechsten Versuch das Richtige."""
    heute = datetime.date.today()
    namen = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    kommend = []
    for i in range(1, 8):
        d = heute + datetime.timedelta(days=i)
        kommend.append(f"{namen[d.weekday()]}={d:%d.%m.%Y}")
    return (f"Heute ist {namen[heute.weekday()]}, der {heute:%d.%m.%Y} "
            "— siehe auch deine JETZT-Zeile. "
            f"Du darfst auch direkt heute/morgen/uebermorgen oder einen Wochentag "
            f"schicken — ich rechne das um. Die naechsten: {', '.join(kommend)}")


def parse_datum(s: str) -> datetime.date | None:
    """'TT.MM.JJJJ' (oder 'heute'/'morgen'/'uebermorgen') -> date; None bei Unfug."""
    try:
        t, m, j = datum_aufloesen(s).split(".")
        return datetime.date(int(j), int(m), int(t))
    except Exception:  # noqa: BLE001
        return None


def add(datum: str, titel: str, zeit: str = "", jaehrlich: bool = False,
        quelle: str = "chat") -> dict:
    d = parse_datum(datum)
    if d is None:
        return {"ok": False,
                "error": (f"Datum '{datum}' ergibt keinen Kalendertag. {datums_hilfe()}")}
    titel = (titel or "").strip()
    if not titel:
        return {"ok": False, "error": "titel fehlt"}
    items = _load()
    eintrag = {"id": uuid.uuid4().hex[:8], "datum": d.strftime("%d.%m.%Y"),
               "zeit": (zeit or "").strip(), "titel": titel,
               "jaehrlich": bool(jaehrlich), "quelle": quelle}
    items.append(eintrag)
    _save(items)
    events.emit("termin_added", {"id": eintrag["id"], "datum": eintrag["datum"],
                                 "titel": titel[:80], "jaehrlich": bool(jaehrlich)})
    return {"ok": True, **eintrag}


def remove(termin_id: str) -> bool:
    items = _load()
    rest = [x for x in items if x.get("id") != str(termin_id).strip()]
    if len(rest) == len(items):
        return False
    _save(rest)
    events.emit("termin_removed", {"id": str(termin_id).strip()})
    return True


def update(termin_id: str, datum: str = "", zeit: str | None = None,
           titel: str = "", jaehrlich: str | None = None) -> dict:
    """Bestehenden Eintrag aendern — nur uebergebene Felder werden angefasst.

    Nacht-Fund 22.07.: ohne Aendern-Werkzeug legten die Modelle bei JEDER
    Korrektur einen ZWEITEN Termin an (TUEV 14 Uhr + TUEV 16 Uhr) oder rieten
    'termin_edit'/'termin_delete' ins Leere. datum nimmt wie add() auch
    heute/morgen/uebermorgen (datum_aufloesen)."""
    tid = str(termin_id or "").strip()
    items = _load()
    eintrag = next((x for x in items if x.get("id") == tid), None)
    if eintrag is None:
        return {"ok": False,
                "error": f"Kein Termin mit id '{tid}'. Die ids stehen in termin_list"}
    geaendert: list[str] = []
    if str(datum or "").strip():
        d = parse_datum(datum)
        if d is None:
            return {"ok": False,
                    "error": (f"Datum '{datum}' ergibt keinen Kalendertag. {datums_hilfe()}")}
        eintrag["datum"] = d.strftime("%d.%m.%Y")
        geaendert.append("datum")
    if zeit is not None and str(zeit).strip():
        eintrag["zeit"] = str(zeit).strip()
        geaendert.append("zeit")
    if str(titel or "").strip():
        eintrag["titel"] = str(titel).strip()
        geaendert.append("titel")
    if jaehrlich is not None and str(jaehrlich).strip():
        eintrag["jaehrlich"] = str(jaehrlich).strip().lower() in ("ja", "1", "true", "yes")
        geaendert.append("jaehrlich")
    if not geaendert:
        return {"ok": False,
                "error": "nichts zu aendern — gib datum, zeit, titel oder jaehrlich an"}
    _save(items)
    events.emit("termin_updated", {"id": tid, "geaendert": geaendert,
                                   "datum": eintrag["datum"], "titel": eintrag["titel"][:80]})
    return {"ok": True, **eintrag, "geaendert": geaendert}


def alle() -> list[dict]:
    return _load()


def _naechstes_vorkommen(e: dict, heute: datetime.date) -> datetime.date | None:
    """Naechstes Auftreten eines Eintrags ab heute; jaehrliche rollen uebers Jahr
    (29.02. faellt in Nicht-Schaltjahren auf den 01.03.)."""
    d = parse_datum(e.get("datum") or "")
    if d is None:
        return None
    if not e.get("jaehrlich"):
        return d
    try:
        naechster = d.replace(year=heute.year)
    except ValueError:
        naechster = datetime.date(heute.year, 3, 1)
    if naechster < heute:
        try:
            naechster = d.replace(year=heute.year + 1)
        except ValueError:
            naechster = datetime.date(heute.year + 1, 3, 1)
    return naechster


def list_upcoming(tage: int = 14, heute: datetime.date | None = None) -> list[dict]:
    """Kommende Eintraege im Fenster, nach Naehe sortiert; jeder mit tage_bis + faellig."""
    heute = heute or datetime.date.today()
    out: list[dict] = []
    for e in _load():
        n = _naechstes_vorkommen(e, heute)
        if n is None:
            continue
        diff = (n - heute).days
        if 0 <= diff <= max(0, int(tage)):
            out.append({**e, "faellig": n.isoformat(), "tage_bis": diff})
    out.sort(key=lambda x: (x["tage_bis"], x.get("zeit") or "99:99"))
    return out


def naechste(vorlauf_tage: int = 8, heute: datetime.date | None = None) -> list[tuple[int, str]]:
    """(tage_bis, zeile) im Format der standup-Termin-Radar-Funde -> direkt mergebar."""
    heute = heute or datetime.date.today()
    funde: list[tuple[int, str]] = []
    for e in list_upcoming(vorlauf_tage, heute=heute):
        diff = e["tage_bis"]
        wann = "HEUTE" if diff == 0 else ("morgen" if diff == 1 else f"in {diff} Tagen")
        zeit = f" um {e['zeit']}" if e.get("zeit") else ""
        d = datetime.date.fromisoformat(e["faellig"])
        funde.append((diff, f"- Termin: {e['titel']} am {d.strftime('%d.%m.')}{zeit} — {wann}"))
    return funde
