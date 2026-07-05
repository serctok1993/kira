"""Sprich-Modus im Cockpit: /api/voice/say liefert MP3 (oder 204), UI-Knopf + Vorlesen.

Kira hoert per Web-App freihaendig zu (Knopfdruck) und antwortet mit Stimme — ohne dass
die Textantwort je an der Sprachausgabe haengt (leer/aus/Fehler -> 204, Browser bleibt still).
"""
from __future__ import annotations

import asyncio


def test_say_leer_gibt_204():
    from core.api import server
    r = asyncio.run(server.api_voice_say({"text": "   "}))
    assert r.status_code == 204


def test_say_ok_liefert_audio(monkeypatch):
    from core.api import server
    from core.agency.connectors import tts
    monkeypatch.setattr(tts, "synthesize", lambda text, session_id=None: (b"MP3BYTES", "audio/mpeg"))
    r = asyncio.run(server.api_voice_say({"text": "Hallo Sergen"}))
    assert r.status_code == 200
    assert r.body == b"MP3BYTES"
    assert r.media_type == "audio/mpeg"


def test_say_stimme_aus_gibt_204(monkeypatch):
    from core.api import server
    from core.agency.connectors import tts
    monkeypatch.setattr(tts, "synthesize", lambda text, session_id=None: None)  # TTS aus/Fehler
    r = asyncio.run(server.api_voice_say({"text": "Hallo"}))
    assert r.status_code == 204


def test_say_crash_gibt_204(monkeypatch):
    from core.api import server
    from core.agency.connectors import tts
    monkeypatch.setattr(tts, "synthesize",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = asyncio.run(server.api_voice_say({"text": "Hallo"}))
    assert r.status_code == 204  # Stimme darf das Cockpit nie brechen


def test_sprich_modus_ui_marker():
    from core.api.ui.views import VIEWS
    from core.api.ui.script import SCRIPT
    assert 'id="sprechbtn"' in VIEWS and 'id="tts-on"' in VIEWS
    assert "/api/voice/say" in SCRIPT
    assert "handsFree" in SCRIPT and "function speak(" in SCRIPT
