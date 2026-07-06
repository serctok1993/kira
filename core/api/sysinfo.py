"""System-Kennzahlen fuer die Desktop-Leiste — best effort, raist NIE.

CPU/RAM via psutil (falls installiert: `uv pip install -r requirements-desktop.txt`),
GPU-Auslastung/-Temperatur via nvidia-smi (falls eine NVIDIA-Karte da ist). Jede Quelle ist
optional: fehlt sie, kommt None zurueck -> das Wallpaper zeigt schlicht „—". 4-Sekunden-Cache.
"""
from __future__ import annotations

import subprocess
import time

_CACHE: dict = {"ts": 0.0, "data": None}


def _nvidia() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return {}
        line = (out.stdout.strip().splitlines() or [""])[0]
        p = [x.strip() for x in line.split(",")]
        return {"gpu": int(p[0]), "gpu_temp": int(p[1]),
                "gpu_mem": round(int(p[2]) / max(1, int(p[3])) * 100)}
    except Exception:  # noqa: BLE001 — kein nvidia-smi / keine NVIDIA -> einfach nichts
        return {}


def _psutil() -> dict:
    try:
        import psutil
        d: dict = {"cpu": round(psutil.cpu_percent(interval=None)),
                   "ram": round(psutil.virtual_memory().percent)}
        try:
            for arr in (psutil.sensors_temperatures() or {}).values():
                if arr:
                    d["cpu_temp"] = round(arr[0].current)
                    break
        except Exception:  # noqa: BLE001 — sensors_temperatures gibt's auf Windows oft nicht
            pass
        return d
    except Exception:  # noqa: BLE001 — psutil nicht installiert
        return {}


def snapshot(max_age: float = 4.0) -> dict:
    now = time.time()
    if _CACHE["data"] is not None and now - _CACHE["ts"] < max_age:
        return _CACHE["data"]
    d = {"cpu": None, "ram": None, "gpu": None, "gpu_temp": None, "cpu_temp": None, "gpu_mem": None}
    d.update(_psutil())
    d.update(_nvidia())
    _CACHE["ts"] = now
    _CACHE["data"] = d
    return d
