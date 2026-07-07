"""Kira Desktop (Stufe 1): das Cockpit als native App + Tray-Symbol — kein Browser noetig.

Es wird NICHTS am Cockpit geaendert: die App stellt (bei Bedarf) den Supervisor sicher und
zeigt http://127.0.0.1:8000 in einem eigenen Fenster (pywebview). Ein Tray-Symbol bietet
"Cockpit oeffnen / Kira neu starten / Beenden".

GUI-Abhaengigkeiten (pywebview, pystray, pillow) sind OPTIONAL und werden LAZY importiert —
Kern und Tests bleiben damit GUI-frei (laufen auch headless). Installieren:

    uv pip install -r requirements-desktop.txt

Start:  uv run python -m core.desktop.app   (oder Doppelklick auf kira-desktop.bat)
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time

from core.config import ROOT

# Muss zum Supervisor passen (core/kernel/supervisor.py -> COMPONENTS["cockpit"]).
COCKPIT_HOST = "127.0.0.1"
COCKPIT_PORT = 8000
RESTART_FLAG = ROOT / "data" / "restart.flag"
_PY = sys.executable  # der (venv-)Python, mit dem die App laeuft


def cockpit_url() -> str:
    return f"http://{COCKPIT_HOST}:{COCKPIT_PORT}/"


def is_cockpit_up(timeout: float = 1.0) -> bool:
    """Lauscht das Cockpit schon auf Port 8000? (reiner Loopback-Check, kein HTTP noetig)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((COCKPIT_HOST, COCKPIT_PORT)) == 0


def start_supervisor() -> subprocess.Popen:
    """Startet den Supervisor (haelt Cockpit/Bot/Runner am Leben). Der Supervisor hat einen
    eigenen Singleton-Lock (Port 8009) -> ein zweiter Start beendet sich sofort selbst.
    Der Aufruf ist also gefahrlos, auch wenn schon eine Instanz laeuft."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # kein Konsolenfenster unter Windows
    return subprocess.Popen([_PY, "-m", "core.kernel.supervisor"], cwd=str(ROOT),
                            creationflags=flags)


def ensure_cockpit(wait: float = 25.0) -> bool:
    """Cockpit erreichbar machen: laeuft es schon -> sofort True. Sonst Supervisor starten und
    bis zu `wait` Sekunden aufs Hochfahren warten. Gibt zurueck, ob das Cockpit antwortet."""
    if is_cockpit_up():
        return True
    start_supervisor()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_cockpit_up():
            return True
        time.sleep(0.5)
    return is_cockpit_up()


def request_restart() -> None:
    """Sicherer Neustart wie 'kira-update.bat': legt data/restart.flag ('all') an — der
    Supervisor bounced dann Cockpit/Bot/Runner, sobald Kira idle ist."""
    RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
    RESTART_FLAG.write_text("all", encoding="utf-8")


def _window_icon():
    """Fenster-/Taskleisten-Symbol fuer pywebview: NUR .ico. Windows/EdgeChromium akzeptiert als
    Fenster-Icon ausschliesslich das ICO-Format — ein .png/.jpg hier laesst die App beim Start
    crashen. Fehlt ein .ico (z.B. weil kira-einrichten.bat noch nicht lief), geben wir None zurueck
    und starten ohne Icon. Das Tray-Symbol (Pillow) und das /wall-Favicon nutzen weiter JEDES Format."""
    p = ROOT / "data" / "kira-icon.ico"
    return str(p) if p.exists() else None


def _load_icon():
    """Tray-Icon: das App-Logo aus data/kira-icon.png (wenn vorhanden), sonst ein schlichtes
    Kira-Lila 'K'. Nutzt Pillow; fehlt es, None (pystray-Default) — die App laeuft immer."""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001 — Pillow ist optional
        return None
    for ext in ("png", "jpg", "jpeg", "webp", "ico"):
        p = ROOT / "data" / f"kira-icon.{ext}"
        if p.exists():
            try:
                return Image.open(str(p)).convert("RGBA")
            except Exception:  # noqa: BLE001 — kaputtes Bild -> auf das gezeichnete 'K' zurueckfallen
                break
    img = Image.new("RGBA", (64, 64), (14, 14, 18, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 59, 59], radius=12, outline=(176, 38, 255, 255), width=4)
    d.text((23, 20), "K", fill=(176, 38, 255, 255))
    return img


def _start_tray(window) -> None:
    """Tray-Symbol in einem Daemon-Thread. Fehlt pystray, laeuft die App ohne Symbol weiter."""
    try:
        import threading

        import pystray
    except Exception:  # noqa: BLE001 — pystray optional
        return

    def _open(icon, item):
        try:
            window.show()
        except Exception:  # noqa: BLE001
            pass

    def _restart(icon, item):
        request_restart()

    def _quit(icon, item):
        icon.stop()
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            pass

    menu = pystray.Menu(
        pystray.MenuItem("Cockpit öffnen", _open, default=True),
        pystray.MenuItem("Kira neu starten", _restart),
        pystray.MenuItem("Beenden", _quit),
    )
    icon = pystray.Icon("kira", _load_icon(), "Kira · Cockpit", menu)
    threading.Thread(target=icon.run, daemon=True).start()


def run() -> None:
    """Desktop-App starten: Cockpit sicherstellen, Tray-Symbol + natives Fenster oeffnen."""
    try:
        import webview
    except Exception as e:  # noqa: BLE001
        print("pywebview fehlt. Installiere die Desktop-Extras:  uv pip install -r requirements-desktop.txt")
        raise SystemExit(1) from e
    # Windows: eigene App-Identitaet -> die Taskleiste gruppiert Kira unter dem eigenen Symbol
    # (statt unter dem generischen Python-Icon) und uebernimmt unser Logo.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Kira.Desktop")
    except Exception:  # noqa: BLE001 — nur Windows; anderswo egal
        pass
    ensure_cockpit()
    window = webview.create_window("Kira · Cockpit", cockpit_url(),
                                   width=1280, height=860, min_size=(900, 600))
    _start_tray(window)
    # Fenster-/Taskleisten-Symbol = data/kira-icon.ico (nur ICO, s. _window_icon). Fehlt es oder
    # mag die pywebview-Version den icon-Parameter nicht -> IMMER ohne Icon weiterstarten, damit die
    # App auf keinen Fall am Symbol scheitert.
    icon = _window_icon()
    if not icon:
        webview.start()
        return
    try:
        webview.start(icon=icon)
    except Exception:  # noqa: BLE001 — alte pywebview / Icon-Problem -> ohne Icon starten
        webview.start()


if __name__ == "__main__":
    run()
