#!/usr/bin/env python3
"""
Sunrise Simulation fuer Sergens Schlafzimmer (Hue Lampe ID 18).
Startet um eine gegebene Uhrzeit + rampt ueber 60 Minuten Helligkeit hoch.
Nutzung: python sunrise_simulation.py [start_time=HH:MM]  oder  start_time=now
"""

import sys
import time
import re
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

LIGHT_ID = 18
RAMP_MINUTES = 60
MIN_BRIGHTNESS = 5
MAX_BRIGHTNESS = 254


def parse_start_time() -> datetime:
    """Liest start_time aus cmdline-Argumenten."""
    raw = None
    for a in sys.argv[1:]:
        if a.startswith("start_time="):
            raw = a.split("=", 1)[1].strip()
            break

    if not raw:
        raw = "06:00"

    if raw == "now":
        return datetime.now()

    match = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if not match:
        print(f"Ungueltiges Format: '{raw}' -- erwarte HH:MM oder 'now'", flush=True)
        sys.exit(1)

    hour, minute = int(match.group(1)), int(match.group(2))
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if target <= now:
        target += timedelta(days=1)

    return target


def set_light(brightness: int, color: str = "orange"):
    """Setzt Hue-Lampe auf Helligkeit + Farbe."""
    from core.tools.hue_control import set_brightness, set_color, light_on_off

    light_on_off(LIGHT_ID, True)
    set_color(LIGHT_ID, color)
    set_brightness(LIGHT_ID, brightness)


def main():
    start_time = parse_start_time()

    now = datetime.now()
    if start_time > now:
        wait_sec = (start_time - now).total_seconds()
        print(f"[Sunrise] Warte {wait_sec:.0f}s bis {start_time.strftime('%H:%M')} Uhr ...", flush=True)
        time.sleep(wait_sec)

    print(f"[Sunrise] Starte jetzt um {datetime.now().strftime('%H:%M:%S')}!", flush=True)

    set_light(MIN_BRIGHTNESS, "orange")
    print(f"   -> Stufe 0/{RAMP_MINUTES}: Helligkeit {MIN_BRIGHTNESS} (orange)", flush=True)

    step_sec = (RAMP_MINUTES * 60) / RAMP_MINUTES  # 60s

    for step in range(1, RAMP_MINUTES + 1):
        progress = step / RAMP_MINUTES
        brightness = int(MIN_BRIGHTNESS + (MAX_BRIGHTNESS - MIN_BRIGHTNESS) * progress)
        brightness = max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, brightness))

        if progress < 0.3:
            color = "orange"
        elif progress < 0.6:
            color = "yellow"
        else:
            color = "white"

        set_light(brightness, color)
        print(f"   -> Stufe {step}/{RAMP_MINUTES}: Helligkeit {brightness} ({color})", flush=True)
        time.sleep(step_sec)

    print(f"\n[Sunrise] Fertig um {datetime.now().strftime('%H:%M:%S')} -- Licht auf voller Helligkeit!", flush=True)


if __name__ == "__main__":
    main()
