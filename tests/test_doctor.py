"""S5.6: Selbst-Check (doctor.check) — strukturiert, nie raisend, 0 Kosten. Offline."""
from __future__ import annotations

from core.kernel import doctor, llm_router


def test_check_shape_offline():
    rep = doctor.check(test_call=False)
    for key in ("problems", "routing", "api_keys", "ollama", "npx", "imports", "ok"):
        assert key in rep, f"Report-Feld fehlt: {key}"
    assert isinstance(rep["problems"], list)
    assert rep["ok"] == (not rep["problems"])
    # Kern-Imports werden geprueft
    assert "fastapi" in rep["imports"] and "python_multipart" in rep["imports"]


def test_check_never_raises_even_if_llm_dead(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Router kaputt")

    monkeypatch.setattr(llm_router, "resolve_model", boom)
    rep = doctor.check(test_call=False)  # darf NICHT werfen
    assert any("Routing" in p for p in rep["problems"])
    assert rep["ok"] is False


def test_missing_binary_surfaces_as_problem(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)  # node/npx "weg"
    rep = doctor.check(test_call=False)
    assert any("npx" in p for p in rep["problems"])


def test_test_call_error_is_captured(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kein Modell")

    monkeypatch.setattr(llm_router, "complete", boom)
    rep = doctor.check(test_call=True)
    assert rep["test_call"]["error"]
    assert any("Test-Call" in p for p in rep["problems"])
