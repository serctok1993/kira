"""Katalog-Runde: der Modell-Katalog speist sich live aus OpenRouter — mit
Datei-Cache (Config-Muster: Frische per mtime), Offline-Fallback und kuratierter
Vorauswahl. Neuerscheinungen sind sofort zuweisbar, ohne Katalog-PR.
Offline: httpx gemockt, Cache-Datei auf tmp.
"""
from __future__ import annotations

import json

import pytest

from core.kernel import models


_FIXTURE = {"data": [
    {"id": "moonshotai/kimi-k3", "name": "Kimi K3",
     "pricing": {"prompt": "0.0000006", "completion": "0.0000025"}, "context_length": 262144,
     "supported_parameters": ["include_reasoning", "reasoning", "temperature"]},
    {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat",
     "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}, "context_length": 131072},
    {"id": "exotisch/nischenmodell", "name": "Nische",
     "pricing": {"prompt": "0.000001", "completion": "0.000002"}, "context_length": 8192},
]}


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_CATALOG_FILE", tmp_path / "openrouter_models.json")
    monkeypatch.setattr(models, "_CATALOG_CACHE", {"ts": 0.0, "data": None})
    monkeypatch.setattr(models, "_HISTORY_FILE", tmp_path / "model_history.json")
    monkeypatch.setattr(models, "_RC_MEMO", {"mtime": -1.0, "ids": frozenset()})
    monkeypatch.setattr(models, "ollama_models", lambda: [])
    monkeypatch.setattr(models, "aimlapi_models", lambda: [])
    return tmp_path


class _Resp:
    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


def test_live_fetch_schreibt_cache_und_kuratiert(monkeypatch, _iso):
    aufrufe = []
    monkeypatch.setattr(models.httpx, "get",
                        lambda url, timeout=15: aufrufe.append(url) or _Resp(_FIXTURE))
    c = models.catalog(force=True)
    assert len(aufrufe) == 1
    kimi = next(m for m in c["openrouter"] if "kimi-k3" in m["id"])
    assert kimi["in"] == "0.0000006" and kimi["out"] == "0.0000025"   # Preise in/out getrennt
    assert (_iso / "openrouter_models.json").exists()                 # Datei-Cache geschrieben
    kur = {m["id"] for m in c["kuratiert"]}
    assert "openrouter/moonshotai/kimi-k3" in kur                     # Neuerscheinung sofort da
    assert "openrouter/deepseek/deepseek-chat" in kur
    assert "openrouter/exotisch/nischenmodell" not in kur             # Nische nur ueber Suche
    assert kimi["rc"] is True                                         # Denk-Faehigkeit = Katalog-Fakt
    ds = next(m for m in c["openrouter"] if "deepseek-chat" in m["id"])
    assert ds["rc"] is False


def test_frische_datei_spart_das_netz(monkeypatch, _iso):
    (_iso / "openrouter_models.json").write_text(
        json.dumps([{"id": "openrouter/deepseek/deepseek-chat", "name": "DS",
                     "in": "0.0000001", "out": "0.0000004", "ctx": 1, "rc": False}]), encoding="utf-8")
    def _explodiert(*a, **k):
        raise AssertionError("Netz darf bei frischer Datei nicht gefragt werden")
    monkeypatch.setattr(models.httpx, "get", _explodiert)
    c = models.catalog()
    assert c["openrouter"][0]["name"] == "DS"


def test_offline_faellt_auf_alte_datei_zurueck(monkeypatch, _iso):
    alt = _iso / "openrouter_models.json"
    alt.write_text(json.dumps([{"id": "openrouter/deepseek/deepseek-chat", "name": "ALT",
                                "in": "1", "out": "2", "ctx": 1}]), encoding="utf-8")
    import os
    import time
    st = alt.stat()
    os.utime(alt, (st.st_atime, time.time() - 8 * 3600))              # Datei kuenstlich altern
    def _netz_tot(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(models.httpx, "get", _netz_tot)
    c = models.catalog(force=True)
    assert c["openrouter"] and c["openrouter"][0]["name"] == "ALT"    # alt schlaegt leer


def test_ui_traegt_preise_und_vorauswahl():
    from core.api.ui.script import SCRIPT
    assert "MCAT.kuratiert" in SCRIPT                                 # Vorauswahl im Steuerpult
    assert "Kuratierte Auswahl" in SCRIPT
    assert SCRIPT.count("money(m.in)") >= 2                           # Preise: Katalog + Rollen
    assert "money(m.out)" in SCRIPT
