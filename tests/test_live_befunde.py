"""Live-Befunde 17.07. (erste Nutzungsrunde, Forensik der Werkstatt):

(1) Dashboard-Modellwechsel erreichte den Bot-Prozess nicht — set_role schrieb
    data/models.json, aber Langlaeufer (Bot/Runner) lasen sie nur beim Start.
    Fix: config.refresh_overrides() per mtime, eingehaengt in beide Schleifen.
(2) cron_remove warf einen ROHEN TypeError bei {"id": …}, obwohl cron_list
    selbst "(id=…)" druckt. Fix: id-Alias + lehrender Fehler (#185-Muster).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core import config


@pytest.fixture()
def _cfg_sandbox(tmp_path, monkeypatch):
    """Override-Dateien auf tmp + CONFIG/_OV_MTIMES nach dem Test restaurieren."""
    monkeypatch.setattr(config, "_MODEL_OVERRIDE", tmp_path / "models.json")
    monkeypatch.setattr(config, "_OVERRIDE_FILE", tmp_path / "overrides.json")
    monkeypatch.setattr(config, "_OV_MTIMES", {})
    schnappschuss = copy.deepcopy(config.CONFIG)
    yield tmp_path
    config.CONFIG.clear()
    config.CONFIG.update(schnappschuss)


def test_refresh_laedt_modellwechsel_ohne_neustart(_cfg_sandbox):
    tmp = _cfg_sandbox
    config.refresh_overrides()                                  # Grundzustand stempeln
    (tmp / "models.json").write_text(json.dumps({"routing": {"chat": "test/c5b"}}),
                                     encoding="utf-8")
    assert config.refresh_overrides() is True                   # Aenderung erkannt
    assert config.CONFIG["models"]["routing"]["chat"] == "test/c5b"
    assert config.refresh_overrides() is False                  # unveraendert -> kein Neuaufbau


def test_refresh_nimmt_auch_allgemeine_overrides(_cfg_sandbox):
    tmp = _cfg_sandbox
    config.refresh_overrides()
    (tmp / "overrides.json").write_text(json.dumps({"mission.goal": "Testziel"}),
                                        encoding="utf-8")
    assert config.refresh_overrides() is True
    assert config.CONFIG["mission"]["goal"] == "Testziel"


def test_langlaeufer_haben_den_refresh_eingehaengt():
    from core.agency.connectors import telegram_bot
    from core.agency.missions import runner

    bot_src = Path(telegram_bot.__file__).read_text(encoding="utf-8")
    run_src = Path(runner.__file__).read_text(encoding="utf-8")
    assert "_maybe_config_refresh()" in bot_src and "refresh_overrides()" in bot_src
    assert "refresh_overrides()" in run_src


def test_cron_remove_id_alias_und_lehrt(monkeypatch):
    from core.agency.missions import cron
    from core.agency.tools.builtin import cron_remove

    geloescht: list[str] = []
    monkeypatch.setattr(cron, "list_jobs",
                        lambda: [{"id": "c7d0cd15", "label": "sunrise"}])
    monkeypatch.setattr(cron, "remove_job", geloescht.append)
    # der Live-Fall woertlich: {"id": …} — vorher roher TypeError, jetzt loescht es
    assert "geloescht" in cron_remove(id="c7d0cd15") and geloescht == ["c7d0cd15"]
    # Kurzform ueber den Alias
    assert "geloescht" in cron_remove(id="c7d0")
    # ohne Angabe / mit unbekanntem Argument: LEHREN statt werfen
    out = cron_remove()
    assert out.startswith("Fehler: cron_remove braucht") and "cron_list" in out
    out = cron_remove(text="sunrise")                           # der zweite Live-Fehlgriff
    assert out.startswith("Fehler:") and "job_id" in out
    assert "Keine geplante Aufgabe" in cron_remove(job_id="gibtsnicht")
