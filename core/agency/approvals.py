"""Freigabe-Inbox: nichts geht nach aussen ohne Sergens GO.

Jede Aussen-Aktion / irreversible / oeffentliche Handlung (Post, Mail, Publish)
und jeder Selbst-Aenderungs-Vorschlag (SOUL/GOAL) landet hier als Eintrag mit
Status 'pending'. Sergen entscheidet im Cockpit: approve / reject. Persistent in
state.db, damit Freigaben Neustarts ueberleben und nachvollziehbar sind.

Sicherheits-Kern der Autonomie: der Runner/die Tools LEGEN nur an. Bei Freigabe
wird ausgefuehrt, was deterministisch nachziehbar ist (evolution, playbook,
email_stranger — Payload steckt im Eintrag); money/external/publish sind reine
Anfragen — dort muss Kira die Aktion nach dem GO erneut anstossen (steht im
decide-Ergebnis). Reject = verworfen, mit Spur im Log.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from core.config import DB_PATH
from core.kernel import events

KINDS = ("publish", "external", "email", "email_stranger", "money", "evolution", "playbook", "generic")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")  # Nebenlaeufigkeit: bis 5s warten statt sofort locken
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


# Richter-Urteil 04.07.2026 (Fleiss-Inflation): mehr als N autonome Eintraege
# pro Tag sind ein Warnsignal — die Inbox darf nicht zur zweiten Last werden.
DAILY_AUTONOMOUS_BUDGET = 3


def created_today(source: str = "kira") -> int:
    """Zaehlt, wie viele Eintraege diese Quelle seit lokalem Mitternacht angelegt hat."""
    lt = time.localtime()
    day_start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) FROM approvals WHERE source=? AND ts>=?",
                      (source, day_start)).fetchone()
    return int(r[0] if r else 0)


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
    if source == "kira":
        # Tagesbudget-Wache: warnt (blockiert NICHT), wenn Kira die Inbox flutet.
        n = created_today("kira")
        if n > DAILY_AUTONOMOUS_BUDGET:
            events.emit("approval_flood_warning", {
                "count_today": n, "budget": DAILY_AUTONOMOUS_BUDGET,
                "hint": "Autonome Inbox-Eintraege buendeln statt fluten (Richter-Rat)."})
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
    hinterlegte SOUL/GOAL-Vorschlag automatisch angewendet (Backup + Guard laufen dort).
    Idempotent: nur pending -> decided; ein zweiter Aufruf (Doppelklick/Race) tut nichts."""
    entry = get(aid)
    if not entry:
        return {"ok": False, "error": "nicht gefunden"}
    if entry.get("status") != "pending":
        return {"ok": False, "error": "already decided", "status": entry.get("status")}
    status = "approved" if approved else "rejected"
    with _conn() as c:
        cur = c.execute("UPDATE approvals SET status=?, decided_ts=?, note=? WHERE id=? AND status='pending'",
                        (status, time.time(), note, aid))
        if cur.rowcount == 0:  # parallele Entscheidung hat gewonnen
            return {"ok": False, "error": "already decided", "status": (get(aid) or {}).get("status")}
    applied = None
    if approved and entry.get("kind") == "evolution" and entry.get("ref"):
        try:
            from core.mind import evolution
            applied = evolution.apply_update(entry["ref"], reason="Freigabe via Inbox")
        except Exception as e:  # noqa: BLE001
            applied = {"error": str(e)}
    if approved and entry.get("kind") == "playbook" and entry.get("ref"):
        # S11: Befoerderungs-Vorschlag angenommen -> Playbook eine Stufe hoch.
        try:
            from core.mind import playbooks
            applied = playbooks.promote(entry["ref"])
        except Exception as e:  # noqa: BLE001
            applied = {"error": str(e)}
    if approved and entry.get("kind") == "email_stranger":
        # Audit-Fund: Freigabe war frueher ein No-Op — die Mail wurde NIE gesendet
        # (gate.guarded verwirft die execute-Lambda). Das Payload steckt komplett im
        # detail-JSON (mail_tools.email_send) -> hier deterministisch nachziehen.
        try:
            raw = (entry.get("detail") or "").split("\n\n--- RATS-URTEIL")[0].strip()
            p = json.loads(raw)
            from core.agency.connectors import mail
            r = mail.send(p["to"], p["subject"], p.get("body") or "")
            applied = {"email_sent": True, "result": str(r)[:200]}
        except Exception as e:  # noqa: BLE001
            applied = {"email_sent": False, "error": str(e)[:200]}
    elif approved and entry.get("kind") in ("money", "external", "publish"):
        # Ehrlichkeit statt stiller Luecke: diese Arten tragen KEIN deterministisches
        # Payload — die Aktion passiert durch die Freigabe allein NICHT.
        applied = {"hint": "Aktion wird nicht automatisch ausgefuehrt — Kira muss sie "
                           "nach der Freigabe erneut anstossen."}
    events.emit("approval_decided", {"id": aid, "status": status, "kind": entry.get("kind"),
                                     "title": (entry.get("title") or "")[:160], "applied": bool(applied)})
    return {"ok": True, "status": status, "applied": applied}
