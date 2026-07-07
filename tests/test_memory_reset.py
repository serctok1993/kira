"""Erinnerungs-Reset: der episodische Gespraechsstrang laesst sich sauber auf null setzen
(mit Backup), waehrend Fakten (semantic) und Skills (procedural) garantiert bleiben.
"""
from __future__ import annotations


def _tmp(monkeypatch, tmp_path):
    import core.config as cfg
    from core.mind.memory import store
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path))
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()
    return store


def test_reset_loescht_nur_episodic_mit_backup(monkeypatch, tmp_path):
    store = _tmp(monkeypatch, tmp_path)
    store.remember("hallo, wie gehts", role="user", kind="episodic", session_id="s1")
    store.remember("alter bug im widget", role="user", kind="episodic", session_id="s2")
    store.remember("Sergen wohnt in Koblenz", role="system", kind="semantic")
    store.remember("Skill: leads recherchieren", role="system", kind="procedural")

    res = store.reset_episodic(backup=True)

    assert res["deleted"] == 2       # beide episodischen weg
    assert res["kept"] == 2          # Fakt + Skill bleiben
    # Backup existiert und enthaelt die geloeschten Zeilen
    from pathlib import Path
    bp = Path(res["backup"])
    assert bp.exists() and "alter bug im widget" in bp.read_text(encoding="utf-8")
    # semantisches/prozedurales Wissen ist technisch garantiert noch da
    with store._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM memory WHERE kind='episodic'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM memory WHERE kind='semantic'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM memory WHERE kind='procedural'").fetchone()[0] == 1


def test_reset_ohne_zeilen_kein_backup(monkeypatch, tmp_path):
    store = _tmp(monkeypatch, tmp_path)
    res = store.reset_episodic(backup=True)
    assert res["deleted"] == 0 and res["backup"] == ""


def test_endpoint_confirm_gesichert(monkeypatch):
    from starlette.testclient import TestClient
    from core.api import server
    calls = []
    monkeypatch.setattr(server.memory, "reset_episodic",
                        lambda backup=True: calls.append(1) or {"deleted": 5, "backup": "x", "kept": 3})
    client = TestClient(server.app)
    # ohne confirm: nichts passiert
    r1 = client.post("/api/memory/reset-episodic", json={})
    assert r1.json()["ok"] is False and not calls
    # mit confirm: fuehrt aus
    r2 = client.post("/api/memory/reset-episodic", json={"confirm": True})
    assert r2.json()["ok"] is True and r2.json()["deleted"] == 5 and calls == [1]
