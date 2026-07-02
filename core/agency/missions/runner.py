"""Mission-Heartbeat: der 24/7-Antrieb.

Ein Tick (run_once):
1. Kill-Switch pruefen (Verfassung #4).
2. Queue leer? -> Planner erzeugt die naechsten Aufgaben.
3. Naechste Aufgabe ziehen und mit der Handlungs-Schleife (act) bearbeiten
   (Werkzeuge: Web etc.) -> Ergebnis protokollieren.
4. Optional Sergen per Telegram benachrichtigen.

Sicher als erster Dauerlauf: nur lesende Recherche/Reflexion, keine Aussen-Aktionen.
Start:  uv run python -m core.agency.missions.runner            (ein Tick zum Testen: --once)
"""
from __future__ import annotations

import os
import sys
import time

from core.agency import outcomes, verifier
from core.agency.act import act
from core.agency.missions import planner, queue, workingset
from core.config import CONFIG
from core.kernel import events
from core.kernel.scheduler import heartbeat_on, kill_switch_active
from core.mind.agent import _read


def _mission() -> dict:
    return CONFIG.get("mission", {})


def _focus() -> str:
    """Sergens aktueller Fokus (Direktive) — live pro Tick gelesen, wirkt ohne Neustart."""
    try:
        import json

        from core.config import ROOT

        d = json.loads((ROOT / "data" / "focus.json").read_text(encoding="utf-8"))
        return (d.get("focus") or "").strip()
    except Exception:
        return ""


def _context(limit: int = 12) -> str:
    lines: list[str] = []
    for e in reversed(events.recent(80)):
        if e["type"] == "mission_task_done":
            lines.append("Erledigt: " + str(e["payload"].get("summary", ""))[:160])
        elif e["type"] == "mission_planned":
            lines.append("Geplant: " + ", ".join(e["payload"].get("tasks", []))[:160])
        elif e["type"] == "task_failed_final":
            # Der Planner soll denselben todgeweihten Task nicht sofort neu planen.
            lines.append("Endgueltig gescheitert (NICHT wiederholen): "
                         + str(e["payload"].get("desc", ""))[:160])
    return "\n".join(lines[-limit:]) or "(noch kein Fortschritt)"


def _notify(text: str) -> None:
    if not _mission().get("notify_telegram"):
        return
    try:
        import httpx

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        if token and chat:
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:4000]},
                timeout=15,
            )
    except Exception as e:  # noqa: BLE001
        events.emit("notify_error", {"error": str(e)})


def _pick_objective(actives: list[dict]) -> dict | None:
    """Waehlt das naechste aktive Ziel: naechste Faelligkeit zuerst, dann geringster Fortschritt."""
    if not actives:
        return None
    import datetime as _dt

    def _key(o: dict):
        td = o.get("target_date")
        try:
            days = (_dt.date.fromisoformat(td) - _dt.date.today()).days if td else 9999
        except Exception:  # noqa: BLE001
            days = 9999
        return (days, o.get("progress", 0))

    return sorted(actives, key=_key)[0]


def _outcomes_enabled() -> bool:
    o = CONFIG.get("outcomes") or {}
    return bool(o.get("enabled", True)) if isinstance(o, dict) else True


def _attempt_prompt(task: dict, criteria: list[dict], attempt: int) -> str:
    """Task-Beschreibung + Akzeptanzkriterien; ab Versuch 2 Pruefer-Feedback + Strategiewechsel.

    Die description in der DB bleibt UNVERAENDERT (Board + stabile Kriterien) —
    nur der Arbeits-Prompt des Versuchs traegt die Zusaetze."""
    parts = []
    if task.get("objective_id"):
        ws = workingset.render(task["objective_id"])
        if ws:
            parts.append("ARBEITSSTAND ZUM ZIEL (darauf aufbauen, nichts wiederholen):\n" + ws + "\n---")
    parts.append(task["description"])
    if criteria:
        parts.append("\nAKZEPTANZKRITERIEN (dein Ergebnis wird unabhaengig dagegen geprueft):\n"
                     + "\n".join(f"- {c['text']}" for c in criteria))
    if attempt >= 2:
        fb = (task.get("feedback") or "").strip()
        if fb:
            parts.append("\nDEIN VORHERIGER VERSUCH WURDE ABGELEHNT. Pruefer-Feedback:\n" + fb)
        if attempt >= 3:
            parts.append("\nWICHTIG: Wechsle die STRATEGIE grundlegend — anderer Ansatz, andere "
                         "Quellen/Werkzeuge als zuvor. Benenne deine neue Strategie im ersten Satz.")
        else:
            parts.append("\nBehebe die Kritikpunkte gezielt.")
    return "\n".join(parts)


