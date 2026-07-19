"""Robuster Modell-Switch: deterministischer /model-Befehl + sichtbarer Fallback.

Hintergrund-Bug: Wechsel von Cloud auf lokal klappte, Rueckwechsel nicht — der
einzige Weg im Web-Chat war ein LLM-Tool-Call, den ein schwaches lokales Modell
nicht absetzen kann. Zusaetzlich fiel resolve_model bei fehlendem Key STILL auf
lokal zurueck, und /api/status meldete das Wunsch- statt das Real-Modell.
"""
from __future__ import annotations

import asyncio


def _events(tmp_path, monkeypatch):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    return events


# ---- A: deterministischer /model-Befehl im Web-Chat ----------------------------------

def test_act_chat_model_command_short_circuits(tmp_path, monkeypatch):
    """/model wird VOR dem normalen Chat-Fluss abgefangen — kein user_message-Event,
    keine LLM. Beweis: model_command wird emittiert, user_message NICHT."""
    events = _events(tmp_path, monkeypatch)
    from core.agency import act
    from core.kernel import models
    monkeypatch.setattr(models, "ollama_models", lambda: [])

    seen: list = []
    out = act.act_chat("/model", "sess-a", on_event=lambda ev: seen.append(ev))

    assert "Modelle" in out
    assert any(ev.get("kind") == "final" for ev in seen)
    types = [e["type"] for e in events.recent(30)]
    assert "model_command" in types
    assert "user_message" not in types  # der Dialog wurde NICHT verschmutzt


def test_act_chat_model_use_switches(tmp_path, monkeypatch):
    _events(tmp_path, monkeypatch)
    from core.agency import act
    from core.kernel import llm_router, models
    rec: dict = {}
    monkeypatch.setattr(models, "set_model", lambda mid, scope="default": rec.setdefault("id", mid) or mid)
    monkeypatch.setattr(llm_router, "has_key", lambda mid: True)

    out = act.act_chat("/model use ollama_chat/qwythos", "sess-b")

    assert rec["id"] == "ollama_chat/qwythos"
    assert "ollama_chat/qwythos" in out


def test_act_chat_model_shortcut_fable_sets_escalation(tmp_path, monkeypatch):
    _events(tmp_path, monkeypatch)
    from core.agency import act
    from core.kernel import llm_router, models
    rec: list = []
    monkeypatch.setattr(models, "set_role", lambda role, mid: rec.append((role, mid)) or mid)
    monkeypatch.setattr(llm_router, "has_key", lambda mid: True)

    act.act_chat("/model fable", "sess-c")

    assert rec == [("escalation", "openrouter/anthropic/claude-fable-5")]


def test_model_command_grammar(monkeypatch):
    """Jeder Zweig liefert einen String, raist nie."""
    from core.agency import act
    from core.kernel import llm_router, models
    calls: dict = {}
    monkeypatch.setattr(models, "ollama_models", lambda: [])
    monkeypatch.setattr(models, "set_model", lambda mid, scope="default": calls.update(model=mid) or mid)
    monkeypatch.setattr(models, "set_role", lambda role, mid: calls.update(role=(role, mid)) or mid)
    monkeypatch.setattr(llm_router, "has_key", lambda mid: True)

    assert "Modelle" in act._handle_model_command("/model")               # Status
    act._handle_model_command("/model use openrouter/x/y")
    assert calls["model"] == "openrouter/x/y"
    act._handle_model_command("/model chat deepseek/deepseek-v4-flash")   # blanke id -> openrouter/
    assert calls["role"] == ("chat", "openrouter/deepseek/deepseek-v4-flash")
    act._handle_model_command("/model local")                            # Notbremse
    assert calls["model"] == "ollama_chat/qwen3.5:9b"
    act._handle_model_command("/model 35b")                              # lokaler Denker
    assert calls["model"] == "ollama_chat/qwen3.6:35b"
    assert "Unbekannter" in act._handle_model_command("/model blafasel")


