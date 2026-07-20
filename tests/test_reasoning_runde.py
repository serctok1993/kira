"""Reasoning-Runde: Denk-Faehigkeit ist ein KATALOG-FAKT (OpenRouter meldet sie pro
Modell live mit), die Denk-Tiefe ist DAUERHAFT einstellbar (/denk im Web-Chat und auf
Telegram, Denk-Tiefe-Feld in den Einstellungen), und der Modell-Picker zeigt
Zuletzt-genutzt + Vorauswahl statt eines 300er-Scrolls.

Live-Fund 20.07.: DeepSeek R1 und 'DeepSeek Reasoner' standen als 'kein Reasoning' im
Modell-Popup — die alte Marker-Liste (glm/anthropic/claude/fable/qwen3) kannte sie
nicht, der Denk-Regler blieb unsichtbar und der reasoning-Parameter wurde nie gesendet.
Offline: httpx gemockt, Katalog-/History-/Override-Dateien auf tmp.
"""
from __future__ import annotations

import json

import pytest

from core.kernel import models


# Roh-Form der OpenRouter-API (verifiziert am 20.07.2026): Denk-Modelle tragen
# 'reasoning' in supported_parameters UND/ODER ein Top-Level reasoning-Objekt.
_OR_ROH = {"data": [
    {"id": "deepseek/deepseek-r1", "name": "DeepSeek: R1",
     "pricing": {"prompt": "0.0000007", "completion": "0.0000025"}, "context_length": 163840,
     "supported_parameters": ["include_reasoning", "reasoning", "temperature"],
     "reasoning": {"mandatory": True}},
    {"id": "z-ai/glm-5.2", "name": "Z.ai: GLM 5.2",
     "pricing": {"prompt": "0.0000009548", "completion": "0.0000030008"}, "context_length": 1048576,
     "supported_parameters": ["reasoning", "reasoning_effort"],
     "reasoning": {"mandatory": False, "default_enabled": True}},
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o-mini",
     "pricing": {"prompt": "0.00000015", "completion": "0.0000006"}, "context_length": 128000,
     "supported_parameters": ["temperature", "tools"]},
]}


class _Resp:
    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_CATALOG_FILE", tmp_path / "openrouter_models.json")
    monkeypatch.setattr(models, "_HISTORY_FILE", tmp_path / "model_history.json")
    monkeypatch.setattr(models, "OVERRIDE", tmp_path / "models.json")
    monkeypatch.setattr(models, "_CATALOG_CACHE", {"ts": 0.0, "data": None})
    monkeypatch.setattr(models, "_RC_MEMO", {"mtime": -1.0, "ids": frozenset()})
    monkeypatch.setattr(models, "ollama_models", lambda: [])
    monkeypatch.setattr(models, "aimlapi_models", lambda: [])
    monkeypatch.setattr(models, "apply_model_overrides", lambda d: None)  # CONFIG nicht anfassen
    monkeypatch.setattr(models.httpx, "get", lambda url, timeout=15: _Resp(_OR_ROH))
    return tmp_path


# ---- Denk-Faehigkeit = Katalog-Fakt ---------------------------------------------------

def test_r1_ist_denkfaehig_der_live_fall():
    """DER Live-Fall: R1 traegt rc=True, das Nicht-Denk-Modell rc=False — und der
    Router erkennt beides ueber den Datei-Cache (erreicht so auch den Bot-Prozess)."""
    from core.kernel import llm_router
    c = models.catalog(force=True)
    r1 = next(m for m in c["openrouter"] if "deepseek-r1" in m["id"])
    mini = next(m for m in c["openrouter"] if "gpt-4o-mini" in m["id"])
    assert r1["rc"] is True and mini["rc"] is False
    assert llm_router.is_reasoning_model("openrouter/deepseek/deepseek-r1") is True
    assert llm_router.is_reasoning_model("openrouter/openai/gpt-4o-mini") is False
    assert llm_router.is_reasoning_model("ollama_chat/qwen3.5:9b") is True  # Marker-Fallback lebt


def test_reasoning_effort_erreicht_r1():
    """Vorher verpuffte denk:hoch bei R1 still — jetzt geht der Parameter wirklich raus."""
    from core.kernel import llm_router
    models.catalog(force=True)
    assert llm_router._reasoning_extra("openrouter/deepseek/deepseek-r1", "hoch") == \
        {"reasoning_effort": "high"}


def test_alter_datei_cache_ohne_rc_wird_aufgefrischt(_iso):
    """Cache-Datei aus der Zeit VOR der Reasoning-Runde (ohne 'rc') zaehlt nicht als
    frisch — einmal live nachladen, statt 6h lang falsche Badges zu zeigen."""
    (_iso / "openrouter_models.json").write_text(
        json.dumps([{"id": "openrouter/deepseek/deepseek-r1", "name": "R1",
                     "in": "1", "out": "2", "ctx": 1}]), encoding="utf-8")
    liste = models._openrouter_liste()          # frische Datei, aber altes Schema
    assert liste and liste[0].get("rc") is True  # kam live, nicht aus der Datei


# ---- /denk: dauerhafte Denk-Tiefe (deterministisch, kein LLM) -------------------------

def test_denk_command_setzt_dauerhaft(monkeypatch):
    from core.agency import act
    calls: list = []
    monkeypatch.setattr(act, "set_override", lambda p, v: calls.append((p, v)))
    monkeypatch.setattr(act.events, "emit", lambda *a, **k: None)  # nie in die Live-DB
    out = act._handle_denk_command("/denk hoch")
    assert calls == [("models.reasoning_level", "hoch")]
    assert "hoch" in out and "denk:" in out               # nennt den Pro-Nachricht-Weg mit
    out2 = act._handle_denk_command("/denk standard")
    assert calls[-1] == ("models.reasoning_level", "")
    assert "Standard" in out2


