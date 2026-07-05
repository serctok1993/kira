"""Voice-Test-Knopf: diagnose() liefert Klartext-Grund; /api/voice/test + UI-Marker."""
from __future__ import annotations


def _set_tts(monkeypatch, **kw):
    from core.config import CONFIG
    tel = dict(CONFIG.get("channels", {}).get("telegram", {}))
    tel["tts"] = kw
    ch = dict(CONFIG.get("channels", {}))
    ch["telegram"] = tel
    monkeypatch.setitem(CONFIG, "channels", ch)


def test_diagnose_aus(monkeypatch):
    from core.agency.connectors import tts
    _set_tts(monkeypatch, enabled=False, provider="elevenlabs")
    d = tts.diagnose()
    assert d["ok"] is False and "AUS" in d["reason"]


def test_diagnose_ohne_key(monkeypatch):
    from core.agency.connectors import tts
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    d = tts.diagnose()
    assert d["ok"] is False and "ELEVENLABS_API_KEY" in d["reason"]


def test_diagnose_ok(monkeypatch):
    from core.agency.connectors import tts
    import httpx
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs", voice_id="V1")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-x")

    class R:
        status_code = 200
        content = b"AUDIOBYTES"
        text = ""

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    d = tts.diagnose()
    assert d["ok"] is True and d["bytes"] == 10 and "V1" in d["reason"]


def test_diagnose_401_und_400(monkeypatch):
    from core.agency.connectors import tts
    import httpx
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-x")

    class R401:
        status_code = 401
        content = b""
        text = "unauthorized"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R401())
    d = tts.diagnose()
    assert d["ok"] is False and "401" in d["reason"] and "Key falsch" in d["reason"]

    class R400:
        status_code = 400
        content = b""
        text = "voice not found"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R400())
    d = tts.diagnose()
    assert d["ok"] is False and "400" in d["reason"] and "Voice-ID" in d["reason"]


def test_endpoint_und_ui_marker():
    import asyncio
    from core.api import server
    r = asyncio.run(server.api_voice_test({}))
    assert "ok" in r and "reason" in r
    from core.api.ui.views import VIEWS
    from core.api.ui.script import SCRIPT
    assert 'id="voice-test"' in VIEWS and "/api/voice/test" in SCRIPT
