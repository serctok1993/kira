"""Modell-Routing (des Nutzers 'safe'-Regel): Plaudern billig auf DeepSeek, echtes Arbeiten auf GLM 5.2.

- normaler Chat  -> task_type 'chat'  (config: DeepSeek)
- /work, work:   -> task_type 'reason' (config: GLM 5.2)
- code:, plan:   -> Denker/GLM (escalate=False), Fable NUR bei reason:/🧠
"""
from __future__ import annotations


def _dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()
    store.init_memory()


def _cap_route(monkeypatch):
    """Faengt den task_type ab, mit dem der Chat-Loop das Modell zieht."""
    from core.agency import act
    seen: dict = {}
    monkeypatch.setattr(act, "_cloud", lambda e, t="chat": True)

    def fake_native(messages, system, session_id, escalate, emit, max_steps=None, task_type="chat", reasoning=None):
        seen["tt"] = task_type
        return "ok"

    monkeypatch.setattr(act, "_native_loop", fake_native)
    return seen


def test_plaudern_bleibt_deepseek(monkeypatch, tmp_path):
    from core.agency import act
    _dbs(monkeypatch, tmp_path)
    seen = _cap_route(monkeypatch)
    act.act_chat("wie geht es dir heute?", "r1")
    assert seen["tt"] == "chat"          # guenstige DeepSeek-Route


def test_work_faehrt_glm_route(monkeypatch, tmp_path):
    from core.agency import act
    _dbs(monkeypatch, tmp_path)
    seen = _cap_route(monkeypatch)
    act.act_chat("/work recherchiere die Konkurrenz und fasse zusammen", "r2")
    assert seen["tt"] == "reason"        # echtes Arbeiten -> GLM 5.2

    seen.clear()
    act.act_chat("work: baue mir eine Uebersicht", "r3")
    assert seen["tt"] == "reason"


def test_plan_und_code_faehren_glm_nicht_fable(monkeypatch, tmp_path):
    from core.agency import act
    _dbs(monkeypatch, tmp_path)
    seen: dict = {}

    def fake_plan(task, session_id=None, on_event=None, escalate=True, code_review=False):
        seen.clear()
        seen.update(escalate=escalate, review=code_review)
        return "ok"

    monkeypatch.setattr(act, "plan_and_execute", fake_plan)

    act.act_chat("plan: grosser Auftrag", "r4")
    assert seen == {"escalate": False, "review": False}   # GLM (Denker), kein Fable

    act.act_chat("code: kleiner Fix", "r5")
    assert seen == {"escalate": False, "review": True}    # GLM + Diff-Review

    # Fable nur, wenn der Nutzer explizit eskaliert
    act.act_chat("reason: plan: harte Nuss", "r6")
    assert seen["escalate"] is True
