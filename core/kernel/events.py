"""Event-Store: append-only Protokoll in SQLite = Single Source of Truth.

Jede Wahrnehmung, jeder Gedanke, jede Aktion wird hier als Event abgelegt.
Daraus speisen sich spaeter Dashboard, ROI-Tracker, Trust-Engine und Audit.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from core.config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id         TEXT PRIMARY KEY,
                ts         REAL NOT NULL,
                type       TEXT NOT NULL,
                session_id TEXT,
                payload    TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")


def emit(type: str, payload: dict[str, Any] | None = None, session_id: str | None = None) -> str:
    """Schreibt ein Event und gibt seine ID zurueck."""
    eid = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO events (id, ts, type, session_id, payload) VALUES (?,?,?,?,?)",
            (eid, time.time(), type, session_id, json.dumps(payload or {}, ensure_ascii=False)),
        )
    return eid


def recent(limit: int = 50, before: float | None = None) -> list[dict]:
    with _conn() as c:
        if before is not None:  # Pagination: nur Events AELTER als 'before' -> "mehr laden"
            rows = c.execute(
                "SELECT id, ts, type, session_id, payload FROM events WHERE ts < ? ORDER BY ts DESC LIMIT ?",
                (before, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, ts, type, session_id, payload FROM events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [
        {
            "id": r[0],
            "ts": r[1],
            "type": r[2],
            "session_id": r[3],
            "payload": json.loads(r[4] or "{}"),
        }
        for r in rows
    ]


def counts_by_type() -> dict[str, int]:
    with _conn() as c:
        rows = c.execute("SELECT type, COUNT(*) FROM events GROUP BY type ORDER BY 2 DESC").fetchall()
    return {r[0]: r[1] for r in rows}


def count_since(types: tuple[str, ...], since_ts: float) -> int:
    """Zaehlt Events bestimmter Typen ab einem Zeitpunkt — fuer ein ehrliches Fehler-Fenster
    (statt eines kumulativen All-Time-Zaehlers). Ein SQL-Count, kein Voll-Scan im UI."""
    if not types:
        return 0
    ph = ",".join("?" * len(types))
    with _conn() as c:
        row = c.execute(
            f"SELECT COUNT(*) FROM events WHERE ts >= ? AND type IN ({ph})",
            (since_ts, *types),
        ).fetchone()
    return int(row[0]) if row else 0


_ERROR_HINTS = ("error", "fail", "blocked", "timeout", "halt", "crash", "rollback", "denied", "exception")
_ACTION_TYPES = {
    "act_start", "act_done", "act_step", "tool_call", "shell_run",
    "plan_start", "plan_made", "plan_step", "plan_done",
    "mission_task_start", "mission_task_done", "mission_planned",
    "task_criteria", "task_scored", "task_retry",
    "cron_run", "cron_added", "self_edit", "file_edited", "restart_requested", "heartbeat_toggle",
}
_CHAT_TYPES = {"partner_message", "user_message", "telegram_in", "telegram_photo", "vision", "reflection"}


def severity(etype: str) -> str:
    """Grobe Einstufung fuer die Dashboard-Ansicht: error | action | chat | info."""
    t = (etype or "").lower()
    if any(h in t for h in _ERROR_HINTS):
        return "error"
    if etype in _CHAT_TYPES:
        return "chat"
    if etype in _ACTION_TYPES:
        return "action"
    return "info"
