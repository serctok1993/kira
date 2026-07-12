"""W0 Stabilitaets-Triage (12.07.2026): Test-Isolation + absolute Pfade + Verify-Timeout.

Forensik-Befund: L6 (Bot-Crash-Loop) war seit 07.07. durch Absturzbremse+Singleton-Lock
behoben (0 Crashes in 5 Tagen). B5/B6 waren FEHLALARME: die Testsuite selbst schrieb ohne
Sandbox in die LIVE state.db (Events, Fakten, Tuning-Exporte). Diese Tests sind die Waechter,
dass das nie wieder passiert.
"""
from __future__ import annotations

import os
from pathlib import Path


def test_testsuite_hat_wegwerf_datenwurzel():
    # conftest.py setzt KIRA_TEST_DATA_DIR -> DATA_DIR zeigt NIE auf das Live-data/
    # (ausser eine echte Sandbox KIRA_ROOT/KIRA_DATA_DIR ist explizit gesetzt).
    from core import config

    if os.getenv("KIRA_ROOT") or os.getenv("KIRA_DATA_DIR"):
        return  # echte Sandbox (Benchmark) -> Regel gilt dort per Definition
    live = (Path(__file__).resolve().parent.parent / "data").resolve()
    assert config.DATA_DIR != live, "Testsuite zeigt auf die LIVE-Datenwurzel!"
    assert str(config.DB_PATH).startswith(str(config.DATA_DIR))


def test_events_landen_nicht_in_live_db():
    # Ein Event OHNE jedes Monkeypatching muss in der Sandbox landen (genau der Leak,
    # der B5/B6 als Phantom-Bugs in Kiras Backlog erzeugte).
    from core import config
    from core.kernel import events

    if os.getenv("KIRA_ROOT") or os.getenv("KIRA_DATA_DIR"):
        return
    assert str(events.DB_PATH).startswith(str(config.DATA_DIR))
    events.init_db()
    events.emit("w0_isolations_probe", {"quelle": "test"})
    assert any(e["type"] == "w0_isolations_probe" for e in events.recent(5))


def test_suppress_repo_writes_bleibt_aktiv():
    # Die Auto-Sandbox darf die Repo-Schutz-Semantik NICHT kippen: KIRA_TEST_DATA_DIR
    # ist bewusst KEIN sandbox_active() -> Git-/Verify-Pfade bleiben in Tests No-Ops.
    from core import config

    if os.getenv("KIRA_ROOT") or os.getenv("KIRA_DATA_DIR"):
        return
    assert config.test_mode() is True
    assert config.sandbox_active() is False
    assert config.suppress_repo_writes() is True


def test_mcp_config_pfad_ist_absolut():
    from core.agency.mcp import registry_bridge as rb

    assert rb._CONFIG_PATH.is_absolute()
    # und haengt an DATA_DIR -> Test-Sandbox + CWD-Unabhaengigkeit in einem
    from core import config

    assert str(rb._CONFIG_PATH).startswith(str(config.DATA_DIR))


def test_verify_timeout_deckt_die_suite():
    # B4: Suite ~350s, alter Deckel 300s -> gute Edits wurden zurueckgerollt.
    import inspect

    from core.agency import selfdev

    src = inspect.getsource(selfdev._verify)
    assert "timeout=600" in src
