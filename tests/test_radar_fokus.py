"""S10: Radar-Fokus — Sergen/Kira legen fest, wonach das Ideen-Radar sucht (persistent).
Offline, Temp-DB, kein LLM/Netz.
"""
from __future__ import annotations

from core.agency import radar
from core.agency.tools import radar_tools


def _tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(radar, "DB_PATH", str(tmp_path / "state.db"))
    radar.init_radar()


def test_fokus_leer_faellt_auf_default(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    assert radar.get_focus() == []
    assert radar._themes() == list(radar._DEFAULT_THEMES)   # Default greift


def test_fokus_setzen_text_und_liste(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    out = radar.set_focus("KI-Tools fuer Handwerker; Social-Media fuer Laeden\nNischen-Automation")
    assert out == ["KI-Tools fuer Handwerker", "Social-Media fuer Laeden", "Nischen-Automation"]
    assert radar.get_focus() == out
    assert radar._themes() == out                           # Fokus schlaegt Default
    # ueberschreiben per Liste
    radar.set_focus(["nur eins"])
    assert radar.get_focus() == ["nur eins"]


def test_fokus_kappt_bei_acht(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    out = radar.set_focus(";".join(f"t{i}" for i in range(20)))
    assert len(out) == 8


def test_radar_fokus_werkzeug(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    leer = radar_tools.radar_fokus("")
    assert "kein eigener Fokus" in leer
    gesetzt = radar_tools.radar_fokus("Handwerker-KI; lokale Laeden")
    assert "Handwerker-KI" in gesetzt and "lokale Laeden" in gesetzt
    assert radar.get_focus() == ["Handwerker-KI", "lokale Laeden"]
    # ohne Argument zeigt er jetzt den aktuellen Fokus
    assert "Aktueller Radar-Fokus" in radar_tools.radar_fokus("")


def test_scan_nutzt_fokus_als_themen(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    radar.set_focus("thema-A; thema-B")
    seen = {}

    def fake_gather(themes):
        seen["themes"] = themes
        return ""                                           # zu kurz -> scan bricht danach ab

    monkeypatch.setattr(radar, "_gather", fake_gather)
    radar.scan(notify=False)
    assert seen["themes"] == ["thema-A", "thema-B"]


# ---- Cockpit-Endpoints ------------------------------------------------------------------

def _client(monkeypatch, tmp_path):
    from starlette.testclient import TestClient
    from core.api import server
    monkeypatch.setattr(radar, "DB_PATH", str(tmp_path / "state.db"))
    radar.init_radar()
    return TestClient(server.app)


def test_api_focus_get_set(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    d = c.get("/api/radar/focus").json()
    assert d["themes"] == [] and d["default"] is True
    r = c.post("/api/radar/focus", json={"themes": "alpha; beta"}).json()
    assert r["ok"] is True and r["themes"] == ["alpha", "beta"]
    d2 = c.get("/api/radar/focus").json()
    assert d2["themes"] == ["alpha", "beta"] and d2["default"] is False
