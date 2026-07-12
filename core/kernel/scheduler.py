"""Heartbeat-Schalter + Not-Aus (Kill-Switch) — die Wahrheit fuers ganze System.

W1: der alte Stub-Loop (tick/run) ist raus — die echte Mission-Schleife lebt in
core/agency/missions/runner.py. Hier wohnen nur noch die Schalter, die ueberall
gelesen werden: heartbeat_on/set_heartbeat (Laufzeit-Flag vor config.yaml) und
kill_switch_active (data/STOP).
"""
from __future__ import annotations

from pathlib import Path

from core.config import CONFIG, ROOT


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
