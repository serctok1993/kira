"""Werkbank PR 5: Gedaechtnis kuratiert — Server-Filter, Batch-Loeschen, kein Scrollfestival."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.kernel import events


def _fake_mem(monkeypatch):
    from core.mind.memory import store as memory
    rows = [
        {"id": "m1", "ts": 3, "role": "partner", "kind": "fact", "text": "Sandra mag Katzen"},
        {"id": "m2", "ts": 2, "role": "user", "kind": "lesson", "text": "Kurz melden"},
        {"id": "m3", "ts": 1, "role": "partner", "kind": "skill", "text": "Leads-Recherche"},
    ]
    monkeypatch.setattr(memory, "recent", lambda limit=80: rows[:limit])
    return memory


def test_memory_filter_und_offset(monkeypatch):
    _fake_mem(monkeypatch)
    cl = TestClient(s.app)
    assert len(cl.get("/api/memory").json()) == 3                     # Alt-Verhalten
    facts = cl.get("/api/memory?kind=fact").json()
    assert [m["id"] for m in facts] == ["m1"]
    users = cl.get("/api/memory?kind=user").json()                    # Rolle als Filter
    assert [m["id"] for m in users] == ["m2"]
    found = cl.get("/api/memory?q=katzen").json()                     # Suche, case-insensitiv
    assert [m["id"] for m in found] == ["m1"]
    page2 = cl.get("/api/memory?limit=1&offset=1").json()             # aeltere laden
    assert [m["id"] for m in page2] == ["m2"]


def test_memory_delete_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    memory = _fake_mem(monkeypatch)
    deleted = []
    monkeypatch.setattr(memory, "delete", lambda mid: deleted.append(mid) or True)
    cl = TestClient(s.app)
    r = cl.post("/api/memory/delete-batch", json={"ids": ["m1", "m3"]}).json()
    assert r["ok"] and r["deleted"] == 2 and deleted == ["m1", "m3"]
    assert any(e["type"] == "memory_deleted_batch" for e in events.recent(5))
    assert not cl.post("/api/memory/delete-batch", json={"ids": []}).json()["ok"]


def test_ui_hat_mehrfachauswahl_und_sticky_editor():
    html = TestClient(s.app).get("/").text
    for marker in ("mem-selbar", "mem-del-batch", "/api/memory/delete-batch", "data-sel",
                   "memSel", ".fedit{position:sticky", "fe.scrollIntoView"):
        assert marker in html, f"fehlt: {marker}"
