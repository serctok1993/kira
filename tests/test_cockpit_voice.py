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
    # Weckwort-Gate + Stille-Erkennung + Assistenz-Prefix
    assert "WAKE" in SCRIPT and "attachVAD" in SCRIPT and "voice:true" in SCRIPT


def _chat_dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()
    store.init_memory()


def test_sprich_prefix_knapp_und_kein_plan(monkeypatch, tmp_path):
    """'sprich:' -> knapper/neutraler Vorlese-Stil, KEIN schwerer Auto-Plan, Prefix abgestreift."""
    from core.agency import act
    _chat_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "plan_and_execute",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Plan im Sprich-Modus")))
    monkeypatch.setattr(act, "_cloud", lambda e, t="chat": True)
    seen: dict = {}

    def fake_native(messages, system, *a, **k):
        seen["system"] = system
        seen["user"] = messages[-1]["content"]
        return "erledigt."

    monkeypatch.setattr(act, "_native_loop", fake_native)
    out = act.act_chat("sprich: Erstelle mir aus den Leads 10 E-Mails als Dateien", "sv1")
    assert out == "erledigt."
    assert "sprich:" not in seen["user"].lower()   # Prefix abgestreift
    assert "SPRICH-MODUS" in seen["system"]         # Vorlese-Stil injiziert


def test_ohne_sprich_kein_vorlese_stil(monkeypatch, tmp_path):
    from core.agency import act
    _chat_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_cloud", lambda e, t="chat": True)
    seen: dict = {}
    monkeypatch.setattr(act, "_native_loop",
                        lambda messages, system, *a, **k: (seen.update(system=system), "ok")[1])
    act.act_chat("wie geht es dir?", "sv2")
    assert "SPRICH-MODUS" not in seen["system"]
