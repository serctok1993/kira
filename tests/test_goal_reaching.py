"""S6.3/W1: Ziel-Mechanik, die BLEIBT — Wochen-Zerlegungs-Parser (planner),
/work @ziel:-Verknuepfung, Arbeits-Buchung. Offline, Temp-DB, Fake-LLM.
(Der Business-Grind — pick_objective/Decompose/Stall — ist in W1 ausgebaut.)"""
from __future__ import annotations

import datetime

from core.agency.missions import objectives, planner, queue
from core.kernel import events, llm_router


def _d(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def _iso(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (objectives, queue, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    objectives.init_objectives()
    return db


# --- Wochen-Zerlegung: robustes Parsen (planner bleibt — generische Mechanik) --------

def _fake_llm(text: str):
    def fake(messages, system=None, task_type=None, escalate=False, **kw):
        return {"text": text, "cost_usd": 0.0, "model": "fake", "fell_back": False,
                "latency_s": 0.1, "escalated": False, "tool_calls": None}
    return fake


def test_propose_weekly_parses_only_valid_lines(monkeypatch):
    parent = {"title": "Buch schreiben", "kind": "big", "target_date": _d(60), "notes": ""}
    raw = "\n".join([
        f"- Kapitel 1 gliedern und Rohtext schreiben | {_d(7)}",
        "- Zeile ohne Datum",
        f"- Kaputtes Datum | 2026-13-45",
        f"- Nach dem Elternziel | {_d(90)}",          # nach target_date -> raus
        f"1) Kapitel 2 recherchieren | {_d(14)}",
        "kompletter Unsinn",
    ])
    monkeypatch.setattr(llm_router, "complete", _fake_llm(raw))
    out = planner.propose_weekly_objectives(parent, "(kein Kontext)")
    assert [w["title"] for w in out] == ["Kapitel 1 gliedern und Rohtext schreiben",
                                         "Kapitel 2 recherchieren"]
    assert out[0]["target_date"] == _d(7)


def test_propose_weekly_without_parent_date(monkeypatch):
    parent = {"title": "Reichweite aufbauen", "kind": "monthly", "target_date": None}
    monkeypatch.setattr(llm_router, "complete", _fake_llm(f"- Profil aufsetzen | {_d(5)}"))
    out = planner.propose_weekly_objectives(parent, "")
    assert len(out) == 1


# --- /work @ziel:-Token --------------------------------------------------------------

def test_resolve_objective_token(monkeypatch, tmp_path):
    from core.agency import act

    _iso(monkeypatch, tmp_path)
    qs = objectives.add("Projekt Kundenwebsite SEO", kind="weekly")
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

    oid = objectives.add("Kundenwebsite SEO", kind="weekly")
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