def _execute_scored(task: dict, mission: str, escalate: bool) -> dict:
    """Ein Task-Versuch MIT Ergebnis-Rueckkopplung (S2): act -> pruefen -> pass/retry/fail.

    Retry = Requeue auf 'pending' fuer den NAECHSTEN Tick (crash-durabel, budget-glatt),
    nicht In-Tick-Schleife. Qualitaets-Retries (quality_retries) sind strikt getrennt
    von Absturz-Retries (retry_count, gehoert reset_stuck)."""
    sid = f"mission-{mission}"
    full = queue.get_task(task["id"]) or task

    if not _outcomes_enabled():  # Alt-Pfad: blind 'done' wie vor S2
        result = act(full["description"], session_id=sid, escalate=escalate, task_type="bulk")
        text = result["text"]
        queue.complete(full["id"], text)
        events.emit("mission_task_done", {"id": full["id"], "summary": text[:300]}, session_id=sid)
        _notify(f"🤖 Mission-Schritt erledigt:\n{full['description']}\n\n{text[:1200]}")
        return {"task": full["description"], "result": text}

    criteria = verifier.ensure_criteria(full)
    attempt = int(full.get("quality_retries") or 0) + 1
    strategy = ("standard", "eskaliert", "strategiewechsel")[min(attempt, 3) - 1]
    t0 = time.time()
    # Versuch 1 auf der billigen bulk-Route (wie bisher); ab Versuch 2 hebt 'reason' an.
    result = act(_attempt_prompt(full, criteria, attempt), session_id=sid,
                 escalate=escalate, task_type=("reason" if attempt >= 2 else "bulk"))
    text = result["text"]
    out = verifier.verify(full, criteria, text)
    outcomes.record(full["id"], attempt, criteria, out["checks"], out["score"], out["verdict"],
                    feedback=out["feedback"], strategy=strategy,
                    cost_usd=out["cost_usd"], duration_s=time.time() - t0)
    events.emit("task_scored", {"id": full["id"], "attempt": attempt, "score": out["score"],
                                "verdict": out["verdict"], "strategy": strategy}, session_id=sid)
    if full.get("objective_id"):
        try:
            takeaway = (out["feedback"] or "").strip() if out["verdict"] != "pass" \
                else (text.strip().splitlines() or [""])[0]
            workingset.append(full["objective_id"],
                              f"[{out['score']}/{out['verdict']}] {full['description'][:80]} -> {takeaway[:120]}")
        except Exception as e:  # noqa: BLE001
            events.emit("workingset_error", {"error": str(e)[:200]})

    if out["verdict"] == "pass":
        queue.complete(full["id"], text)
        queue.update_task(full["id"], score=out["score"])
        events.emit("mission_task_done", {"id": full["id"], "summary": text[:300],
                                          "score": out["score"]}, session_id=sid)
        label = f" (Score {out['score']})" if out["score"] is not None else ""
        _notify(f"🤖 Mission-Schritt erledigt{label}:\n{full['description']}\n\n{text[:1200]}")
        return {"task": full["description"], "result": text, "score": out["score"]}

    if attempt <= verifier.max_quality_retries():
        # Naechster Tick versucht es erneut: pop_next sortiert nach (priority, ts ASC),
        # der alte ts bringt den Task als erstes wieder dran.
        queue.update_task(full["id"], status="pending", quality_retries=attempt,
                          feedback=out["feedback"], score=out["score"])
        events.emit("task_retry", {"id": full["id"], "attempt": attempt, "score": out["score"],
                                   "feedback": (out["feedback"] or "")[:300]}, session_id=sid)
        return {"task": full["description"], "retry": attempt, "score": out["score"]}

    queue.complete(full["id"], text, status="failed")
    queue.update_task(full["id"], score=out["score"])
    events.emit("task_failed_final", {"id": full["id"], "attempts": attempt, "score": out["score"],
                                      "desc": full["description"][:200]}, session_id=sid)
    try:
        from core.mind import reflection

        reflection.reflect_on(
            full["description"],
            f"Nach {attempt} Versuchen an den Akzeptanzkriterien gescheitert. "
            f"Letztes Pruefer-Feedback: {out['feedback']}\n\nLetztes Ergebnis:\n{text[:1500]}")
    except Exception as e:  # noqa: BLE001
        events.emit("reflect_error", {"error": str(e)[:200]})
    try:
        from core.agency import approvals

        approvals.create(
            f"Task {attempt}x an Qualitaet gescheitert: {full['description'][:80]}",
            kind="generic", source="task",
            detail=(f"Aufgabe: {full['description']}\n\nKriterien:\n"
                    + "\n".join(f"- {c['text']}" for c in criteria)
                    + f"\n\nLetzter Score: {out['score']}\nLetztes Feedback: {out['feedback']}"))
    except Exception as e:  # noqa: BLE001
        events.emit("approval_error", {"error": str(e)[:200]})
    _notify(f"⚠️ Task endgueltig gescheitert ({attempt} Versuche, Score {out['score']}):\n"
            f"{full['description']}\n\nPruefer: {(out['feedback'] or '')[:600]}")
    return {"task": full["description"], "failed": True, "score": out["score"]}


