"""Stufe 2d: Wartungs-Gate — feuert 1x pro Intervall, persistiert ueber Neustarts."""
from __future__ import annotations

import json
import time

from core.agency.missions import maintenance


def _use_tmp_state(monkeypatch, tmp_path):
    p = tmp_path / "maintenance.json"
    monkeypatch.setattr(maintenance, "_STATE_PATH", p)
    return p


def test_fires_once_per_interval(monkeypatch, tmp_path):
    _use_tmp_state(monkeypatch, tmp_path)
    assert maintenance.maybe_run("curate_skills") is True
    assert maintenance.maybe_run("curate_skills") is False  # gleicher Tag -> gesperrt


def test_persists_across_restart(monkeypatch, tmp_path):
    p = _use_tmp_state(monkeypatch, tmp_path)
    assert maintenance.maybe_run("curate_skills") is True
    # "Neustart": Zustand liegt in der Datei, nicht im Prozess
    assert json.loads(p.read_text(encoding="utf-8"))["curate_skills"] > 0
    assert maintenance.maybe_run("curate_skills") is False


def test_fires_again_after_interval(monkeypatch, tmp_path):
    p = _use_tmp_state(monkeypatch, tmp_path)
    assert maintenance.maybe_run("curate_skills") is True
    # Uhr zuruckdrehen: letzter Lauf war vor > 1 Tag
    state = json.loads(p.read_text(encoding="utf-8"))
    state["curate_skills"] = time.time() - 90000
    p.write_text(json.dumps(state), encoding="utf-8")
    assert maintenance.maybe_run("curate_skills") is True


def test_jobs_are_independent(monkeypatch, tmp_path):
    _use_tmp_state(monkeypatch, tmp_path)
    assert maintenance.maybe_run("curate_skills") is True
    assert maintenance.maybe_run("anderer_job") is True  # eigener Zeitstempel


def test_corrupt_state_file_is_tolerated(monkeypatch, tmp_path):
    p = _use_tmp_state(monkeypatch, tmp_path)
    p.write_text("kein json {", encoding="utf-8")
    assert maintenance.maybe_run("curate_skills") is True  # fail-open, frisch starten
