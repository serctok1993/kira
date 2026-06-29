"""Heartbeat — der autonome Takt.

Phase 1: nur ein Stub und standardmaessig deaktiviert (config.yaml).
Die volle Mission-Schleife (Queue abarbeiten, nachts laufen) kommt in Phase 4.
Der Kill-Switch wird hier bereits respektiert.
"""
from __future__ import annotations

import time

from core.config import CONFIG, ROOT
from core.kernel import events


def kill_switch_active() -> bool:
    rel = CONFIG.get("governance", {}).get("kill_switch_file", "data/STOP")
    return (ROOT / rel).exists()


def tick() -> None:
    if kill_switch_active():
        events.emit("heartbeat_halted", {"reason": "kill_switch"})
        return
    events.emit("heartbeat", {"note": "stub — noch keine Missionen"})


def run() -> None:
    hb = CONFIG.get("heartbeat", {})
    if not hb.get("enabled"):
        print("Heartbeat ist deaktiviert (config.yaml: heartbeat.enabled=false).")
        return
    interval = hb.get("interval_seconds", 900)
    print(f"Heartbeat laeuft alle {interval}s. Strg+C zum Stoppen.")
    events.init_db()
    try:
        while True:
            if kill_switch_active():
                print("KILL-SWITCH aktiv — Heartbeat haelt an.")
                break
            tick()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nHeartbeat gestoppt.")


if __name__ == "__main__":
    run()
