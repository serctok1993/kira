"""Heartbeat — der autonome Takt.

Phase 1: nur ein Stub und standardmaessig deaktiviert (config.yaml).
Die volle Mission-Schleife (Queue abarbeiten, nachts laufen) kommt in Phase 4.
Der Kill-Switch wird hier bereits respektiert.
"""
from __future__ import annotations

import time
from pathlib import Path

from core.config import CONFIG, ROOT
from core.kernel import events


def kill_switch_path() -> Path:
    rel = CONFIG.get("governance", {}).get("kill_switch_file", "data/STOP")
    return ROOT / rel


def kill_switch_active() -> bool:
    return kill_switch_path().exists()


def heartbeat_path() -> Path:
    return ROOT / "data" / "heartbeat.flag"


def heartbeat_on() -> bool:
    """24/7-Mission-Loop aktiv? Laufzeit-Flag (Cockpit) hat Vorrang vor config.yaml."""
    p = heartbeat_path()
    if p.exists():
        return p.read_text(encoding="utf-8").strip() == "on"
    return bool(CONFIG.get("heartbeat", {}).get("enabled"))


def set_heartbeat(on: bool) -> None:
    p = heartbeat_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("on" if on else "off", encoding="utf-8")


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
