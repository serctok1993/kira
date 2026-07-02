"""Lebens-Metriken: Gewicht, Gewohnheiten, Zaehlbares (S5, persistent in state.db).

Kleine Zeitreihen fuer die Coach-Rolle und die Sparklines im Cockpit:
'Gewicht 91.4', 'Training 1', 'Schlaf 6.5' — geloggt per Chat/Telegram
(metric_log-Werkzeug) oder Cockpit. Reines Datenmodell, kein LLM.
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


def init_metrics() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id    TEXT PRIMARY KEY,
                ts    REAL NOT NULL,
                name  TEXT NOT NULL,
                value REAL NOT NULL,
                note  TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(name, ts)")


def log(name: str, value: float, note: str | None = None) -> str:
    init_metrics()
    mid = uuid.uuid4().hex
    with _conn() as c:
        c.execute("INSERT INTO metrics (id, ts, name, value, note) VALUES (?,?,?,?,?)",
                  (mid, time.time(), name.strip().lower(), float(value), (note or "")[:200] or None))
    return mid


def series(name: str, days: int = 90) -> list[dict]:
    """Zeitreihe einer Metrik, chronologisch (alt -> neu)."""
    init_metrics()
    cutoff = time.time() - days * 86400
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, value, note FROM metrics WHERE name=? AND ts >= ? ORDER BY ts ASC",
            (name.strip().lower(), cutoff),
        ).fetchall()
    return [{"ts": r[0], "value": r[1], "note": r[2]} for r in rows]


def names() -> list[str]:
    init_metrics()
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT name FROM metrics ORDER BY name").fetchall()
    return [r[0] for r in rows]


def latest(limit: int = 8) -> list[dict]:
    """Je Metrik der juengste Wert + Delta zum Vorwert — fuer Standup/Cockpit."""
    out = []
    for n in names()[:limit]:
        s = series(n, days=365)
        if not s:
            continue
        delta = round(s[-1]["value"] - s[-2]["value"], 2) if len(s) >= 2 else None
        out.append({"name": n, "value": s[-1]["value"], "delta": delta, "count": len(s)})
    return out
