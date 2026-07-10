"""Computer-Use (Macht-Schritt 1): Kira sieht den Bildschirm und bedient Maus,
Tastatur und Fenster — damit sie JEDES Programm steuern kann, auch solche ohne API
(Photoshop, Legacy-Tools, Desktop-Apps).

Bewusst OHNE neue Abhaengigkeit: Bildschirmfoto via PowerShell (System.Drawing),
Maus/Tastatur/Fenster via ctypes (user32) — reines Windows-Bordmittel. Off-Windows
liefern die Werkzeuge einen klaren Hinweis statt zu krachen.

Sicherheits-Schichten (Prinzip 'jede Macht bekommt ihr Gate'):
- Standard AUS: nur nutzbar, wenn agency.computer_use.enabled im Steuerpult an ist.
- Not-Aus (kill switch) blockt hart — wie bei Shell/Browser.
- Test-/Sandbox-Modus (KIRA_TEST_MODE) fuehrt NIE echte Eingaben aus (simuliert nur),
  damit Suite und Benchmark den echten Rechner nie anfassen.
- Jede Aktion wird als 'computer_use'-Event auditiert (im Protokoll sichtbar).

Die reine Logik (Gate, Argument-Parsing, Tasten-Mapping) ist offline testbar;
die OS-Aufrufe sind lazy und plattformgeschuetzt.
"""
from __future__ import annotations

import sys
import time

from core.agency.tools.registry import tool
from core.config import CONFIG, test_mode
from core.kernel import events

_IS_WIN = sys.platform.startswith("win")

# Tastatur: Namen -> virtuelle Windows-Tastencodes (VK). Nur was man wirklich braucht.
_VK = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _VK[_c] = 0x41 + _i
for _d in "0123456789":
    _VK[_d] = 0x30 + int(_d)


def _enabled() -> bool:
    ag = CONFIG.get("agency", {})
    cu = ag.get("computer_use", {}) if isinstance(ag, dict) else {}
    return bool(cu.get("enabled"))


def _gate(aktion: str) -> str | None:
    """Blockier-Text, wenn Computer-Use gerade nicht darf — sonst None."""
    from core.kernel.scheduler import kill_switch_active

    if kill_switch_active():
        return "Not-Aus ist aktiv — ich steuere den Rechner gerade nicht."
    if not _enabled():
        return ("Computer-Steuerung ist AUS. Sergen schaltet sie im Steuerpult frei "
                "(Kira → Steuerpult → 'Rechner steuern'). Standard ist aus — bewusste Freigabe.")
    if not _IS_WIN:
        return f"Computer-Steuerung laeuft nur unter Windows ({aktion} hier nicht verfuegbar)."
    return None


def _parse_keys(keys: str) -> list[int]:
    """'ctrl+shift+s' -> [VK_CTRL, VK_SHIFT, VK_S]. Unbekannte Teile werden uebersprungen."""
    out: list[int] = []
    for part in str(keys).lower().replace(" ", "").split("+"):
        if part in _VK:
            out.append(_VK[part])
    return out


# ---------------------------------------------------------------------------
# OS-Schicht (Windows). Lazy importiert, damit Import auf jeder Plattform klappt.
# ---------------------------------------------------------------------------

def _screen_size() -> tuple[int, int]:
    import ctypes

    u = ctypes.windll.user32
    u.SetProcessDPIAware()
    return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))


def _do_move(x: int, y: int) -> None:
    import ctypes

    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def _do_click(x: int | None, y: int | None, button: str, double: bool) -> None:
    import ctypes

    u = ctypes.windll.user32
    if x is not None and y is not None:
        u.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
    down, up = (0x0008, 0x0010) if button == "right" else (0x0002, 0x0004)
    for _ in range(2 if double else 1):
        u.mouse_event(down, 0, 0, 0, 0)
        u.mouse_event(up, 0, 0, 0, 0)
        if double:
            time.sleep(0.05)


def _do_type(text: str) -> None:
    """Unicode-Zeichen tippen (KEYEVENTF_UNICODE) — unabhaengig vom Tastaturlayout."""
    import ctypes

    u = ctypes.windll.user32
    for ch in str(text):
        u.keybd_event(0, ord(ch), 0x0004, 0)          # KEYEVENTF_UNICODE down
        u.keybd_event(0, ord(ch), 0x0004 | 0x0002, 0)  # + KEYEVENTF_KEYUP
        time.sleep(0.005)