def run_once(escalate: bool = False) -> dict:
    events.init_db()
    if kill_switch_active():
        events.emit("heartbeat_halted", {"reason": "kill_switch"})
        return {"halted": True}

    m = _mission()
    mission = m.get("name", "default")
    goal = m.get("goal") or _read("GOAL.md")
    focus = _focus()
    if focus:
        goal = f"AKTUELLER FOKUS von Sergen (hat Vorrang vor dem Dauer-Ziel): {focus}\n\n{goal}"
    queue.init_queue()

    if not queue.pending(mission):
        # Ziel-gerichtet planen: existieren aktive Objectives, arbeite aufs DRINGENDSTE hin
        # und verknuepfe die Tasks (objective_id) -> der Fortschritt fuellt sich automatisch.
        from core.agency.missions import objectives as _obj
        _obj.init_objectives()
        # S5: nur Business-Ziele werden vom Heartbeat gegrindet — Lebens-Ziele
        # (domain='leben') laufen ueber Coach/Briefings, nie automatisch.
        actives = _obj.list_active(domain="business")
        target = _pick_objective(actives)
        if target:
            plan_goal = (f"AKTIVES ZIEL (arbeite konkret hierauf hin): {target['title']}"
                         + (f"\n{target['notes']}" if target.get("notes") else "")
                         + f"\n\nUEBERGEORDNETE MISSION:\n{goal}")
            oid = target["id"]
            if target.get("venture_id"):
                # Unternehmer-Kontext: Kira plant mit Blick auf Kasse + Meilenstein (ROI statt Aktivitaet).
                try:
                    from core.agency import ventures as _ventures

                    v = _ventures.get(target["venture_id"])
                    if v:
                        plan_goal = (f"VENTURE: {v['name']} — {v.get('hypothesis') or ''} "
                                     f"(Kasse: {_ventures.balance(v['id']):.2f} EUR"
                                     + (f", Meilenstein {v['milestone_eur']:.0f} EUR" if v.get("milestone_eur") else "")
                                     + ")\n" + plan_goal)
                except Exception as e:  # noqa: BLE001
                    events.emit("venture_context_error", {"error": str(e)[:200]})
            ws = workingset.render(oid)
            if ws:  # Plaene bauen auf dem Stand auf, statt Erledigtes neu zu planen
                plan_goal += f"\n\nARBEITSSTAND ZUM ZIEL (nichts davon wiederholen):\n{ws}"
        else:
            plan_goal, oid = goal, None
        tasks = planner.generate_tasks(plan_goal, _context(), escalate=escalate)
        for t in tasks:
            queue.add(t, mission=mission, objective_id=oid)
        events.emit("mission_planned", {"mission": mission, "tasks": tasks,
                                        "objective": (target or {}).get("title")})

    task = queue.pop_next(mission)
    if not task:
        events.emit("heartbeat_idle", {"mission": mission})
        return {"idle": True}

    events.emit("mission_task_start", {"id": task["id"], "desc": task["description"]}, session_id=f"mission-{mission}")
    try:
        # 24/7-Grind guenstig: Versuch 1 laeuft auf der 'bulk'-Stufe (flash) statt 'reason'
        # (pro) -> ~5-8x billiger pro Tick; erst Qualitaets-Retries eskalieren die Route.
        # Ergebnis-Rueckkopplung (S2): pruefen statt blind 'done' melden.
        return _execute_scored(task, mission, escalate)
    except Exception as e:  # noqa: BLE001
        queue.complete(task["id"], str(e), status="failed")
        events.emit("mission_task_failed", {"id": task["id"], "error": str(e)})
        return {"task": task["description"], "error": str(e)}


