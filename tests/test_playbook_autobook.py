"""Deterministische Playbook-Reifung (Audit-Fund): das Richter-Urteil wird automatisch
auf gelesene Playbooks gebucht — unabhaengig davon, ob das Modell playbook_result ruft.
"""
from __future__ import annotations

import json


def _setup(monkeypatch, tmp_path):
    from core.kernel import events
    from core import config
    db = str(tmp_path / "state.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(events, "DB_PATH", db)
    events.init_db()
    return events


def _step(events, sid, tool, name):
    events.emit("act_step", {"step": 1, "tool": tool, "args": {"name": name}},
                session_id=sid)


def test_bucht_gelesenes_playbook_mit_richter_urteil(monkeypatch, tmp_path):
    events = _setup(monkeypatch, tmp_path)
    from core.agency.missions import runner
    from core.mind import playbooks
    gebucht = []
    monkeypatch.setattr(playbooks, "record_result",
                        lambda name, erfolg, notiz="": gebucht.append((name, erfolg, notiz)) or {"ok": True})
    _step(events, "mission-m", "playbook_read", "akquise-email")
    runner._book_playbook_results("mission-m", 0.0, erfolg=True, score=88)
    assert gebucht == [("akquise-email", True, "auto: Richter-pass (Score 88)")]


def test_bucht_nicht_doppelt_wenn_modell_selbst_bucht(monkeypatch, tmp_path):
    events = _setup(monkeypatch, tmp_path)
    from core.agency.missions import runner
    from core.mind import playbooks
    gebucht = []
    monkeypatch.setattr(playbooks, "record_result",
                        lambda name, erfolg, notiz="": gebucht.append(name) or {"ok": True})
    _step(events, "mission-m", "playbook_read", "tages-journal")
    _step(events, "mission-m", "playbook_result", "tages-journal")   # Modell hat selbst gebucht
    runner._book_playbook_results("mission-m", 0.0, erfolg=True, score=90)
    assert gebucht == []


def test_fail_bucht_misserfolg_und_fremde_sessions_zaehlen_nicht(monkeypatch, tmp_path):
    events = _setup(monkeypatch, tmp_path)
    from core.agency.missions import runner
    from core.mind import playbooks
    gebucht = []
    monkeypatch.setattr(playbooks, "record_result",
                        lambda name, erfolg, notiz="": gebucht.append((name, erfolg)) or {"ok": True})
    _step(events, "mission-m", "playbook_read", "wochen-verdichtung")
    _step(events, "telegram-1", "playbook_read", "anderes")   # fremde Session -> ignoriert
    runner._book_playbook_results("mission-m", 0.0, erfolg=False, score=30)
    assert gebucht == [("wochen-verdichtung", False)]


def test_raist_nie_bei_kaputter_db(monkeypatch, tmp_path):
    from core.agency.missions import runner
    from core import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "gibt-es-nicht" / "x.db"))
    runner._book_playbook_results("mission-m", 0.0, erfolg=True, score=None)  # darf nicht werfen


def test_verdrahtung_in_pass_und_fail_zweig():
    import inspect
    from core.agency.missions import runner
    src = inspect.getsource(runner._execute_scored)
    assert src.count("_book_playbook_results") == 2  # pass + endgueltiger Fehlschlag