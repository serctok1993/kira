"""Nachtdenker-Runde: eigene OpenAI-kompatible Endpunkte (llama.cpp-Server) sind im
Katalog zuweisbar, und ein Zeitfenster-Automat teilt die GPU — tagsueber Ollama,
nachts das grosse Modell (4B und 35B passen nicht zusammen in 10 GB VRAM).

Werkstatt-Benchmark 20.07.: Qwen3.6-35B via llama.cpp = 51 tok/s / BFCL 82,8 auf
der 3080 — der Harness muss den Server nur zeitgesteuert fahren und die Rollen
umlegen. Offline: alle Prozess-/Netz-/Modell-Zugriffe gemockt.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import CONFIG, ROOT
from core.kernel import llm_router, nachtdenker


_PROVIDERS = {"nacht35b": {"model": "openai/kira-35b",
                           "api_base": "http://127.0.0.1:8081/v1", "api_key_env": ""}}


# ---- Keyless-Endpunkte: has_key + Dummy-Key -------------------------------------------

def test_keyless_provider_faellt_nicht_auf_lokal(monkeypatch):
    """Registrierter Endpunkt OHNE api_key_env = bewusst keyless -> has_key True
    (vorher fiel die Rolle still auf local_fallback zurueck)."""
    monkeypatch.setitem(CONFIG["models"], "providers", dict(_PROVIDERS))
    assert llm_router.has_key("nacht35b") is True
    # MIT Key-Pflicht und fehlender Env-Var bleibt es ehrlich False
    monkeypatch.setitem(CONFIG["models"], "providers",
                        {"cloudx": {"model": "openai/x", "api_base": "https://x", "api_key_env": "CLOUDX_KEY"}})
    monkeypatch.delenv("CLOUDX_KEY", raising=False)
    assert llm_router.has_key("cloudx") is False


def test_complete_sendet_dummy_key_an_keyless_endpunkt(monkeypatch, tmp_path):
    """litellm verlangt fuer openai/-Modelle IRGENDEINEN Key — der llama.cpp-Server
    ignoriert ihn. Ohne Dummy flog frueher ein AuthenticationError."""
    from core.kernel import events
    from core.governance import treasury
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()
    monkeypatch.setitem(CONFIG["models"], "providers", dict(_PROVIDERS))
    monkeypatch.setattr(treasury, "can_spend", lambda *a, **k: (True, ""))
    monkeypatch.setattr(llm_router.litellm, "completion_cost", lambda **kw: 0.0)
    seen: dict = {}
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
                           usage=None)
    monkeypatch.setattr(llm_router, "_completion", lambda **kw: (seen.update(kw), resp)[1])

    res = llm_router.complete([{"role": "user", "content": "hi"}], model="nacht35b")

    assert seen["model"] == "openai/kira-35b"                       # Alias -> litellm-ID
    assert seen["api_base"] == "http://127.0.0.1:8081/v1"
    assert seen["api_key"] == "sk-lokal"                            # Platzhalter statt Auth-Fehler
    assert res["text"] == "ok"


def test_eigene_endpunkte_im_katalog(monkeypatch):
    from core.kernel import models
    import httpx
    monkeypatch.setitem(CONFIG["models"], "providers", dict(_PROVIDERS))
    monkeypatch.setattr(models, "ollama_models", lambda: [])
    monkeypatch.setattr(models, "aimlapi_models", lambda: [])
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(models, "_CATALOG_FILE", models._CATALOG_FILE.with_name("gibtsnicht.json"))
    monkeypatch.setattr(models, "_HISTORY_FILE", models._HISTORY_FILE.with_name("gibtsnicht-h.json"))
    cat = models.catalog(force=True)
    assert "eigene" in cat
    assert cat["eigene"][0]["id"] == "nacht35b"
    assert "127.0.0.1:8081" in cat["eigene"][0]["name"]             # Klartext: wohin zeigt der Alias
    models._CATALOG_CACHE.update(ts=0.0, data=None)


# ---- Zeitfenster ----------------------------------------------------------------------

def _cfg(monkeypatch, **extra):
    cfg = {"enabled": True, "start": "23:30", "ende": "07:30",
           "server_cmd": "powershell -File server35.ps1",
           "endpunkt": "http://127.0.0.1:8081/v1", "modell": "openai/kira-35b",
           "provider": "nacht35b", "rollen": ["reason", "worker"], **extra}
    monkeypatch.setitem(CONFIG, "nachtdenker", cfg)
    return cfg


def test_fenster_ueber_mitternacht(monkeypatch):
    _cfg(monkeypatch)
    t = lambda h, m: dt.datetime(2026, 7, 21, h, m)
    assert nachtdenker.fenster_aktiv(t(0, 30)) is True
    assert nachtdenker.fenster_aktiv(t(23, 30)) is True             # Startminute inklusive
    assert nachtdenker.fenster_aktiv(t(7, 30)) is False             # Endminute exklusive
    assert nachtdenker.fenster_aktiv(t(12, 0)) is False
    _cfg(monkeypatch, start="08:00", ende="10:00")                  # normales Tag-Fenster
    assert nachtdenker.fenster_aktiv(t(9, 0)) is True
    assert nachtdenker.fenster_aktiv(t(10, 0)) is False
    _cfg(monkeypatch, start="08:00", ende="08:00")                  # start==ende = kein Fenster
    assert nachtdenker.fenster_aktiv(t(8, 0)) is False


# ---- Der Automat ----------------------------------------------------------------------

@pytest.fixture()
def _auto(monkeypatch, tmp_path):
    """Voll gemockter Automat: Prozesse, Netz, Rollen, Events — nur die Logik ist echt."""
    from core.kernel import models
    _cfg(monkeypatch)
    monkeypatch.setattr(nachtdenker, "_STATE_FILE", tmp_path / "nachtdenker.json")
    welt = {"health": False, "alive": True, "events": [], "rollen": {"reason": "openrouter/z-ai/glm-5.2",
                                                                     "worker": "openrouter/deepseek/deepseek-v4-flash"},
            "gestartet": [], "beendet": [], "entladen": 0}
    monkeypatch.setattr(nachtdenker, "_health", lambda: welt["health"])
    monkeypatch.setattr(nachtdenker, "pid_alive", lambda pid: welt["alive"])
    monkeypatch.setattr(nachtdenker, "_server_starten", lambda: welt["gestartet"].append(4242) or 4242)
    monkeypatch.setattr(nachtdenker, "_server_beenden", lambda pid: welt["beendet"].append(pid))
    monkeypatch.setattr(nachtdenker, "_ollama_entladen", lambda: welt.update(entladen=welt["entladen"] + 1))
    monkeypatch.setattr(nachtdenker.events, "emit", lambda t, p=None, **k: welt["events"].append((t, p or {})))
    monkeypatch.setattr(models, "roles", lambda: dict(welt["rollen"]))
    monkeypatch.setattr(models, "set_role", lambda r, m: welt["rollen"].__setitem__(r, m) or m)
    monkeypatch.setattr(models, "add_provider", lambda a, m, b, e: welt.setdefault("provider", (a, m, b, e)))
    monkeypatch.setitem(CONFIG["models"], "providers", {})
    return welt


_NACHTS = dt.datetime(2026, 7, 21, 23, 45)
_TAGS = dt.datetime(2026, 7, 21, 12, 0)


def test_automat_startet_aktiviert_und_raeumt_auf(_auto):
    welt = _auto
    nachtdenker.tick(_NACHTS)                                       # Fensterbeginn -> spawnen
    assert welt["gestartet"] == [4242]
    assert nachtdenker.status()["phase"] == "startend"
    nachtdenker.tick(_NACHTS)                                       # Health noch tot -> warten
    assert nachtdenker.status()["phase"] == "startend"
    welt["health"] = True
    nachtdenker.tick(_NACHTS)                                       # Health da -> uebernehmen
    st = nachtdenker.status()
    assert st["phase"] == "aktiv" and st["aktiv"] is True
    assert welt["rollen"] == {"reason": "nacht35b", "worker": "nacht35b"}
    assert welt["provider"][0] == "nacht35b" and welt["provider"][3] == ""   # keyless registriert
    assert welt["entladen"] == 1                                    # Ollama hat den VRAM geraeumt
    assert any(t == "nachtdenker_start" for t, _p in welt["events"])
    nachtdenker.tick(_TAGS)                                         # Fensterende -> alles zurueck
    assert welt["rollen"] == {"reason": "openrouter/z-ai/glm-5.2",
                              "worker": "openrouter/deepseek/deepseek-v4-flash"}
    assert welt["beendet"] == [4242]
    assert nachtdenker.status()["phase"] == "aus"


def test_automat_neustart_ist_gedeckelt(_auto):
    welt = _auto
    welt["health"] = True
    nachtdenker.tick(_NACHTS)                                       # laeuft schon -> direkt aktiv
    assert nachtdenker.status()["phase"] == "aktiv"
    schnappschuss = dict(welt["rollen"])
    for runde in range(nachtdenker._MAX_NEUSTARTS):                 # Server stirbt wiederholt
        welt["alive"] = False
        welt["health"] = False
        nachtdenker.tick(_NACHTS)                                   # tot -> Neustart (startend)
        assert nachtdenker.status()["phase"] == "startend"
        welt["alive"] = True
        welt["health"] = True
        nachtdenker.tick(_NACHTS)                                   # wieder da -> aktiv
        assert nachtdenker.status()["phase"] == "aktiv"
    assert schnappschuss == {"reason": "nacht35b", "worker": "nacht35b"}
    welt["alive"] = False
    nachtdenker.tick(_NACHTS)                                       # 4. Tod -> aufgeben
    assert nachtdenker.status()["phase"] == "fehler"
    assert any(t == "nachtdenker_fehler" for t, _p in welt["events"])
    assert welt["rollen"] == {"reason": "openrouter/z-ai/glm-5.2",  # aufgeben = Rollen zurueck
                              "worker": "openrouter/deepseek/deepseek-v4-flash"}
    nachtdenker.tick(_TAGS)                                         # Fensterende loest die Parkung
    assert nachtdenker.status()["phase"] == "aus"


def test_automat_snapshot_ueberlebt_neustart(_auto):
    """Beim Neustart mitten im Fenster darf der Rollen-Schnappschuss NICHT mit dem
    Alias ueberschrieben werden — sonst 'restauriert' das Fensterende den Alias."""
    welt = _auto
    welt["health"] = True
    nachtdenker.tick(_NACHTS)                                       # aktiv
    welt["alive"] = False
    welt["health"] = False
    nachtdenker.tick(_NACHTS)                                       # Neustart
    welt["alive"] = True
    welt["health"] = True
    nachtdenker.tick(_NACHTS)                                       # wieder aktiv
    nachtdenker.tick(_TAGS)                                         # Fensterende
    assert welt["rollen"]["reason"] == "openrouter/z-ai/glm-5.2"    # Original, NICHT der Alias
    assert welt["rollen"]["worker"] == "openrouter/deepseek/deepseek-v4-flash"


def test_automat_aus_bleibt_stumm(_auto, monkeypatch):
    welt = _auto
    monkeypatch.setitem(CONFIG, "nachtdenker", {"enabled": False})
    nachtdenker.tick(_NACHTS)
    assert welt["gestartet"] == [] and welt["events"] == []


def test_leeres_server_cmd_lehrt(_auto, monkeypatch):
    welt = _auto
    _cfg(monkeypatch, server_cmd="")
    monkeypatch.setattr(nachtdenker, "_server_starten", lambda: None)
    nachtdenker.tick(_NACHTS)
    assert nachtdenker.status()["phase"] == "fehler"
    fehler = [p for t, p in welt["events"] if t == "nachtdenker_fehler"]
    assert fehler and "server_cmd" in fehler[0]["error"]            # lehrender Fehlertext


# ---- Verdrahtung ----------------------------------------------------------------------

def test_runner_traegt_den_tick():
    src = (ROOT / "core" / "agency" / "missions" / "runner.py").read_text(encoding="utf-8")
    assert "nachtdenker.tick()" in src                              # Immer-Block = 24/7


def test_api_provider_endpoint(monkeypatch):
    from core.api import server
    calls: list = []
    monkeypatch.setattr(server.models, "add_provider",
                        lambda a, m, b, e: calls.append((a, m, b, e)) or {"model": m, "api_base": b, "api_key_env": e})
    monkeypatch.setattr(server.events, "emit", lambda *a, **k: None)
    r = asyncio.run(server.api_model_provider(
        {"alias": "nacht35b", "api_base": "http://127.0.0.1:8081/v1"}))
    assert r["ok"] and calls == [("nacht35b", "openai/nacht35b", "http://127.0.0.1:8081/v1", "")]
    r2 = asyncio.run(server.api_model_provider({"alias": ""}))
    assert not r2["ok"] and "api_base" in r2["error"]               # lehrender Fehlertext


def test_cockpit_traegt_nachtdenker_und_endpunkte():
    from core.api.ui.script import SCRIPT
    from core.api.ui.views import VIEWS
    assert 'id="nd-on"' in VIEWS and 'id="nd-start"' in VIEWS       # Nachtdenker-Karte
    assert 'id="m-ep-add"' in VIEWS                                 # Endpunkt-Registrierung
    assert "nachtdenker.enabled" in SCRIPT and "/api/model/provider" in SCRIPT
    assert "Eigene Endpunkte" in SCRIPT                             # Picker-Gruppe
