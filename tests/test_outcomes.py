"""Stufe 2a: Outcome-Ledger + Task-Spalten — offline, Temp-DB, deterministisch."""
from __future__ import annotations

import sqlite3

from core.agency import outcomes
from core.agency.missions import queue
from core.kernel import events


def _use_tmp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (queue, outcomes, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    return db


def test_init_idempotent(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    outcomes.init_outcomes()
    outcomes.init_outcomes()  # zweiter Aufruf darf nicht knallen
    queue.init_queue()
    queue.init_queue()


def test_record_roundtrip_and_replace(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    crit = [{"text": "nennt 3 Quellen", "kind": "judge"}]
    checks = [{"text": "nicht leer", "ok": True, "evidence": "812 Zeichen", "source": "det"}]

    outcomes.record("t1", 1, crit, checks, 55, "retry", feedback="konkreter werden", strategy="standard")
    outcomes.record("t1", 2, crit, checks, 85, "pass", strategy="eskaliert", cost_usd=0.002, duration_s=12.5)

    attempts = outcomes.for_task("t1")
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert attempts[0]["verdict"] == "retry" and attempts[0]["feedback"] == "konkreter werden"
    assert attempts[0]["criteria"] == crit and attempts[0]["checks"] == checks
    assert attempts[1]["score"] == 85 and attempts[1]["strategy"] == "eskaliert"
    assert outcomes.last("t1")["attempt"] == 2

    # Gleicher (task_id, attempt) ueberschreibt -> genau EINE Zeile (Crash-Idempotenz)
    outcomes.record("t1", 2, crit, checks, 90, "pass", strategy="eskaliert")
    attempts = outcomes.for_task("t1")
    assert len(attempts) == 2
    assert attempts[1]["score"] == 90


def test_stats(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    assert outcomes.stats()["attempts"] == 0
    outcomes.record("a", 1, [], [], 80, "pass")
    outcomes.record("b", 1, [], [], 40, "retry")
    outcomes.record("b", 2, [], [], None, "fail")
    s = outcomes.stats()
    assert s["attempts"] == 3 and s["passed"] == 1
    assert s["pass_rate"] == round(1 / 3, 3)
    assert s["avg_score"] == 60.0  # nur Scores != NULL zaehlen


def test_task_new_columns_defaults(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    queue.init_queue()
    tid = queue.add("Recherchiere X", kind="research")
    full = queue.get_task(tid)
    assert full is not None
    assert full["quality_retries"] == 0
    assert full["acceptance"] is None and full["feedback"] is None and full["score"] is None
    assert full["retry_count"] == 0
    assert queue.get_task("gibt-es-nicht") is None


def test_update_task_new_fields(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    queue.init_queue()
    tid = queue.add("Baue Y", kind="produce")
    assert queue.update_task(tid, acceptance='[{"text":"Datei existiert"}]',
                             quality_retries=1, feedback="anders machen", score=42,
                             artifact_path="data/out.py")
    full = queue.get_task(tid)
    assert full["quality_retries"] == 1 and full["score"] == 42
    assert full["feedback"] == "anders machen"
    assert full["artifact_path"] == "data/out.py"
    # Absturz-Zaehler bleibt von Qualitaets-Feldern unberuehrt
    assert full["retry_count"] == 0


def test_migration_from_old_schema(monkeypatch, tmp_path):
    """Bestehende DB mit ALTEM Schema -> init_queue() ruestet Spalten defensiv nach."""
    db = _use_tmp_db(monkeypatch, tmp_path)
    with sqlite3.connect(db) as c:
        c.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, ts REAL NOT NULL, mission TEXT,
                description TEXT NOT NULL, status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 5, result TEXT
            )
            """
        )
        c.execute("INSERT INTO tasks (id, ts, mission, description) VALUES ('alt1', 1.0, 'default', 'Alt-Task')")
    queue.init_queue()
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(tasks)").fetchall()}
    assert {"acceptance", "quality_retries", "feedback", "score", "kind", "artifact_path"} <= cols
    full = queue.get_task("alt1")
    assert full["description"] == "Alt-Task"
    # Alt-Zeilen: nachgeruestete Spalten sind NULL -> Code muss (x or 0) rechnen
    assert full["quality_retries"] in (0, None)
