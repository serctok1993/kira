"""S10: Ziele-Dashboard — Metrik-Metadaten (Zielwert/Einheit/Emoji/Anheftung),
Kira-Schreibzugriff (metric_ziel-Werkzeug) und die Cockpit-Endpoints. Offline, Temp-DB.
"""
from __future__ import annotations

from core.agency.missions import metrics
from core.agency.tools import life_tools


def _tmp(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    monkeypatch.setattr(metrics, "DB_PATH", db)
    metrics.init_metrics()
    return db


# ---- Datenmodell: Meta + Dashboard + Fortschritt ---------------------------------------

def test_meta_setzen_und_lesen(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    metrics.set_meta("follower", pinned=True, target=10000, unit="Abos", emoji="📈")
    m = metrics.get_meta("follower")
    assert m["pinned"] == 1 and m["target"] == 10000.0
    assert m["unit"] == "Abos" and m["emoji"] == "📈"


def test_meta_none_laesst_unveraendert(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    metrics.set_meta("x", target=50, unit="kg")
    metrics.set_meta("x", pinned=True)                 # nur pinnen, Rest bleibt
    m = metrics.get_meta("x")
    assert m["pinned"] == 1 and m["target"] == 50.0 and m["unit"] == "kg"
    metrics.set_meta("x", target="")                   # "" loescht den Zielwert
    assert metrics.get_meta("x")["target"] is None


def test_dashboard_rechnet_fortschritt_und_sortiert(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    metrics.log("follower", 1200)
    metrics.log("follower", 1450)
    metrics.log("gewicht", 91.0)
    metrics.set_meta("follower", pinned=True, target=10000, unit="Abos", emoji="📈")
    dash = metrics.dashboard()
    assert dash[0]["name"] == "follower"               # angeheftet zuerst
    f = dash[0]
    assert f["value"] == 1450.0 and f["delta"] == 250.0
    assert f["progress"] == 14                          # 1450/10000
    assert f["series"] == [1200.0, 1450.0]
    assert [d["name"] for d in metrics.pinned()] == ["follower"]


def test_kein_ziel_kein_fortschritt(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    metrics.log("schlaf", 7)
    d = metrics.dashboard()[0]
    assert d["progress"] is None and d["target"] is None and d["pinned"] is False


# ---- Kira schreibt selbst: metric_ziel-Werkzeug ----------------------------------------

def test_metric_ziel_setzt_und_heftet_an(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    metrics.log("follower", 1450)
    out = life_tools.metric_ziel("follower", ziel="10000", einheit="Abos",
                                 emoji="📈", zentrale="ja")
    assert "angeheftet" in out
    assert [d["name"] for d in metrics.pinned()] == ["follower"]
    m = metrics.get_meta("follower")
    assert m["target"] == 10000.0 and m["unit"] == "Abos"


def test_metric_ziel_loest_aus_zentrale(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    metrics.set_meta("follower", pinned=True, target=10000)
    out = life_tools.metric_ziel("follower", zentrale="nein")
    assert "geloest" in out
    assert metrics.pinned() == []


def test_metric_ziel_meckert_bei_krummer_zahl(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    assert "keine Zahl" in life_tools.metric_ziel("x", ziel="viele")
    assert "Welche Kennzahl" in life_tools.metric_ziel("")


# ---- Cockpit-Endpoints ------------------------------------------------------------------

def _client(monkeypatch, tmp_path):
    from starlette.testclient import TestClient
    from core.api import server
    db = str(tmp_path / "state.db")
    monkeypatch.setattr(metrics, "DB_PATH", db)
    metrics.init_metrics()
    return TestClient(server.app)


def test_api_metrics_liefert_dashboard_und_pinned(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/metrics/log", json={"name": "follower", "value": "1450"})
    r = c.post("/api/metrics/meta", json={"name": "follower", "target": "10000",
                                          "unit": "Abos", "emoji": "📈", "pinned": True})
    assert r.json().get("ok") is True
    d = c.get("/api/metrics").json()
    assert "dashboard" in d and "pinned" in d
    assert any(x["name"] == "follower" and x["pinned"] for x in d["dashboard"])
    assert [x["name"] for x in d["pinned"]] == ["follower"]


def test_api_metrics_meta_toggle_und_fehler(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.post("/api/metrics/meta", json={}).json()["ok"] is False        # name fehlt
    assert c.post("/api/metrics/meta", json={"name": "x", "target": "abc"}).json()["ok"] is False
    c.post("/api/metrics/log", json={"name": "x", "value": "5"})
    c.post("/api/metrics/meta", json={"name": "x", "pinned": True})
    assert [p["name"] for p in c.get("/api/metrics").json()["pinned"]] == ["x"]
    c.post("/api/metrics/meta", json={"name": "x", "pinned": False})
    assert c.get("/api/metrics").json()["pinned"] == []
