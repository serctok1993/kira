"""Aufgaben-Queue der Missionen (persistent in state.db).

Der Planner fuellt sie, der Heartbeat arbeitet sie ab. So ueberlebt der
Fortschritt Neustarts und ist im Dashboard nachvollziehbar.
"""
from __future__ import annotations

import sqlite3
import time
import uuid

from core.config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_queue() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                ts          REAL NOT NULL,
                mission     TEXT,
                description TEXT NOT NULL,
                status      TEXT DEFAULT 'pending',   -- pending | running | done | failed
                priority    INTEGER DEFAULT 5,
                result      TEXT,
                retry_count INTEGER DEFAULT 0,
                updated_ts  REAL
            )
            """
        )
        # Nachtraegliche Ergaenzung fuer bereits existierende DBs (Spalten fehlen ggf. noch).
        try:
            c.execute("ALTER TABLE tasks ADD COLUMN retry_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE tasks ADD COLUMN updated_ts REAL")
        except sqlite3.OperationalError:
            pass
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(mission, status, priority, ts)")


def add(description: str, mission: str = "default", priority: int = 5) -> str:
    tid = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO tasks (id, ts, mission, description, status, priority) VALUES (?,?,?,?, 'pending', ?)",
            (tid, time.time(), mission, description, priority),
        )
    return tid


def pending(mission: str | None = None, limit: int = 20) -> list[dict]:
    with _conn() as c:
        if mission:
            rows = c.execute(
                "SELECT id, description, priority FROM tasks WHERE mission=? AND status='pending' "
                "ORDER BY priority ASC, ts ASC LIMIT ?",
                (mission, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, description, priority FROM tasks WHERE status='pending' "
                "ORDER BY priority ASC, ts ASC LIMIT ?",
                (limit,),
            ).fetchall()
    return [{"id": r[0], "description": r[1], "priority": r[2]} for r in rows]


def pop_next(mission: str | None = None) -> dict | None:
    p = pending(mission, limit=1)
    if not p:
        return None
    task = p[0]
    with _conn() as c:
        c.execute("UPDATE tasks SET status='running', updated_ts=? WHERE id=?", (time.time(), task["id"]))
    return task


def complete(task_id: str, result: str, status: str = "done") -> None:
    with _conn() as c:
        c.execute(
            "UPDATE tasks SET status=?, result=?, updated_ts=? WHERE id=?",
            (status, result[:4000], time.time(), task_id),
        )


def remove(task_id: str) -> bool:
    """Eine offene Aufgabe aus der Queue loeschen (nur solange 'pending')."""
    with _conn() as c:
        cur = c.execute("DELETE FROM tasks WHERE id=? AND status='pending'", (task_id,))
    return cur.rowcount > 0


def clear(mission: str | None = None, status: str = "pending") -> int:
    """Alle offenen Aufgaben (einer Mission) verwerfen. Gibt Anzahl zurueck."""
    with _conn() as c:
        if mission:
            cur = c.execute("DELETE FROM tasks WHERE mission=? AND status=?", (mission, status))
        else:
            cur = c.execute("DELETE FROM tasks WHERE status=?", (status,))
    return cur.rowcount


def reset_stuck(timeout_seconds: int = 1800, max_retries: int = 3) -> dict:
    """Macht nach einem Absturz haengengebliebene 'running'-Tasks wieder flott.

    Tasks, die laenger als timeout_seconds nicht mehr aktualisiert wurden,
    gelten als verwaist (z.B. weil der Prozess waehrend der Bearbeitung
    abgestuerzt ist). Solche Tasks werden erneut auf 'pending' gesetzt
    (Durable Execution: nichts geht verloren), solange sie noch nicht zu
    oft gescheitert sind. Ist das Retry-Limit erreicht, werden sie final
    als 'failed' markiert, damit sie nicht endlos wiederholt werden.
    """
    now = time.time()
    cutoff = now - timeout_seconds
    with _conn() as c:
        rows = c.execute(
            "SELECT id, retry_count FROM tasks WHERE status='running' "
            "AND (updated_ts IS NULL OR updated_ts < ?)",
            (cutoff,),
        ).fetchall()

        requeued = 0
        failed = 0
        for task_id, retry_count in rows:
            retry_count = retry_count or 0
            if retry_count < max_retries:
                c.execute(
                    "UPDATE tasks SET status='pending', retry_count=?, updated_ts=? WHERE id=?",
                    (retry_count + 1, now, task_id),
                )
                requeued += 1
            else:
                c.execute(
                    "UPDATE tasks SET status='failed', result=?, updated_ts=? WHERE id=?",
                    ("stuck: max retries erreicht", now, task_id),
                )
                failed += 1

    return {"requeued": requeued, "failed": failed}