def run_forever(interval: int | None = None) -> None:
    interval = interval or CONFIG.get("heartbeat", {}).get("interval_seconds", 1800)
    events.init_db()
    try:  # MCP-Bruecke im Hintergrund anschliessen (Ausfall darf den Boot nie bricken)
        from core.agency.mcp import registry_bridge as _mcp_bridge

        _mcp_bridge.init_background()
    except Exception as e:  # noqa: BLE001
        events.emit("mcp_bridge_error", {"error": str(e)[:200]})
    last_stuck_check = 0.0
    print(f"Mission-Runner laeuft. Cron+Monitor laufen immer; 24/7-Missionen nur wenn eingeschaltet. Takt {interval}s.")
    while True:
        try:
            if kill_switch_active():
                time.sleep(15)  # Not-Aus: pausieren, nach /go weiter
                continue

            # Durable Execution: haengengebliebene Tasks periodisch wiederbeleben.
            try:
                if time.time() - last_stuck_check >= 600:
                    reset_result = queue.reset_stuck(timeout_seconds=1800, max_retries=3)
                    last_stuck_check = time.time()
                    if reset_result.get("requeued", 0) > 0 or reset_result.get("failed", 0) > 0:
                        events.emit("mission_stuck_reset", reset_result)
            except Exception as e:  # noqa: BLE001
                events.emit("stuck_reset_error", {"error": str(e)})

            # Immer (unabhaengig vom Missions-Toggle): Monitor + geplante Aufgaben.
            try:
                from core.agency.connectors import news_monitor

                news_monitor.run_all(force=False, notify=True)
            except Exception as e:  # noqa: BLE001
                events.emit("monitor_error", {"error": str(e)})
            try:
                from core.agency.missions import cron

                cron.run_due()
            except Exception as e:  # noqa: BLE001
                events.emit("cron_error", {"error": str(e)})
            try:
                # Proaktive Trigger (S4): neue Events gegen Wenn-Dann-Reflexe matchen.
                from core.agency.missions import triggers as _triggers

                _triggers.check()
            except Exception as e:  # noqa: BLE001
                events.emit("trigger_error", {"error": str(e)})
            try:
                # Taegliche Pflege: Skill-Bibliothek entduplizieren (gebaut, jetzt verdrahtet).
                from core.agency.missions import maintenance

                if maintenance.maybe_run("curate_skills"):
                    from core.mind import curator

                    curator.curate_skills()
                if maintenance.maybe_run("curate_lessons"):
                    from core.mind import curator

                    curator.curate_lessons()
                if maintenance.maybe_run("embed_backfill", interval_s=7 * 86400):
                    from core.mind.memory import store as _mem

                    n = _mem.backfill_embeddings()
                    if n:
                        events.emit("embed_backfill", {"count": n})
                if maintenance.maybe_run("body_refresh"):
                    from core.mind import body

                    res = body.refresh()  # Anatomie-Fakten frisch abschreiben (S5)
                    events.emit("body_refreshed", res)
            except Exception as e:  # noqa: BLE001
                events.emit("maintenance_error", {"error": str(e)})
            try:
                # Stripe-Einnahmen alle 6h ins Venture-Konto-Buch ziehen (rein lesend).
                from core.agency.missions import maintenance

                if maintenance.maybe_run("stripe_sync", interval_s=6 * 3600):
                    from core.agency.connectors import stripe_sync

                    res = stripe_sync.sync()
                    if res.get("booked"):
                        _notify(f"💶 Stripe: {res['booked']} neue Zahlung(en), "
                                f"+{res['total_eur']:.2f} EUR im Konto-Buch.")
            except Exception as e:  # noqa: BLE001
                events.emit("stripe_sync_error", {"error": str(e)})
            try:
                # Business-Radar (S5): woechentlich nach Einkommens-Chancen scannen.
                from core.agency.missions import maintenance

                if maintenance.maybe_run("radar_scan", interval_s=7 * 86400):
                    from core.agency import radar

                    res = radar.scan(notify=True)
                    events.emit("radar_scan_done", res)
            except Exception as e:  # noqa: BLE001
                events.emit("radar_error", {"error": str(e)})

            if heartbeat_on():
                out = run_once()
                print("tick:", {k: (str(v)[:80]) for k, v in out.items()})
                # Unterbrechbarer Schlaf: reagiert binnen ~15s auf Abschalten (Dashboard-
                # Toggle) oder Kill-Switch, statt stur bis zu 'interval' Sek. weiterzulaufen.
                slept = 0
                while slept < interval and heartbeat_on() and not kill_switch_active():
                    step = min(15, interval - slept)
                    time.sleep(step)
                    slept += step
            else:
                time.sleep(60)  # aus -> Cron/Monitor ~minuetlich pruefen
        except KeyboardInterrupt:
            print("\nGestoppt.")
            break
        except Exception as e:  # noqa: BLE001
            events.emit("heartbeat_error", {"error": str(e)})
            time.sleep(20)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows-Konsole nicht crashen lassen
    except Exception:
        pass
    if "--once" in sys.argv:
        import json

        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    else:
        run_forever()