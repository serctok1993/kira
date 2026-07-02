"""S6.2: Queue termin-bewusst — Ueberfaelliges zuerst, Aufgeschobenes uebersprungen,
Retry-first-Invariante des Runners bleibt erhalten. Offline, Temp-DB."""
from __future__ import annotations

import datetime

from core.agency.missions import queue
from core.kernel import events


def _iso(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (queue, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    queue.init_queue()


def _d(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def test_overdue_beats_priority(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    queue.add("wichtig ohne Termin", mission="m", priority=1)
    tid_due = queue.add("ueberfaellig, niedrige Prio", mission="m", priority=9, due_date=_d(-2))
    p = queue.pending("m")
    assert p[0]["id"] == tid_due  # Termin schlaegt Prioritaet


def test_most_overdue_first(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    a = queue.add("gestern faellig", mission="m", due_date=_d(-1))
    b = queue.add("vor 3 Tagen faellig", mission="m", due_date=_d(-3))
    assert [t["id"] for t in queue.pending("m")] == [b, a]


def test_deferred_skipped_until_date(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    tid = queue.add("aufgeschoben", mission="m")
    queue.defer(tid, _d(3))
    assert queue.pending("m") == []       # Bug-Fix: vorher wurde das trotzdem gezogen
    assert queue.pop_next("m") is None
    queue.defer(tid, _d(0))               # heute faellig -> wieder dran
    assert [t["id"] for t in queue.pending("m")] == [tid]


def test_retry_first_among_undated(monkeypatch, tmp_path):
    """Der Runner-Vertrag: ein requeueter Task (alter ts) kommt vor neuen Tasks
    gleicher Prioritaet — sonst bricht die Qualitaets-Retry-Logik."""
    _iso(monkeypatch, tmp_path)
    old = queue.add("alter Task (Retry)", mission="m")
    popped = queue.pop_next("m")
    assert popped["id"] == old
    queue.add("neuer Task", mission="m")
    queue.update_task(old, status="pending", quality_retries=1)  # Requeue wie im Runner
    assert queue.pending("m")[0]["id"] == old


def test_priority_still_wins_without_due_dates(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    queue.add("normal", mission="m", priority=5)
    trig = queue.add("Trigger-Task", mission="m", priority=3)
    assert queue.pending("m")[0]["id"] == trig


def test_future_due_sorts_within_priority(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    undated = queue.add("ohne Termin", mission="m", priority=5)
    dated = queue.add("in 3 Tagen", mission="m", priority=5, due_date=_d(3))
    # gleiche Prio: terminierte Aufgabe vor unterminierter, aber NICHT vor hoeherer Prio
    assert [t["id"] for t in queue.pending("m")] == [dated, undated]
    urgent = queue.add("hohe Prio ohne Termin", mission="m", priority=1)
    assert queue.pending("m")[0]["id"] == urgent
