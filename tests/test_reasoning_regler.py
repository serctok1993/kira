"""S11: Ehrlicher, modell-abhaengiger Denk-Tiefe-Regler.

- is_reasoning_model / _reasoning_extra: nur denk-faehige Modelle bekommen den Parameter
- 'denk:'-Prefix im Chat wird geparst und als reasoning bis zum LLM-Call durchgereicht
- /api/status liefert die reasoning_markers (fuer den Live-Regler im Cockpit)
"""
from __future__ import annotations

from core.kernel import llm_router


# ---- Modell-Faehigkeit + Parameter-Mapping -------------------------------------------

def test_is_reasoning_model():
    assert llm_router.is_reasoning_model("openrouter/z-ai/glm-5.2")
    assert llm_router.is_reasoning_model("openrouter/anthropic/claude-fable-5")
    assert not llm_router.is_reasoning_model("openrouter/deepseek/deepseek-v4-flash")


def test_reasoning_extra_nur_bei_faehigen():
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "hoch") == {"reasoning_effort": "high"}
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "aus") == {"reasoning_effort": "minimal"}
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "niedrig") == {"reasoning_effort": "low"}
    # nicht denk-faehig -> leer (der Parameter verpufft nicht mal, er wird gar nicht gesetzt)
    assert llm_router._reasoning_extra("openrouter/deepseek/deepseek-v4-flash", "hoch") == {}
    # kein Level / Standard -> leer
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", None) == {}
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "") == {}


# ---- 'denk:'-Prefix wird geparst und bis zum Modell-Call durchgereicht ----------------

def _dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()
    store.init_memory()


def test_denk_prefix_reicht_reasoning_durch(monkeypatch, tmp_path):
    from core.agency import act
    _dbs(monkeypatch, tmp_path)
    seen: dict = {}

    def fake_native(messages, system, session_id, escalate, emit, max_steps=None,
                    task_type="chat", reasoning=None):
        seen["reasoning"] = reasoning
        seen["text"] = messages[-1]["content"]
        return "ok"

    monkeypatch.setattr(act, "_cloud", lambda e, t="chat": True)
    monkeypatch.setattr(act, "_native_loop", fake_native)

    act.act_chat("denk:hoch erklaer mir Photosynthese", "r1")
    assert seen["reasoning"] == "hoch"
    assert seen["text"].startswith("erklaer mir")          # Prefix wurde abgestreift

    seen.clear()
    act.act_chat("ganz normal ohne prefix", "r2")
    assert seen["reasoning"] is None                        # ohne Prefix kein Level


# ---- /api/status liefert die Marker fuer den Live-Regler -------------------------------

def test_status_liefert_reasoning_markers():
    from starlette.testclient import TestClient
    from core.api import server
    d = TestClient(server.app).get("/api/status").json()
    assert "reasoning_markers" in d
    assert any("glm" in m for m in d["reasoning_markers"])
    assert any(("claude" in m or "anthropic" in m or "fable" in m) for m in d["reasoning_markers"])
