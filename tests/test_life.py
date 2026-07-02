"""S5.1: Lebens-Ebene — Domain-Trennung, Todos, Metriken. Offline, Temp-DB."""
from __future__ import annotations

import datetime
import sqlite3

from core.agency.missions import metrics, objectives, queue
from core.agency.tools import life_tools
from core.kernel import events


def _use_tmp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (objectives, queue, metrics, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    objectives.init_objectives()
    queue.init_queue()
    return db


def test_domain_migration_old_rows_default_business(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (objectives, queue, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    with sqlite3.connect(db) as c:  # Alt-Schema OHNE domain
        c.execute(
            """
            CREATE TABLE objectives (
                id TEXT PRIMARY KEY, ts REAL NOT NULL, kind TEXT DEFAULT 'weekly',
                title TEXT NOT NULL, parent_id TEXT, status TEXT DEFAULT 'active',
                progress INTEGER, target_date TEXT, notes TEXT, updated_ts REAL
            )
            """
        )
        c.execute("INSERT INTO objectives (id, ts, title) VALUES ('alt1', 1.0, 'Alt-Ziel')")
    objectives.init_objectives()
    queue.init_queue()
    objs = {o["id"]: o for o in objectives.list_all()}
    assert objs["alt1"]["domain"] == "business"  # Alt-Zeilen sind Business (Heartbeat-Verhalten unveraendert)


def test_list_active_domain_filter(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    b = objectives.add("Business-Ziel", domain="business")
    l = objectives.add("Abnehmen auf 85kg", kind="big", domain="leben")
    done = objectives.add("Fertig", domain="leben")
    objectives.update(done, status="done")
    objectives.add("Quatsch-Domain", domain="quatsch")  # wird zu business geklemmt

    biz = [o["id"] for o in objectives.list_active(domain="business")]
    leben = [o["id"] for o in objectives.list_active(domain="leben")]
    assert b in biz and l not in biz
    assert l in leben and done not in leben
    assert len(objectives.list_active()) == 3  # ohne Filter: alle aktiven


def test_todo_add_buckets_and_done(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    out = life_tools.todo_add("Zahnarzt anrufen", due="heute", prio="1")
    assert "Todo notiert" in out and datetime.date.today().isoformat() in out
    life_tools.todo_add("Steuer vorbereiten", due="woche")
    life_tools.todo_add("Irgendwann: Keller", due="")

    board = queue.board("leben")
    assert len(board["today"]) == 1 and "Zahnarzt" in board["today"][0]["description"]
    assert len(board["week"]) == 1
    assert len(board["later"]) == 1
    # Business-Queue bleibt leer — Lebens-Todos sind fuer den Heartbeat unsichtbar
    assert queue.pending("Wachstum") == []

    listing = life_tools.todo_list()
    assert "HEUTE" in listing and "Zahnarzt" in listing
    tid8 = board["today"][0]["id"][:8]
    assert "Abgehakt" in life_tools.todo_done(tid8)
    assert "Zahnarzt" not in life_tools.todo_list()


def test_todo_done_ambiguous_is_safe(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    life_tools.todo_add("A")
    life_tools.todo_add("B")
    out = life_tools.todo_done("")  # matcht beide -> nichts abhaken
    assert "Kein eindeutiges" in out


def test_objective_add_tool(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    out = life_tools.objective_add("10k mit Ventures verdienen", kind="big",
                                   domain="leben", target_date="2026-12-31")
    assert "leben/big" in out and "2026-12-31" in out
    assert len(objectives.list_active(domain="leben")) == 1


def test_metrics_log_series_delta(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    assert "Notiert" in life_tools.metric_log("Gewicht", "92,0")  # Komma-Toleranz
    out = life_tools.metric_log("gewicht", "91.4")
    assert "-0.6" in out  # Delta zum Vorwert
    assert "braucht eine Zahl" in life_tools.metric_log("gewicht", "viel")

    s = metrics.series("gewicht")
    assert [e["value"] for e in s] == [92.0, 91.4]
    latest = metrics.latest()
    assert latest[0]["name"] == "gewicht" and latest[0]["delta"] == -0.6
    assert "gewicht" in life_tools.metric_list()
    assert "92.0 -> 91.4" in life_tools.metric_list(name="gewicht")
