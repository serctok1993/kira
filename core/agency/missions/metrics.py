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
    conn.execute("PRAGMA busy_timeout=5000")  # Nebenlaeufigkeit: bis 5s warten statt sofort locken
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


# ---- Ziel-Metadaten: Zielwert, Einheit, Emoji, Zentrale-Anheftung ---------------------
# Damit aus einer nackten Zeitreihe ein sichtbares Ziel wird — und Kira das Dashboard
# selbst gestalten kann (metric_ziel-Werkzeug schreibt hier rein, Cockpit liest/aendert).

def _meta_init() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_meta (
                name    TEXT PRIMARY KEY,
                pinned  INTEGER DEFAULT 0,
                target  REAL,
                unit    TEXT,
                emoji   TEXT,
                updated REAL
            )
            """
        )


def get_meta(name: str) -> dict:
    _meta_init()
    with _conn() as c:
        r = c.execute("SELECT pinned,target,unit,emoji FROM metric_meta WHERE name=?",
                      (name.strip().lower(),)).fetchone()
    if not r:
        return {"pinned": 0, "target": None, "unit": None, "emoji": None}
    return {"pinned": r[0], "target": r[1], "unit": r[2], "emoji": r[3]}


def all_meta() -> dict:
    _meta_init()
    with _conn() as c:
        rows = c.execute("SELECT name,pinned,target,unit,emoji FROM metric_meta").fetchall()
    return {r[0]: {"pinned": r[1], "target": r[2], "unit": r[3], "emoji": r[4]} for r in rows}


def set_meta(name: str, pinned: bool | None = None, target=None,
             unit: str | None = None, emoji: str | None = None) -> str:
    """Setzt Ziel-Metadaten. None = unveraendert lassen; "" bei target/unit/emoji = loeschen."""
    name = name.strip().lower()
    cur = get_meta(name)
    p = cur["pinned"] if pinned is None else (1 if pinned else 0)
    if target is None:
        t = cur["target"]
    elif target == "":
        t = None
    else:
        t = float(target)
    u = cur["unit"] if unit is None else (unit or None)
    e = cur["emoji"] if emoji is None else (emoji or None)
    with _conn() as c:
        c.execute(
            "INSERT INTO metric_meta (name,pinned,target,unit,emoji,updated) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET pinned=excluded.pinned,target=excluded.target,"
            "unit=excluded.unit,emoji=excluded.emoji,updated=excluded.updated",
            (name, p, t, u, e, time.time()),
        )
    return name


def dashboard(days: int = 90) -> list[dict]:
    """Alle Kennzahlen mit Meta + juengstem Wert + Ziel-Fortschritt — fuers Ziele-Dashboard.
    Angeheftete (pinned) zuerst, dann alphabetisch."""
    meta = all_meta()
    out = []
    for n in names():
        s = series(n, days=days)
        if not s:
            continue
        m = meta.get(n, {"pinned": 0, "target": None, "unit": None, "emoji": None})
        val = s[-1]["value"]
        delta = round(val - s[-2]["value"], 2) if len(s) >= 2 else None
        prog = None
        if m.get("target"):
            try:
                prog = max(0, min(100, round(100 * val / float(m["target"]))))
            except (TypeError, ValueError, ZeroDivisionError):
                prog = None
        out.append({
            "name": n, "value": val, "delta": delta, "count": len(s),
            "pinned": bool(m.get("pinned")), "target": m.get("target"),
            "unit": m.get("unit"), "emoji": m.get("emoji"), "progress": prog,
            "series": [p["value"] for p in s],
        })
    out.sort(key=lambda x: (not x["pinned"], x["name"]))
    return out


def pinned(days: int = 90) -> list[dict]:
    """Nur die in die Zentrale angehefteten Kennzahlen."""
    return [d for d in dashboard(days) if d["pinned"]]
