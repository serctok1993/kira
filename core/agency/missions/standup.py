"""Standup-Kontext: der strukturierte Lagebericht fuer Briefings und Coach (S5).

build_context() ist ein reiner Daten-Read (KEIN LLM-Call, ~2500 Zeichen Cap):
Leben-Board, Ziele nach Domaene, Ventures-Kasse, offene Freigaben, Tagesstand,
Metriken, Fokus. Cron-Prompts nutzen den Platzhalter {{standup}} (cron.run_job
expandiert ihn) — so lesen Morgen-Briefing, Abend-Review und Coach-Check echte
Boards statt zu raten.
"""
from __future__ import annotations

import datetime
import json
import time

from core.config import ROOT
from core.kernel import events

_CAP = 2500


def _focus() -> str:
    try:
        d = json.loads((ROOT / "data" / "focus.json").read_text(encoding="utf-8"))
        return (d.get("focus") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _today_numbers() -> dict:
    start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    done = fails = 0
    for e in events.recent(500):
        if e["ts"] < start:
            continue
        if e["type"] == "mission_task_done":
            done += 1
        elif e["type"] in ("mission_task_failed", "task_failed_final"):
            fails += 1
    try:
        from core.governance import treasury

        spend = round(treasury.today_spend(), 2)
    except Exception:  # noqa: BLE001
        spend = None
    return {"done": done, "fails": fails, "spend": spend}


def _fmt_obj(o: dict) -> str:
    tail = f" (bis {o['target_date']})" if o.get("target_date") else ""
    return f"- [{o['kind']}] {o['title']} — {o['progress']}%{tail}"


def build_context(scope: str = "morgen") -> str:
    """Der Lagebericht. scope ist informativ (morgen|abend|coach) — Inhalt identisch."""
    from core.agency.missions import metrics, objectives, queue

    objectives.init_objectives()
    queue.init_queue()
    parts: list[str] = [f"=== LAGEBERICHT ({scope}, {time.strftime('%d.%m.%Y %H:%M')}) ==="]

    focus = _focus()
    if focus:
        parts.append(f"FOKUS von Sergen: {focus}")

    # Leben: Todos heute/Woche + Ziele
    board = queue.board("leben")
    heute = board.get("today", [])
    woche = board.get("week", [])
    parts.append(f"LEBEN — Todos: {len(heute)} heute, {len(woche)} diese Woche, "
                 f"{len(board.get('later', []))} spaeter")
    for t in heute[:5]:
        parts.append(f"- HEUTE: {t['description'][:90]}")
    for t in woche[:4]:
        parts.append(f"- Woche: {t['description'][:90]}")
    leben_ziele = objectives.list_active(domain="leben")
    if leben_ziele:
        parts.append("LEBEN — Missionen/Ziele:")
        parts.extend(_fmt_obj(o) for o in leben_ziele[:6])

    # Business: Ziele-Kopf + Ventures
    biz = objectives.list_active(domain="business")
    if biz:
        parts.append("BUSINESS — aktive Ziele:")
        parts.extend(_fmt_obj(o) for o in biz[:4])
    try:
        from core.agency import ventures

        vs = ventures.summary()
        if vs:
            parts.append("VENTURES:")
            for v in vs[:5]:
                ms = f", Meilenstein {v['milestone_progress']}%" if v.get("milestone_progress") is not None else ""
                parts.append(f"- {v['name']} [{v['status']}]: Kasse {v['balance_eur']:.2f} EUR{ms}")
    except Exception:  # noqa: BLE001
        pass

    # Offen fuer Sergen + Tagesstand
    try:
        from core.agency import approvals

        pend = approvals.pending()
        if pend:
            parts.append(f"WARTET AUF SERGEN ({len(pend)}):")
            parts.extend(f"- {p['title'][:90]}" for p in pend[:3])
    except Exception:  # noqa: BLE001
        pass
    nums = _today_numbers()
    spend = f", {nums['spend']} EUR ausgegeben" if nums.get("spend") is not None else ""
    parts.append(f"HEUTE: {nums['done']} Aufgaben erledigt, {nums['fails']} gescheitert{spend}")

    # Metriken (Coach-Futter)
    try:
        ms = metrics.latest()
        if ms:
            parts.append("METRIKEN:")
            for m in ms[:6]:
                delta = f" ({'+' if m['delta'] > 0 else ''}{m['delta']} seit letztem Mal)" if m.get("delta") is not None else ""
                parts.append(f"- {m['name']}: {m['value']}{delta}")
    except Exception:  # noqa: BLE001
        pass

    text = "\n".join(parts)
    return text[:_CAP]
