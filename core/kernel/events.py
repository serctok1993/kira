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


def recent(limit: int = 50) -> list[dict]:
    with _conn() as c:
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