def test_denk_command_lehrt_bei_unsinn(monkeypatch):
    """Nach dem #185-Muster: der Fehlertext nennt den naechsten korrekten Aufruf."""
    from core.agency import act
    monkeypatch.setattr(act, "set_override", lambda p, v: (_ for _ in ()).throw(AssertionError("darf nicht setzen")))
    out = act._handle_denk_command("/denk quatsch")
    assert "/denk hoch" in out and "/denk standard" in out
    status = act._handle_denk_command("/denk")
    assert "/denk hoch|mittel|niedrig|aus" in status


def test_default_reasoning_aus_config(monkeypatch):
    from core.agency import act
    m = act.CONFIG.setdefault("models", {})
    monkeypatch.setitem(m, "reasoning_level", "hoch")
    assert act._default_reasoning() == "hoch"
    monkeypatch.setitem(m, "reasoning_level", "")
    assert act._default_reasoning() is None
    monkeypatch.setitem(m, "reasoning_level", "quatsch")   # kaputter Wert faellt still auf None
    assert act._default_reasoning() is None


def test_act_chat_denk_short_circuits(tmp_path, monkeypatch):
    """/denk wird wie /model VOR dem Chat-Fluss abgefangen — kein user_message-Event,
    keine LLM. Auch mit Modus-Praefix (Coding-Chat) nicht verschluckt."""
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    from core.agency import act
    monkeypatch.setattr(act, "set_override", lambda p, v: None)
    monkeypatch.setattr(act, "refresh_overrides", lambda: False)

    out = act.act_chat("/denk hoch", "sess-denk")
    assert "hoch" in out
    out2 = act.act_chat("code: /denk", "sess-denk2")
    assert "Denk-Tiefe aktuell" in out2
    types = [e["type"] for e in events.recent(30)]
    assert "denk_command" in types
    assert "user_message" not in types                     # Dialog nicht verschmutzt


def test_default_erreicht_den_llm_call(monkeypatch, tmp_path):
    """Der /denk-Standard wirkt OHNE Prefix: act_chat reicht ihn als reasoning durch."""
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()
    store.init_memory()
    from core.agency import act
    seen: dict = {}

    def fake_native(messages, system, session_id, escalate, emit, max_steps=None,
                    task_type="chat", reasoning=None):
        seen["reasoning"] = reasoning
        return "ok"

    monkeypatch.setattr(act, "_cloud", lambda e, t="chat": True)
    monkeypatch.setattr(act, "_native_loop", fake_native)
    monkeypatch.setattr(act, "refresh_overrides", lambda: False)
    monkeypatch.setitem(act.CONFIG.setdefault("models", {}), "reasoning_level", "mittel")

    act.act_chat("was steht heute an?", "sess-default")
    assert seen["reasoning"] == "mittel"                   # Standard greift
    act.act_chat("denk:aus kurze frage", "sess-default2")
    assert seen["reasoning"] == "aus"                      # Prefix uebersteuert den Standard


# ---- Zuletzt genutzt ------------------------------------------------------------------

def test_zuletzt_genutzt_im_katalog(_iso):
    models.set_role("chat", "openrouter/deepseek/deepseek-r1")
    models.set_role("reason", "openrouter/z-ai/glm-5.2")
    models.set_role("chat", "openrouter/deepseek/deepseek-r1")   # erneut -> dedupliziert nach vorn
    c = models.catalog(force=True)
    zl = [m["id"] for m in c["zuletzt"]]
    assert zl[0] == "openrouter/deepseek/deepseek-r1"
    assert zl.count("openrouter/deepseek/deepseek-r1") == 1
    assert "openrouter/z-ai/glm-5.2" in zl
    r1 = c["zuletzt"][0]
    assert r1["in"] == "0.0000007" and r1["rc"] is True    # gegen den Katalog aufgeloest


def test_history_ist_gedeckelt(_iso):
    for i in range(12):
        models.set_model(f"openrouter/x/m{i}")
    hist = json.loads((_iso / "model_history.json").read_text(encoding="utf-8"))
    assert len(hist) == models._HISTORY_MAX
    assert hist[0] == "openrouter/x/m11"                   # juengstes zuerst


# ---- Oberflaechen tragen die Regler ---------------------------------------------------

def test_cockpit_und_telegram_tragen_die_regler():
    from core.api.ui.script import SCRIPT
    from core.api.ui.views import VIEWS
    assert "reasoning_ids" in SCRIPT and "RC_IDS" in SCRIPT      # Katalog-Fakt im Regler
    assert "Zuletzt genutzt" in SCRIPT                           # Picker: Vorauswahl statt Scroll
    assert '["/denk "' in SCRIPT                                 # Befehls-Palette kennt /denk
    assert 'id="s-denk"' in VIEWS                                # Einstellungen: Denk-Tiefe-Feld
    assert "models.reasoning_level" in SCRIPT                    # ... und speichert sie live
    import inspect
    from core.agency.connectors import telegram_bot
    assert any(c == "denk" for c, _d in telegram_bot._BOT_COMMANDS)   # BotFather-Menue
    src = inspect.getsource(telegram_bot._handle_command)
    assert '"denk"' in src and "_handle_denk_command" in src          # Bot-Zweig -> EIN Handler


def test_status_liefert_reasoning_fakten():
    from starlette.testclient import TestClient
    from core.api import server
    d = TestClient(server.app).get("/api/status").json()
    assert isinstance(d.get("reasoning_ids"), list)
    assert "reasoning_level" in d
