"""S8.1: Re-Zentrierung — Assistenz>Selbst>Geld, Selbst-Tick-Rhythmus, Melde-Regeln,
entschaerfter Venture-Prompt, Evolution-Endpoint. Offline, Temp-DB/-State."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.mind import agent


# --- Persona & Mission: Zweck-Hierarchie + Melde-Regeln ----------------------------

def test_persona_has_purpose_hierarchy_and_reporting_rules():
    p = agent.PERSONA_DIRECTIVE
    assert "Sergen dienen" in p and "Dich verbessern" in p
    assert "Geld ist NUR Mittel" in p  # Geld entwertet
    assert "SOFORT und ehrlich" in p and "ohne Beleg" in p  # Melde-Regeln
    assert "project_note" in p  # Projekt-Daueranweisungen


def test_mission_goal_reordered():
    from core.config import CONFIG

    m = CONFIG.get("mission", {})
    assert m.get("self_every") == 3
    g = m.get("goal", "")
    assert "SERGEN DIENEN" in g and "DICH VERBESSERN" in g
    # Assistenz steht VOR Projekten
    assert g.index("SERGEN DIENEN") < g.index("GENEHMIGTE PROJEKTE")
    assert "Kasse/Meilenstein/ROI" in g  # explizit verboten


# --- Selbst-Tick-Rhythmus (jeder N-te Tick) ----------------------------------------

def _iso_runner(monkeypatch, tmp_path):
    from core.agency import outcomes
    from core.agency.missions import objectives, queue
    from core.governance import treasury
    from core.kernel import events

    db = str(tmp_path / "state.db")
    for mod in (queue, objectives, outcomes, events, treasury):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    return db


def test_self_tick_every_third(monkeypatch, tmp_path):
    from core.agency.missions import maintenance, runner
    from core.config import CONFIG

    _iso_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "m", "goal": "G", "self_every": 3,
                                            "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_focus", lambda: "")

    calls = {"self": 0, "normal": 0}
    monkeypatch.setattr(runner, "_self_improve_tick",
                        lambda mission, esc: calls.__setitem__("self", calls["self"] + 1) or {"self_tick": True})
    # kein aktives Ziel -> normaler Pfad endet idle; wir zaehlen nur, welcher Zweig lief
    monkeypatch.setattr(runner.planner, "generate_tasks", lambda *a, **k: [])

    kinds = []
    for _ in range(6):
        out = runner.run_once()
        kinds.append("self" if out.get("self_tick") else "normal")
    # Tick 3 und 6 sind Selbst-Ticks
    assert kinds == ["normal", "normal", "self", "normal", "normal", "self"]
    assert calls["self"] == 2


def test_self_tick_skipped_when_focus_set(monkeypatch, tmp_path):
    from core.agency.missions import maintenance, runner
    from core.config import CONFIG

    _iso_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "m", "goal": "G", "self_every": 2,
                                            "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_focus", lambda: "Mach das Kundenprojekt fertig")  # Sergen-Fokus
    monkeypatch.setattr(runner, "_self_improve_tick", lambda *a: {"self_tick": True})
    monkeypatch.setattr(runner.planner, "generate_tasks", lambda *a, **k: [])

    for _ in range(4):
        assert runner.run_once().get("self_tick") is not True  # Fokus schlaegt Selbst-Tick


def test_bump_counter_persists(monkeypatch, tmp_path):
    from core.agency.missions import maintenance

    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    assert [maintenance.bump_counter("x") for _ in range(3)] == [1, 2, 3]
    assert maintenance.bump_counter("y") == 1  # unabhaengiger Zaehler


# --- Venture-Prompt entschaerft (kein Kasse/Meilenstein) ---------------------------

def test_venture_prompt_has_no_money_framing(monkeypatch, tmp_path):
    from core.agency import outcomes, ventures
    from core.agency.missions import objectives, runner
    from core.config import CONFIG
    from core.governance import treasury

    db = _iso_runner(monkeypatch, tmp_path)
    for mod in (ventures,):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(treasury, "DB_PATH", db)
    monkeypatch.setitem(CONFIG, "mission", {"name": "m", "goal": "G", "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_focus", lambda: "")

    objectives.init_objectives()
    ventures.init_ventures()
    vid = ventures.add("Kaltakquise", hypothesis="KMU zahlen fuer Sichtbarkeit", milestone_eur=2000)
    objectives.add("Erste 20 Leads", kind="weekly", venture_id=vid)

    captured = {}
    monkeypatch.setattr(runner.planner, "generate_tasks",
                        lambda goal, ctx, **k: captured.setdefault("g", goal) or [])
    runner.run_once()
    g = captured.get("g", "")
    assert "PROJEKT: Kaltakquise" in g
    assert "Kasse" not in g and "Meilenstein" not in g and "ROI" not in g


# --- /api/evolution ----------------------------------------------------------------

def test_evolution_endpoint_shape():
    d = TestClient(s.app).get("/api/evolution").json()
    assert set(d) >= {"timeline", "skills", "lessons"}
    assert isinstance(d["timeline"], list)


# --- Radar entschaerft --------------------------------------------------------------

def test_radar_prompt_is_experimental():
    import inspect

    from core.agency import radar

    src = inspect.getsource(radar)
    assert "EXPERIMENTE" in src
    assert "Verfassung bleibt bindend" in src
    assert "Einkommens-Chancen" not in src  # alte reine Umsatz-Jagd raus
