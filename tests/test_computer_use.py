"""Macht-Schritt 1: Computer-Use (Bildschirm sehen + Maus/Tastatur/Fenster steuern).

Kern-Sicherheit: Standard AUS, Not-Aus blockt, Testmodus fasst den echten Rechner NIE
an (simuliert nur), jede Aktion wird auditiert. Die OS-Aufrufe selbst werden hier nicht
ausgefuehrt — getestet werden Gate, Parsing und die Simulations-Pfade."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.agency import computer
from core.agency.tools import registry


def _enable(monkeypatch, on=True):
    monkeypatch.setattr(computer, "_enabled", lambda: on)
    monkeypatch.setattr(computer, "_IS_WIN", True)  # Gate soll nicht an der Plattform scheitern


# ---------- Gate ----------

def test_standard_aus_blockt_alles(monkeypatch):
    monkeypatch.setattr(computer, "_enabled", lambda: False)
    for out in (computer.bildschirm_foto(), computer.maus_klick(10, 10),
                computer.tippen("hi"), computer.taste("enter"),
                computer.fenster_liste(), computer.fenster_fokus("x")):
        assert "AUS" in out or "Steuerpult" in out


def test_not_aus_blockt(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr("core.kernel.scheduler.kill_switch_active", lambda: True)
    assert "Not-Aus" in computer.maus_klick(5, 5)


def test_off_windows_klarer_hinweis(monkeypatch):
    monkeypatch.setattr(computer, "_enabled", lambda: True)
    monkeypatch.setattr(computer, "_IS_WIN", False)
    monkeypatch.setattr("core.kernel.scheduler.kill_switch_active", lambda: False)
    assert "Windows" in computer.taste("ctrl+s")


# ---------- Testmodus fasst den Rechner nie an ----------

def test_testmodus_simuliert_nur(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr("core.kernel.scheduler.kill_switch_active", lambda: False)
    monkeypatch.setattr(computer, "test_mode", lambda: True)
    # wuerde eine echte OS-Funktion laufen, wuerde dieser Sabotage-Patch das Testergebnis kippen
    monkeypatch.setattr(computer, "_do_click", lambda *a: (_ for _ in ()).throw(AssertionError("echter Klick!")))
    monkeypatch.setattr(computer, "_do_type", lambda *a: (_ for _ in ()).throw(AssertionError("echtes Tippen!")))
    assert "Testmodus" in computer.maus_klick(100, 200)
    assert "Testmodus" in computer.tippen("geheim")
    assert "Testmodus" in computer.taste("ctrl+s")


def test_klick_auditiert(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr("core.kernel.scheduler.kill_switch_active", lambda: False)
    monkeypatch.setattr(computer, "test_mode", lambda: True)
    seen = []
    monkeypatch.setattr(computer.events, "emit", lambda t, p=None, **k: seen.append((t, p or {})))
    computer.maus_klick(3, 7, button="rechts", doppel="1")
    assert seen and seen[0][0] == "computer_use"
    assert seen[0][1]["button"] == "right" and seen[0][1]["doppel"] is True


# ---------- Tasten-Parsing ----------

def test_parse_keys():
    assert computer._parse_keys("ctrl+s") == [0x11, 0x53]
    assert computer._parse_keys("Ctrl+Shift+Esc") == [0x11, 0x10, 0x1B]
    assert computer._parse_keys("enter") == [0x0D]
    assert computer._parse_keys("bloedsinn+quatsch") == []      # nichts Erkanntes -> leer


def test_taste_unbekannt_meldet(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr("core.kernel.scheduler.kill_switch_active", lambda: False)
    monkeypatch.setattr(computer, "test_mode", lambda: False)
    assert "nicht erkannt" in computer.taste("gibtsnicht")


def test_klick_braucht_zahlen(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr("core.kernel.scheduler.kill_switch_active", lambda: False)
    assert "Zahlen" in computer.maus_klick("links", "rechts")


# ---------- Registrierung + Steuerpult-Gate ----------

def test_werkzeuge_registriert():
    # S12: feature desktop_low_level ist standardmaessig AUS -> get() filtert die Werkzeuge
    # aus dem Manifest; registriert bleiben sie (Flag an holt sie ohne Neustart zurueck).
    namen = {t.name for t in registry.all_tools(include_disabled=True)}
    for name in ("bildschirm_foto", "maus_klick", "maus_bewegen", "tippen", "taste",
                 "fenster_liste", "fenster_fokus"):
        assert name in namen, f"{name} nicht registriert"
        assert registry.get(name) is None, f"{name} muesste bei Flag aus gefiltert sein"


def test_steuerpult_zeigt_und_schaltet_computer_use(tmp_path, monkeypatch):
    # frische Override-Datei, damit der Test nichts Echtes umstellt
    monkeypatch.setattr("core.config._OVERRIDE_FILE", tmp_path / "ov.json")
    c = TestClient(s.app)
    r = c.get("/api/steuer").json()
    assert "computer_use" in r                                  # Flag im Steuerpult sichtbar
    ok = c.post("/api/config/set", json={"path": "agency.computer_use.enabled", "value": True}).json()
    assert ok.get("ok") is True                                 # steht auf der Whitelist


def test_computer_use_gilt_als_aktion():
    from core.kernel import events
    assert events.severity("computer_use") == "action"
