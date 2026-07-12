"""Testumgebung — Fundament (Tier 1a): Sandbox-Praedikate + ephemere Test-Sessions.

Ephemer heisst: ein Test-/Benchmark-Chat (sid-Praefix 'test-'/'bench-') erinnert sich an SICH
selbst, leckt aber NIE in das Cross-Session-Gedaechtnis (recall) anderer Sessions — so kann der Nutzer
gefahrlos testen, ohne den echten Erinnerungsstrang zu verfaelschen.
"""
from __future__ import annotations


def _tmp(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()
    return store


# ---- Praedikate ------------------------------------------------------------------------

def test_praedikate(monkeypatch):
    import core.config as cfg
    # Ohne jede Env: alles False (Live-Verhalten byte-identisch)
    monkeypatch.delenv("KIRA_TEST_MODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("KIRA_ROOT", raising=False)
    monkeypatch.delenv("KIRA_DATA_DIR", raising=False)
    assert cfg.test_mode() is False
    assert cfg.sandbox_active() is False
    assert cfg.suppress_repo_writes() is False
    # Testmodus an: suppress an (blankes pytest fasst Git/Verify nicht an)
    monkeypatch.setenv("KIRA_TEST_MODE", "1")
    assert cfg.test_mode() is True and cfg.suppress_repo_writes() is True
    # Aktive Sandbox (eigener Datenpfad): suppress AUS -> Git/Verify laufen real (im Worktree)
    monkeypatch.setenv("KIRA_DATA_DIR", "/tmp/whatever")
    assert cfg.sandbox_active() is True and cfg.suppress_repo_writes() is False


# ---- Ephemere Sessions -----------------------------------------------------------------

def test_test_chat_leckt_nicht_in_andere_sessions(monkeypatch, tmp_path):
    store = _tmp(monkeypatch, tmp_path)
    store.remember("geheimer testbug xyzzy", role="user", kind="episodic", session_id="test-abc")
    store.remember("Luxex faktum planitzki", role="user", kind="episodic", session_id="real-1")
    # recall aus einer ANDEREN Session: der Test-Chat darf NICHT auftauchen
    res = store.recall("testbug xyzzy planitzki", limit=10, exclude_session="egal")
    sids = [(r.get("session_id") or "") for r in res]
    assert all(not s.startswith(("test-", "bench-")) for s in sids), sids
    # aber die echte Session ist erinnerbar
    assert any(s == "real-1" for s in sids)


def test_test_chat_erinnert_sich_an_sich_selbst(monkeypatch, tmp_path):
    store = _tmp(monkeypatch, tmp_path)
    store.remember("erste testnachricht", role="user", kind="episodic", session_id="test-xy")
    store.remember("kira antwortet im test", role="partner", kind="episodic", session_id="test-xy")
    hist = store.recent_dialogue("test-xy", limit=10)
    assert [h["text"] for h in hist] == ["erste testnachricht", "kira antwortet im test"]


def test_reset_raeumt_ephemere_mit(monkeypatch, tmp_path):
    store = _tmp(monkeypatch, tmp_path)
    store.remember("test kram", role="user", kind="episodic", session_id="test-abc")
    store.remember("echtes gespraech", role="user", kind="episodic", session_id="real-1")
    store.remember("Mia wohnt in Berlin", role="system", kind="semantic")
    res = store.reset_episodic(backup=False)
    assert res["deleted"] == 2  # beide episodischen (Test + real) weg
    assert res["kept"] == 1     # Fakt bleibt


def test_cockpit_hat_test_chat_knopf():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="sess-test"' in html          # der 🧪-Knopf im Gespraeche-Panel
    assert "newTestSession" in html          # und sein Handler (sid mit test-Praefix)
