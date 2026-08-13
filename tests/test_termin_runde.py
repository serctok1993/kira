"""Termin-Runde: termin_update + termin_remove — die Kalender-Familie wird komplett.

Nacht-Fund 22.07. (autonome Testbatterien, events-belegt): Ohne Aendern/Loeschen
legte JEDE Korrektur einen Doppel-Termin an ("TUEV 16 Uhr" -> zwei Eintraege,
4B UND 9B identisch), "Friseur verschieben" scheiterte an geratenen Namen
(termin_edit/termin_delete existierten nicht). Die alte Manifest-Diaet
("Loeschen macht der Nutzer im Cockpit") war ein Produktbug.
"""
from __future__ import annotations

import datetime

import pytest

from core.agency import termine
from core.agency.tools.termin_tools import termin_remove, termin_update


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(termine, "_PATH", tmp_path / "kalender.json")
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    return tmp_path


# ---- Backend ---------------------------------------------------------------------------

def test_update_zeit_statt_doppeltermin():
    """DER Live-Fall: TUEV von 14 auf 16 Uhr — EIN Eintrag, geaendert, kein Duplikat."""
    t = termine.add("24.07.2026", "TUEV", zeit="14:00")
    res = termine.update(t["id"], zeit="16:00")
    assert res["ok"] and res["geaendert"] == ["zeit"] and res["zeit"] == "16:00"
    assert len(termine.alle()) == 1                       # kein zweiter TUEV
    assert termine.alle()[0]["datum"] == "24.07.2026"     # Rest unangetastet


def test_update_verschiebt_mit_relativdatum():
    """Live-Fall 'Friseur auf Freitag verschieben' — datum nimmt auch morgen/uebermorgen."""
    t = termine.add("23.07.2026", "Friseur", zeit="9:30")
    res = termine.update(t["id"], datum="uebermorgen")
    erwartet = (datetime.date.today() + datetime.timedelta(days=2)).strftime("%d.%m.%Y")
    assert res["ok"] and res["datum"] == erwartet
    assert termine.alle()[0]["zeit"] == "9:30"            # Zeit bleibt


def test_update_lehrt_bei_unbekannter_id_und_unfug():
    t = termine.add("24.07.2026", "Amt")
    res = termine.update("gibtsnicht", zeit="10:00")
    assert not res["ok"] and "termin_list" in res["error"]
    res2 = termine.update(t["id"], datum="naechste Woche")
    # Ankerdaten (#190-Muster). Seit dem 28.07. nennt die Hilfe den Wochentag von
    # heute UND die naechsten sieben Tage mit Datum — "Heute ist Mittwoch, der …".
    assert not res2["ok"] and "Heute ist" in res2["error"]
    assert "heute/morgen" in res2["error"] and "=" in res2["error"]
    res3 = termine.update(t["id"])
    assert not res3["ok"] and "nichts zu aendern" in res3["error"]


def test_remove_backend():
    t = termine.add("24.07.2026", "Probe")
    assert termine.remove(t["id"]) is True
    assert termine.alle() == []
    assert termine.remove(t["id"]) is False               # weg ist weg


# ---- Tool-Ebene (Wortlaute = Trainingsmaterial) ----------------------------------------

def test_tool_update_happy_und_lehrfehler():
    t = termine.add("24.07.2026", "TUEV", zeit="14:00")
    out = termin_update(id=t["id"], zeit="16:00")
    assert "Geaendert (zeit)" in out and "16:00" in out and t["id"] in out
    assert "Beispiel" in termin_update()                              # ohne id -> lehrt
    assert 'ACT termin_update' in termin_update()
    kaputt = termin_update(id=t["id"], uhrzeit="17:00")               # erfundenes Arg
    assert "Fehler" in kaputt and "termin_update" in kaputt
    weg = termin_update(id="fake", zeit="16:00")
    assert "termin_list" in weg                                       # zeigt den Weg


def test_tool_remove_happy_und_lehrfehler():
    t = termine.add("24.07.2026", "Probe")
    assert f"id {t['id']}" in termin_remove(id=t["id"])
    assert termine.alle() == []
    assert "ACT termin_list {}" in termin_remove(id=t["id"])          # weg -> nachschauen lehren
    assert "Beispiel" in termin_remove()


# ---- Rollen-Karte + Registry -----------------------------------------------------------

def test_haupt_karte_traegt_die_komplette_familie():
    """Familien-Vollstaendigkeit (todo_list-Lehre: halbe Familien verwirren) —
    Termin- UND Cron-Familie stehen jetzt komplett auf der Alltags-Karte."""
    from core.agency import rollen
    ts = rollen.toolset("haupt")
    for name in ("termin_add", "termin_list", "termin_update", "termin_remove",
                 "cron_add", "cron_list", "cron_remove"):
        assert name in ts, f"haupt braucht {name}"
    assert len(ts) <= 50            # 13.08.2026: +2 neue Alltags-Werkzeuge


def test_registry_kennt_die_neuen():
    from core.agency.tools import registry
    import core.agency.tools.builtin  # noqa: F401
    m = registry.manifest()
    assert "- termin_update (" in m and "- termin_remove (" in m
