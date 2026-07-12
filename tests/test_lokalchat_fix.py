"""Fix 09.07. (Praxis-Fund): Chat mit lokalem Modell brach sofort ab.

Ursache: der Benchmark-Commit (Modell-Direktwahl) baute in stream_tagged ein
'if model:' ein, vergass aber den Parameter -> UnboundLocalError bei JEDEM
lokalen Chat ('cannot access local variable model'). Cloud-Chats gingen vorher
raus und waren nicht betroffen. Dazu: frisch gezogene Ollama-Modelle sollen
sofort im Katalog stehen (lokale Liste nicht mehr 10 min mitgecacht)."""
from __future__ import annotations

import inspect

from core.kernel import llm_router, models


def test_stream_tagged_hat_model_parameter():
    sig = inspect.signature(llm_router.stream_tagged)
    assert "model" in sig.parameters                            # der vergessene Parameter
    assert sig.parameters["model"].default is None


def test_stream_tagged_ohne_model_crasht_nicht(monkeypatch):
    # Router aufloesen lassen (frueher: UnboundLocalError genau hier)
    monkeypatch.setattr(llm_router, "resolve_model", lambda tt, escalate=False: ("openrouter/x", False))
    monkeypatch.setattr(llm_router, "_provider_config", lambda m: ("openrouter/x", None, None))
    monkeypatch.setattr(llm_router, "complete",
                        lambda *a, **k: {"text": "hallo zurueck", "model": "openrouter/x",
                                         "fell_back": False, "latency_s": 0.1, "cost_usd": 0.0})
    out = list(llm_router.stream_tagged([{"role": "user", "content": "hallo qwen"}]))
    assert out and out[0]["kind"] == "answer" and "hallo" in out[0]["text"]


def test_stream_tagged_mit_direktwahl_nutzt_das_modell(monkeypatch):
    gesehen = {}

    def fake_resolve(tt, escalate=False):  # darf bei Direktwahl NICHT gefragt werden
        raise AssertionError("resolve_model soll bei Direktwahl nicht laufen")

    monkeypatch.setattr(llm_router, "resolve_model", fake_resolve)
    monkeypatch.setattr(llm_router, "_provider_config", lambda m: (gesehen.setdefault("m", m), None, None))
    monkeypatch.setattr(llm_router, "complete",
                        lambda *a, **k: {"text": "ok", "model": "openrouter/y",
                                         "fell_back": False, "latency_s": 0.1, "cost_usd": 0.0})
    list(llm_router.stream_tagged([{"role": "user", "content": "hi"}], model="openrouter/y"))
    assert gesehen["m"] == "openrouter/y"


def test_katalog_lokal_immer_frisch(monkeypatch):
    # OpenRouter-Teil einmal cachen lassen, dann neue lokale Modelle "ziehen":
    # sie muessen SOFORT erscheinen, ohne den 10-min-Cache abzuwarten.
    monkeypatch.setattr(models, "_CATALOG_CACHE", {"ts": 0.0, "data": None})
    monkeypatch.setattr(models.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(models, "aimlapi_models", lambda: [])
    monkeypatch.setattr(models, "ollama_models", lambda: ["qwen3.5:9b"])
    c1 = models.catalog()
    assert [m["id"] for m in c1["local"]] == ["ollama_chat/qwen3.5:9b"]
    monkeypatch.setattr(models, "ollama_models", lambda: ["qwen3.5:9b", "neu:7b"])
    c2 = models.catalog()                                       # Cache ist noch warm ...
    assert "ollama_chat/neu:7b" in [m["id"] for m in c2["local"]]  # ... lokal trotzdem frisch
