"""Tagewerk: was Kira HEUTE getan hat — deterministisch aus dem Event-Log (0 Token).

Ein Aggregator, zwei Anzeigen: das Cockpit (/api/tagewerk, Zentrale + Checkliste)
und Telegram (/tagewerk) lesen dieselben Zahlen — Malen nach Zahlen, ueberall gleich.
Phase 2: zeitraum() verallgemeinert dieselbe Schleife auf beliebige Fenster —
die Wochen-/Monatsreports (core/agency/reports.py) lesen daraus; heute() delegiert,
seine Vertraege (API/Telegram) bleiben byte-identisch.
"""
from __future__ import annotations

import datetime as _dt

from core.kernel import events
from core.kernel.llm_router import today_spend_usd


def zeitraum(start_ts: float, ende_ts: float | None = None, max_events: int = 6000) -> dict:
    """Event-Aggregat fuer ein Zeitfenster [start_ts, ende_ts). ende_ts None = jetzt.

    Bewusst OHNE Momentaufnahmen (offene Freigaben, Tageskosten) — die gehoeren
    nur zu heute() und waeren fuer vergangene Fenster schlicht falsch."""
    mails: list[str] = []
    skills: list[str] = []
    crons: list[str] = []
    edits: list[str] = []
    diagnose: dict | None = None
    tasks_done = 0
    tasks_fail = 0
    scores: list[int] = []
    self_ticks = 0
    lektionen = 0
    for ev in events.recent(max_events):
        if ende_ts is not None and ev["ts"] >= ende_ts:
            continue
        if ev["ts"] < start_ts:
            break
        t, p = ev["type"], ev.get("payload") or {}
        if t == "audit" and p.get("action") == "email_send":
            mails.append(str(p.get("target") or "?"))
        elif t == "approval_decided" and p.get("kind") == "email_stranger" and p.get("status") == "approved":
            mails.append(str(p.get("title") or "?")[:60])
        elif t == "skill_learned":
            skills.append(str(p.get("name") or "?"))
        elif t == "cron_run":
            crons.append(str(p.get("label") or "?"))
        elif t == "selfdev_applied":
            edits.append(str(p.get("file") or "?"))
        elif t == "doctor_report" and diagnose is None:
            diagnose = {"ts": ev["ts"], "ok": bool(p.get("ok")),
                        "probleme": len(p.get("problems") or [])}
        elif t == "mission_task_done":
            tasks_done += 1
            if p.get("score") is not None:
                scores.append(int(p["score"]))
        elif t == "task_failed_final":
            tasks_fail += 1
        elif t == "self_tick":
            self_ticks += 1
        elif t == "memory_add" and p.get("kind") == "lesson":
            lektionen += 1
    return {
        "mails": {"anzahl": len(mails), "an": mails[:5]},
        "skills": {"anzahl": len(skills), "namen": skills[:5]},
        "crons": {"anzahl": len(crons), "labels": list(dict.fromkeys(crons))[:6]},
        "selbstverbesserung": {"ticks": self_ticks, "code_edits": edits[:5]},
        "diagnose": diagnose,
        "tasks": {"done": tasks_done, "failed": tasks_fail,
                  "avg_score": round(sum(scores) / len(scores), 1) if scores else None},
        "lektionen": lektionen,
    }


def heute() -> dict:
    mitternacht = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    out = zeitraum(mitternacht, max_events=900)
    from core.agency import approvals as _appr

    out["freigaben_offen"] = len(_appr.pending())
    out["kosten_heute_usd"] = round(today_spend_usd(), 4)
    return out
