"""S6.3: Ziel-Erreichung — Wochen-Zerlegung, Leaf-first-Auswahl, Stall-Erkennung,
/work @ziel:-Verknuepfung. Offline, Temp-DB, Fake-LLM."""
from __future__ import annotations

import datetime
import sqlite3
import time

from core.agency import insights
from core.agency.missions import objectives, planner, queue, runner
from core.kernel import events, llm_router


def _d(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def _iso(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (objectives, queue, events, insights):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    objectives.init_objectives()
    return db


# --- Wochen-Zerlegung: robustes Parsen -------------------------------------------

def _fake_llm(text: str):
    def fake(messages, system=None, task_type=None, escalate=False, **kw):
        return {"text": text, "cost_usd": 0.0, "model": "fake", "fell_back": False,
                "latency_s": 0.1, "escalated": False, "tool_calls": None}
    return fake


def test_propose_weekly_parses_only_valid_lines(monkeypatch):
    parent = {"title": "10k Umsatz", "kind": "big", "target_date": _d(60), "notes": ""}
    raw = "\n".join([
        f"- Erste 20 Leads recherchieren und qualifizieren | {_d(7)}",
        "- Zeile ohne Datum",
        f"- Kaputtes Datum | 2026-13-45",
        f"- Nach dem Elternziel | {_d(90)}",          # nach target_date -> raus
        f"1) Gespraechsleitfaden fuer Top-5-Leads schreiben | {_d(14)}",
        "kompletter Unsinn",
    ])
    monkeypatch.setattr(llm_router, "complete", _fake_llm(raw))
    out = planner.propose_weekly_objectives(parent, "(kein Kontext)")
    assert [w["title"] for w in out] == ["Erste 20 Leads recherchieren und qualifizieren",
                                         "Gespraechsleitfaden fuer Top-5-Leads schreiben"]
    assert out[0]["target_date"] == _d(7)


def test_propose_weekly_without_parent_date(monkeypatch):
    parent = {"title": "Reichweite aufbauen", "kind": "monthly", "target_date": None}
    monkeypatch.setattr(llm_router, "complete", _fake_llm(f"- LinkedIn-Profil aufsetzen | {_d(5)}"))
    out = planner.propose_weekly_objectives(parent, "")
    assert len(out) == 1


# --- Leaf-first-Auswahl ------------------------------------------------------------

def _o(oid, kind, target=None, parent=None, progress=0):
    return {"id": oid, "kind": kind, "target_date": target, "parent_id": parent,
            "progress": progress}


def test_pick_objective_prefers_weekly_leaf():
    big = _o("b1", "big", target=_d(3))          # dringend, aber Eltern mit Kind
    weekly = _o("w1", "weekly", target=_d(10), parent="b1")
    assert runner._pick_objective([big, weekly])["id"] == "w1"


def test_pick_objective_parent_without_children_selectable():
    big = _o("b1", "big", target=_d(3))
    other = _o("w9", "weekly", target=_d(10))    # kein Kind von b1
    # b1 hat KEINE aktiven Kinder -> waehlbar; weekly-Rang gewinnt trotzdem
    assert runner._pick_objective([big, other])["id"] == "w9"
    assert runner._pick_objective([big])["id"] == "b1"


def test_pick_objective_overdue_weekly_first():
    late = _o("w1", "weekly", target=_d(-3))
    soon = _o("w2", "weekly", target=_d(5))
    assert runner._pick_objective([soon, late])["id"] == "w1"


# --- Dekomposition im run_once-Planungszweig ---------------------------------------

def test_run_once_decomposes_big_objective(monkeypatch, tmp_path):
    from core.agency import outcomes
    from core.agency.missions import maintenance
    from core.config import CONFIG
    from core.governance import treasury

    db = _iso(monkeypatch, tmp_path)
    for mod in (outcomes, treasury):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "testmission", "goal": "Testziel",
                                            "notify_telegram": False})
    # S12: Business-Grind haengt am Feature-Flag — hier wird die Zerlegung selbst getestet
    monkeypatch.setitem(CONFIG["features"], "business", True)
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)

    big_id = objectives.add("10k Umsatz", kind="big", target_date=_d(60))
    calls = {"propose": 0}

    def fake_propose(parent, context, n=3, escalate=False):
        calls["propose"] += 1
        return [{"title": "Woche 1: Leads finden", "target_date": _d(7)},
                {"title": "Woche 2: Leitfaeden", "target_date": _d(14)}]

    monkeypatch.setattr(runner.planner, "propose_weekly_objectives", fake_propose)
    monkeypatch.setattr(runner.planner, "generate_tasks",
                        lambda *a, **k: [])  # nichts einplanen -> Tick endet idle

    out = runner.run_once()
    assert out.get("idle") is True
    kids = objectives.children(big_id)
    assert len(kids) == 2 and all(k["kind"] == "weekly" for k in kids)
    assert any(e["type"] == "objective_decomposed" for e in events.recent(20))

    # Zweiter Tick: Kinder existieren -> keine erneute Zerlegung (Gate + children-Check)
    runner.run_once()
    assert calls["propose"] == 1


