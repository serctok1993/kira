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
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs", voice_id="Vset")  # feste Stimme, keine Konto-Abfrage
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


def test_konto_stimme_wird_geholt(monkeypatch):
    """Leere voice_id -> Kira holt eine freie (premade) Stimme aus dem Konto."""
    from core.agency.connectors import tts
    import httpx
    tts._ACCOUNT_VOICE["id"] = None
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs")  # KEINE voice_id

    def fake_get(url, headers=None, timeout=None):
        class R:
            status_code = 200
            def json(self_):
                return {"voices": [
                    {"voice_id": "clone1", "category": "cloned"},
                    {"voice_id": "free1", "category": "premade"},
                ]}
        return R()

    monkeypatch.setattr(httpx, "get", fake_get)
    v = tts._resolve_voice(tts._cfg(), "sk-x")
    assert v == "free1"                     # premade bevorzugt (nicht die geklonte)
    assert tts._account_voice("sk-x") == "free1"  # gecacht
    tts._ACCOUNT_VOICE["id"] = None         # Cache nicht in andere Tests lecken


def test_gesetzte_voice_id_hat_vorrang(monkeypatch):
    from core.agency.connectors import tts
    import httpx
    tts._ACCOUNT_VOICE["id"] = None
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs", voice_id="MEINE")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("darf Konto nicht fragen")))
    assert tts._resolve_voice(tts._cfg(), "sk-x") == "MEINE"


def test_diagnose_402_gibt_lokal_hinweis(monkeypatch):
    from core.agency.connectors import tts
    import httpx
    tts._ACCOUNT_VOICE["id"] = None
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs", voice_id="Vlib")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-x")

    class R:
        status_code = 402
        content = b""
        text = '{"detail":{"code":"paid_plan_required"}}'

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    d = tts.diagnose()
    assert d["ok"] is False and "402" in d["reason"]
    assert "Kokoro" in d["reason"] or "premade" in d["reason"]   # klarer Ausweg genannt


def test_endpoint_und_ui_marker():
    import asyncio
    from core.api import server
    r = asyncio.run(server.api_voice_test({}))
    assert "ok" in r and "reason" in r
    from core.api.ui.views import VIEWS
    from core.api.ui.script import SCRIPT
    assert 'id="voice-test"' in VIEWS and "/api/voice/test" in SCRIPT
