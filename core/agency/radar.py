"""Ideen-Radar: Kira sucht selbst nach kleinen Experimenten & Chancen (S5, S8.1 entschaerft).

Woechentlicher Scan: Web-Suche zu konfigurierbaren Themen + juengste Monitor-
Digests -> EIN guenstiger LLM-Call destilliert daraus konkrete Opportunities
(Titel, Hypothese 'wer zahlt wofuer', Score 0-100) -> Pipeline im Cockpit
(new -> shortlist/rejected -> converted). Ein Klick macht aus einer Chance ein
Venture mit Validierungs-Ziel — ab da uebernimmt der normale Heartbeat.

Rein lesend + ein bulk-Call pro Scan; Dedupe ueber Titel-Hash. Fehlende
Suche (kein Brave-Key) oder LLM-Muell degradieren still zu 0 Funden.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid

from core.config import CONFIG, DB_PATH
from core.kernel import events, llm_router

# S8.1: experimentelle/unkonventionelle Ideen statt reiner Umsatz-Jagd.
_DEFAULT_THEMES = [
    "ungewoehnliche Automatisierungs-Ideen kleiner Teams 2026",
    "experimentelle KI-Agenten Anwendungen Nischen",
    "kreative digitale Werkzeuge unerwartete Nutzung",
]
STATUSES = ("new", "shortlist", "rejected", "converted")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_radar() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunities (
                id         TEXT PRIMARY KEY,
                ts         REAL NOT NULL,
                title      TEXT NOT NULL,
                hypothesis TEXT,               -- wer zahlt wofuer, warum jetzt
                source_url TEXT,
                score      INTEGER,            -- 0..100 (geclampt)
                status     TEXT DEFAULT 'new', -- new | shortlist | rejected | converted
                notes      TEXT,
                hash       TEXT,               -- md5(titel) -> Dedupe ueber Scans
                updated_ts REAL
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status, score DESC)")


def _themes() -> list[str]:
    t = (CONFIG.get("radar") or {}).get("themes")
    return list(t) if isinstance(t, (list, tuple)) and t else list(_DEFAULT_THEMES)


def _gather(themes: list[str]) -> str:
    """Roh-Signale einsammeln: Web-Suche je Thema (fail-soft) + Monitor-Digests."""
    parts: list[str] = []
    try:
        from core.agency.tools.builtin import web_search

        for th in themes[:4]:
            try:
                parts.append(f"## Suche: {th}\n{web_search(th, max_results=6)}")
            except Exception as e:  # noqa: BLE001
                parts.append(f"## Suche: {th}\n(fehlgeschlagen: {e})")
    except Exception:  # noqa: BLE001
        pass
    digests = [str((e.get("payload") or {}).get("summary", ""))[:400]
               for e in events.recent(300) if e["type"] == "monitor_new"][:5]
    if digests:
        parts.append("## Markt-Monitor (juengste Meldungen)\n" + "\n".join(f"- {d}" for d in digests))
    return "\n\n".join(parts)


def scan(themes: list[str] | None = None, notify: bool = True) -> dict:
    """Chancen destillieren und in die Pipeline legen. Idempotent (Titel-Dedupe)."""
    init_radar()
    raw = _gather(themes or _themes())
    if len(raw.strip()) < 100:
        return {"found": 0, "note": "keine Roh-Signale (Suche blockiert/kein Key?)"}

    system = (
        "Du bist ein neugieriger Ideen-Scout fuer Sergen und seinen KI-Agenten Kira "
        "(kann Websites bauen/deployen, Recherche, Content, Automatisierung; Budget klein). "
        "Destilliere aus den Roh-Signalen KONKRETE, kleine, selbst startbare EXPERIMENTE — "
        "unkonventionell und kreativ, gern abseits des Offensichtlichen. Nuetzlich fuer Sergens "
        "Alltag/Werkzeuge ODER als kleines Einkommens-Experiment (Einkommen finanziert Autonomie, "
        "ist aber nicht der einzige Massstab). Die Verfassung bleibt bindend: nichts, was taeuscht, "
        "ausbeutet oder schadet. Kein Selbstzweck-Geld. "
        'Antworte AUSSCHLIESSLICH mit einem JSON-Array: [{"title": "...", '
        '"hypothesis": "worum geht es, warum interessant/jetzt (1 Satz)", "source_url": "...", '
        '"score": 0-100}] — hoechstens 6 Eintraege, keine Luftschloesser.'
    )
    try:
        res = llm_router.complete([{"role": "user", "content": raw[:9000]}],
                                  system=system, task_type="bulk", escalate=False)
        m = re.search(r"\[.*\]", res["text"], re.DOTALL)
        items = json.loads(m.group(0)) if m else []
    except Exception as e:  # noqa: BLE001
        events.emit("radar_error", {"error": str(e)[:300]})
        return {"found": 0, "error": str(e)[:200]}

    found: list[dict] = []
    now = time.time()
    with _conn() as c:
        for it in items[:6]:
            title = str(it.get("title") or "").strip()[:160]
            if len(title) < 8:
                continue
            h = hashlib.md5(title.lower().encode("utf-8")).hexdigest()
            if c.execute("SELECT 1 FROM opportunities WHERE hash=?", (h,)).fetchone():
                continue
            try:
                score = max(0, min(100, int(float(it.get("score") or 0))))
            except (TypeError, ValueError):
                score = 0
            oid = uuid.uuid4().hex
            c.execute("INSERT INTO opportunities (id, ts, title, hypothesis, source_url, score, status, hash, updated_ts) "
                      "VALUES (?,?,?,?,?,?, 'new', ?, ?)",
                      (oid, now, title, str(it.get("hypothesis") or "")[:400],
                       str(it.get("source_url") or "")[:300], score, h, now))
            found.append({"id": oid, "title": title, "score": score})

    # Events ERST nach dem Transaktions-Block: emit() oeffnet eine eigene Verbindung
    # auf dieselbe DB — innerhalb der offenen Schreib-Transaktion gaebe das einen Lock.
    for o in found:
        events.emit("opportunity_found", o)

    if found and notify:
        try:
            from core.agency.missions.cron import _notify

            top = sorted(found, key=lambda x: -x["score"])[:3]
            _notify("📡 Radar — neue Business-Chancen:\n"
                    + "\n".join(f"- [{o['score']}] {o['title']}" for o in top)
                    + "\nDetails im Cockpit unter Radar.")
        except Exception:  # noqa: BLE001
            pass
    return {"found": len(found), "checked": len(items)}


_O_COLS = ["id", "ts", "title", "hypothesis", "source_url", "score", "status", "notes", "updated_ts"]


def list_all(status: str = "") -> list[dict]:
    init_radar()
    sel = ", ".join(_O_COLS)
    with _conn() as c:
        if status:
            rows = c.execute(f"SELECT {sel} FROM opportunities WHERE status=? "
                             f"ORDER BY score DESC, ts DESC", (status,)).fetchall()
        else:
            rows = c.execute(f"SELECT {sel} FROM opportunities "
                             f"ORDER BY CASE status WHEN 'new' THEN 0 WHEN 'shortlist' THEN 1 "
                             f"WHEN 'converted' THEN 2 ELSE 3 END, score DESC").fetchall()
    return [dict(zip(_O_COLS, r)) for r in rows]


def _resolve(oid: str) -> dict | None:
    matches = [o for o in list_all() if o["id"] == oid or o["id"].startswith(oid)]
    return matches[0] if len(matches) == 1 else None


def decide(oid: str, status: str, note: str = "") -> bool:
    if status not in STATUSES:
        return False
    o = _resolve(oid)
    if not o:
        return False
    with _conn() as c:
        c.execute("UPDATE opportunities SET status=?, notes=?, updated_ts=? WHERE id=?",
                  (status, note[:300] or o.get("notes"), time.time(), o["id"]))
    events.emit("opportunity_decided", {"id": o["id"], "title": o["title"], "status": status})
    return True


def convert(oid: str) -> dict:
    """Chance -> Venture (Status idea) + Validierungs-Ziel. Ab hier arbeitet der Heartbeat."""
    o = _resolve(oid)
    if not o:
        return {"ok": False, "error": "Opportunity nicht gefunden"}
    from core.agency import ventures
    from core.agency.missions import objectives

    vid = ventures.add(o["title"][:80], hypothesis=o.get("hypothesis") or "", status="idea")
    objectives.init_objectives()
    obj = objectives.add(f"Validiere: {o['title'][:100]}", kind="monthly",
                         domain="business", venture_id=vid)
    decide(o["id"], "converted", note=f"venture:{vid[:8]}")
    events.emit("opportunity_converted", {"id": o["id"], "venture_id": vid, "objective_id": obj})
    return {"ok": True, "venture_id": vid, "objective_id": obj}