def _do_hotkey(vks: list[int]) -> None:
    import ctypes

    u = ctypes.windll.user32
    for vk in vks:                       # alle druecken (Modifier zuerst)
        u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.02)
    for vk in reversed(vks):             # in umgekehrter Reihenfolge loslassen
        u.keybd_event(vk, 0, 0x0002, 0)


def _list_windows() -> list[dict]:
    import ctypes

    u = ctypes.windll.user32
    out: list[dict] = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if title:
            out.append({"hwnd": int(hwnd), "titel": title})
        return True

    u.EnumWindows(EnumProc(_cb), 0)
    return out


def _focus_window(hwnd: int) -> None:
    import ctypes

    u = ctypes.windll.user32
    u.ShowWindow(hwnd, 9)          # SW_RESTORE (falls minimiert)
    u.SetForegroundWindow(hwnd)


def _screenshot_png(path: str) -> None:
    """Vollbild als PNG via PowerShell (System.Drawing) — 0 Python-Abhaengigkeit."""
    import subprocess

    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size);"
        f"$bmp.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose();$bmp.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30, check=False)


# ---------------------------------------------------------------------------
# Werkzeuge
# ---------------------------------------------------------------------------

@tool("bildschirm_foto",
      "Macht ein Foto vom Bildschirm und beschreibt/analysiert, was zu sehen ist (per "
      "Vision). Damit sehe ich, was gerade laeuft, bevor ich klicke. Gib eine konkrete "
      "Frage mit ('Wo ist der Speichern-Knopf?'), dann suche ich gezielt.",
      {"prompt": "optional: worauf ich achten / was ich finden soll"},
      feature="desktop_low_level")
def bildschirm_foto(prompt: str = "") -> str:
    blocked = _gate("bildschirm_foto")
    if blocked:
        return blocked
    if test_mode():
        events.emit("computer_use", {"aktion": "screenshot", "sim": True})
        return "(Testmodus: kein echtes Foto)"
    import base64
    import tempfile
    from pathlib import Path

    f = Path(tempfile.gettempdir()) / f"kira_screen_{int(time.time())}.png"
    try:
        _screenshot_png(str(f))
        if not f.exists() or f.stat().st_size == 0:
            return "(Bildschirmfoto fehlgeschlagen — kam kein Bild zurueck.)"
        data = base64.b64encode(f.read_bytes()).decode()
        w, h = _screen_size()
        events.emit("computer_use", {"aktion": "screenshot", "bytes": f.stat().st_size})
        from core.agency import vision

        desc = vision.describe(f"data:image/png;base64,{data}",
                               prompt or "Beschreibe den Bildschirm: welche App, welche "
                               "klickbaren Elemente, wo stehen sie ungefaehr?")
        return f"[Bildschirm {w}x{h}px]\n{desc}"
    except Exception as e:  # noqa: BLE001
        return f"(Bildschirmfoto-Fehler: {e})"
    finally:
        try:
            f.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


@tool("maus_klick",
      "Klickt an eine Bildschirm-Position (Pixel, 0,0 = oben links). Erst "
      "bildschirm_foto nutzen, um die Position zu finden. button='links'|'rechts', "
      "doppel=1 fuer Doppelklick.",
      {"x": "X-Pixel", "y": "Y-Pixel",
       "button": "optional: links (Standard) oder rechts",
       "doppel": "optional: 1 fuer Doppelklick"},
      feature="desktop_low_level")
def maus_klick(x, y, button: str = "links", doppel="0") -> str:
    blocked = _gate("maus_klick")
    if blocked:
        return blocked
    try:
        xi, yi = int(x), int(y)
    except Exception:  # noqa: BLE001
        return "(x und y muessen Zahlen sein)"
    btn = "right" if str(button).lower().startswith("r") else "left"
    dbl = str(doppel) in ("1", "true", "ja")
    events.emit("computer_use", {"aktion": "klick", "x": xi, "y": yi, "button": btn, "doppel": dbl})
    if test_mode():
        return f"(Testmodus: kein echter Klick @ {xi},{yi})"
    try:
        _do_click(xi, yi, btn, dbl)
        return f"Geklickt ({btn}{'/doppel' if dbl else ''}) @ {xi},{yi}."
    except Exception as e:  # noqa: BLE001
        return f"(Klick-Fehler: {e})"


@tool("maus_bewegen",
      "Bewegt den Mauszeiger an eine Position, ohne zu klicken (z.B. um ein Menue "
      "aufzuklappen, das auf Hover reagiert).",
      {"x": "X-Pixel", "y": "Y-Pixel"}, feature="desktop_low_level")
