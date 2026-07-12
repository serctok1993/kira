"""S8.0: Reparatur — atomare Sidecar-Writes, defensiver MCP-Status, Telegram-Backoff.

Hintergrund: data/mcp_servers.json war transient korrupt ('Expecting value: line 1
column 1'); der Telegram-Loop retryte Fehler ohne Pause (Hammer-Loop + Event-Spam).
"""
from __future__ import annotations

import json
import os

from core.kernel.fs import atomic_write


# --- atomic_write ------------------------------------------------------------------

def test_atomic_write_roundtrip_and_no_temp_leftovers(tmp_path):
    p = tmp_path / "sidecar.json"
    atomic_write(p, json.dumps({"a": 1}))
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    atomic_write(p, json.dumps({"a": 2}))  # Ueberschreiben ist genauso atomar
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2}
    assert [f.name for f in tmp_path.iterdir()] == ["sidecar.json"]  # keine .tmp-Leichen


def test_atomic_write_creates_parents(tmp_path):
    p = tmp_path / "tief" / "verschachtelt" / "x.json"
    atomic_write(p, "{}")
    assert p.exists()


def test_atomic_write_failure_leaves_target_intact(tmp_path, monkeypatch):
    """Simulierter Crash beim replace: die Zieldatei bleibt unversehrt (DER Kern von S8.0)."""
    p = tmp_path / "wichtig.json"
    atomic_write(p, '{"heil": true}')

    def boom(src, dst):
        raise OSError("simulierter Crash")

    monkeypatch.setattr(os, "replace", boom)
    try:
        atomic_write(p, '{"kaputt": true}')
    except OSError:
        pass
    assert json.loads(p.read_text(encoding="utf-8")) == {"heil": True}
    assert [f.name for f in tmp_path.iterdir()] == ["wichtig.json"]  # Temp aufgeraeumt


def test_sidecar_writers_use_atomic_write():
    """Regressionswache: die JSON-Sidecar-Writer laufen ueber atomic_write, nicht write_text."""
    import inspect

    from core.agency.connectors import news_monitor
    from core.agency.missions import cron, maintenance, triggers
    from core.governance import autonomy, secrets
    from core.kernel import models

    for mod, fn in ((triggers, triggers._save), (cron, cron._save),
                    (news_monitor, news_monitor._save), (secrets, secrets._save),
                    (models, models._save)):
        src = inspect.getsource(fn)
        assert "atomic_write" in src, f"{mod.__name__}._save schreibt nicht atomar"
    assert "atomic_write" in inspect.getsource(maintenance.maybe_run)
    assert "atomic_write" in inspect.getsource(autonomy.set_config)


# --- MCP server_status defensiv -----------------------------------------------------

def test_server_status_survives_corrupt_config(monkeypatch, tmp_path):
    """Korrupte mcp_servers.json darf nie mehr bis in die API werfen."""
    from core.agency.mcp import registry_bridge as rb
    from core.kernel import events

    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    bad = tmp_path / "mcp_servers.json"
    bad.write_text("", encoding="utf-8")  # exakt der Live-Fall: leere Datei
    # W0: server_status liest jetzt den absoluten Modul-Pfad _CONFIG_PATH -> direkt patchen
    monkeypatch.setattr(rb, "_CONFIG_PATH", bad)
    assert rb.server_status() == {}  # sauber leer statt 'Expecting value'-Crash


# --- Telegram-Backoff + Buendelung ---------------------------------------------------

def test_backoff_doubles_and_caps():
    from core.agency.connectors import telegram_bot as tb

    assert tb._backoff_next(2.0) == 4.0
    assert tb._backoff_next(4.0) == 8.0
    assert tb._backoff_next(50.0) == 60.0
    assert tb._backoff_next(60.0) == 60.0
    assert tb._backoff_next(0.0) == 4.0  # nie unter die Basis rutschen


def test_bundle_emits_first_error_then_summary(monkeypatch):
    from core.agency.connectors import telegram_bot as tb

    t = {"now": 1000.0}
    monkeypatch.setattr(tb.time, "time", lambda: t["now"])
    state: dict = {}

    first = tb._bundle(state, "ConnectError: kein Netz")
    assert first and first["type"] == "telegram_loop_error"
    for _ in range(11):  # 11 weitere Fehler -> KEIN weiteres Event
        assert tb._bundle(state, "ConnectError: kein Netz") is None

    t["now"] = 1600.0  # 10 Minuten spaeter: Erholung
    rec = tb._bundle(state, None)
    assert rec and rec["type"] == "telegram_loop_recovered"
    assert rec["count"] == 12 and rec["seconds"] == 600
    assert tb._bundle(state, None) is None  # ohne Serie kein Event
