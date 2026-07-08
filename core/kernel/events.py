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
    # Heartbeat + Chat schreiben gleichzeitig Events -> statt sofort "database is locked"
    # bis zu 5s auf den Schreib-Lock warten. Macht die 24/7-Nebenlaeufigkeit robust.
    conn.execute("PRAGMA busy_timeout=5000")
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


def rows_since(types: tuple[str, ...], since_ts: float, limit: int = 20000) -> list[dict]:
    """Events bestimmter Typen ab Zeitpunkt (aelteste zuerst) — fuer Aggregationen
    wie den Kalibrierungs-Report. Ein Index-Scan statt recent()-Pagination."""
    if not types:
        return []
    ph = ",".join("?" * len(types))
    with _conn() as c:
        rows = c.execute(
            f"SELECT ts, type, payload FROM events WHERE ts >= ? AND type IN ({ph}) "
            f"ORDER BY ts ASC LIMIT ?",
            (since_ts, *types, limit),
        ).fetchall()
    return [{"ts": r[0], "type": r[1], "payload": json.loads(r[2] or "{}")} for r in rows]


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


# ---- Klartext fuer Live-Ops & Desktop-Ticker (deterministisch, 0 Token) --------------
# Sergen will im Feed SEHEN, was laeuft — nicht nur "aktiv". describe() liefert pro Event
# einen Menschen-Satz (text) plus den technischen Auszug (detail: Werkzeug, Datei, Label,
# Score, Fehler). Serverseitig, damit Cockpit UND /wall dieselbe Uebersetzung nutzen.

_TOOL_TEXT = {
    "read_file": "liest Datei", "write_file": "schreibt Datei", "append_file": "ergaenzt Datei",
    "edit_datei": "aendert Code", "self_edit": "baut an sich selbst", "code_suche": "sucht im Code",
    "datei_finden": "sucht Dateien", "run_command": "fuehrt Befehl aus", "run_shell": "fuehrt Befehl aus",
    "web_fetch": "liest Webseite", "web_search": "recherchiert", "browse": "surft",
    "screenshot_url": "macht Screenshot", "read_logs": "prueft Logs", "health": "prueft Zustand",
    "learn_skill": "lernt Faehigkeit", "jetzt": "schaut auf die Uhr", "send_mail": "sendet E-Mail",
    "delegiere": "delegiert an die Armee", "venture_add": "legt Projekt an",
}

_ARG_KEYS = ("path", "pfad", "file", "rel_path", "url", "command", "query", "muster", "label", "name", "to")


def _first_arg(args: dict) -> str:
    for k in _ARG_KEYS:
        v = args.get(k)
        if v:
            return str(v).replace("https://", "").replace("http://", "")[:70]
    return ""


def _kv_fallback(payload: dict, skip: tuple = ()) -> str:
    """Kompakter k=v-Auszug der ersten Payload-Felder — nichts bleibt mehr unsichtbar."""
    parts = []
    for k, v in payload.items():
        if k in skip or v in (None, "", [], {}):
            continue
        s = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        parts.append(f"{k}={s[:60]}")
        if len(parts) >= 3:
            break
    return " · ".join(parts)


