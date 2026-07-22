"""Endpunkt-lokal-Runde: registrierte 127.0.0.1-Endpunkte (llama.cpp-Nachtdenker)
gelten als LOKAL — Chat faehrt den ACT-Pfad mit dem schlanken haupt-Manifest.

35B-Premiere 22.07. (events-belegt): Der Cloud-Pfad schickte dem lokalen Endpunkt
17,7k Token (volle Schema-Flotte) — ContextWindowExceeded, dann 150s-Wall-Clock-
Riss. Dasselbe Modell antwortete roh am Endpunkt in 7,3s. Der Prompt war der
Killer, nicht das Modell.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.config import CONFIG
from core.kernel import llm_router


_PROVIDERS = {"nacht35b": {"model": "openai/qwen3.6-35b",
                           "api_base": "http://127.0.0.1:8081/v1", "api_key_env": ""}}


def test_ist_lokal_kennt_alle_familien(monkeypatch):
    monkeypatch.setitem(CONFIG["models"], "providers", dict(_PROVIDERS))
    assert llm_router.ist_lokal("ollama_chat/kira-c6") is True
    assert llm_router.ist_lokal("nacht35b") is True                    # DER Live-Fall
    assert llm_router.ist_lokal("openrouter/z-ai/glm-5.2") is False
    monkeypatch.setitem(CONFIG["models"], "providers",
                        {"cloudx": {"model": "openai/x", "api_base": "https://api.x.ai/v1",
                                    "api_key_env": "X_KEY"}})
    assert llm_router.ist_lokal("cloudx") is False                     # extern bleibt Cloud


def test_cloud_weiche_nimmt_act_pfad_fuer_endpunkt(monkeypatch):
    from core.agency import act
    monkeypatch.setitem(CONFIG["models"], "providers", dict(_PROVIDERS))
    monkeypatch.setattr(act.llm_router, "resolve_model",
                        lambda t="default", escalate=False: ("nacht35b", False))
    assert act._cloud(False, "chat") is False                          # lokal -> ACT-Pfad
    monkeypatch.setattr(act.llm_router, "resolve_model",
                        lambda t="default", escalate=False: ("openrouter/z-ai/glm-5.2", False))
    assert act._cloud(True, "chat") is True                            # Cloud bleibt Cloud


def _fake_stream(*chunks):
    def _mk(text):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])
    return [_mk(c) for c in chunks]


def test_stream_tagged_streamt_den_endpunkt(monkeypatch, tmp_path):
    """Der lokale Endpunkt wird WIRKLICH gestreamt (nicht als Cloud-Block) und
    bekommt api_base + Dummy-Key durchgereicht."""
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()
    monkeypatch.setitem(CONFIG["models"], "providers", dict(_PROVIDERS))
    seen: dict = {}

    def fake_completion(**kw):
        seen.update(kw)
        return _fake_stream("Hal", "lo!")

    monkeypatch.setattr(llm_router.litellm, "completion", fake_completion)
    out = list(llm_router.stream_tagged([{"role": "user", "content": "hi"}],
                                        model="nacht35b"))
    assert seen["model"] == "openai/qwen3.6-35b"
    assert seen["api_base"] == "http://127.0.0.1:8081/v1"
    assert seen["api_key"] == "sk-lokal"
    assert seen["stream"] is True
    antwort = "".join(d["text"] for d in out if d["kind"] == "answer")
    assert antwort == "Hallo!"


def test_lokal_extra_trennt_die_familien():
    ollama = llm_router._lokal_extra("ollama_chat/kira-c6", None, None)
    assert "api_base" not in ollama and "keep_alive" in ollama
    ep = llm_router._lokal_extra("openai/qwen3.6-35b", "http://127.0.0.1:8081/v1", "")
    assert ep == {"api_base": "http://127.0.0.1:8081/v1", "api_key": "sk-lokal"}