def test_model_command_keywarn_without_key(monkeypatch):
    from core.agency import act
    from core.kernel import llm_router, models
    monkeypatch.setattr(models, "set_model", lambda mid, scope="default": mid)
    monkeypatch.setattr(llm_router, "has_key", lambda mid: False)
    out = act._handle_model_command("/model use openrouter/deepseek/deepseek-v4-flash")
    assert "Kein Key" in out  # ehrlich statt still


# ---- B: kein stiller Fallback -------------------------------------------------------

def test_resolve_model_emits_fallback_throttled(tmp_path, monkeypatch):
    events = _events(tmp_path, monkeypatch)
    from core.config import CONFIG
    from core.kernel import llm_router
    for env in set(llm_router._PROVIDER_KEYS.values()):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setitem(CONFIG["models"], "default", "openrouter/deepseek/deepseek-v4-flash")
    monkeypatch.setitem(CONFIG["models"], "routing", {"chat": "openrouter/deepseek/deepseek-v4-flash"})
    llm_router._FALLBACK_SEEN.clear()

    mid, fb = llm_router.resolve_model("chat")
    assert fb is True and mid == CONFIG["models"]["local_fallback"]
    fe = [e for e in events.recent(30) if e["type"] == "model_fallback"]
    assert len(fe) == 1
    llm_router.resolve_model("chat")  # sofort nochmal -> gedrosselt, kein Duplikat
    fe2 = [e for e in events.recent(30) if e["type"] == "model_fallback"]
    assert len(fe2) == 1


def test_api_status_reports_resolved_and_fallback(monkeypatch):
    from core.api import server
    from core.kernel import llm_router
    monkeypatch.setattr(server.models, "status", lambda: {
        "default": "openrouter/x/y", "api_keys": {}, "providers": {}, "ollama_local": [],
        "escalation_model": "e", "num_ctx": 1, "max_tokens": 1})
    monkeypatch.setattr(server.treasury, "status", lambda: {})
    monkeypatch.setattr(server, "today_spend_usd", lambda: 0.0)
    monkeypatch.setattr(server, "kill_switch_active", lambda: False)
    monkeypatch.setattr(server.events, "counts_by_type", lambda: {})
    monkeypatch.setattr(server.memory, "recall_lessons", lambda n: [])
    monkeypatch.setattr(llm_router, "resolve_model", lambda t="default", escalate=False: ("ollama_chat/qwythos", True))

    r = server.api_status()
    assert r["model"] == "openrouter/x/y"            # rueckwaertskompatibel
    assert r["resolved_model"] == "ollama_chat/qwythos"
    assert r["fallback_active"] is True


def test_api_model_use_warns_without_key(monkeypatch):
    from core.api import server
    from core.kernel import llm_router
    monkeypatch.setattr(server.models, "set_model", lambda mid, scope="default": mid)
    monkeypatch.setattr(server.events, "emit", lambda *a, **k: None)

    monkeypatch.setattr(llm_router, "has_key", lambda mid: False)
    r = asyncio.run(server.api_model_use({"id": "openrouter/deepseek/deepseek-v4-flash"}))
    assert r["ok"] and r["active"] == "openrouter/deepseek/deepseek-v4-flash"
    assert r["warning"] and "Kein Key" in r["warning"]

    monkeypatch.setattr(llm_router, "has_key", lambda mid: True)
    r2 = asyncio.run(server.api_model_use({"id": "ollama_chat/qwythos"}))
    assert r2["warning"] is None


# ---- C: Katalog + Raenge im Cockpit ---------------------------------------------------

def test_roles_enthaelt_reflex_und_arbeiter():
    """Die Rang-Zeilen im Cockpit (Reflex/Arbeiter) brauchen roles()-Eintraege."""
    from core.kernel import models
    r = models.roles()
    for key in ("chat", "reason", "bulk", "classify", "worker", "escalation", "default"):
        assert key in r, f"roles() ohne {key}"


