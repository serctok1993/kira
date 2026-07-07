"""Outcome-Ledger: eine Zeile pro Qualitaets-VERSUCH eines Tasks (persistent in state.db).

Das ist das Gedaechtnis der Ergebnis-Rueckkopplung (S2): Score-Verlauf, Strategie-
Wechsel und Kosten pro Versuch bleiben erhalten — der Lern-Rohstoff, aus dem Kira
messbar besser wird statt nur fleissig. UNIQUE(task_id, attempt) + INSERT OR REPLACE
macht Re-Verifikation nach einem Absturz idempotent (kein Doppel-Scoring).
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from core.config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")  # Nebenlaeufigkeit: bis 5s warten statt sofort locken
    return conn


def init_outcomes() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS outcomes (
                id         TEXT PRIMARY KEY,
                task_id    TEXT NOT NULL,
                attempt    INTEGER NOT NULL,   -- 1..3 (Qualitaets-Versuche)
                ts         REAL NOT NULL,
                criteria   TEXT,               -- JSON: Akzeptanzkriterien
                checks     TEXT,               -- JSON: [{"text","ok","evidence","source":"det"|"llm"}]
                score      INTEGER,            -- 0..100, NULL wenn der Judge ausfiel
                verdict    TEXT,               -- pass | retry | fail | error
                feedback   TEXT,               -- was der naechste Versuch anders machen soll
                strategy   TEXT,               -- standard | eskaliert | strategiewechsel
                cost_usd   REAL DEFAULT 0,
                duration_s REAL,
                UNIQUE(task_id, attempt)
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_task ON outcomes(task_id, attempt)")


def record(task_id: str, attempt: int, criteria: list | None, checks: list | None,
           score: int | None, verdict: str, feedback: str = "", strategy: str = "",
           cost_usd: float = 0.0, duration_s: float = 0.0) -> str:
    """Einen Versuch protokollieren. Gleicher (task_id, attempt) ueberschreibt (idempotent)."""
    init_outcomes()
    oid = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO outcomes "
            "(id, task_id, attempt, ts, criteria, checks, score, verdict, feedback, strategy, cost_usd, duration_s) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, task_id, int(attempt), time.time(),
             json.dumps(criteria or [], ensure_ascii=False),
             json.dumps(checks or [], ensure_ascii=False),
             score, verdict, (feedback or "")[:2000], strategy,
             float(cost_usd or 0.0), float(duration_s or 0.0)),
        )
    return oid


_COLS = ["id", "task_id", "attempt", "ts", "criteria", "checks", "score",
         "verdict", "feedback", "strategy", "cost_usd", "duration_s"]


def _row_to_dict(r: tuple) -> dict:
    d = dict(zip(_COLS, r))
    for key in ("criteria", "checks"):
        try:
            d[key] = json.loads(d[key]) if d[key] else []
        except Exception:  # noqa: BLE001
            d[key] = []
    return d


def for_task(task_id: str) -> list[dict]:
    """Alle Versuche eines Tasks, aufsteigend nach attempt."""
    init_outcomes()
    sel = ", ".join(_COLS)
    with _conn() as c:
        rows = c.execute(
            f"SELECT {sel} FROM outcomes WHERE task_id=? ORDER BY attempt ASC", (task_id,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def last(task_id: str) -> dict | None:
    """Der juengste Versuch eines Tasks (hoechstes attempt) oder None."""
    attempts = for_task(task_id)
    return attempts[-1] if attempts else None


def stats(days: int = 7) -> dict:
    """Pass-Rate und Durchschnitts-Score der letzten Tage — fuers Cockpit/Standup."""
    init_outcomes()
    cutoff = time.time() - days * 86400
    with _conn() as c:
        rows = c.execute(
            "SELECT verdict, score FROM outcomes WHERE ts >= ?", (cutoff,)
        ).fetchall()
    total = len(rows)
    passed = sum(1 for v, _ in rows if v == "pass")
    scores = [s for _, s in rows if s is not None]
    return {
        "days": days,
        "attempts": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else None,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
    }
