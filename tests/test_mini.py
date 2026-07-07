"""Phase 4 — Mini-Chat-Fenster (/chat-mini) + globaler Hotkey.

Prueft die ausgelieferte Seite (echter Fokus, ephemerer Chat, „Kira oeffnen"-Bruecke) und den
reinen Hotkey-Parser (ohne Windows testbar). Das native Fenster + die Win32-Registrierung werden
live am PC abgenommen (wie die uebrige Desktop-Einrichtung).
"""
from __future__ import annotations

from starlette.testclient import TestClient

from core.api.server import app
from core.desktop import app as desktop


def test_chat_mini_seite_wird_ausgeliefert():
    c = TestClient(app)
    r = c.get("/chat-mini")
    assert r.status_code == 200
    body = r.text
    for m in ('id="cin"', 'id="reply"', 'data-mode="chat"', 'id="open"', 'id="close"'):
        assert m in body, f"Baustein fehlt: {m}"
    # ephemerer Chat ueber den bestehenden WS (frische mini-Session) + echtes Reasoning
    assert "/ws/chat?sid=" in body and '"mini-"' in body
    assert 'm.kind==="think"' in body and "reasonBuf" in body
    # „Kira oeffnen" nutzt die pywebview-Bruecke (sonst Cockpit im Browser); Cockpit-Farben uebernommen
    assert "pywebview.api.open_app" in body and "kira_custom" in body
    # PHRASES injiziert (Platzhalter ersetzt)
    assert "/*__PHRASES__*/" not in body


def test_hotkey_parser():
    # alt+space -> MOD_ALT (0x1) + VK_SPACE (0x20)
    assert desktop._parse_hotkey("alt+space") == (0x0001, 0x20)
    # deutsche/englische Modifier, Reihenfolge egal, Gross/Klein egal, Leerzeichen egal
    assert desktop._parse_hotkey("Strg + Shift + K") == (0x0002 | 0x0004, ord("K"))
    assert desktop._parse_hotkey("win+k") == (0x0008, ord("K"))
    # ohne Taste -> None (nichts zu registrieren)
    assert desktop._parse_hotkey("alt") is None
    assert desktop._parse_hotkey("") is None


def test_chat_hotkey_default_und_config(monkeypatch):
    import core.config as cfg
    # Default, wenn nichts konfiguriert ist
    monkeypatch.setitem(cfg.CONFIG, "desktop", {})
    assert desktop._chat_hotkey() == "alt+space"
    # aus der Config uebernommen
    monkeypatch.setitem(cfg.CONFIG, "desktop", {"chat_hotkey": "ctrl+space"})
    assert desktop._chat_hotkey() == "ctrl+space"


def test_start_hotkey_ohne_windows_faellt_sanft(monkeypatch):
    # Auf Nicht-Windows (kein ctypes.windll) darf nichts crashen -> False, App laeuft weiter
    called = []
    ok = desktop._start_hotkey("alt+space", lambda: called.append(1))
    assert ok in (True, False)   # je nach Plattform; wichtig: kein Fehler


def test_hotkey_dokumentiert_und_konfigurierbar():
    from core.config import ROOT
    cfg = (ROOT / "config.yaml").read_text(encoding="utf-8")
    assert "chat_hotkey" in cfg                       # Hotkey per Config aenderbar
    doc = (ROOT / "docs" / "DESKTOP.md").read_text(encoding="utf-8")
    assert "Schwebe-Fenster" in doc and "chat_hotkey" in doc and "Alt + Leertaste" in doc