def maus_bewegen(x, y) -> str:
    blocked = _gate("maus_bewegen")
    if blocked:
        return blocked
    try:
        xi, yi = int(x), int(y)
    except Exception:  # noqa: BLE001
        return "(x und y muessen Zahlen sein)"
    events.emit("computer_use", {"aktion": "bewegen", "x": xi, "y": yi})
    if test_mode():
        return f"(Testmodus: keine echte Bewegung @ {xi},{yi})"
    try:
        _do_move(xi, yi)
        return f"Zeiger @ {xi},{yi}."
    except Exception as e:  # noqa: BLE001
        return f"(Bewegen-Fehler: {e})"


@tool("tippen",
      "Tippt Text an der aktuellen Cursor-Stelle (Unicode, layout-unabhaengig — Umlaute "
      "und Emojis gehen). Erst ins Zielfeld klicken.",
      {"text": "der zu tippende Text"}, feature="desktop_low_level")
def tippen(text: str) -> str:
    blocked = _gate("tippen")
    if blocked:
        return blocked
    text = str(text or "")
    events.emit("computer_use", {"aktion": "tippen", "len": len(text)})
    if test_mode():
        return f"(Testmodus: kein echtes Tippen, {len(text)} Zeichen)"
    try:
        _do_type(text)
        return f"Getippt ({len(text)} Zeichen)."
    except Exception as e:  # noqa: BLE001
        return f"(Tipp-Fehler: {e})"


@tool("taste",
      "Drueckt eine Taste oder Tastenkombination, z.B. 'enter', 'ctrl+s', 'alt+tab', "
      "'win+d', 'ctrl+shift+esc'. Fuer Sonder-/Steuertasten und Shortcuts (NICHT fuer "
      "normalen Text — dafuer 'tippen').",
      {"keys": "z.B. 'enter' oder 'ctrl+s'"}, feature="desktop_low_level")
def taste(keys: str) -> str:
    blocked = _gate("taste")
    if blocked:
        return blocked
    vks = _parse_keys(keys)
    if not vks:
        return f"(Taste(n) nicht erkannt: '{keys}'. Beispiele: enter, ctrl+s, alt+tab)"
    events.emit("computer_use", {"aktion": "taste", "keys": str(keys)})
    if test_mode():
        return f"(Testmodus: kein echter Tastendruck '{keys}')"
    try:
        _do_hotkey(vks)
        return f"Gedrueckt: {keys}."
    except Exception as e:  # noqa: BLE001
        return f"(Tasten-Fehler: {e})"


@tool("fenster_liste",
      "Listet die offenen Fenster (sichtbare Programme) mit Titel — damit ich weiss, was "
      "laeuft und was ich per fenster_fokus in den Vordergrund holen kann.",
      {}, feature="desktop_low_level")
def fenster_liste() -> str:
    blocked = _gate("fenster_liste")
    if blocked:
        return blocked
    if test_mode():
        return "(Testmodus: keine Fensterliste)"
    try:
        ws = _list_windows()
        if not ws:
            return "(keine sichtbaren Fenster gefunden)"
        return "\n".join(f"- {w['titel']}" for w in ws[:40])
    except Exception as e:  # noqa: BLE001
        return f"(Fensterliste-Fehler: {e})"


@tool("fenster_fokus",
      "Holt ein Fenster in den Vordergrund. Gib einen Teil des Titels an (z.B. 'Photoshop' "
      "oder 'Rechnung.pdf'); das erste passende Fenster wird aktiviert.",
      {"titel": "Teil des Fenstertitels"}, feature="desktop_low_level")
def fenster_fokus(titel: str) -> str:
    blocked = _gate("fenster_fokus")
    if blocked:
        return blocked
    q = str(titel or "").lower().strip()
    if not q:
        return "(bitte einen Teil des Fenstertitels angeben)"
    events.emit("computer_use", {"aktion": "fokus", "titel": q[:60]})
    if test_mode():
        return f"(Testmodus: kein echter Fokus auf '{titel}')"
    try:
        for w in _list_windows():
            if q in w["titel"].lower():
                _focus_window(w["hwnd"])
                return f"Im Vordergrund: {w['titel']}"
        return f"(kein Fenster mit '{titel}' im Titel gefunden — fenster_liste zeigt alle)"
    except Exception as e:  # noqa: BLE001
        return f"(Fokus-Fehler: {e})"
