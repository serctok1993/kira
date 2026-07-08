"""Werkbank PR 2a: 'An Kira zu diesem Projekt' — Auftrag laeuft in der Projekt-Session
(Briefing/Kontext injiziert), plus Inline-Aufgabe in der Projekt-Akte."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.kernel import events


def test_direktive_now_nutzt_projekt_session(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    seen = {}

    def fake_act(prompt, session_id=None, escalate=False, **k):
        seen.update(prompt=prompt, session_id=session_id)
        return {"text": "erledigt"}

    import core.agency.act as act_mod
    monkeypatch.setattr(act_mod, "act", fake_act)
    cl = TestClient(s.app)

    r = cl.post("/api/direktive/now", json={"prompt": "Leads pruefen", "venture_id": "abc123"}).json()
    assert r["ok"] and r["result"] == "erledigt"
    assert seen["session_id"] == "venture-abc123"      # Projekt-Kontext-Session
    ev = [e for e in events.recent(5) if e["type"] == "direktive_now"][0]
    assert ev["payload"]["venture_id"] == "abc123"

    cl.post("/api/direktive/now", json={"prompt": "ohne Projekt"})
    assert seen["session_id"] == "direktive"           # Alt-Verhalten unveraendert


def test_cockpit_hat_projekt_werkbank_felder():
    html = TestClient(s.app).get("/").text
    for marker in ("ak-cmd-go", "AN KIRA ZU DIESEM PROJEKT", "ak-task-add", "venture_id:v.id"):
        assert marker in html, f"fehlt: {marker}"
