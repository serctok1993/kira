"""Handover-Härtung B: Übergabe-Preflight — grüner Start-Blick.

Prüft, dass die Checkliste Blocker/Warnungen/Todos korrekt aus doctor + MCP-Status +
Wissensbasis ableitet. doctor.check() und die Nachbar-Module werden gemockt, damit der
Test deterministisch ist und keinen echten Selbst-Check fährt."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.kernel import preflight


_GESUND = {
    "routing": {"chat": {"model": "openrouter/x", "fallback": False}},
    "imports": {"fastapi": True, "mcp": True, "playwright": True, "python_multipart": True},
    "npx": True, "ollama": True, "disk_free_gb": 100,
}


def _patch(monkeypatch, doc=None, servers=None, docs=None):
    monkeypatch.setattr(preflight.doctor, "check", lambda test_call=False: dict(doc or _GESUND))
    import core.agency.mcp.registry_bridge as rb
    monkeypatch.setattr(rb, "server_status", lambda: servers if servers is not None else {})
    import core.mind.knowledge as kn
    monkeypatch.setattr(kn, "list_docs", lambda limit=1: docs if docs is not None else [])


def _by(items, label):
    return next(i for i in items if i["label"] == label)


def test_alles_gruen_ist_startklar(monkeypatch):
    _patch(monkeypatch, servers={"github": {"enabled": True, "running": True}},
           docs=[{"id": "x"}])
    r = preflight.check()
    assert r["ready"] is True and r["blockers"] == 0
    assert _by(r["items"], "Modell erreichbar")["state"] == "ok"
    assert _by(r["items"], "MCP-Server")["state"] == "ok"
    assert _by(r["items"], "Wissensbasis")["state"] == "ok"


def test_kaputte_abhaengigkeit_ist_blocker(monkeypatch):
    doc = dict(_GESUND, imports={"fastapi": False, "mcp": True, "playwright": True, "python_multipart": True})
    _patch(monkeypatch, doc=doc)
    r = preflight.check()
    assert r["ready"] is False and r["blockers"] >= 1
    assert _by(r["items"], "Abhaengigkeiten")["state"] == "blocker"


def test_alles_lokal_ohne_ollama_ist_blocker(monkeypatch):
    doc = dict(_GESUND, routing={"chat": {"model": "ollama/x", "fallback": True}}, ollama=False)
    _patch(monkeypatch, doc=doc)
    r = preflight.check()
    assert _by(r["items"], "Modell erreichbar")["state"] == "blocker"
    assert r["ready"] is False


def test_alles_lokal_mit_ollama_ist_nur_warnung(monkeypatch):
    doc = dict(_GESUND, routing={"chat": {"model": "ollama/x", "fallback": True}}, ollama=True)
    _patch(monkeypatch, doc=doc)
    r = preflight.check()
    assert _by(r["items"], "Modell erreichbar")["state"] == "warn"
    assert r["ready"] is True                                   # lokal ist kein Blocker


def test_leere_wissensbasis_ist_todo_kein_blocker(monkeypatch):
    _patch(monkeypatch, docs=[])
    r = preflight.check()
    assert _by(r["items"], "Wissensbasis")["state"] == "todo"
    assert r["ready"] is True                                   # optional, blockt nicht


def test_mcp_aktiviert_aber_tot_ist_warnung(monkeypatch):
    _patch(monkeypatch, servers={"github": {"enabled": True, "running": False}})
    r = preflight.check()
    it = _by(r["items"], "MCP-Server")
    assert it["state"] == "warn" and "github" in it["detail"]


def test_kein_npx_ist_warnung(monkeypatch):
    _patch(monkeypatch, doc=dict(_GESUND, npx=False))
    r = preflight.check()
    assert _by(r["items"], "MCP-Laufzeit (npx/node)")["state"] == "warn"


def test_api_preflight_liefert_checkliste(monkeypatch):
    _patch(monkeypatch, servers={}, docs=[{"id": "x"}])
    r = TestClient(s.app).get("/api/preflight").json()
    assert "items" in r and "ready" in r and "blockers" in r
