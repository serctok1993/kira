"""erinnerung (c4-Nachzug): der Einmal-Wecker — anlegen, faellig werden, zustellen.

Schliesst die Luecke aus dem 16.07.-Vorfall: "Weck mich heute um 15 Uhr per
Telegram" hatte kein Werkzeug, kira-c4 erfand daraufhin 'telegram_add_reminder'.
Offline: tmp-Store, Events als No-Op, Zusteller gemockt.
"""
from __future__ import annotations

import time

import pytest

from core.agency import erinnerungen


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(erinnerungen, "_PATH", tmp_path / "erinnerungen.json")
    monkeypatch.setattr(erinnerungen, "_melden", lambda *a, **k: None)


def _morgen() -> tuple[str, str]:
    t = time.localtime(time.time() + 86400)
    return time.strftime("%d.%m.%Y", t), time.strftime("%H:%M", t)


def test_anlegen_und_lehrende_fehler():
    datum, zeit = _morgen()
    e, err = erinnerungen.add("Anruf Mama", datum, zeit)
    assert not err and e["text"] == "Anruf Mama" and e["wann"] == f"{datum} {zeit}"
    _, err = erinnerungen.add("", datum, zeit)
    assert "text fehlt" in err and "Beispiel" in err
    _, err = erinnerungen.add("x", "15:00", "")                 # Zeit ins Datum (c4-Fehler!)
    assert "TT.MM.JJJJ" in err and "JETZT-Zeile" in err
    _, err = erinnerungen.add("x", "01.01.2020", "12:00")
    assert "Vergangenheit" in err and "JETZT:" in err
    assert len(erinnerungen.alle()) == 1                        # nur der gueltige Eintrag


def test_zustellen_traegt_aus_und_haelt_bei_fehler(monkeypatch):
    datum, zeit = _morgen()
    erinnerungen.add("spaeter", datum, zeit)                    # noch nicht faellig
    e, _ = erinnerungen.add("Aufstehen", datum, zeit)
    with_faellig = time.time() + 2 * 86400                      # Blick in die Zukunft
    gesendet: list[str] = []
    n = erinnerungen.zustellen(gesendet.append, now=with_faellig)
    assert n == 2 and any("⏰" in t and "Aufstehen" in t for t in gesendet)
    assert erinnerungen.alle() == []                            # zugestellt = weg
    # Versand scheitert -> Eintrag bleibt fuer die naechste Runde liegen
    erinnerungen.add("nochmal", datum, zeit)

    def kaputt(_t):
        raise RuntimeError("telegram down")

    assert erinnerungen.zustellen(kaputt, now=with_faellig) == 0
    assert len(erinnerungen.alle()) == 1


def test_deckel(monkeypatch):
    datum, zeit = _morgen()
    monkeypatch.setattr(erinnerungen, "_MAX", 2)
    erinnerungen.add("a", datum, zeit)
    erinnerungen.add("b", datum, zeit)
    _, err = erinnerungen.add("c", datum, zeit)
    assert "offene Erinnerungen" in err


def test_tool_registriert_und_grenzt_ab(monkeypatch):
    from core.agency.tools import termin_tools
    from core.agency.tools import registry

    namen = [t.name for t in registry.all_tools(include_disabled=True)]
    assert "erinnerung" in namen
    desc = next(t for t in registry.all_tools(include_disabled=True)
                if t.name == "erinnerung").description
    assert "EINMALIGEN" in desc and "cron_add" in desc and "termin_add" in desc
    datum, zeit = _morgen()
    monkeypatch.setattr(erinnerungen, "telegram_konfiguriert", lambda: True)
    out = termin_tools.erinnerung("Aufstehen", datum, zeit)
    assert out.startswith("Wecker gestellt") and "per Telegram" in out
    out = termin_tools.erinnerung("x", "kaputt", "15:00")
    assert out.startswith("Fehler:") and "TT.MM.JJJJ" in out
    out = termin_tools.erinnerung(text="x", datum=datum, zeit=zeit, quatsch="y")
    assert "kennt nur text, datum, zeit" in out
