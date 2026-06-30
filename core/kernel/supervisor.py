"""Supervisor / Watchdog: haelt Kiras Dienste am Leben.

Startet Cockpit, Telegram-Bot und Mission-Runner und ueberwacht sie. Stirbt einer
(Crash, Self-Edit, manueller Kill) -> Neustart in Sekunden. Ein Restart-Flag
(data/restart.flag) erlaubt einen SICHEREN Bounce nach self_edit, ohne dass Kira
sich selbst killt (Self-Kill ist in shelltool zusaetzlich gesperrt).

Singleton: laeuft nur, wenn Port 8000 frei ist (sonst ist schon ein System aktiv).
Start:  uv run python -m core.kernel.supervisor   (oder via start-all.ps1 / Autostart)
"""
from __future__ import annotations

import datetime
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from core.config import ROOT

PY = sys.executable  # der (venv-)Python, mit dem der Supervisor laeuft
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

COMPONENTS: dict[str, list[str]] = {
    "cockpit": [PY, "-m", "uvicorn", "core.api.server:app", "--host", "127.0.0.1", "--port", "8000"],
    "bot": [PY, "-m", "core.agency.connectors.telegram_bot"],
    "runner": [PY, "-m", "core.agency.missions.runner"],
}
RESTART_FLAG = ROOT / "data" / "restart.flag"


def _port_in_use(port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _launch(name: str) -> subprocess.Popen:
    log = ROOT / "data" / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    f = open(log, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 (lebt mit dem Prozess)
    f.write(f"\n===== {name} gestartet {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    f.flush()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}  # Logs sofort sichtbar (kein Puffer)
    return subprocess.Popen(COMPONENTS[name], cwd=str(ROOT), creationflags=_NO_WINDOW,
                            stdout=f, stderr=subprocess.STDOUT, env=env)


def main() -> None:
    if _port_in_use(8000):
        print("Port 8000 belegt -> es laeuft bereits ein Kira-System. Supervisor beendet sich.")
        return

    RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
    if RESTART_FLAG.exists():
        RESTART_FLAG.unlink()

    procs: dict[str, subprocess.Popen] = {}
    for name in COMPONENTS:
        procs[name] = _launch(name)
        time.sleep(1)  # Cockpit zuerst -> Port belegen, bevor andere starten
    print("Supervisor laeuft. Bewacht:", ", ".join(COMPONENTS))

    while True:
        try:
            time.sleep(5)

            # 1) Tote Komponenten neu starten
            for name, p in list(procs.items()):
                if p.poll() is not None:
                    print(f"[supervisor] {name} gestorben (code {p.returncode}) -> Neustart")
                    procs[name] = _launch(name)

            # 2) Restart-Flag (z.B. nach self_edit): sicherer Bounce der genannten Dienste
            if RESTART_FLAG.exists():
                try:
                    want = RESTART_FLAG.read_text(encoding="utf-8").strip().lower()
                    RESTART_FLAG.unlink()
                except Exception:  # noqa: BLE001
                    want = "all"
                targets = (list(COMPONENTS) if want in ("", "all")
                           else [w.strip() for w in want.split(",") if w.strip() in COMPONENTS])
                time.sleep(20)  # laufende Antwort fertig + Bericht senden lassen, dann erst bouncen
                for name in targets:
                    try:
                        procs[name].terminate()
                    except Exception:  # noqa: BLE001
                        pass
                time.sleep(2)
                for name in targets:
                    procs[name] = _launch(name)
                print("[supervisor] Bounce per Flag:", targets)
        except KeyboardInterrupt:
            print("\nSupervisor gestoppt.")
            break
        except Exception as e:  # noqa: BLE001
            print("[supervisor] Fehler:", e)
            time.sleep(5)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
