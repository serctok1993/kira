"""Wochentags-Zeitplaene (Live-Fund 26.07.): der Planer kannte nur taeglich+Intervall.
Folge im Betrieb: "werktags 08:00" war unmoeglich, und der Job "Wochen-Review" lief
noetigerweise TAEGLICH — Haupttreiber der Melde-Flut."""
from __future__ import annotations

import datetime as dt

from core.agency.missions import cron


def test_parse_werktags():
    s = cron.parse_schedule("werktags 08:00")
    assert s == {"type": "weekly", "days": [0, 1, 2, 3, 4], "time": "08:00"}


def test_parse_einzelner_wochentag():
    assert cron.parse_schedule("montags 09:00") == {"type": "weekly", "days": [0], "time": "09:00"}
    assert cron.parse_schedule("sonntags 18:30") == {"type": "weekly", "days": [6], "time": "18:30"}


def test_parse_tagesliste_und_gruppen():
    assert cron.parse_schedule("mo,mi,fr 07:30")["days"] == [0, 2, 4]
    assert cron.parse_schedule("wochenende 10:00")["days"] == [5, 6]
    assert cron.parse_schedule("woechentlich 20:00") == {"type": "weekly", "days": [0], "time": "20:00"}


def test_ohne_uhrzeit_default_acht_uhr():
    assert cron.parse_schedule("werktags")["time"] == "08:00"


def test_alte_formate_unveraendert():
    # Vertrag: bestehende Jobs duerfen sich NICHT anders verhalten.
    assert cron.parse_schedule("08:00") == {"type": "daily", "time": "08:00"}
    assert cron.parse_schedule("30m") == {"type": "interval", "minutes": 30}
    assert cron.parse_schedule("2h") == {"type": "interval", "minutes": 120}
    assert cron.parse_schedule("quatsch mit sosse") == {"type": "interval", "minutes": 60}


def test_next_run_trifft_den_richtigen_wochentag():
    # Referenz: Mittwoch, 22.07.2026, 12:00 -> naechster Werktags-Lauf ist Donnerstag 08:00
    ref = dt.datetime(2026, 7, 22, 12, 0).timestamp()
    nxt = dt.datetime.fromtimestamp(cron._next_run(cron.parse_schedule("werktags 08:00"), ref))
    assert (nxt.weekday(), nxt.hour, nxt.minute) == (3, 8, 0)
    # Freitag 12:00 + "werktags" -> ueberspringt das Wochenende auf Montag
    ref_fr = dt.datetime(2026, 7, 24, 12, 0).timestamp()
    nxt_mo = dt.datetime.fromtimestamp(cron._next_run(cron.parse_schedule("werktags 08:00"), ref_fr))
    assert nxt_mo.weekday() == 0 and nxt_mo.day == 27


def test_next_run_heute_noch_moeglich():
    # Mittwoch 06:00, Plan "mittwochs 08:00" -> HEUTE 08:00, nicht erst naechste Woche
    ref = dt.datetime(2026, 7, 22, 6, 0).timestamp()
    nxt = dt.datetime.fromtimestamp(cron._next_run(cron.parse_schedule("mittwochs 08:00"), ref))
    assert (nxt.day, nxt.hour) == (22, 8)


def test_woechentlich_taktet_sieben_tage_weiter():
    ref = dt.datetime(2026, 7, 22, 12, 0).timestamp()      # Mittwoch
    nxt = dt.datetime.fromtimestamp(cron._next_run(cron.parse_schedule("montags 20:00"), ref))
    assert nxt.weekday() == 0 and nxt.day == 27


def test_cron_add_beschreibung_nennt_wochentage():
    # Manifest-Vertrag: das Modell muss die neue Moeglichkeit SEHEN, sonst nutzt es sie nie.
    from core.agency.tools import builtin  # noqa: F401  (Import registriert die Werkzeuge)
    from core.agency.tools import registry

    t = registry.get("cron_add")
    assert "werktags" in t.description and "montags" in t.description
    assert "werktags" in t.params["schedule"]