# --- Stall-Erkennung ----------------------------------------------------------------

def _age_objective(db: str, oid: str, days: int) -> None:
    with sqlite3.connect(db) as c:
        c.execute("UPDATE objectives SET ts=? WHERE id=?", (time.time() - days * 86400, oid))


def test_stalled_objectives_detects_idle_goal(monkeypatch, tmp_path):
    db = _iso(monkeypatch, tmp_path)
    oid = objectives.add("Zaehes Ziel", kind="weekly")
    _age_objective(db, oid, days=10)

    stalled = insights.stalled_objectives(days=5)
    assert [o["id"] for o in stalled] == [oid]
    assert stalled[0]["idle_days"] >= 5


def test_stalled_objectives_ignores_active_and_young(monkeypatch, tmp_path):
    db = _iso(monkeypatch, tmp_path)
    young = objectives.add("Frisches Ziel", kind="weekly")          # zu jung
    busy = objectives.add("Aktives Ziel", kind="weekly")
    _age_objective(db, busy, days=10)
    tid = queue.add("Arbeit", mission="m", objective_id=busy)
    queue.complete(tid, "erledigt")                                  # juengst erledigter Task

    assert insights.stalled_objectives(days=5) == []
    assert young and busy  # (nur Lesbarkeit)


# --- /work @ziel:-Token --------------------------------------------------------------

def test_resolve_objective_token(monkeypatch, tmp_path):
    from core.agency import act

    _iso(monkeypatch, tmp_path)
    qs = objectives.add("Projekt QS-Transporte SEO", kind="weekly")
    objectives.add("Projekt Playbook schreiben", kind="weekly")

    text, oid = act._resolve_objective_token(f"Baue die Sitemap @ziel:{qs[:8]} fertig")
    assert oid == qs and "@ziel:" not in text and "Baue die Sitemap" in text

    text, oid = act._resolve_objective_token("Schreib Kapitel 1 @ziel:playbook")
    assert oid and "@ziel:" not in text

    # mehrdeutig -> None. Token bewusst NICHT-hex ('projekt' trifft beide Titel,
    # kann aber nie eine uuid-hex-ID praefixen — sonst flakt der Test ~12%/Lauf)
    _, oid = act._resolve_objective_token("Irgendwas @ziel:projekt")
    assert oid is None

    text, oid = act._resolve_objective_token("ohne Token")
    assert oid is None and text == "ohne Token"


def test_book_work_result_moves_progress(monkeypatch, tmp_path):
    from core.agency import act
    from core.config import CONFIG

    _iso(monkeypatch, tmp_path)
    monkeypatch.setitem(CONFIG, "mission", {"name": "testmission"})
    import core.agency.missions.workingset as ws
    appended = []
    monkeypatch.setattr(ws, "append", lambda oid, line: appended.append((oid, line)))

    oid = objectives.add("QS-Transporte SEO", kind="weekly")
    act._book_work_result(oid, "Sitemap bauen", "Sitemap fertig: 12 Seiten\nDetails...")

    tasks = [t for t in queue.all_tasks("testmission") if t["objective_id"] == oid]
    assert len(tasks) == 1 and tasks[0]["status"] == "done"
    obj = [o for o in objectives.list_all() if o["id"] == oid][0]
    assert obj["tasks_done"] == 1 and obj["progress"] == 100
    assert appended and appended[0][0] == oid and "[chat]" in appended[0][1]
    assert any(e["type"] == "work_booked" for e in events.recent(10))


def test_book_work_result_noop_without_objective(monkeypatch, tmp_path):
    from core.agency import act

    _iso(monkeypatch, tmp_path)
    act._book_work_result(None, "egal", "egal")
    assert queue.all_tasks() == []