def test_catalog_hat_aimlapi_gruppe(monkeypatch):
    """Der Live-Katalog fuehrt alle Quellen: OpenRouter + lokal + AIMLAPI —
    plus die kuratierte Vorauswahl (Katalog-Runde)."""
    import httpx
    from core.kernel import models
    monkeypatch.setattr(models, "ollama_models", lambda: ["qwen3.5:9b"])
    monkeypatch.setattr(models, "aimlapi_models",
                        lambda: [{"id": "aimlapi/openai/gpt-4o", "name": "GPT-4o", "in": 0, "out": 0, "ctx": 128000}])
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(models, "_CATALOG_FILE", models._CATALOG_FILE.with_name("gibtsnicht.json"))
    cat = models.catalog(force=True)
    assert set(cat.keys()) == {"openrouter", "local", "aimlapi", "kuratiert"}
    assert cat["local"][0]["id"] == "ollama_chat/qwen3.5:9b"
    assert cat["aimlapi"][0]["id"].startswith("aimlapi/")
    models._CATALOG_CACHE.update(ts=0.0, data=None)  # Cache nicht vergiften


def test_cockpit_katalog_rendert_aimlapi_und_raenge():
    """UI-Marker: aimlapi-Gruppe im Renderer, Reflex/Arbeiter im Zuweisen-Dropdown."""
    from core.api.ui.script import SCRIPT
    from core.api.ui.views import VIEWS
    assert "MCAT.aimlapi" in SCRIPT
    assert 'value="classify"' in VIEWS and 'value="worker"' in VIEWS


def test_shortcuts_zeigen_auf_qwen():
    """Notbremse + neue Kurzbefehle: qwythos ist in Rente."""
    from core.agency import act
    assert act._MODEL_SHORTCUTS["local"][1] == "ollama_chat/qwen3.5:9b"
    assert act._MODEL_SHORTCUTS["9b"][1] == "ollama_chat/qwen3.5:9b"
    assert act._MODEL_SHORTCUTS["35b"][1] == "ollama_chat/qwen3.6:35b"
    assert act._MODEL_SHORTCUTS["glm"] == ("reason", "openrouter/z-ai/glm-5.2")
    assert not any("qwythos" in mid for _r, mid in act._MODEL_SHORTCUTS.values())


def test_fuenf_stufen_config():
    """des Nutzers Oekonomie: lokal / Chat Flash / Arbeiter Flash / Denker GLM / Spitze GLM (Fable RAUS)."""
    from core.config import CONFIG
    m = CONFIG["models"]
    rt = m["routing"]
    assert rt["classify"].startswith("ollama_chat/qwen")          # Stufe 1: lokal, 0 EUR
    assert "flash" in rt["chat"]                                  # Stufe 2: Chat
    assert "flash" in rt["worker"] and "flash" in rt["bulk"]      # Stufe 3: Arbeiter/Grind
    assert rt["reason"] == "openrouter/z-ai/glm-5.2"              # Stufe 4: Denker
    assert m["escalation_model"] == "openrouter/z-ai/glm-5.2"     # Stufe 5: GLM (kein teures Fable mehr)
    assert "fable" not in m["escalation_model"].lower()           # Fable ist raus aus der Auto-Oekonomie
    assert m["local_fallback"].startswith("ollama_chat/")         # Notbremse immer lokal


def test_model_command_ueberlebt_modus_praefixe(tmp_path, monkeypatch):
    """BUG-Regression (Praxis-Fund): der Coding-/Research-Modus haengt code://work
    vor JEDE Nachricht -> '/model' wurde als Planungs-Auftrag an die LLM verschluckt.
    Steuerbefehle muessen in JEDEM Modus deterministisch greifen."""
    events = _events(tmp_path, monkeypatch)
    from core.agency import act
    from core.kernel import models
    monkeypatch.setattr(models, "ollama_models", lambda: [])

    for praefix in ("code: ", "plan: ", "/work ", "work: ", "reason: code: "):
        out = act.act_chat(praefix + "/model", f"sess-{praefix.strip(': /')}",
                           on_event=lambda ev: None)
        assert "Modelle" in out, f"verschluckt bei Praefix {praefix!r}"
    types = [e["type"] for e in events.recent(50)]
    assert "user_message" not in types  # nie in den normalen Chat-Fluss gerutscht
