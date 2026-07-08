"""Ideen-Takt (Sergens Regel 08.07.): Ideen als Wochenaufgabe — Bericht alle N Tage
mit M Ideen (Default 7 Tage / 2 Ideen), im Cockpit einstellbar."""
from __future__ import annotations

import json

from core.agency import radar
from core.kernel import events


def _setup(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    monkeypatch.setattr(radar, "DB_PATH", db)
    monkeypatch.setattr(events, "DB_PATH", db)
    events.init_db()
    radar.init_radar()


def test_takt_defaults_und_clamping(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert radar.get_takt() == {"intervall_tage": 7, "max_ideen": 2}   # Sergens Standard
    t = radar.set_takt(intervall_tage=14, max_ideen=1)
    assert t == {"intervall_tage": 14, "max_ideen": 1}
    assert radar.get_takt() == t                                       # persistent
    assert radar.set_takt(intervall_tage=99, max_ideen=99) == {"intervall_tage": 30, "max_ideen": 6}
    assert radar.set_takt(intervall_tage="quatsch") == {"intervall_tage": 30, "max_ideen": 6}


def test_scan_bericht_folgt_takt(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    radar.set_takt(intervall_tage=7, max_ideen=2)
    monkeypatch.setattr(radar, "_gather", lambda themes: "x" * 200)
    monkeypatch.setattr(radar.llm_router, "complete", lambda *a, **k: {"text": json.dumps([
        {"title": "Idee Alpha mit Substanz", "hypothesis": "Handwerker zahlen fuer Termin-Bots",
         "first_step": "3 Handwerker anrufen und fragen", "score": 90},
        {"title": "Idee Beta mit Substanz", "hypothesis": "Laeden brauchen Review-Automatik",
         "first_step": "Landingpage bauen", "score": 80},
        {"title": "Idee Gamma mit Substanz", "hypothesis": "dritte Idee", "score": 70},
    ])})
    sent = []
    from core.agency.missions import cron
    monkeypatch.setattr(cron, "_notify", lambda text: sent.append(text))

    res = radar.scan(notify=True)
    assert res["found"] == 3                                # Pipeline bekommt alle
    assert len(sent) == 1
    msg = sent[0]
    assert "2 Idee(n) alle 7 Tage" in msg
    assert "Idee Alpha" in msg and "Idee Beta" in msg
    assert "Idee Gamma" not in msg                          # Bericht kappt auf max_ideen
    assert "Erster Schritt: 3 Handwerker anrufen" in msg    # direkter Umsetzungs-Tipp
    assert "Cockpit" in msg


def test_first_step_landet_in_notes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(radar, "_gather", lambda themes: "x" * 200)
    monkeypatch.setattr(radar.llm_router, "complete", lambda *a, **k: {"text": json.dumps([
        {"title": "Idee mit erstem Schritt", "hypothesis": "h",
         "first_step": "Demo bei einem Kunden zeigen", "score": 60}])})
    radar.scan(notify=False)
    o = radar.list_all()[0]
    assert o["notes"] == "Erster Schritt: Demo bei einem Kunden zeigen"


def test_runner_nutzt_takt_intervall(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    radar.set_takt(intervall_tage=10)
    assert radar.get_takt()["intervall_tage"] * 86400 == 10 * 86400


def test_api_takt_endpoints(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import core.api.server as s
    _setup(monkeypatch, tmp_path)
    cl = TestClient(s.app)
    r = cl.post("/api/radar/takt", json={"intervall_tage": 7, "max_ideen": 2}).json()
    assert r["ok"] and r["intervall_tage"] == 7 and r["max_ideen"] == 2
    assert cl.get("/api/radar/takt").json() == {"intervall_tage": 7, "max_ideen": 2}


def test_cockpit_hat_takt_einstellung():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="rd-takt-tage"' in html and 'id="rd-takt-ideen"' in html
    assert "/api/radar/takt" in html
