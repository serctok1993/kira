"""Stufe 2c: Runner-Hook der Ergebnis-Rueckkopplung — offline, Temp-DB, act/verifier gefakt."""
from __future__ import annotations

from core.agency import approvals, outcomes, verifier
from core.agency.missions import queue, runner
from core.config import CONFIG
from core.kernel import events
from core.mind import reflection


def _setup(monkeypatch, tmp_path, verdicts: list[dict]):
    """Temp-DB + stiller Runner + geskriptete Verdicts. Liefert (task_id, act_calls)."""
    db = str(tmp_path / "state.db")
    from core.agency.missions import objectives as _objectives

    # WICHTIG: auch objectives patchen — run_once ruft init_objectives(); ohne Patch
    # ginge das auf die ECHTE state.db (Lock-Flakes + Hands-off-Verstoss).
    for mod in (queue, outcomes, events, approvals, _objectives):
        monkeypatch.setattr(mod, "DB_PATH", db)

    monkeypatch.setitem(CONFIG, "mission", {"name": "testmission", "notify_telegram": False})
    monkeypatch.setitem(CONFIG, "outcomes", {"enabled": True, "pass_score": 70, "max_quality_retries": 2})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_notify", lambda text: None)
    monkeypatch.setattr(reflection, "reflect_on", lambda task, work, escalate=False: {"lessons": []})

    crit = [{"text": "Kriterium A"}, {"text": "Kriterium B"}]
    monkeypatch.setattr(verifier, "ensure_criteria", lambda task: crit)

    it = iter(verdicts)
    monkeypatch.setattr(verifier, "verify", lambda task, criteria, text: next(it))

    act_calls: list[dict] = []

    def fake_act(task, session_id=None, escalate=False, task_type="reason", **kw):
        act_calls.append({"prompt": task, "task_type": task_type})
        return {"text": "Ergebnis des Versuchs " + "x" * 60, "steps": 1}

    monkeypatch.setattr(runner, "act", fake_act)

    events.init_db()
    queue.init_queue()
    tid = queue.add("Recherchiere Hosting-Anbieter", mission="testmission", kind="research")
    return tid, act_calls


def _v(score, verdict, feedback=""):
    return {"score": score, "verdict": verdict, "checks": [], "feedback": feedback, "cost_usd": 0.0}


def test_pass_completes_with_score(monkeypatch, tmp_path):
    tid, act_calls = _setup(monkeypatch, tmp_path, [_v(85, "pass")])
    out = runner.run_once()
    assert out.get("score") == 85
    full = queue.get_task(tid)
    assert full["status"] == "done" and full["score"] == 85
    assert len(outcomes.for_task(tid)) == 1
    assert outcomes.last(tid)["strategy"] == "standard"
    assert act_calls[0]["task_type"] == "bulk"
    # Kriterien stehen im Arbeits-Prompt, nicht in der DB-description
    assert "AKZEPTANZKRITERIEN" in act_calls[0]["prompt"]
    assert full["description"] == "Recherchiere Hosting-Anbieter"


def test_retry_requeues_and_escalates(monkeypatch, tmp_path):
    tid, act_calls = _setup(monkeypatch, tmp_path,
                            [_v(45, "retry", "Suche 2 weitere Quellen"), _v(80, "pass")])
    out = runner.run_once()
    assert out.get("retry") == 1
    full = queue.get_task(tid)
    assert full["status"] == "pending" and full["quality_retries"] == 1
    assert full["feedback"] == "Suche 2 weitere Quellen"
    assert full["retry_count"] == 0  # Absturz-Zaehler bleibt UNBERUEHRT (harte Trennung)

    # Naechster Tick: gleicher Task, eskalierte Route, Feedback im Prompt
    out = runner.run_once()
    assert out.get("score") == 80
    assert act_calls[1]["task_type"] == "reason"
    assert "Suche 2 weitere Quellen" in act_calls[1]["prompt"]
    assert "ABGELEHNT" in act_calls[1]["prompt"]
    full = queue.get_task(tid)
    assert full["status"] == "done"
    assert [o["attempt"] for o in outcomes.for_task(tid)] == [1, 2]
    assert outcomes.last(tid)["strategy"] == "eskaliert"


def test_three_fails_final(monkeypatch, tmp_path):
    tid, act_calls = _setup(monkeypatch, tmp_path,
                            [_v(30, "retry", "f1"), _v(35, "retry", "f2"), _v(40, "retry", "f3")])
    runner.run_once()
    runner.run_once()
    # Versuch 3 verlangt expliziten Strategiewechsel
    out = runner.run_once()
    assert out.get("failed") is True
    assert "STRATEGIE grundlegend" in act_calls[2]["prompt"]
    full = queue.get_task(tid)
    assert full["status"] == "failed"
    assert [o["attempt"] for o in outcomes.for_task(tid)] == [1, 2, 3]
    assert outcomes.last(tid)["strategy"] == "strategiewechsel"
    assert any(e["type"] == "task_failed_final" for e in events.recent(30))
    # Beratender Inbox-Eintrag liegt vor
    assert any("Qualitaet gescheitert" in a["title"] for a in approvals.pending())
    # Planner-Kontext warnt vor Wiederholung
    assert "Endgueltig gescheitert" in runner._context()


def test_disabled_uses_legacy_path(monkeypatch, tmp_path):
    tid, act_calls = _setup(monkeypatch, tmp_path, [])  # verify wuerde StopIteration werfen
    monkeypatch.setitem(CONFIG, "outcomes", {"enabled": False})
    out = runner.run_once()
    assert "result" in out and "score" not in out
    full = queue.get_task(tid)
    assert full["status"] == "done" and full["score"] is None
    assert outcomes.for_task(tid) == []  # kein Scoring gelaufen
    assert act_calls[0]["prompt"] == "Recherchiere Hosting-Anbieter"  # ohne Kriterien-Zusatz


def test_act_exception_marks_failed(monkeypatch, tmp_path):
    tid, _ = _setup(monkeypatch, tmp_path, [])

    def boom(*a, **k):
        raise RuntimeError("act kaputt")

    monkeypatch.setattr(runner, "act", boom)
    out = runner.run_once()
    assert "error" in out
    full = queue.get_task(tid)
    assert full["status"] == "failed"
    assert outcomes.for_task(tid) == []  # kein Outcome-Eintrag, alter Fehlerpfad
