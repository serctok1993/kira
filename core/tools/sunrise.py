"""
Sunrise-Simulation — Kira weckt Sergen sanft mit Licht.

Läuft einmalig und rampt über 60 Minuten die Helligkeit hoch von 1 auf 254.
Aufruf: python core/tools/sunrise.py [--light 18] [--start 06:00]

Farbtemperatur: warm (ct=500), damit es sich wie echter Sonnenaufgang anfühlt.
"""

import argparse
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Hue-Import (relativ zum Projekt)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.tools.hue_control import light_on_off, set_brightness, _req

BRIGHTNESS_MIN = 1      # kaum wahrnehmbar
BRIGHTNESS_MAX = 254    # volle Helle
DURATION_MINUTES = 60   # Rampen-Dauer
STEPS = 60              # Anzahl Schritte (einer pro Minute)
COLOR_TEMP = 500        # warmweiss (500 = sehr warm)

def set_warm_white(light_id: int, bri: int) -> dict:
    """Setzt Lampe auf warmweiss mit gegebener Helligkeit."""
    return _req("PUT", f"/lights/{light_id}/state", {
        "on": True,
        "bri": bri,
        "ct": COLOR_TEMP,
        "sat": 0,        # Farbsättigung aus
        "transitiontime": 0
    })

def sunrise(light_id: int = 18, start_hour: int = 6, start_min: int = 0):
    """Führt den Sonnenaufgang durch."""
    now = datetime.now()
    start = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)

    # Wenn die Startzeit noch in der Zukunft liegt: warten
    if start > now:
        wait_seconds = (start - now).total_seconds()
        print(f"☀️  Sunrise startet um {start_hour:02d}:{start_min:02d} Uhr "
              f"(noch {int(wait_seconds // 60)} Minuten warten)")
        time.sleep(wait_seconds)

    print(f"☀️  Sunrise gestartet – rampe Lampe {light_id} hoch über {DURATION_MINUTES} min")

    # Lampe einschalten auf niedrigster Stufe
    set_warm_white(light_id, BRIGHTNESS_MIN)
    print(f"   Schritt 0/{STEPS}: Helligkeit {BRIGHTNESS_MIN}")

    delay = (DURATION_MINUTES * 60) / STEPS  # Sekunden zwischen Schritten

    for step in range(1, STEPS + 1):
        bri = int(BRIGHTNESS_MIN + (BRIGHTNESS_MAX - BRIGHTNESS_MIN) * (step / STEPS))
        bri = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, bri))
        set_warm_white(light_id, bri)
        if step % 10 == 0 or step == STEPS:
            print(f"   Schritt {step}/{STEPS}: Helligkeit {bri}")
        time.sleep(delay)

    print(f"☀️  Sunrise abgeschlossen – Lampe {light_id} auf voller Helligkeit")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sunrise-Simulation für Hue-Lampe")
    parser.add_argument("--light", type=int, default=18, help="Lampen-ID (Standard: 18)")
    parser.add_argument("--start", type=str, default="06:00", help="Startzeit (HH:MM, Standard: 06:00)")
    args = parser.parse_args()

    try:
        hour, minute = map(int, args.start.split(":"))
    except ValueError:
        print("Fehler: Startzeit muss im Format HH:MM sein, z.B. 06:00")
        sys.exit(1)

    print(f"🌅 Sunrise-Script gestartet")
    print(f"   Lampe: {args.light} | Start: {args.start} Uhr | Dauer: {DURATION_MINUTES} min")
    print(f"   Von Helligkeit {BRIGHTNESS_MIN} → {BRIGHTNESS_MAX} (warmweiss, ct={COLOR_TEMP})")

    sunrise(light_id=args.light, start_hour=hour, start_min=minute)
