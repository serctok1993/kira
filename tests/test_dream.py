"""P7 (dream): gegatete Verdichtung episodisch -> dauerhaft (kind='dream').

Cheapest gate first (enabled -> reife Sessions -> Lock), konservatives Loeschen
(nur bei sauberer Modell-Antwort, immer mit jsonl-Backup). Offline: tmp-DB,
tmp-DATA_DIR, LLM + Embeddings gemockt.
"""
from __future__ import annotations

import time

import pytest

from core.mind import dream
from core.mind.memory import store


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    store.init_memory()
    monkeypatch.setattr(dream, "DATA_DIR", tmp_path)
    monkeypatch.setattr(dream, "_LOCK", tmp_path / "dream.lock")
    import core.mind.memory.embed as embed
    monkeypatch.setattr(embed, "embed", lambda text: None)   # kein Ollama im Test
    return tmp_path


def _alte_session(sid: str, texte: list[str], alter_s: int = 3 * 86400):
    for i, t in enumerate(texte):
        store.remember(t, role="user" if i % 2 == 0 else "partner",
                       kind="episodic", session_id=sid)
    with store._conn() as c:                                  # kuenstlich altern
        c.execute("UPDATE memory SET ts=? WHERE session_id=?", (time.time() - alter_s, sid))


def _mock_llm(monkeypatch, antwort: str):
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "complete",
                        lambda *a, **k: {"text": antwort, "model": "mock"})


def test_gates_cheapest_first(monkeypatch):
    monkeypatch.setitem(dream.CONFIG, "dream", {"enabled": False})
    assert "enabled" in dream.dream()["grund"]
    monkeypatch.setitem(dream.CONFIG, "dream", {"enabled": True, "min_sessions": 3})
    _alte_session("s1", ["hallo", "hi"])                      # nur 1 reife Session
    out = dream.dream()
    assert not out["gelaufen"] and "reife Sessions" in out["grund"]
    # Lock: frischer Fremd-Lock blockiert auch force
    assert dream._lock_setzen()
    assert "Lock" in dream.dream(force=True)["grund"]
    dream._lock_loesen()


def test_verdichtet_loescht_und_sichert(monkeypatch, tmp_path):
    monkeypatch.setitem(dream.CONFIG, "dream", {"enabled": True, "min_sessions": 1})
    _alte_session("alt-1", ["mein Lieblingsessen ist Lasagne", "gemerkt!"])
    _alte_session("jung", ["laufendes Gespraech"], alter_s=60)   # zu jung -> bleibt
    _mock_llm(monkeypatch, "KERN: Der Nutzer isst am liebsten Lasagne.")
    out = dream.dream()
    assert out["gelaufen"] and out["sessions"] == 1 and out["kerne"] == 1
    assert out["geloescht"] == 2 and out["backup"]
    assert (tmp_path / "backups").glob("dream-*.jsonl")
    kerne = [m for m in store.recent(20) if m["kind"] == "dream"]
    assert len(kerne) == 1 and "Lasagne" in kerne[0]["text"]
    assert store.count_by_kind("episodic") == 1                  # nur die junge Session
    assert not dream._LOCK.exists()                              # Lock wieder frei


def test_nichts_loescht_muell_ohne_kern(monkeypatch):
    monkeypatch.setitem(dream.CONFIG, "dream", {"enabled": True, "min_sessions": 1})
    _alte_session("muell", ["asdf", "test test", "asdf?"])
    _mock_llm(monkeypatch, "NICHTS")
    out = dream.dream()
    assert out["gelaufen"] and out["kerne"] == 0 and out["geloescht"] == 3
    assert store.count_by_kind("dream") == 0                     # kein Pseudo-Kern


def test_unsaubere_antwort_laesst_alles_stehen(monkeypatch):
    monkeypatch.setitem(dream.CONFIG, "dream", {"enabled": True, "min_sessions": 1})
    _alte_session("alt-2", ["wichtiger Fakt", "ok"])
    _mock_llm(monkeypatch, "Also ich denke, das Gespraech war ganz nett...")
    out = dream.dream()
    assert out["gelaufen"] and out["geloescht"] == 0             # konservativ: nichts fiel
    assert store.count_by_kind("episodic") == 2


def test_ephemere_sessions_bleiben_unangetastet(monkeypatch):
    monkeypatch.setitem(dream.CONFIG, "dream", {"enabled": True, "min_sessions": 1})
    _alte_session("test-abc", ["benchmark chatter", "ok"])
    _mock_llm(monkeypatch, "KERN: nie erreichbar")
    out = dream.dream()
    assert not out["gelaufen"] and "reife" in out["grund"].lower()


def test_api_dream_force(monkeypatch):
    import core.api.server as s
    from fastapi.testclient import TestClient

    monkeypatch.setitem(dream.CONFIG, "dream", {"enabled": False})  # force ignoriert enabled
    _alte_session("alt-3", ["Projekt X startet Montag", "notiert"])
    _mock_llm(monkeypatch, "KERN: Projekt X startet am Montag.")
    r = TestClient(s.app).post("/api/dream").json()
    assert r["gelaufen"] and r["sessions"] == 1
