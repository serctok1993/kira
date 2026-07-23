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
import webbrowser

from core import identity as _identity
from core.config import ROOT

# W2: sichtbarer Agenten-Name fuer Fenster/Tray (AppUserModelID bleibt statisch 'Kira.Desktop').
_AGENT = _identity.agent_name()

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


# Boot-Splash statt weissem Fenster: das Fenster oeffnet SOFORT (dunkel, pulsierendes
# KIRA), waehrend der Supervisor hochfaehrt — vorher blockierte ensure_cockpit() bis
# zu 25s, bevor ueberhaupt ein Fenster erschien.
SPLASH_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#0a0a0d;color:#eceef4;
 font:14px/1.5 ui-monospace,Consolas,monospace;display:flex;align-items:center;justify-content:center}
.box{text-align:center}
.k{font-size:44px;letter-spacing:6px;font-weight:700;
 background:linear-gradient(100deg,#e9d5ff,#c084fc,#b026ff,#d946ef,#9333ea);
 -webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;
 filter:drop-shadow(0 0 14px rgba(176,38,255,.55));animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{opacity:.55}}
#st{margin-top:14px;color:#9b97b0;font-size:12px}
body.err .k{animation:none;filter:none;-webkit-text-fill-color:#ff3d68}
</style></head><body><div class="box"><div class="k">KIRA</div>
<div id="st">Cockpit startet…</div></div></body></html>"""


def _boot_into_cockpit(window) -> bool:
    """Splash -> Cockpit: wartet aufs Hochfahren, laedt dann um. Bei Fehlschlag zeigt
    der Splash einen Hinweis statt ewig zu pulsieren. GUI-frei testbar (Fake-Window)."""
    if ensure_cockpit():
        window.load_url(cockpit_url())
        return True
    try:
        window.evaluate_js(
            "document.body.classList.add('err');"
            "var s=document.getElementById('st');"
            "if(s)s.textContent='Cockpit startet nicht — bitte data/logs/cockpit.log pruefen.';")
    except Exception:  # noqa: BLE001 — Fenster evtl. schon zu; Hinweis ist Best-Effort
        pass
    return False


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

    def _browser(icon, item):
        webbrowser.open(cockpit_url())

    def _wall(icon, item):
        webbrowser.open(cockpit_url() + "wall")

    def _quit(icon, item):
        icon.stop()
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            pass

    menu = pystray.Menu(
        pystray.MenuItem("Cockpit öffnen", _open, default=True),
        pystray.MenuItem("Im Browser öffnen", _browser),
        pystray.MenuItem("Wallpaper-Vorschau", _wall),
        pystray.MenuItem(f"{_AGENT} neu starten", _restart),
        pystray.MenuItem("Beenden", _quit),
    )
    icon = pystray.Icon("kira", _load_icon(), f"{_AGENT} · Cockpit", menu)
    threading.Thread(target=icon.run, daemon=True).start()


def _hotkey_cfg() -> tuple[str, str]:
    """Tastenkuerzel aus config.yaml (desktop.hotkey / desktop.ptt_key) mit Defaults."""
    try:
        from core.config import CONFIG
        d = CONFIG.get("desktop", {}) or {}
    except Exception:  # noqa: BLE001
        d = {}
    return (str(d.get("hotkey") or "alt+space"), str(d.get("ptt_key") or "f9"))


def _start_hotkeys(window) -> None:
    """Globale Tasten (Phase 4): Hotkey holt das Chatfenster aus JEDER App nach vorn,
    PTT-Taste HALTEN = aufnehmen, LOSLASSEN = transkribieren + senden (window.kiraPTT
    im Cockpit-JS). Fehlt das keyboard-Paket, laeuft die App einfach ohne Hotkeys."""
    try:
        import keyboard  # type: ignore
    except Exception:  # noqa: BLE001 — optional (requirements-desktop.txt)
        return
    show_key, ptt_key = _hotkey_cfg()

    def _show(*_a):
        try:
            window.restore()
        except Exception:  # noqa: BLE001 — aeltere pywebview ohne restore()
            pass
        try:
            window.show()
        except Exception:  # noqa: BLE001
            pass

    def _ptt(down: bool):
        if down:
            _show()
        try:  # kiraPTT ist idempotent gegen Tasten-Autorepeat
            window.evaluate_js(f"window.kiraPTT&&window.kiraPTT({str(down).lower()})")
        except Exception:  # noqa: BLE001
            pass

    try:
        keyboard.add_hotkey(show_key, _show)
        keyboard.on_press_key(ptt_key, lambda e: _ptt(True))
        keyboard.on_release_key(ptt_key, lambda e: _ptt(False))
    except Exception:  # noqa: BLE001 — kaputte Taste/fehlende Rechte: App laeuft weiter
        pass


def run() -> None:
    """Desktop-App starten: Cockpit sicherstellen, Tray-Symbol + natives Fenster oeffnen."""
    # Worktree-Vorfall 18./19.07.: kira-desktop.bat lief aus einem Worktree-Checkout —
    # dort bootete eine Alt-Kira mit leerem data/ (setup_required). Veto vor allem anderen.
    from core import config as _cfg
    veto = _cfg.dienststart_verweigert()
    if veto:
        print(veto)
        return
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
    # Fenster SOFORT oeffnen: laeuft das Cockpit schon, direkt dorthin; sonst dunkler
    # Splash + Boot im Hintergrund (statt bis zu 25s gar kein Fenster). background_color
    # verhindert den weissen Blitz, bevor die Seite gerendert ist.
    win_kwargs = dict(width=1280, height=860, min_size=(900, 600), background_color="#0a0a0d")
    if is_cockpit_up():
        window = webview.create_window(f"{_AGENT} · Cockpit", cockpit_url(), **win_kwargs)
        boot = None
    else:
        window = webview.create_window(f"{_AGENT} · Cockpit", html=SPLASH_HTML, **win_kwargs)
        boot = _boot_into_cockpit
    _start_tray(window)
    _start_hotkeys(window)
    func = (lambda: boot(window)) if boot else None
    # Fenster-/Taskleisten-Symbol = data/kira-icon.ico (nur ICO, s. _window_icon). Fehlt es oder
    # mag die pywebview-Version den icon-Parameter nicht -> IMMER ohne Icon weiterstarten, damit die
    # App auf keinen Fall am Symbol scheitert.
    icon = _window_icon()
    if not icon:
        webview.start(func)
        return
    try:
        webview.start(func, icon=icon)
    except Exception:  # noqa: BLE001 — alte pywebview / Icon-Problem -> ohne Icon starten
        webview.start(func)


if __name__ == "__main__":
    run()
