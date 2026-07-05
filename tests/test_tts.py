"""TTS: Kira spricht zurueck (anbieter-agnostisch, Default aus, raist nie).
Voice-rein -> Voice-raus in Telegram; ElevenLabs via Fake-HTTP.
"""
from __future__ import annotations


def _set_tts(monkeypatch, **kw):
    from core.config import CONFIG
    tel = dict(CONFIG.get("channels", {}).get("telegram", {}))
    tel["tts"] = kw
    ch = dict(CONFIG.get("channels", {}))
    ch["telegram"] = tel
    monkeypatch.setitem(CONFIG, "channels", ch)


def _events(monkeypatch, tmp_path):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    return events


# ---- enabled / Config ------------------------------------------------------------------

def test_enabled_schalter(monkeypatch):
    from core.agency.connectors import tts
    _set_tts(monkeypatch, enabled=False, provider="elevenlabs")
    assert tts.enabled() is False
    _set_tts(monkeypatch, enabled=True, provider="off")
    assert tts.enabled() is False
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs")
    assert tts.enabled() is True


def test_synthesize_aus_liefert_none(monkeypatch, tmp_path):
    _events(monkeypatch, tmp_path)
    from core.agency.connectors import tts
    _set_tts(monkeypatch, enabled=False, provider="elevenlabs")
    assert tts.synthesize("Hallo") is None


def test_cap_deckelt_an_wortgrenze(monkeypatch):
    from core.agency.connectors import tts
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs", max_chars=20)
    out = tts._cap("eins zwei drei vier fuenf sechs sieben")
    assert len(out) <= 24 and out.endswith("…") and "  " not in out


# ---- ElevenLabs (Fake-HTTP) ------------------------------------------------------------

def test_elevenlabs_ok(monkeypatch, tmp_path):
    events = _events(monkeypatch, tmp_path)
    from core.agency.connectors import tts
    import httpx
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs", voice_id="V1", max_chars=600)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    seen = {}

    class R:
        status_code = 200
        content = b"MP3BYTES"
        text = ""

    def fake_post(url, headers=None, params=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, params=params, json=json)
        return R()

    monkeypatch.setattr(httpx, "post", fake_post)
    out = tts.synthesize("Hallo Sergen", session_id="v1")

    assert out == (b"MP3BYTES", "audio/mpeg")
    assert "V1" in seen["url"] and seen["headers"]["xi-api-key"] == "sk-test"
    assert seen["json"]["text"] == "Hallo Sergen"
    assert "tts_ok" in [e["type"] for e in events.recent(10)]


def test_elevenlabs_ohne_key_none(monkeypatch, tmp_path):
    events = _events(monkeypatch, tmp_path)
    from core.agency.connectors import tts
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert tts.synthesize("Hallo") is None
    assert "tts_no_key" in [e["type"] for e in events.recent(10)]


def test_elevenlabs_http_fehler_none(monkeypatch, tmp_path):
    _events(monkeypatch, tmp_path)
    from core.agency.connectors import tts
    import httpx
    _set_tts(monkeypatch, enabled=True, provider="elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")

    class R:
        status_code = 401
        content = b""
        text = "unauthorized"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    assert tts.synthesize("Hallo") is None  # Fehler -> None, kein Crash


# ---- Telegram: Voice rein -> Voice raus (Helfer _voice_back) ----------------------------

def test_voice_back_sendet_audio(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency.connectors import tts
    posts: list = []

    class Client:
        def post(self, url, **kw):
            posts.append((url, kw))

    monkeypatch.setattr(tts, "synthesize", lambda text, session_id=None: (b"AUDIO", "audio/mpeg"))
    tb._voice_back(Client(), 42, "telegram-42", "Okay, erledigt")

    assert len(posts) == 1
    url, kw = posts[0]
    assert "sendAudio" in url
    assert kw["files"]["audio"][1] == b"AUDIO"       # die Audiobytes gehen raus
    assert kw["data"]["chat_id"] == 42


def test_voice_back_ohne_audio_still(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency.connectors import tts
    posts: list = []

    class Client:
        def post(self, url, **kw):
            posts.append(url)

    monkeypatch.setattr(tts, "synthesize", lambda text, session_id=None: None)  # TTS aus
    tb._voice_back(Client(), 42, "telegram-42", "Antwort")
    assert posts == []                               # keine Stimme -> nichts gesendet

    # leere Antwort -> gar nichts (kein TTS-Aufruf)
    monkeypatch.setattr(tts, "synthesize",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nicht rufen")))
    tb._voice_back(Client(), 42, "telegram-42", "   ")
    assert posts == []


# ---- Cockpit: Kira-Stimme in den Zugaengen -------------------------------------------

def test_secrets_endpoint_bietet_stimme(monkeypatch):
    from core.api import server
    monkeypatch.setattr(server.secrets, "names_status", lambda: {"ELEVENLABS_API_KEY": True})
    monkeypatch.setattr(server.secrets, "pending", lambda: [])
    r = server.api_secrets()
    assert "ELEVENLABS_API_KEY" in r["suggested"]     # klickbarer Vorschlag
    assert r["tts"]["key_set"] is True                # Status fuer die Voice-Karte
    assert "enabled" in r["tts"] and "voice_id" in r["tts"]


def test_config_whitelist_erlaubt_stimme():
    from core.api.server import _CONFIG_WHITELIST
    for p in ("channels.telegram.tts.enabled", "channels.telegram.tts.voice_id",
              "channels.telegram.tts.provider"):
        assert p in _CONFIG_WHITELIST


def test_voice_karte_ui_marker():
    from core.api.ui.views import VIEWS
    from core.api.ui.script import SCRIPT
    assert "Kira-Stimme" in VIEWS and 'id="voice-on"' in VIEWS and 'id="voice-key"' in VIEWS
    assert "voice-key-save" in SCRIPT and "channels.telegram.tts.enabled" in SCRIPT
