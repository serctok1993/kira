"""Router-Absicherung: ein vertipptes/ungueltiges Cloud-Modell darf den Chat NICHT lahmlegen.

Regression zum Live-Bug: data/models.json zeigte auf 'openrouter/glm/glm-5.2' (das z-ai/ fehlt).
OpenRouter antwortete 400 'not a valid model ID' -> jeder Aufruf brach hart ab (hunderte Fehler,
Chat tot). Jetzt: einmal aufs lokale Fallback ausweichen und weiterlaufen.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.kernel import events, llm_router
from core.mind.memory import store as memory


def test_ungueltiges_modell_faellt_auf_lokal(monkeypatch, tmp_path):
    db = str(tmp_path / "e.db")
    for mod in (memory, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    memory.init_memory()

    from core.governance import treasury
    monkeypatch.setattr(treasury, "can_spend", lambda *a, **k: (True, ""))
    monkeypatch.setattr(llm_router.litellm, "completion_cost", lambda **k: 0.0)
    # Chat routet auf ein ungueltiges Cloud-Modell (wie der Live-Override).
    monkeypatch.setattr(llm_router, "resolve_model", lambda *a, **k: ("openrouter/glm/glm-5.2", False))

    seen = {"cloud": 0, "local": 0}

    def fake_completion(**kw):
        if "ollama" in str(kw.get("model", "")):
            seen["local"] += 1
            msg = SimpleNamespace(content="lokal geantwortet", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)
        seen["cloud"] += 1
        raise Exception('OpenrouterException - {"error":{"message":"glm/glm-5.2 is not a valid model ID","code":400}}')

    monkeypatch.setattr(llm_router, "_completion", fake_completion)

    res = llm_router.complete([{"role": "user", "content": "hi kira"}], task_type="chat")
    assert res["text"] == "lokal geantwortet"       # Chat lebt weiter statt zu sterben
    assert res["fell_back"] is True
    assert seen["cloud"] == 1 and seen["local"] == 1  # genau EIN Cloud-Versuch, dann lokal

    # und es wurde als eigenes Ereignis sichtbar gemacht (kein stiller Schlucker)
    assert any(e["type"] == "model_invalid_fallback" for e in events.recent(20))
