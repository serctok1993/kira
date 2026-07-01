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

from core.agency.act import act
from core.agency.missions import planner, queue
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
        tasks = planner.generate_tasks(goal, _context(), escalate=escalate)
        for t in tasks:
            queue.add(t, mission=mission)
        events.emit("mission_planned", {"mission": mission, "tasks": tasks})

    task = queue.pop_next(mission)
    if not task:
        events.emit("heartbeat_idle", {"mission": mission})
        return {"idle": True}

    events.emit("mission_task_start", {"id": task["id"], "desc": task["description"]}, session_id=f"mission-{mission}")
    try:
        result = act(task["description"], session_id=f"mission-{mission}", escalate=escalate)
        text = result["text"]
        queue.complete(task["id"], text)
        events.emit("mission_task_done", {"id": task["id"], "summary": text[:300]}, session_id=f"mission-{mission}")
        _notify(f"🤖 Mission-Schritt erledigt:\n{task['description']}\n\n{text[:1200]}")
        return {"task": task["description"], "result": text}
    except Exception as e:  # noqa: BLE001
        queue.complete(task["id"], str(e), status="failed")
        events.emit("mission_task_failed", {"id": task["id"], "error": str(e)})
        return {"task": task["description"], "error": str(e)}


def run_forever(interval: int | None = None) -> None:
    interval = interval or CONFIG.get("heartbeat", {}).get("interval_seconds", 1800)
    events.init_db()
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

            if heartbeat_on():
                out = run_once()
                print("tick:", {k: (str(v)[:80]) for k, v in out.items()})
                time.sleep(interval)
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