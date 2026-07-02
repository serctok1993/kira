"""Ziel-/Projekt-Modell: die Hierarchie ueber der Task-Queue.

Big Project -> Monthly -> Weekly (parent_id verkettet). Jedes Ziel hat Status +
Fortschritt (manuell ODER automatisch aus den verknuepften Tasks abgeleitet).
Persistent in state.db, damit Fortschritt Neustarts ueberlebt und im Cockpit
als Fahrplan sichtbar ist. Read-only-sicher: reines Datenmodell, keine Aussen-Aktionen.
"""
from __future__ import annotations

import sqlite3
import time
import uuid

from core.config import DB_PATH

KINDS = ("big", "monthly", "weekly")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_objectives() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS objectives (
                id          TEXT PRIMARY KEY,
                ts          REAL NOT NULL,
                kind        TEXT DEFAULT 'weekly',   -- big | monthly | weekly
                title       TEXT NOT NULL,
                parent_id   TEXT,
                status      TEXT DEFAULT 'active',   -- active | done | paused
                progress    INTEGER,                 -- 0..100 manuell; NULL = aus Tasks ableiten
                target_date TEXT,                    -- ISO 'YYYY-MM-DD' oder NULL
                notes       TEXT,
                updated_ts  REAL
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_obj_parent ON objectives(parent_id, status)")
        try:
            c.execute("ALTER TABLE objectives ADD COLUMN venture_id TEXT")  # Ziel gehoert zu einem Venture (S3)
        except sqlite3.OperationalError:
            pass


def add(title: str, kind: str = "weekly", parent_id: str | None = None,
        target_date: str | None = None, notes: str | None = None,
        venture_id: str | None = None) -> str:
    oid = uuid.uuid4().hex
    kind = kind if kind in KINDS else "weekly"
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO objectives (id, ts, kind, title, parent_id, status, target_date, notes, updated_ts, venture_id) "
            "VALUES (?,?,?,?,?, 'active', ?, ?, ?, ?)",
            (oid, now, kind, title.strip(), parent_id, target_date, notes, now, venture_id),
        )
    return oid


def update(oid: str, **fields) -> bool:
    allowed = {"title", "kind", "parent_id", "status", "progress", "target_date", "notes", "venture_id"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return False
    sets.append("updated_ts=?")
    params.append(time.time())
    params.append(oid)
    with _conn() as c:
        cur = c.execute(f"UPDATE objectives SET {', '.join(sets)} WHERE id=?", params)
    return cur.rowcount > 0


def delete(oid: str) -> bool:
    """Ziel loeschen; Kind-Ziele + verknuepfte Tasks werden entkoppelt (parent/objective -> NULL)."""
    with _conn() as c:
        c.execute("UPDATE objectives SET parent_id=NULL WHERE parent_id=?", (oid,))
        try:
            c.execute("UPDATE tasks SET objective_id=NULL WHERE objective_id=?", (oid,))
        except sqlite3.OperationalError:
            pass
        cur = c.execute("DELETE FROM objectives WHERE id=?", (oid,))
    return cur.rowcount > 0


def _task_progress(oid: str) -> tuple[int, int]:
    """(erledigt, gesamt) der verknuepften Tasks — fuer automatischen Fortschritt."""
    with _conn() as c:
        try:
            total = c.execute("SELECT COUNT(*) FROM tasks WHERE objective_id=?", (oid,)).fetchone()[0]
            done = c.execute("SELECT COUNT(*) FROM tasks WHERE objective_id=? AND status='done'", (oid,)).fetchone()[0]
        except sqlite3.OperationalError:
            return (0, 0)
    return (int(done), int(total))


def list_all(include_done: bool = True) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ts, kind, title, parent_id, status, progress, target_date, notes, venture_id "
            "FROM objectives ORDER BY "
            "CASE kind WHEN 'big' THEN 0 WHEN 'monthly' THEN 1 ELSE 2 END, ts ASC"
        ).fetchall()
    out = []
    for r in rows:
        if not include_done and r[5] == "done":
            continue
        done, total = _task_progress(r[0])
        prog = r[6]
        if prog is None:
            prog = round(100 * done / total) if total else 0
        out.append({
            "id": r[0], "ts": r[1], "kind": r[2], "title": r[3], "parent_id": r[4],
            "status": r[5], "progress": int(prog), "target_date": r[7], "notes": r[8],
            "venture_id": r[9], "tasks_done": done, "tasks_total": total,
        })
    return out
