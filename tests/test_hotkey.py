"""Phase 4: globaler Hotkey + Push-to-Talk — headless getestet (keyboard-Paket gefakt)."""
from __future__ import annotations

import sys
import types

from core.desktop import app


class FakeWindow:
    def __init__(self):
        self.shown = 0
        self.js: list[str] = []

    def show(self):
        self.shown += 1

    def restore(self):
        pass

    def evaluate_js(self, code):
        self.js.append(code)


def _fake_keyboard():
    kb = types.ModuleType("keyboard")
    kb.hotkeys, kb.press, kb.release = {}, {}, {}
    kb.add_hotkey = lambda key, cb: kb.hotkeys.__setitem__(key, cb)
    kb.on_press_key = lambda key, cb: kb.press.__setitem__(key, cb)
    kb.on_release_key = lambda key, cb: kb.release.__setitem__(key, cb)
    return kb


def test_hotkeys_registriert_und_wirken(monkeypatch):
    kb = _fake_keyboard()
    monkeypatch.setitem(sys.modules, "keyboard", kb)
    w = FakeWindow()
    app._start_hotkeys(w)
    assert "alt+space" in kb.hotkeys and "f9" in kb.press and "f9" in kb.release
    kb.hotkeys["alt+space"]()                       # Hotkey -> Fenster nach vorn
    assert w.shown == 1
    kb.press["f9"](None)                            # PTT halten -> Fenster + Aufnahme an
    assert w.shown == 2 and w.js[-1].endswith("window.kiraPTT(true)")
    kb.release["f9"](None)                          # loslassen -> transkribieren + senden
    assert w.js[-1].endswith("window.kiraPTT(false)")


def test_hotkeys_konfigurierbar(monkeypatch):
    kb = _fake_keyboard()
    monkeypatch.setitem(sys.modules, "keyboard", kb)
    from core.config import CONFIG
    monkeypatch.setitem(CONFIG, "desktop", {"hotkey": "ctrl+alt+k", "ptt_key": "f8"})
    app._start_hotkeys(FakeWindow())
    assert "ctrl+alt+k" in kb.hotkeys and "f8" in kb.press


def test_ohne_keyboard_paket_kein_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyboard", None)  # import wirft -> still weiter
    app._start_hotkeys(FakeWindow())


def test_fenster_fehler_bricht_nichts(monkeypatch):
    kb = _fake_keyboard()
    monkeypatch.setitem(sys.modules, "keyboard", kb)

    class BrokenWindow:
        def show(self):
            raise RuntimeError("weg")

        def restore(self):
            raise RuntimeError("weg")

        def evaluate_js(self, code):
            raise RuntimeError("weg")

    app._start_hotkeys(BrokenWindow())
    kb.hotkeys["alt+space"]()   # darf nicht raisen
    kb.press["f9"](None)
    kb.release["f9"](None)


def test_cockpit_hat_ptt_hook():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert "window.kiraPTT" in html and "pttSend" in html


def test_requirements_und_config_defaults():
    from core.config import CONFIG, ROOT
    req = (ROOT / "requirements-desktop.txt").read_text(encoding="utf-8")
    assert "keyboard" in req
    d = CONFIG.get("desktop", {}) or {}
    assert d.get("hotkey") == "alt+space" and d.get("ptt_key") == "f9"
    assert app._hotkey_cfg() == ("alt+space", "f9")
