"""S6.2: Lern-Schleife geschlossen — insights liest den Outcome-Ledger zurueck,
Planner bekommt Budget+Erkenntnisse, Treasury summiert per SQL. Offline, Temp-DB."""
from __future__ import annotations

import time

from core.agency import insights, outcomes
from core.agency.missions import planner, queue
from core.governance import treasury
from core.kernel import events, llm_router
from core.mind.memory import store as memory


def _iso(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (insights, outcomes, queue, events, treasury):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    outcomes.init_outcomes()
    return db


def _seed(kind: str, n_pass: int, n_fail: int, feedback: str = "Quellen fehlen, konkrete Zahlen noetig",
          cost: float = 0.1, strategy: str = "standard") -> list[str]:
    ids = []
    for i in range(n_pass + n_fail):
        tid = queue.add(f"Task {kind} {i}", mission="m", kind=kind)
        ok = i < n_pass
        outcomes.record(tid, 1, [], [], 80 if ok else 40, "pass" if ok else "fail",
                        feedback="" if ok else feedback, strategy=strategy, cost_usd=cost)
        ids.append(tid)
    return ids


# --- Aggregation -----------------------------------------------------------------

def test_fail_patterns_aggregates_by_kind(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    _seed("produce", n_pass=2, n_fail=6)
    _seed("research", n_pass=4, n_fail=0)

    pat = insights.fail_patterns(days=14)
    assert pat["attempts"] == 12
    worst = pat["by_kind"][0]  # schwaechste zuerst
    assert worst["key"] == "produce"
    assert worst["passed"] == 2 and worst["attempts"] == 8
    assert worst["pass_rate"] == 0.25
    assert worst["cost_per_success"] == round(8 * 0.1 / 2, 4)
    assert "quellen" in pat["themes"]  # wiederkehrende Pruefer-Kritik


def test_render_brief_and_empty(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    assert insights.render_brief() == ""  # ohne Daten: kein Block
    _seed("produce", n_pass=1, n_fail=5)
    brief = insights.render_brief()
    assert brief.startswith("ERKENNTNISSE")
    assert "produce" in brief and "Pass-Rate" in brief
    assert len(brief) <= 900


def test_weekly_lessons_stored(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    stored = []
    monkeypatch.setattr(memory, "remember",
                        lambda text, role="user", kind="episodic", **kw: stored.append((kind, text)))
    _seed("produce", n_pass=1, n_fail=5)
    lessons = insights.weekly_lessons(days=7)
    assert 1 <= len(lessons) <= 3
    assert all(k == "lesson" for k, _ in stored)
    assert any("produce" in t for _, t in stored)
    assert any(e["type"] == "insights_weekly" for e in events.recent(10))


def test_weekly_lessons_empty_ledger_is_silent(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    stored = []
    monkeypatch.setattr(memory, "remember", lambda *a, **k: stored.append(a))
    assert insights.weekly_lessons() == [] and stored == []


# --- Planner: Budget + Erkenntnisse im Prompt --------------------------------------

_FAKE_RES = {"text": "- Aufgabe eins\n- Aufgabe zwei", "cost_usd": 0.0, "model": "fake",
             "fell_back": False, "latency_s": 0.1, "escalated": False, "tool_calls": None}


def test_planner_prompt_gets_budget_and_insights(monkeypatch):
    prompts = []

    def fake(messages, system=None, task_type=None, escalate=False, **kw):
        prompts.append(messages[0]["content"])
        return dict(_FAKE_RES)

    monkeypatch.setattr(llm_router, "complete", fake)
    tasks = planner.generate_tasks(
        "Ziel", "Kontext",
        budget={"day_limit": 20.0, "day_remaining": 2.0, "month_remaining": 100.0},
        insights="ERKENNTNISSE AUS BISHERIGEN ERGEBNISSEN: Task-Art produce scheitert oft")
    assert tasks == ["Aufgabe eins", "Aufgabe zwei"]
    p = prompts[0]
    # S8.1: KEINE Budget-Kalkulation im Prompt mehr — nur die Schutz-Warnung bei knapp.
    assert "BUDGET: heute noch" not in p
    assert "Tagesbudget fast erschoepft" in p  # 2.0 < 20% von 20
    assert "ERKENNTNISSE" in p


def test_planner_backward_compatible(monkeypatch):
    prompts = []

    def fake(messages, system=None, task_type=None, escalate=False, **kw):
        prompts.append(messages[0]["content"])
        return dict(_FAKE_RES)

    monkeypatch.setattr(llm_router, "complete", fake)
    planner.generate_tasks("Ziel", "Kontext")  # alte Signatur ohne kwargs
    assert "Tagesbudget" not in prompts[0] and "ERKENNTNISSE" not in prompts[0]


def test_planner_no_warning_when_budget_comfortable(monkeypatch):
    prompts = []

    def fake(messages, system=None, task_type=None, escalate=False, **kw):
        prompts.append(messages[0]["content"])
        return dict(_FAKE_RES)

    monkeypatch.setattr(llm_router, "complete", fake)
    planner.generate_tasks("Ziel", "Kontext",
                           budget={"day_limit": 20.0, "day_remaining": 15.0, "month_remaining": 100.0})
    # S8.1: komfortables Budget -> gar keine Budget-Zeile (Sergen kalkuliert, nicht Kira)
    assert "Tagesbudget" not in prompts[0]
    assert "erschoepft" not in prompts[0]


# --- Runner-Verdrahtung -------------------------------------------------------------

def test_runner_passes_insights_and_budget_to_planner(monkeypatch, tmp_path):
    from core.agency.missions import objectives, runner
    from core.config import CONFIG

    db = _iso(monkeypatch, tmp_path)
    monkeypatch.setattr(objectives, "DB_PATH", db)
    monkeypatch.setitem(CONFIG, "mission", {"name": "testmission", "goal": "Testziel",
                                            "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    _seed("produce", n_pass=1, n_fail=5)  # Ledger-Futter fuer den Brief

    captured = {}

    def fake_gen(goal, context, n=3, escalate=False, budget=None, insights=None):
        captured.update({"budget": budget, "insights": insights})
        return []  # nichts einplanen -> run_once endet idle

    monkeypatch.setattr(runner.planner, "generate_tasks", fake_gen)
    out = runner.run_once()
    assert out.get("idle") is True
    assert isinstance(captured["budget"], dict) and "day_limit" in captured["budget"]
    assert captured["insights"] and captured["insights"].startswith("ERKENNTNISSE")


# --- Treasury: SQL-Summe statt recent(5000)-Fenster ---------------------------------

def test_treasury_sums_all_events_since(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    events.emit("llm_call", {"cost_usd": 0.5, "model": "x"})
    events.emit("llm_call", {"cost_usd": 0.25, "model": "x"})
    events.emit("spend", {"amount": 2.0, "reason": "Domain"})
    events.emit("mission_task_done", {"id": "egal"})  # zaehlt nicht

    assert treasury._spent_since(0.0) == 2.75
    assert treasury._spent_since(time.time() + 100) == 0.0


def test_treasury_ignores_null_costs(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    events.emit("llm_call", {"model": "lokal"})  # kein cost_usd-Feld
    events.emit("spend", {"reason": "ohne Betrag"})
    assert treasury._spent_since(0.0) == 0.0