def describe(etype: str, payload: dict | None) -> dict:
    """(text, detail) fuer die Live-Ansichten. Raist NIE — kaputte Payload = Fallback."""
    try:
        p = payload if isinstance(payload, dict) else {}
        t = etype or "?"
        if t in ("tool_call", "act_step"):
            tool = str(p.get("tool") or "")
            args = p.get("args") if isinstance(p.get("args"), dict) else {}
            verb = (_TOOL_TEXT.get(tool) or f"nutzt {tool}") if tool else "arbeitet"
            text = "⚙ Kira " + verb
            detail = " · ".join(x for x in (tool, _first_arg(args),
                                            str(p.get("error") or "")[:80]) if x)
            return {"text": text, "detail": detail}
        if t == "act_start":
            return {"text": "▶ Auftrag gestartet", "detail": str(p.get("task") or "")[:110]}
        if t == "act_done":
            steps = p.get("steps")
            return {"text": "✓ Auftrag fertig", "detail": f"{steps} Schritte" if steps else ""}
        if t in ("plan_made", "plan_start"):
            steps = p.get("steps") or []
            n = len(steps) if isinstance(steps, list) else steps
            first = str(steps[0])[:70] if isinstance(steps, list) and steps else ""
            return {"text": "🗺 Plan erstellt", "detail": f"{n} Schritte" + (f" · 1. {first}" if first else "")}
        if t == "plan_step":
            return {"text": f"🗺 Plan-Schritt {p.get('n', '?')}",
                    "detail": " · ".join(x for x in (str(p.get('rang') or ''),
                                                     str(p.get('step') or '')[:90]) if x)}
        if t == "mission_task_start":
            return {"text": "🎯 Arbeitet an Task", "detail": str(p.get("desc") or "")[:110]}
        if t == "mission_task_done":
            return {"text": "✅ Task fertig", "detail": str(p.get("summary") or "")[:110]}
        if t == "task_scored":
            return {"text": "⚖ Richter hat benotet",
                    "detail": f"Score {p.get('score', '?')} · Versuch {p.get('attempt', '?')}"}
        if t == "cron_run":
            ok = "ok" if p.get("ok") else "Problem"
            return {"text": f"⏰ Cron gelaufen ({ok})",
                    "detail": " · ".join(x for x in (str(p.get('label') or ''),
                                                     str(p.get('summary') or '')[:80]) if x)}
        if t == "cron_missed":
            return {"text": "⏰ Cron verpasst — uebersprungen (PC aus?)",
                    "detail": f"{p.get('label', '?')} · {p.get('overdue_h', '?')}h ueberfaellig"}
        if t in ("selfdev_applied", "file_edited"):
            return {"text": "🔧 Code geaendert",
                    "detail": " · ".join(x for x in (str(p.get('file') or ''),
                                                     str(p.get('reason') or '')[:60]) if x)}
        if t == "write_blocked":
            return {"text": "🛡 Schreibzugriff geblockt",
                    "detail": " · ".join(x for x in (str(p.get('tool') or ''),
                                                     str(p.get('path') or '')[:80]) if x)}
        if t == "service_crash":
            return {"text": "⚠ Dienst abgestuerzt",
                    "detail": f"{p.get('service', '?')} · code {p.get('exit_code', '?')}"}
        if t == "partner_message":
            return {"text": "💬 Kira hat geantwortet", "detail": str(p.get("preview") or p.get("text") or "")[:90]}
        if t in ("user_message", "telegram_in"):
            return {"text": "👂 Nachricht von Sergen", "detail": str(p.get("preview") or p.get("text") or "")[:90]}
        if t == "reflection":
            return {"text": "🪞 Denkt ueber sich nach", "detail": ""}
        if t == "self_tick":
            return {"text": "🔧 Selbst-Optimierungs-Tick", "detail": _kv_fallback(p)}
        if t == "skill_learned":
            return {"text": "🧠 Neue Faehigkeit gelernt", "detail": str(p.get("name") or "")[:80]}
        if t == "skill_rejected":
            return {"text": "🛡 Skeptiker hat Skill verworfen",
                    "detail": " · ".join(x for x in (str(p.get('name') or ''),
                                                     str(p.get('grund') or '')[:70]) if x)}
        if t == "budget_block":
            return {"text": "💰 Budget-Bremse hat gegriffen", "detail": _kv_fallback(p)}
        if t == "heartbeat_toggle":
            return {"text": "🫀 Heartbeat " + ("AN" if p.get("on") else "aus"), "detail": ""}
        if severity(t) == "error":
            return {"text": "⚠ " + t, "detail": str(p.get("error") or "")[:100] or _kv_fallback(p, skip=("tail",))}
        # Fallback: Typ + kompakte Payload — nichts erscheint mehr als nur "aktiv"
        return {"text": "· " + t, "detail": _kv_fallback(p, skip=("tail",))}
    except Exception:  # noqa: BLE001 — die Live-Ansicht darf nie am Beschreiben scheitern
        return {"text": "· " + (etype or "?"), "detail": ""}
