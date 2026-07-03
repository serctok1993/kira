#!/usr/bin/env python3
"""Sunrise-Simulation für Hue-Lampe (Schlafzimmer, ID 18).
Startet das Skript mit Ziel-Uhrzeit als Argument: python sunrise_hue.py 06:00
Ramped Helligkeit über 60 Minuten von 1 auf 254 (kaum wahrnehmbar → voll).
"""

import sys
import time
import subprocess
from datetime import datetime, timedelta

LIGHT_ID = 18

def call_hue(method, *args):
    """Ruft die hue_control-Tools aus dem Projekt auf."""
    cmd = [
        sys.executable, "-c",
        f"from core.tools.hue_control import {method}; {method}(*{args})"
    ]
    subprocess.run(cmd, capture_output=True, timeout=10)

def wait_until(target: datetime):
    """Blockiert bis zur Zielzeit."""
    now = datetime.now()
    delay = (target - now).total_seconds()
    if delay > 0:
        print(f"Warte {delay:.0f} Sekunden bis zur Zielzeit {target.strftime('%H:%M')}...")
        time.sleep(delay)

def sunrise(target_str: str):
    target = datetime.strptime(target_str, "%H:%M").replace(
        year=datetime.now().year,
        month=datetime.now().month,
        day=datetime.now().day
    )
    # Falls die Zielzeit heute schon vorbei ist, +1 Tag
    if target < datetime.now():
        target += timedelta(days=1)

    wait_until(target)

    duration_minutes = 60
    steps = duration_minutes  # einmal pro Minute
    min_bri = 1
    max_bri = 254

    # Lampe einschalten mit minimaler Helligkeit
    print("Schalte Lampe ein (minimale Helligkeit)...")
    call_hue("light_on_off", LIGHT_ID, True)
    call_hue("set_brightness", LIGHT_ID, min_bri)
    call_hue("set_color", LIGHT_ID, "white")

    for step in range(1, steps + 1):
        brightness = int(min_bri + (max_bri - min_bri) * (step / steps))
        call_hue("set_brightness", LIGHT_ID, brightness)
        print(f"  Schritt {step}/{steps}: Helligkeit {brightness}")
        time.sleep(60)  # 1 Minute pro Schritt

    print("Sunrise abgeschlossen. Helligkeit auf Maximum.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sunrise_hue.py <HH:MM>")
        sys.exit(1)
    sunrise(sys.argv[1])
