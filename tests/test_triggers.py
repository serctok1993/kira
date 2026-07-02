"""S4.3: Proaktive Trigger — Event -> Aufgabe, Cooldown, Schleifen-Schutz. Offline."""
from __future__ import annotations

import time

from core.agency.missions import queue, triggers
from core.config import CONFIG
from core.kernel import events


def _setup(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (queue, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(triggers, "_PATH", tmp_path / "triggers.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "testmission"})
    events.init_db()
    queue.init_queue()
    triggers.check()  # erster Lauf: nur Basislinie setzen (ID-Dedupe macht das racefrei)


def test_add_list_remove_roundtrip(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    tid = triggers.add("Einnahmen-Reflex", "stripe_income", "Pruefe Skalierung")
    assert len(triggers.list_all()) == 1
    assert triggers.remove(tid[:8])  # Kurzform reicht
    assert triggers.list_all() == []


def test_event_creates_task(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    triggers.add("Einnahmen-Reflex", "stripe_income", "Pruefe, ob das Venture skaliert werden kann")
    events.emit("stripe_income", {"booked": 1, "total_eur": 49.0})

    fired = triggers.check()
    assert len(fired) == 1
    pend = queue.pending("testmission")
    assert len(pend) == 1
    assert "Trigger 'Einnahmen-Reflex'" in pend[0]["description"]
    assert pend[0]["priority"] == 3  # vor Planner-Tasks (5)
    assert any(e["type"] == "trigger_fired" for e in events.recent(10))


def test_baseline_ignores_old_history(monkeypatch, tmp_path):
    """Alt-Events VOR dem ersten Check duerfen nie nachfeuern."""
    db = str(tmp_path / "state.db")
    for mod in (queue, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(triggers, "_PATH", tmp_path / "triggers.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "testmission"})
    events.init_db()
    queue.init_queue()
    events.emit("stripe_income", {"total_eur": 999.0})  # Alt-Event
    triggers.add("Reflex", "stripe_income", "egal")
    assert triggers.check() == []  # erster Lauf = Basislinie, kein Nachfeuern
    assert queue.pending("testmission") == []


def test_contains_filter(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    triggers.add("Nur-GitHub", "mcp_server_died", "Diagnostiziere GitHub-MCP", contains="github")
    events.emit("mcp_server_died", {"server": "supabase"})
    assert triggers.check() == []  # falscher Server -> kein Match
    events.emit("mcp_server_died", {"server": "github"})
    assert len(triggers.check()) == 1


def test_cooldown_blocks_repeat(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    triggers.add("Reflex", "stripe_income", "Pruefe X", cooldown_s=3600)
    events.emit("stripe_income", {"total_eur": 10.0})
    assert len(triggers.check()) == 1
    events.emit("stripe_income", {"total_eur": 20.0})
    assert triggers.check() == []  # Cooldown blockt
    assert len(queue.pending("testmission")) == 1

    # Cooldown abgelaufen -> feuert wieder
    state = triggers._load()
    state["triggers"][0]["last_fired"] = time.time() - 7200
    triggers._save(state)
    events.emit("stripe_income", {"total_eur": 30.0})
    assert len(triggers.check()) == 1


def test_disabled_trigger_silent(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    tid = triggers.add("Aus", "stripe_income", "egal")
    triggers.set_enabled(tid, False)
    events.emit("stripe_income", {})
    assert triggers.check() == []


def test_no_self_triggering_loop(monkeypatch, tmp_path):
    """trigger_fired darf nie selbst triggern — sonst Endlos-Schleife."""
    _setup(monkeypatch, tmp_path)
    triggers.add("Boese Schleife", "trigger_fired", "noch eine Aufgabe", cooldown_s=0)
    triggers.add("Normal", "stripe_income", "Pruefe X", cooldown_s=0)
    events.emit("stripe_income", {})
    fired = triggers.check()
    assert len(fired) == 1  # nur der normale Reflex
    fired = triggers.check()  # das trigger_fired-Event vom letzten Lauf liegt jetzt vor
    assert fired == []       # ... und zuendet NICHT
