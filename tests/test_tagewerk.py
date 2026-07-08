"""Tagewerk (Malen nach Zahlen): was Kira HEUTE getan hat — deterministisch aus Events."""
from __future__ import annotations

import time


def test_tagewerk_aggregiert_heutige_events(monkeypatch):
    from fastapi.testclient import TestClient
    import core.api.server as s
    from core.kernel import events
    from core.agency import approvals
    jetzt = time.time()
    gestern = jetzt - 2 * 86400
    monkeypatch.setattr(events, "recent", lambda limit=900: [
        {"ts": jetzt, "type": "audit", "payload": {"action": "email_send", "target": "kunde@x.de"}},
        {"ts": jetzt, "type": "approval_decided",
         "payload": {"kind": "email_stranger", "status": "approved", "title": "E-Mail an b@y.de"}},
        {"ts": jetzt, "type": "skill_learned", "payload": {"name": "Impressum-Recherche"}},
        {"ts": jetzt, "type": "cron_run", "payload": {"label": "Morgen-Briefing"}},
        {"ts": jetzt, "type": "mission_task_done", "payload": {"score": 90}},
        {"ts": jetzt, "type": "mission_task_done", "payload": {"score": 70}},
        {"ts": jetzt, "type": "task_failed_final", "payload": {}},
        {"ts": jetzt, "type": "self_tick", "payload": {}},
        {"ts": jetzt, "type": "selfdev_applied", "payload": {"file": "core/x.py"}},
        {"ts": jetzt, "type": "doctor_report", "payload": {"ok": True, "problems": []}},
        {"ts": jetzt, "type": "memory_add", "payload": {"kind": "lesson"}},
        {"ts": gestern, "type": "cron_run", "payload": {"label": "ALT — zaehlt nicht"}},
    ])
    monkeypatch.setattr(approvals, "pending", lambda: [{"id": "1"}])
    from core.agency import tagewerk
    monkeypatch.setattr(tagewerk, "today_spend_usd", lambda: 0.42)
    d = TestClient(s.app).get("/api/tagewerk").json()
    assert d["mails"]["anzahl"] == 2 and "kunde@x.de" in d["mails"]["an"]
    assert d["skills"] == {"anzahl": 1, "namen": ["Impressum-Recherche"]}
    assert d["crons"]["anzahl"] == 1 and "ALT — zaehlt nicht" not in d["crons"]["labels"]
    assert d["tasks"] == {"done": 2, "failed": 1, "avg_score": 80.0}
    assert d["selbstverbesserung"]["ticks"] == 1 and d["selbstverbesserung"]["code_edits"] == ["core/x.py"]
    assert d["diagnose"]["ok"] is True
    assert d["lektionen"] == 1 and d["freigaben_offen"] == 1
    assert d["kosten_heute_usd"] == 0.42


def test_tagewerk_leerer_tag_raist_nicht(monkeypatch):
    from fastapi.testclient import TestClient
    import core.api.server as s
    from core.kernel import events
    monkeypatch.setattr(events, "recent", lambda limit=900: [])
    d = TestClient(s.app).get("/api/tagewerk").json()
    assert d["tasks"]["done"] == 0 and d["diagnose"] is None


def test_cockpit_zeigt_tagewerk():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="tagewerk"' in html and "loadTagewerk" in html      # Zentrale-Panel
    assert 'id="ck-tagewerk"' in html                              # Detail im Kira-Tab
