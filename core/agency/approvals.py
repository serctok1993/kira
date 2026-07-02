"""Freigabe-Inbox: nichts geht nach aussen ohne Sergens GO.

Jede Aussen-Aktion / irreversible / oeffentliche Handlung (Post, Mail, Publish)
und jeder Selbst-Aenderungs-Vorschlag (SOUL/GOAL) landet hier als Eintrag mit
Status 'pending'. Sergen entscheidet im Cockpit: approve / reject. Persistent in
state.db, damit Freigaben Neustarts ueberleben und nachvollziehbar sind.

Sicherheits-Kern der Autonomie: der Runner/die Tools LEGEN nur an — ausgefuehrt
wird erst NACH einer Freigabe (approve). Reject = verworfen, mit Spur im Log.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from core.config import DB_PATH
from core.kernel import events

KINDS = ("publish", "external", "email", "email_stranger", "money", "evolution", "generic")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_approvals() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id          TEXT PRIMARY KEY,
                ts          REAL NOT NULL,
                kind        TEXT DEFAULT 'generic',   -- publish|external|email|evolution|generic
                title       TEXT NOT NULL,
                detail      TEXT,                      -- Volltext / Entwurf / Diff
                ref         TEXT,                      -- z.B. Proposal-Doc oder Artefakt-Pfad
                source      TEXT,                      -- kira | task | dashboard
                status      TEXT DEFAULT 'pending',    -- pending | approved | rejected
                decided_ts  REAL,
                note        TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_appr_status ON approvals(status, ts)")


def create(title: str, kind: str = "generic", detail: str | None = None,
           ref: str | None = None, source: str = "kira") -> str:
    init_approvals()
    aid = uuid.uuid4().hex
    kind = kind if kind in KINDS else "generic"
    with _conn() as c:
        c.execute(
            "INSERT INTO approvals (id, ts, kind, title, detail, ref, source, status) "
            "VALUES (?,?,?,?,?,?,?, 'pending')",
            (aid, time.time(), kind, title.strip(), detail, ref, source),
        )
    events.emit("approval_requested", {"id": aid, "kind": kind, "title": title[:200], "source": source})
    return aid


def _row(r: sqlite3.Row) -> dict:
    keys = ["id", "ts", "kind", "title", "detail", "ref", "source", "status", "decided_ts", "note"]
    return dict(zip(keys, r))


def pending() -> list[dict]:
    with _conn() as c:
        c.row_factory = None
        rows = c.execute(
            "SELECT id, ts, kind, title, detail, ref, source, status, decided_ts, note "
            "FROM approvals WHERE status='pending' ORDER BY ts DESC"
        ).fetchall()
    return [_row(r) for r in rows]


def recent(limit: int = 30) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ts, kind, title, detail, ref, source, status, decided_ts, note "
            "FROM approvals ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row(r) for r in rows]


def get(aid: str) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT id, ts, kind, title, detail, ref, source, status, decided_ts, note "
            "FROM approvals WHERE id=?", (aid,)
        ).fetchone()
    return _row(r) if r else None


def decide(aid: str, approved: bool, note: str | None = None) -> dict:
    """Freigeben oder ablehnen. Fuer 'evolution'-Eintraege wird bei Freigabe der
    hinterlegte SOUL/GOAL-Vorschlag automatisch angewendet (Backup + Guard laufen dort)."""
    entry = get(aid)
    if not entry:
        return {"ok": False, "error": "nicht gefunden"}
    status = "approved" if approved else "rejected"
    with _conn() as c:
        c.execute("UPDATE approvals SET status=?, decided_ts=?, note=? WHERE id=?",
                  (status, time.time(), note, aid))
    applied = None
    if approved and entry.get("kind") == "evolution" and entry.get("ref"):
        try:
            from core.mind import evolution
            applied = evolution.apply_update(entry["ref"], reason="Freigabe via Inbox")
        except Exception as e:  # noqa: BLE001
            applied = {"error": str(e)}
    events.emit("approval_decided", {"id": aid, "status": status, "kind": entry.get("kind"),
                                     "title": (entry.get("title") or "")[:160], "applied": bool(applied)})
    return {"ok": True, "status": status, "applied": applied}
