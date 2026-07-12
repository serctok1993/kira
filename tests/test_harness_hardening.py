"""Harness-Haertung (Schritt 3): Runner-Watchdog (time-boxed Tick) + DB busy_timeout.

Ziel: haengt EIN act-Lauf, friert der 24/7-Loop (Cron/Monitor/Trigger) NICHT mehr ein;
und Heartbeat + Chat kollidieren nicht mehr an der SQLite-Schreibsperre.
"""
from __future__ import annotations

import time


def _tmp_events(monkeypatch, tmp_path):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    return events


# ---- DB busy_timeout auf den heissen Verbindungen -------------------------------------

def test_busy_timeout_auf_allen_verbindungen(monkeypatch, tmp_path):
    """Alle _conn-Helfer warten unter Nebenlaeufigkeit bis 5s statt sofort zu locken —
    so kollidieren Heartbeat + Chat nirgends mehr an der SQLite-Schreibsperre."""
    from core.kernel import events
    from core.mind import knowledge
    from core.mind.memory import store
    from core.agency import outcomes, approvals, insights
    from core.agency.missions import queue, metrics, objectives
    db = str(tmp_path / "state.db")
    mods = (events, store, queue, knowledge, outcomes,
            approvals, insights, metrics, objectives)
    for mod in mods:
        monkeypatch.setattr(mod, "DB_PATH", db)
    for mod in mods:
        c = mod._conn()
        try:
            assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000, mod.__name__
        finally:
            c.close()


# ---- Runner: time-boxed Tick ----------------------------------------------------------

def test_tick_timeout_aus_config():
    from core.agency.missions import runner
    assert isinstance(runner._tick_timeout(), int)


def test_timeboxed_schneller_tick_liefert_ergebnis(monkeypatch):
    from core.agency.missions import runner
    monkeypatch.setattr(runner, "_tick_timeout", lambda: 5)
    monkeypatch.setattr(runner, "run_once", lambda: {"ok": True})
    monkeypatch.setattr(runner, "_tick_thread", None, raising=False)
    assert runner._run_tick_timeboxed() == {"ok": True}


def test_timeboxed_haengender_tick_gibt_none_und_meldet(monkeypatch, tmp_path):
    events = _tmp_events(monkeypatch, tmp_path)
    from core.agency.missions import runner
    monkeypatch.setattr(runner, "_tick_timeout", lambda: 0.3)
    monkeypatch.setattr(runner, "_tick_thread", None, raising=False)

    def _slow():
        time.sleep(2.0)  # haengt laenger als die Deadline
        return {"late": True}

    monkeypatch.setattr(runner, "run_once", _slow)
    # Loop bleibt lebendig: Rueckgabe None statt blockierendem Warten
    assert runner._run_tick_timeboxed() is None
    assert "heartbeat_tick_timeout" in [e["type"] for e in events.recent(20)]


def test_timeboxed_disabled_blockiert_wie_frueher(monkeypatch):
    from core.agency.missions import runner
    monkeypatch.setattr(runner, "_tick_timeout", lambda: 0)  # Watchdog aus
    monkeypatch.setattr(runner, "run_once", lambda: {"blocking": True})
    monkeypatch.setattr(runner, "_tick_thread", None, raising=False)
    assert runner._run_tick_timeboxed() == {"blocking": True}
