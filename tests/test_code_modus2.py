"""Code-Modus 2.0: Read-before-Edit-Guard (B-028), Diff-Review (B-029),
mittlere Arbeitsflaeche fuer starke offene Modelle (B-030), code: auf Denker-Rang.
"""
from __future__ import annotations


def _tmp_dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()
    return events


def _router(monkeypatch, model: str, fell_back: bool = False):
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda t="default", escalate=False: (model, fell_back))


# ---- B-030: mittlere Arbeitsflaeche ----------------------------------------------------

def test_medium_budget_fuer_glm(monkeypatch):
    from core.agency import act
    monkeypatch.setattr(act, "_STRONG_CFG", {"max_steps": 200})
    monkeypatch.setattr(act, "_STRONG_MARKERS", ["anthropic/"])
    monkeypatch.setattr(act, "_MEDIUM_CFG", {"max_steps": 120})
    monkeypatch.setattr(act, "_MEDIUM_MARKERS", ["z-ai/", "glm"])

    _router(monkeypatch, "openrouter/z-ai/glm-5.2")
    assert act._budget("max_steps", 80) == 120          # medium greift
    _router(monkeypatch, "openrouter/anthropic/claude-fable-5")
    assert act._budget("max_steps", 80) == 200          # strong schlaegt medium
    _router(monkeypatch, "openrouter/deepseek/deepseek-v4-flash")
    assert act._budget("max_steps", 80) == 80           # Basis
    _router(monkeypatch, "openrouter/z-ai/glm-5.2", fell_back=True)
    assert act._budget("max_steps", 80) == 80           # Fallback -> IMMER Basis


