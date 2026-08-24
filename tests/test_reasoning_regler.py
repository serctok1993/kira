"""S11: Ehrlicher, modell-abhaengiger Denk-Tiefe-Regler.

- is_reasoning_model / _reasoning_extra: nur denk-faehige Modelle bekommen den Parameter
- 'denk:'-Prefix im Chat wird geparst und als reasoning bis zum LLM-Call durchgereicht
- /api/status liefert die reasoning_markers (fuer den Live-Regler im Cockpit)

Seit der Reasoning-Runde ist die Faehigkeit primaer ein KATALOG-Fakt (models.reasoning_ids
aus der OpenRouter-Liste, siehe test_reasoning_runde.py) — diese Tests hier pruefen den
MARKER-FALLBACK und pinnen dafuer den Katalog auf leer (sonst haengt das Ergebnis von der
Live-Datei data/openrouter_models.json der jeweiligen Maschine ab).
"""
from __future__ import annotations

import pytest

from core.kernel import llm_router


@pytest.fixture()
def _ohne_katalog(monkeypatch):
    from core.kernel import models
    monkeypatch.setattr(models, "_CATALOG_FILE", models._CATALOG_FILE.with_name("gibtsnicht.json"))
    monkeypatch.setattr(models, "_RC_MEMO", {"mtime": -1.0, "ids": frozenset()})


# ---- Modell-Faehigkeit + Parameter-Mapping (Marker-Fallback) --------------------------

def test_is_reasoning_model(_ohne_katalog):
    assert llm_router.is_reasoning_model("openrouter/z-ai/glm-5.2")
    assert llm_router.is_reasoning_model("openrouter/anthropic/claude-fable-5")
    assert not llm_router.is_reasoning_model("openrouter/deepseek/deepseek-v4-flash")


def test_reasoning_extra_nur_bei_faehigen(_ohne_katalog):
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "hoch") == {"reasoning_effort": "high"}
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "aus") == {"reasoning_effort": "minimal"}
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "niedrig") == {"reasoning_effort": "low"}
    # nicht denk-faehig (laut Markern; der Katalog ist hier bewusst leer) -> leer
    assert llm_router._reasoning_extra("openrouter/deepseek/deepseek-v4-flash", "hoch") == {}
    # kein Level / Standard -> leer
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", None) == {}
    assert llm_router._reasoning_extra("openrouter/z-ai/glm-5.2", "") == {}


def test_reasoning_effort_bench_override(_ohne_katalog, monkeypatch):
    """KIRA_FORCE_REASONING_EFFORT erzwingt den effort BEDINGUNGSLOS — auch fuer Modelle,
    die der Katalog nicht als denk-faehig meldet (ox-alpha). Ohne die Env bleibt alles
    katalog-gesteuert; das ist die Voraussetzung fuer den agentischen ox-alpha-Lauf."""
    oxa = "openrouter/stealth/ox-alpha"
    # ohne Env: Katalog kennt ox-alpha nicht -> kein effort, es verdenkt sich
    monkeypatch.delenv("KIRA_FORCE_REASONING_EFFORT", raising=False)
    assert llm_router._reasoning_extra(oxa, None) == {}
    assert llm_router._reasoning_extra(oxa, "hoch") == {}   # Level allein reicht nicht
    # mit Env: bedingungslos. Fuer OpenRouter als ROHER reasoning-Parameter (extra_body),
    # weil litellms drop_params reasoning_effort bei litellm-unbekannten Modellen verwirft.
    monkeypatch.setenv("KIRA_FORCE_REASONING_EFFORT", "niedrig")
    assert llm_router._reasoning_extra(oxa, None) == {"extra_body": {"reasoning": {"effort": "low"}}}
    assert llm_router._reasoning_extra("openrouter/deepseek/deepseek-v4-flash", None) == {"extra_body": {"reasoning": {"effort": "low"}}}
    # Nicht-OpenRouter behaelt den litellm-Standardparameter
    assert llm_router._reasoning_extra("anthropic/claude-x", None) == {"reasoning_effort": "low"}
    # unbekannter Wert wird ignoriert (fail-soft, faellt auf Katalog-Logik zurueck)
    monkeypatch.setenv("KIRA_FORCE_REASONING_EFFORT", "quatsch")
    assert llm_router._reasoning_extra(oxa, None) == {}


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
    # kein Config-Reload mitten im Test (ein LIVE-Prozess koennte overrides.json anfassen)
    monkeypatch.setattr(act, "refresh_overrides", lambda: False)

    act.act_chat("denk:hoch erklaer mir Photosynthese", "r1")
    assert seen["reasoning"] == "hoch"
    assert seen["text"].startswith("erklaer mir")          # Prefix wurde abgestreift

    seen.clear()
    # Standard-Denk-Tiefe explizit leer pinnen — auf einer Live-Maschine koennte
    # /denk sie gesetzt haben (overrides.json), der Test bleibt deterministisch.
    monkeypatch.setitem(act.CONFIG.setdefault("models", {}), "reasoning_level", "")
    act.act_chat("ganz normal ohne prefix", "r2")
    assert seen["reasoning"] is None                        # kein Prefix, kein Standard -> kein Level


# ---- /api/status liefert die Marker fuer den Live-Regler -------------------------------

def test_status_liefert_reasoning_markers():
    from starlette.testclient import TestClient
    from core.api import server
    d = TestClient(server.app).get("/api/status").json()
    assert "reasoning_markers" in d
    assert any("glm" in m for m in d["reasoning_markers"])
    assert any(("claude" in m or "anthropic" in m or "fable" in m) for m in d["reasoning_markers"])
