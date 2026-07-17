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


def datum_aufloesen(s: str) -> str:
    """Eindeutige Relativ-Angaben ('heute'/'morgen'/'uebermorgen') -> TT.MM.JJJJ,
    alles andere unveraendert. Live-Fund 17.07.: Modelle rechnen Relativdaten
    selbst — und verrechnen sich (Erinnerung einen Tag zu spaet). Eindeutiges
    loest der Harness auf, der Rest lehrt mit den aufgeloesten Daten."""
    t = str(s or "").strip().lower()
    if t in _RELATIV:
        return (datetime.date.today() + datetime.timedelta(days=_RELATIV[t])).strftime("%d.%m.%Y")
    return str(s or "").strip()


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
        heute = datetime.date.today()
        morgen = heute + datetime.timedelta(days=1)
        return {"ok": False,
                "error": (f"Datum '{datum}' ergibt keinen Kalendertag (Format TT.MM.JJJJ). "
                          f"Heute ist der {heute:%d.%m.%Y}, morgen der {morgen:%d.%m.%Y}")}
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
