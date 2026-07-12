"""Werkbank PR 8: Widget-System — Kira liefert CONFIG (data/widgets/*.json), nie Code.
Drei feste Renderer (metric/chart/list), Endpoint-Whitelist, Slots zentrale/projekt/serc."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import core.api.server as s
from core.agency import widgets
from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.script import SCRIPT
from core.api.ui.views import VIEWS


def _dir(monkeypatch, tmp_path):
    monkeypatch.setattr(widgets, "DIR", tmp_path / "widgets")


# ---------- Validierung: die einzige Tuer ----------

def test_validate_lehnt_fremdes_ab():
    ok = {"id": "follower", "title": "Follower", "type": "metric",
          "slot": "zentrale", "metric": "follower"}
    assert widgets.validate(ok) == ""
    assert "type" in widgets.validate({**ok, "type": "iframe"})        # kein 4. Renderer
    assert "slot" in widgets.validate({**ok, "slot": "ueberall"})
    assert "id" in widgets.validate({**ok, "id": "../../etc/passwd"})  # kein Traversal
    assert "metric" in widgets.validate({"id": "x1", "title": "T", "type": "chart",
                                         "slot": "serc"})              # Kennzahl Pflicht
    lst = {"id": "heute", "title": "Heute", "type": "list", "slot": "serc",
           "endpoint": "/api/digest", "key": "tasks_done"}
    assert widgets.validate(lst) == ""
    assert "whitelisted" in widgets.validate({**lst, "endpoint": "/api/keys"})
    assert "whitelisted" in widgets.validate({**lst, "endpoint": "https://boese.de"})


def test_save_schreibt_nur_bekannte_felder(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    res = widgets.save({"id": "follower", "title": "Follower", "type": "metric",
                        "slot": "zentrale", "metric": "Follower",
                        "html": "<script>alert(1)</script>"})          # Fremdfeld
    assert res["ok"]
    raw = json.loads((tmp_path / "widgets" / "follower.json").read_text(encoding="utf-8"))
    assert "html" not in raw and raw["metric"] == "follower"           # bereinigt + normalisiert
    assert widgets.save({"id": "boese", "title": "X", "type": "list", "slot": "serc",
                         "endpoint": "/api/kill", "key": "x"})["ok"] is False


def test_list_demo_und_lebenszyklus(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    ws = widgets.list_all()                                            # noch nie angefasst: Demo
    assert len(ws) == 1 and ws[0]["id"] == "demo-follower" and ws[0].get("demo")
    assert widgets.delete("demo-follower") is True                     # Demo abwaehlbar
    assert widgets.list_all() == []                                    # und bleibt weg
    widgets.save({"id": "follower", "title": "F", "type": "metric",
                  "slot": "zentrale", "metric": "follower"})
    (tmp_path / "widgets" / "kaputt.json").write_text("{nicht json", encoding="utf-8")
    (tmp_path / "widgets" / "boese.json").write_text(
        json.dumps({"id": "boese", "title": "X", "type": "iframe", "slot": "zentrale"}),
        encoding="utf-8")
    assert [w["id"] for w in widgets.list_all()] == ["follower"]       # kaputt/boese fliegen raus
    assert widgets.delete("follower") is True and widgets.list_all() == []


# ---------- API ----------

def test_api_widgets(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    c = TestClient(s.app)
    r = c.get("/api/widgets").json()
    assert r["types"] == ["metric", "chart", "list"] and "zentrale" in r["slots"]
    assert r["widgets"][0]["id"] == "demo-follower"
    assert c.post("/api/widgets/save", json={"id": "heute", "title": "Heute", "type": "list",
                                             "slot": "serc", "endpoint": "/api/digest",
                                             "key": "tasks_done"}).json()["ok"]
    assert c.post("/api/widgets/save", json={"id": "x", "title": "X", "type": "eval",
                                             "slot": "serc"}).json()["ok"] is False
    assert c.post("/api/widgets/delete", json={"id": "heute"}).json()["ok"]


# ---------- Kira-Werkzeuge: Config, nie Code ----------

def test_widget_tools(monkeypatch, tmp_path):
    _dir(monkeypatch, tmp_path)
    from core.agency.tools import widget_tools
    out = widget_tools.widget_add("follower", "📈 Follower", "metric", "zentrale",
                                  metric="follower")
    assert "eingeblendet" in out
    assert "abgelehnt" in widget_tools.widget_add("h4x", "X", "script", "zentrale")
    assert "entfernt" in widget_tools.widget_weg("follower")
    assert "Kein Widget" in widget_tools.widget_weg("follower")
    from core.agency.tools import registry
    assert registry.get("widget_add") and registry.get("widget_weg")   # im Manifest


# ---------- Cockpit: Slots + sicherer Renderer ----------

def test_slots_und_renderer_markup():
    for slot in ('id="widgets-home"', 'id="widgets-serc"'):
        assert slot in VIEWS, f"Widget-Slot fehlt: {slot}"
    assert "async function loadWidgets(" in SCRIPT and "async function renderWidget(" in SCRIPT
    # Client prueft die Whitelist nochmal (Defense in depth) und escaped alles
    assert 'const W_ENDPOINTS=["/api/digest","/api/tagewerk","/api/status","/api/evolution"]' in SCRIPT
    assert "W_ENDPOINTS.includes(w.endpoint)" in SCRIPT
    assert "esc(w.title||w.id)" in SCRIPT
    # in allen drei Bereichen verdrahtet
    assert 'loadWidgets("zentrale","#widgets-home")' in SCRIPT
    assert 'loadWidgets("serc","#widgets-serc")' in SCRIPT
    assert ".wslot{display:grid" in CSS and ".wslot:empty{display:none}" in CSS
