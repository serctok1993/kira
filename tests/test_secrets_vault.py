"""Zugangs-Tresor laedt in die Umgebung — sonst sieht der separate Telegram-Bot
(und nach Neustart auch das Cockpit) einen im Cockpit eingegebenen Key NIE.
"""
from __future__ import annotations

import json
import os


def test_vault_laedt_in_env(monkeypatch, tmp_path):
    from core import config
    (tmp_path / "secrets.json").write_text(
        json.dumps({"secrets": {"ELEVENLABS_API_KEY": "sk-vault", "LEER": ""}}), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("LEER", raising=False)

    config._load_vault_secrets()

    assert os.environ.get("ELEVENLABS_API_KEY") == "sk-vault"  # aus dem Tresor in die Umgebung
    assert "LEER" not in os.environ                            # leere Werte werden ignoriert


def test_env_hat_vorrang(monkeypatch, tmp_path):
    from core import config
    (tmp_path / "secrets.json").write_text(
        json.dumps({"secrets": {"OPENROUTER_API_KEY": "aus-tresor"}}), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "aus-env")

    config._load_vault_secrets()

    assert os.environ["OPENROUTER_API_KEY"] == "aus-env"  # explizite .env/Umgebung gewinnt


def test_kein_tresor_kein_crash(monkeypatch, tmp_path):
    from core import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # keine secrets.json vorhanden
    config._load_vault_secrets()                       # darf nicht raisen

    (tmp_path / "secrets.json").write_text("{kaputt", encoding="utf-8")
    config._load_vault_secrets()                       # kaputtes JSON -> still, kein Crash


def test_bot_wuerde_key_sehen(monkeypatch, tmp_path):
    """End-to-End-Gedanke: nach dem Laden findet os.getenv den Key -> tts.synthesize kann feuern."""
    from core import config
    (tmp_path / "secrets.json").write_text(
        json.dumps({"secrets": {"ELEVENLABS_API_KEY": "sk-live"}}), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    config._load_vault_secrets()
    assert os.getenv("ELEVENLABS_API_KEY") == "sk-live"
