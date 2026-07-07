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


def mini_url() -> str:
    return f"http://{COCKPIT_HOST}:{COCKPIT_PORT}/chat-mini"


# Globaler Hotkey fuers Mini-Fenster (Phase 4). Aus config.yaml -> desktop.chat_hotkey, Default Alt+Space.
_MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "strg": 0x0002,
        "shift": 0x0004, "win": 0x0008, "super": 0x0008}
_VK = {"space": 0x20, "leertaste": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09,
       "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73}


def _parse_hotkey(combo: str):
    """"alt+space" / "ctrl+shift+k" -> (modifiers, virtual_key) fuer Win32 RegisterHotKey.
    Reine Funktion (ohne Windows testbar). None, wenn keine Taste erkannt wird."""
    if not combo:
        return None
    mods, vk = 0, None
    for part in str(combo).lower().replace(" ", "").split("+"):
        if not part:
            continue
        if part in _MOD:
            mods |= _MOD[part]
        elif part in _VK:
            vk = _VK[part]
        elif len(part) == 1:
            vk = ord(part.upper())
    return (mods, vk) if vk is not None else None


def _chat_hotkey() -> str:
    """Konfigurierter Hotkey (config.yaml: desktop.chat_hotkey), Default Alt+Space."""
    try:
        from core.config import CONFIG
        return str((CONFIG.get("desktop") or {}).get("chat_hotkey") or "alt+space")
    except Exception:  # noqa: BLE001
        return "alt+space"


def _start_hotkey(combo: str, on_press) -> bool:
    """Registriert den globalen Hotkey (nur Windows) in einem Daemon-Thread mit eigener
    Message-Loop. Ruft on_press() bei jedem Druck. Gibt zurueck, ob es losgelaufen ist —
    schlaegt es fehl (kein Windows, Taste belegt), laeuft die App ohne Hotkey weiter."""
    parsed = _parse_hotkey(combo)
    if not parsed:
        return False
    mods, vk = parsed
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32  # nur Windows -> sonst AttributeError
    except Exception:  # noqa: BLE001
        return False

    def _loop():
        if not user32.RegisterHotKey(None, 1, mods | 0x4000, vk):  # 0x4000 = MOD_NOREPEAT
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                try:
                    on_press()
                except Exception:  # noqa: BLE001
                    pass

    import threading
    threading.Thread(target=_loop, daemon=True).start()
    return True


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


def _icon_path():
    """Pfad zum App-Logo als Datei (fuer das Fenster-/Taskleisten-Symbol). .ico bevorzugt
    (Windows-Taskleiste mag das Format am liebsten), sonst PNG etc. None, wenn keins liegt."""
    for ext in ("ico", "png", "jpg", "jpeg", "webp"):
        p = ROOT / "data" / f"kira-icon.{ext}"
        if p.exists():
            return str(p)
    return None


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

    # Phase 4: kleines Schwebe-Fenster (echter Tastatur-Fokus) + globaler Hotkey.
    # Bruecke fuer die Knoepfe im Mini-Fenster: „Kira oeffnen" / „Schliessen".
    class _MiniApi:
        def open_app(self):
            try:
                window.show()
            except Exception:  # noqa: BLE001
                pass

        def hide_mini(self):
            try:
                _mini["win"].hide()
                _mini["shown"] = False
            except Exception:  # noqa: BLE001
                pass

    _mini = {"win": None, "shown": False}
    try:
        _mini["win"] = webview.create_window(
            "Kira", mini_url(), width=560, height=190, frameless=True,
            on_top=True, easy_drag=True, hidden=True, js_api=_MiniApi())
    except Exception:  # noqa: BLE001 — aeltere pywebview ohne diese Parameter: Mini-Fenster entfaellt
        _mini["win"] = None

    def _toggle_mini():
        w = _mini["win"]
        if not w:
            return
        try:
            if _mini["shown"]:
                w.hide()
                _mini["shown"] = False
            else:
                w.show()
                _mini["shown"] = True
        except Exception:  # noqa: BLE001
            pass

    if _mini["win"] is not None:
        _start_hotkey(_chat_hotkey(), _toggle_mini)

    # Fenster-/Taskleisten-Symbol = unser Logo (data/kira-icon.*). Aeltere pywebview-Versionen
    # kennen den icon-Parameter nicht -> dann ohne starten (App laeuft trotzdem).
    icon = _icon_path()
    try:
        webview.start(icon=icon) if icon else webview.start()
    except TypeError:
        webview.start()


if __name__ == "__main__":
    run()
