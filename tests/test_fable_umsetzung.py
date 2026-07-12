"""Umsetzung der Fable-Review-Entscheidungen (07.07.2026):
Verfassungs-Kompass, Judge=Denker, Motor liest Lektionen, Doctor-Eskalations-Warnung,
Dirty-Check, Token-Statistik, Einstellungen-Ebene.
"""
from __future__ import annotations


# ---- 2: Verfassung traegt nur noch den zeitlosen Kompass ------------------------------

def test_verfassung_kompass_statt_alter_mission():
    from core.config import MIND_DIR
    t = (MIND_DIR / "constitution.md").read_text(encoding="utf-8")
    assert "Der Kompass" in t
    assert "100.000" not in t                       # alte Geld-Mission ist raus
    assert "GOAL.md" in t and "gilt" in t           # lebende Mission delegiert an GOAL
    assert "Not-Aus" in t and "Budget ist heilig" in t  # zeitlose Regeln unangetastet


# ---- Judge != Actor ---------------------------------------------------------------------

def test_verifier_route_ist_denker():
    from core.config import CONFIG
    assert (CONFIG.get("outcomes") or {}).get("verifier_task_type") == "reason"


# ---- Motor liest eigene Lektionen -------------------------------------------------------

def test_identity_enthaelt_lektionen_und_skills(monkeypatch):
    from core.agency import act
    from core.mind.memory import store
    monkeypatch.setattr(store, "recall_lessons", lambda limit=5: ["nie ohne test pushen"])
    monkeypatch.setattr(store, "recall_skills", lambda limit=6: ["leads recherchieren"])
    ident = act._identity()
    assert "DEINE GELERNTEN LEKTIONEN" in ident and "nie ohne test pushen" in ident
    assert "DEINE SKILLS" in ident and "leads recherchieren" in ident


def test_identity_failsoft_ohne_memory(monkeypatch):
    from core.agency import act
    from core.mind.memory import store
    def boom(limit=5):
        raise RuntimeError("db weg")
    monkeypatch.setattr(store, "recall_lessons", boom)
    ident = act._identity()  # darf nie raisen
    assert "DEINE VERFASSUNG" in ident


# ---- Doctor: Eskalations-Warnung (flexibel, kein Festnageln) ---------------------------

def test_doctor_warnt_bei_massen_eskalation(monkeypatch):
    from core.kernel import doctor, llm_router
    monkeypatch.setitem(doctor.CONFIG, "models", {
        **doctor.CONFIG.get("models", {}),
        "escalation_model": "openrouter/gratis/hy3",
    })
    routing = {"chat": "openrouter/gratis/hy3", "bulk": "openrouter/gratis/hy3",
               "reason": "openrouter/z-ai/glm-5.2", "classify": "ollama_chat/qwen3.5:9b"}
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda tt="default", escalate=False: (routing.get(tt, "x"), False))
    rep = doctor.check()
    assert any("Eskalation" in p and "Denker" in p for p in rep["problems"]), rep["problems"]


def test_doctor_still_wenn_eskalation_stark(monkeypatch):
    from core.kernel import doctor, llm_router
    monkeypatch.setitem(doctor.CONFIG, "models", {
        **doctor.CONFIG.get("models", {}),
        "escalation_model": "openrouter/z-ai/glm-5.2",
    })
    routing = {"chat": "openrouter/deepseek/deepseek-v4-flash", "bulk": "openrouter/deepseek/deepseek-v4-flash",
               "reason": "openrouter/z-ai/glm-5.2", "classify": "ollama_chat/qwen3.5:9b"}
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda tt="default", escalate=False: (routing.get(tt, "x"), False))
    rep = doctor.check()
    assert not any("Eskalation" in p and "Denker" in p for p in rep["problems"])


# ---- Dirty-Check: code:-Lauf frisst nie des Nutzers ungesicherte Arbeit ---------------------

def test_dirty_check_verweigert_am_live_system(monkeypatch, tmp_path):
    from core.kernel import events
    from core.agency import act
    import core.config as cfg
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setattr(cfg, "test_mode", lambda: False)          # Live-System simulieren
    monkeypatch.setattr(act, "_git_out", lambda *a: " M core/wichtig.py" if "status" in a else "abc")
    out = act.plan_and_execute("code: bau was", session_id="dc1", code_review=True)
    assert "NICHT gestartet" in out and "committen" in out
    assert "plan_dirty_refused" in [e["type"] for e in events.recent(10)]


def test_dirty_check_entfaellt_in_sandbox(monkeypatch, tmp_path):
    """In test_mode (Sandbox/Worktree) laeuft der Lauf trotz dirty — Wegwerf-Material."""
    from core.kernel import events
    from core.agency import act
    from core.kernel import llm_router
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    from core.mind import reflection
    monkeypatch.setattr(reflection, "reflect_on", lambda *a, **k: {})
    monkeypatch.setattr(act, "_CLAIM_CHECK", False)
    monkeypatch.setattr(act, "_git_out", lambda *a: " M x.py" if "status" in a else "abc")
    monkeypatch.setattr(act, "_make_plan", lambda t, s, escalate=True: [{"schritt": "lese", "rang": "reflex"}])
    monkeypatch.setattr(act, "act", lambda *a, **k: {"text": "ok", "steps": 1})
    monkeypatch.setattr(llm_router, "complete", lambda *a, **k: {
        "text": "fertig", "cost_usd": 0, "model": "f", "fell_back": False, "latency_s": 0,
        "escalated": False, "tool_calls": []})
    monkeypatch.setattr(llm_router, "resolve_model", lambda t="d", escalate=False: ("m", False))
    out = act.plan_and_execute("code: x", session_id="dc2", code_review=True)
    assert "NICHT gestartet" not in out


# ---- Token-Statistik + Einstellungen-Ebene ----------------------------------------------

def test_insights_liefert_token_statistik(monkeypatch, tmp_path):
    from starlette.testclient import TestClient
    import core.api.server as s
    import core.config as cfg
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "state.db")
    events.init_db()
    events.emit("llm_call", {"task_type": "chat", "cost_usd": 0.001,
                             "tokens": {"prompt": 100, "completion": 50}})
    d = TestClient(s.app).get("/api/insights").json()
    tk = d["tokens_heute"]
    assert tk["total_calls"] == 1 and tk["total_tokens"] == 150
    assert tk["by_role"][0]["role"] == "chat"


def test_einstellungen_ebene_im_cockpit():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="gear"' in html                     # ⚙ in der Topbar
    assert "⚙ Einstellungen" in html               # Gruppe umbenannt
    assert 'id="st-tokens"' in html                # Token-Statistik-Karte
    assert "tokens_heute" in html                  # JS rendert sie