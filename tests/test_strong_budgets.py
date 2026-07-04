"""Modellstarke Arbeitsflaeche: Budgets folgen dem Modell, das REAL laeuft.

Die Basis-Decken (max_steps etc.) sind fuer schwache/lokale Modelle kalibriert.
Laeuft die Runde auf einem starken Cloud-Modell (agency.strong_markers, kein
Fallback), gelten die grosszuegigeren Werte aus agency.strong. Im Fallback
(Key fehlt -> lokal) bleiben IMMER die engen Basis-Decken.
"""
from __future__ import annotations


def _router(monkeypatch, model: str, fell_back: bool):
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda t="default", escalate=False: (model, fell_back))


def test_strong_model_detection(monkeypatch):
    from core.agency import act
    monkeypatch.setattr(act, "_STRONG_MARKERS", ["anthropic/", "claude"])

    _router(monkeypatch, "openrouter/anthropic/claude-fable-5", False)
    assert act._strong_model("chat") is True

    _router(monkeypatch, "ollama_chat/qwythos", False)
    assert act._strong_model("chat") is False

    # Fallback aktiv -> NIE stark, selbst wenn das Wunschmodell stark waere
    _router(monkeypatch, "ollama_chat/qwythos", True)
    assert act._strong_model("chat") is False


def test_budget_uses_strong_values(monkeypatch):
    from core.agency import act
    monkeypatch.setattr(act, "_STRONG_MARKERS", ["anthropic/"])
    monkeypatch.setattr(act, "_STRONG_CFG", {"max_steps": 200, "max_steps_chat": 30})

    _router(monkeypatch, "openrouter/anthropic/claude-fable-5", False)
    assert act._budget("max_steps", 80) == 200
    assert act._budget("max_steps_chat", 8) == 30
    assert act._budget("unbekannt", 12) == 12  # kein strong-Wert -> Basis

    _router(monkeypatch, "openrouter/deepseek/deepseek-v4-flash", False)
    assert act._budget("max_steps", 80) == 80  # kein starkes Modell -> Basis


def test_budget_base_without_strong_cfg(monkeypatch):
    from core.agency import act
    monkeypatch.setattr(act, "_STRONG_CFG", {})
    _router(monkeypatch, "openrouter/anthropic/claude-fable-5", False)
    assert act._budget("max_steps", 80) == 80  # keine strong-Config -> unveraendert


def test_budget_never_raises(monkeypatch):
    from core.agency import act
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda t="default", escalate=False: (_ for _ in ()).throw(RuntimeError("kaputt")))
    monkeypatch.setattr(act, "_STRONG_CFG", {"max_steps": 200})
    assert act._budget("max_steps", 80) == 80  # im Zweifel enge Decken, nie Crash


def test_config_has_strong_block():
    """Die Fable-Arbeitsflaeche ist in config.yaml verankert und plausibel."""
    from core.config import CONFIG
    ag = CONFIG.get("agency", {})
    strong = ag.get("strong", {})
    assert strong, "agency.strong fehlt in config.yaml"
    assert int(strong["max_steps"]) > int(ag.get("max_steps", 40))
    assert int(strong["max_steps_chat"]) > int(ag.get("max_steps_chat", 8))
    assert int(strong["obs_max_chars"]) > int(ag.get("obs_max_chars", 16000))
    assert any("anthropic" in str(m) for m in ag.get("strong_markers", []))
