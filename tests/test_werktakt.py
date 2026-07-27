"""Werktakt (des Nutzers Regel 08.07.): max. N erledigte Schritte pro Ziel und Tag —
dosierte Fallstudien statt 4-6 am Tag, Rest rueckt auf morgen."""
from __future__ import annotations

import datetime as dt
import time

from core.agency.missions import queue, runner
from core.kernel import events


def _setup(monkeypatch, tmp_path, cap=2):
    db = str(tmp_path / "state.db")
    monkeypatch.setattr(queue, "DB_PATH", db, raising=False)
    import core.config as _c
    monkeypatch.setattr(_c, "DB_PATH", db)
    monkeypatch.setattr(events, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    monkeypatch.setattr(runner, "_mission",
                        lambda: {"name": "m", "steps_per_objective_daily": cap})


def test_done_today_zaehlt_nur_heute_und_dieses_ziel(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    t1 = queue.add("A", mission="m", objective_id="ziel1")
    t2 = queue.add("B", mission="m", objective_id="ziel1")
    t3 = queue.add("C", mission="m", objective_id="ziel2")
    queue.complete(t1, "ok")
    queue.complete(t3, "ok")
    assert queue.done_today("ziel1") == 1
    assert queue.done_today("ziel2") == 1
    # gestern erledigt -> zaehlt nicht
    queue.complete(t2, "ok")
    gestern = time.time() - 86400
    queue.update_task(t2, status="done")  # updated_ts frisch; jetzt hart zurueckdatieren
    import sqlite3
    con = sqlite3.connect(str(tmp_path / "state.db"))
    con.execute("UPDATE tasks SET updated_ts=? WHERE id=?", (gestern, t2))
    con.commit()
    con.close()
    assert queue.done_today("ziel1") == 1


def test_pop_paced_verschiebt_volles_ziel(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, cap=2)
    for i in range(2):  # Tagespensum von ziel1 ist schon voll
        tid = queue.add(f"fertig{i}", mission="m", objective_id="ziel1")
        queue.complete(tid, "ok")
    queue.add("Fallstudie 5 analysieren", mission="m", objective_id="ziel1", priority=1)
    queue.add("Anderes Ziel: Preise checken", mission="m", objective_id="ziel2", priority=2)

    task = runner._pop_paced("m")
    assert task and "Anderes Ziel" in task["description"]   # ziel1 pausiert, ziel2 kommt dran
    morgen = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    verschoben = [t for t in queue.all_tasks("m") if t["description"].startswith("Fallstudie")][0]
    assert verschoben["status"] == "pending" and verschoben["deferred_until"] == morgen
    assert any(e["type"] == "objective_paced" for e in events.recent(10))


def test_pop_paced_ohne_cap_und_unter_pensum(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, cap=0)                    # 0 = aus
    queue.add("X", mission="m", objective_id="ziel1")
    assert runner._pop_paced("m")["description"] == "X"

    monkeypatch.setattr(runner, "_mission",                 # unter Pensum -> laeuft
                        lambda: {"name": "m", "steps_per_objective_daily": 3})
    queue.add("Y", mission="m", objective_id="ziel1")
    assert runner._pop_paced("m")["description"] == "Y"


def test_pop_paced_alle_voll_ergibt_none(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, cap=1)
    tid = queue.add("fertig", mission="m", objective_id="ziel1")
    queue.complete(tid, "ok")
    queue.add("mehr davon", mission="m", objective_id="ziel1")
    assert runner._pop_paced("m") is None                   # heute nichts mehr -> Tick idle


def test_pop_paced_task_ohne_ziel_laeuft_immer(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, cap=1)
    queue.add("freier Task", mission="m")
    assert runner._pop_paced("m")["description"] == "freier Task"


def test_planner_prompt_hat_recherche_disziplin(monkeypatch):
    from core.agency.missions import planner
    seen = {}

    def fake_complete(messages, system=None, task_type=None, escalate=False, **k):
        seen["user"] = messages[0]["content"]
        return {"text": "- Aufgabe eins"}

    monkeypatch.setattr(planner.llm_router, "complete", fake_complete)
    tasks = planner.generate_tasks("Ziel", "Kontext")
    assert tasks == ["Aufgabe eins"]
    # Die Disziplin-Regel bleibt, ihre Ueberschrift nicht: die Grossbuchstaben-Zeile
    # "RECHERCHE-DISZIPLIN" und das Beispiel "Micro-SaaS X" haben das schwache
    # Planer-Modell auf Marktforschung gelenkt (Live-Befund 27.07.).
    assert "Klasse statt Masse" in seen["user"]
    assert "hoechstens EINE pro Planung" in seen["user"]
    assert "direkten Empfehlung" in seen["user"]
    assert "Micro-SaaS" not in seen["user"]


def test_werktakt_default():
    assert runner._werktakt() >= 0                          # liest config, raist nie