def test_config_hat_medium_block():
    from core.config import CONFIG
    ag = CONFIG.get("agency", {})
    med = ag.get("medium", {})
    assert med, "agency.medium fehlt in config.yaml"
    assert int(med["max_steps"]) > int(ag.get("max_steps", 80) // 2)
    assert int(med["max_steps"]) < int(ag.get("strong", {}).get("max_steps", 200))
    assert any("glm" in str(m) or "z-ai" in str(m) for m in ag.get("medium_markers", []))
    assert ag.get("read_before_edit", False) is True


# ---- B-028: Read-before-Edit-Guard ------------------------------------------------------

def _fresh_session(name: str) -> str:
    from core.agency import act
    act._SEEN_FILES.pop(name, None)
    return name


def test_edit_ohne_lesen_wird_blockiert(monkeypatch, tmp_path):
    events = _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    sid = _fresh_session("rbe-1")

    block = act._rbe_block(sid, "edit_datei", {"pfad": "core/config.py"})  # existiert, ungelesen
    assert block and "GESPERRT" in block and "core/config.py" in block
    assert "edit_blocked_unread" in [e["type"] for e in events.recent(10)]

    # neue (nicht existierende) Datei -> frei
    assert act._rbe_block(sid, "edit_datei", {"pfad": "gibt_es_nicht_xyz.py"}) is None
    # Nicht-Edit-Werkzeuge -> nie blockiert
    assert act._rbe_block(sid, "read_file", {"path": "core/config.py"}) is None


def test_nach_lesen_ist_edit_frei(monkeypatch, tmp_path):
    _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    sid = _fresh_session("rbe-2")

    act._rbe_record(sid, "read_file", {"path": "core/config.py"}, "inhalt...")
    assert act._rbe_block(sid, "edit_datei", {"pfad": "core/config.py"}) is None
    # absoluter Pfad auf dieselbe Datei -> gleiche Normalisierung, ebenfalls frei
    from core.config import ROOT
    assert act._rbe_block(sid, "self_edit", {"path": str(ROOT / "core" / "config.py")}) is None


def test_suche_treffer_zaehlen_als_gelesen(monkeypatch, tmp_path):
    _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    sid = _fresh_session("rbe-3")

    obs = "core/kernel/llm_router.py:42: def resolve_model(...)\ncore/agency/act.py:7: import re"
    act._rbe_record(sid, "code_suche", {"muster": "x"}, obs)
    assert act._rbe_block(sid, "edit_datei", {"pfad": "core/kernel/llm_router.py"}) is None
    assert act._rbe_block(sid, "edit_datei", {"pfad": "core/agency/act.py"}) is None
    # andere Datei bleibt gesperrt
    assert act._rbe_block(sid, "edit_datei", {"pfad": "core/config.py"}) is not None


def test_guard_abschaltbar_und_raist_nie(monkeypatch, tmp_path):
    _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    monkeypatch.setattr(act, "_RBE_ON", False)
    assert act._rbe_block("rbe-4", "edit_datei", {"pfad": "core/config.py"}) is None
    monkeypatch.setattr(act, "_RBE_ON", True)
    assert act._rbe_block("rbe-5", "edit_datei", {}) is None  # kaputte Args -> kein Crash


# ---- code: laeuft auf dem Denker (GLM), nicht mehr zwangs-eskaliert ---------------------

def test_code_mode_eskaliert_nicht_mehr_automatisch(monkeypatch, tmp_path):
    _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    seen: dict = {}

    def fake_plan(task, session_id=None, on_event=None, escalate=True, code_review=False):
        seen.update(escalate=escalate, review=code_review)
        return "fertig"

    monkeypatch.setattr(act, "plan_and_execute", fake_plan)

    act.act_chat("code: kleiner Fix", session_id="cm1")
    assert seen == {"escalate": False, "review": True}     # Denker-Rang (GLM) + Diff-Review

    act.act_chat("reason: code: harter Fix", session_id="cm1")
    assert seen == {"escalate": True, "review": True}      # explizit -> Richter (Fable)

    act.act_chat("plan: grosser Auftrag", session_id="cm1")
    assert seen == {"escalate": False, "review": False}    # plan: laeuft jetzt auf GLM (Denker), nicht Fable


# ---- B-029: Diff-Review -----------------------------------------------------------------

def _fake_complete(text: str):
    def fake(messages, system=None, task_type="chat", session_id=None, escalate=False, tools=None):
        return {"text": text, "cost_usd": 0.0, "model": "fake", "fell_back": False,
                "latency_s": 0.0, "escalated": False, "tool_calls": []}
    return fake


def test_review_bestanden(monkeypatch, tmp_path):
    events = _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    from core.kernel import llm_router
    monkeypatch.setattr(act, "_git_out", lambda *a: "diff --git a/x.py" if "diff" in a else "abc123")
    monkeypatch.setattr(llm_router, "complete", _fake_complete("URTEIL: OK\n- sauber"))

    note = act._code_review_run("Auftrag", "abc123", "cr1", False, lambda ev: None)
    assert "bestanden" in note
    assert "code_review_pass" in [e["type"] for e in events.recent(10)]


def test_review_maengel_loest_fix_aus(monkeypatch, tmp_path):
    events = _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    from core.kernel import llm_router
    monkeypatch.setattr(act, "_git_out", lambda *a: "diff --git a/x.py" if "diff" in a else "abc123")
    monkeypatch.setattr(llm_router, "complete",
                        _fake_complete("URTEIL: MAENGEL\n- Test fuer y fehlt"))
    fixes: list = []
    monkeypatch.setattr(act, "act", lambda task, **kw: fixes.append(task) or {"text": "nachgebessert", "steps": 1})

    note = act._code_review_run("Auftrag", "abc123", "cr2", False, lambda ev: None)

    assert len(fixes) == 1 and "Maengel" in fixes[0]
    assert "nachgebessert" in note
    types = [e["type"] for e in events.recent(10)]
    assert "code_review_fail" in types and "code_review_fixed" in types


def test_review_ohne_diff_still(monkeypatch, tmp_path):
    _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    monkeypatch.setattr(act, "_git_out", lambda *a: "")
    assert act._code_review_run("Auftrag", "abc123", "cr3", False, lambda ev: None) == ""
