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
        for ddl in (
            "ALTER TABLE tasks ADD COLUMN retry_count INTEGER DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN updated_ts REAL",
            "ALTER TABLE tasks ADD COLUMN objective_id TEXT",     # Verknuepfung zum Ziel/Projekt
            "ALTER TABLE tasks ADD COLUMN due_date TEXT",         # ISO 'YYYY-MM-DD' oder NULL
            "ALTER TABLE tasks ADD COLUMN deferred_until TEXT",   # aufgeschoben bis ISO-Datum
            "ALTER TABLE tasks ADD COLUMN kind TEXT DEFAULT 'research'",  # research | produce | publish
            "ALTER TABLE tasks ADD COLUMN artifact_path TEXT",    # erzeugtes Artefakt (P2)
            "ALTER TABLE tasks ADD COLUMN acceptance TEXT",       # JSON-Akzeptanzkriterien (S2, einmal generiert)
            "ALTER TABLE tasks ADD COLUMN quality_retries INTEGER DEFAULT 0",  # Qualitaets-Retries (S2, getrennt von retry_count/Absturz)
            "ALTER TABLE tasks ADD COLUMN feedback TEXT",         # Pruefer-Feedback fuer den naechsten Versuch (S2)
            "ALTER TABLE tasks ADD COLUMN score INTEGER",         # letzter Outcome-Score 0..100 (S2)
        ):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(mission, status, priority, ts)")


def add(description: str, mission: str = "default", priority: int = 5,
        objective_id: str | None = None, due_date: str | None = None,
        kind: str = "research") -> str:
    tid = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO tasks (id, ts, mission, description, status, priority, objective_id, due_date, kind) "
            "VALUES (?,?,?,?, 'pending', ?, ?, ?, ?)",
            (tid, time.time(), mission, description, priority, objective_id, due_date, kind),
        )
    return tid


_TASK_COLS = ["id", "ts", "mission", "description", "status", "priority", "result",
              "objective_id", "due_date", "deferred_until", "kind", "artifact_path", "updated_ts",
              "acceptance", "quality_retries", "feedback", "score", "retry_count"]


def all_tasks(mission: str | None = None, limit: int = 200) -> list[dict]:
    """Alle Aufgaben (fuer Board/Backlog), sinnvoll sortiert."""
    order = ("CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, "
             "priority ASC, ts ASC")
    sel = ", ".join(_TASK_COLS)
    with _conn() as c:
        if mission:
            rows = c.execute(f"SELECT {sel} FROM tasks WHERE mission=? ORDER BY {order} LIMIT ?",
                             (mission, limit)).fetchall()
        else:
            rows = c.execute(f"SELECT {sel} FROM tasks ORDER BY {order} LIMIT ?", (limit,)).fetchall()
    return [dict(zip(_TASK_COLS, r)) for r in rows]


def get_task(task_id: str) -> dict | None:
    """Volle Task-Zeile (inkl. kind/acceptance/Zaehler) — pop_next bleibt bewusst schlank."""
    sel = ", ".join(_TASK_COLS)
    with _conn() as c:
        row = c.execute(f"SELECT {sel} FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(zip(_TASK_COLS, row)) if row else None


def update_task(task_id: str, **fields) -> bool:
    allowed = {"description", "priority", "status", "objective_id", "due_date",
               "deferred_until", "kind", "result", "artifact_path",
               "acceptance", "quality_retries", "feedback", "score"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return False
    sets.append("updated_ts=?")
    params.append(time.time())
    params.append(task_id)
    with _conn() as c:
        cur = c.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)
    return cur.rowcount > 0


def defer(task_id: str, until_date: str) -> bool:
    """Aufgabe aufschieben bis ISO-Datum 'YYYY-MM-DD'."""
    return update_task(task_id, deferred_until=until_date)


def board(mission: str | None = None, limit: int = 200) -> dict:
    """Aufgaben fuer das Cockpit-Board gruppieren:
    laeuft / heute (faellig+ueberfaellig) / woche / spaeter / aufgeschoben / erledigt."""
    import datetime as _dt

    today = _dt.date.today()

    def _iso(s):
        try:
            return _dt.date.fromisoformat(str(s)[:10])
        except Exception:
            return None

    def _bucket(t: dict) -> str:
        if t["status"] == "running":
            return "running"
        if t["status"] in ("done", "failed"):
            return "done"
        dfr = _iso(t.get("deferred_until"))
        if dfr and dfr > today:
            return "deferred"
        due = _iso(t.get("due_date"))
        if due:
            if due <= today:
                return "today"
            if (due - today).days <= 7:
                return "week"
            return "later"
        return "later"

    groups: dict[str, list] = {"running": [], "today": [], "week": [], "later": [], "deferred": [], "done": []}
    for t in all_tasks(mission, limit=limit):
        groups[_bucket(t)].append(t)
    groups["done"] = groups["done"][:8]
    return groups


def pending(mission: str | None = None, limit: int = 20) -> list[dict]:
    """Naechste offene Aufgaben, termin-bewusst (S6.2):
    1. faellig/ueberfaellig (due_date <= heute) zuerst, das Ueberfaelligste vorn,
    2. sonst: priority, dann Termin-Naehe, dann Alter (alter ts = Retry zuerst).
    deferred_until in der Zukunft wird uebersprungen (war vorher ein Bug: Aufgeschobenes
    wurde trotzdem gezogen). Datum kommt aus Python (kein SQLite-UTC-Drift)."""
    import datetime as _dt

    today = _dt.date.today().isoformat()
    where = ("status='pending' AND (deferred_until IS NULL OR deferred_until <= :today)"
             + (" AND mission=:mission" if mission else ""))
    order = ("CASE WHEN due_date IS NOT NULL AND due_date <= :today THEN 0 ELSE 1 END, "
             "CASE WHEN due_date IS NOT NULL AND due_date <= :today THEN due_date END ASC, "
             "priority ASC, COALESCE(due_date, '9999-12-31') ASC, ts ASC")
    params: dict = {"today": today, "limit": limit}
    if mission:
        params["mission"] = mission
    with _conn() as c:
        rows = c.execute(
            f"SELECT id, description, priority FROM tasks WHERE {where} "
            f"ORDER BY {order} LIMIT :limit", params,
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