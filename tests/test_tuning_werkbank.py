"""Tuning-Werkbank (Phase 1 der Unschlagbar-Kombi): passiver Datensammler + Synth-
Generator + Export. Kern-Garantien: sammelt still, fasst Kira nie an, keine Test-
Sessions im Trainingsset, Synth kommt live aus der echten Werkzeug-Registry, Export
ist gültiges ChatML."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import core.api.server as s
from core.mind import tuning


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(tuning, "_DIR", tmp_path / "tuning")
    monkeypatch.setattr(tuning, "_EPISODES", tmp_path / "tuning" / "episodes.jsonl")
    monkeypatch.setattr(tuning, "test_mode", lambda: False)   # sonst wuerde record alles skippen


# ---------- Rekorder ----------

def test_record_schreibt_echte_episode(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    ok = tuning.record_chat("cockpit-1", "Wie ist das Wetter?", "Ich schaue nach — es ist sonnig.",
                            used_tools=True)
    assert ok is True
    eps = tuning.episodes()
    assert len(eps) == 1 and eps[0]["used_tools"] is True
    assert eps[0]["user"] and eps[0]["assistant"]


def test_record_ueberspringt_test_und_ephemer(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    # Testmodus -> nichts
    monkeypatch.setattr(tuning, "test_mode", lambda: True)
    assert tuning.record_chat("cockpit-1", "hallo dubidu", "eine lange echte Antwort hier") is False
    # ephemere Sessions -> nichts (auch ohne Testmodus)
    monkeypatch.setattr(tuning, "test_mode", lambda: False)
    for sid in ("bench-9", "test-3", "desktop-x"):
        assert tuning.record_chat(sid, "frage hier", "eine lange echte Antwort hier") is False
    assert tuning.episodes() == []


def test_record_ueberspringt_trivial_und_steuerbefehle(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert tuning.record_chat("cockpit-1", "hi", "ok") is False           # zu kurz
    assert tuning.record_chat("cockpit-1", "/model x", "gewechselt zu x jaja") is False  # Steuerbefehl
    assert tuning.episodes() == []


def test_record_wirft_nie(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    # Schreiben sabotieren -> record darf trotzdem nicht werfen (Chat nie stoeren)
    monkeypatch.setattr(tuning, "_DIR", None)
    assert tuning.record_chat("cockpit-1", "frage", "eine ausreichend lange antwort") is False


# ---------- Synth-Generator ----------

def test_synth_kommt_aus_der_liven_registry():
    import core.agency.tools.builtin  # noqa: F401 — registriert die Werkzeuge
    from core.agency.tools import registry

    ex = tuning.synth_examples()
    tool_ex = [e for e in ex if e["source"] == "synth_tool"]
    assert len(tool_ex) == len(registry.all_tools())          # je Werkzeug ein Beispiel
    # jede Werkzeug-Zeile ist echtes ACT-Protokoll und vom echten Parser lesbar
    from core.agency.act import _parse_act
    sample = next(e for e in tool_ex if e["assistant"].startswith("ACT web_search"))
    parsed = _parse_act(sample["assistant"])
    assert parsed and parsed[0] == "web_search"


def test_synth_enthaelt_disziplin_und_ton():
    src = {e["source"] for e in tuning.synth_examples()}
    assert "synth_discipline" in src and "synth_persona" in src


# ---------- Export ----------

def test_export_ist_gueltiges_chatml(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    tuning.record_chat("cockpit-1", "Merk dir X", "Erledigt, ich habe mir X gemerkt.")
    res = tuning.export()
    assert res["ok"] and res["count"] > 0
    lines = [json.loads(x) for x in open(res["path"], encoding="utf-8").read().splitlines() if x.strip()]
    assert len(lines) == res["count"]
    for row in lines:
        roles = [m["role"] for m in row["messages"]]
        assert roles == ["system", "user", "assistant"]       # sauberes ChatML-Tripel


def test_export_ohne_episoden(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    only_synth = tuning.export(include_episodes=False)
    assert only_synth["count"] == len(tuning.synth_examples())


# ---------- API ----------

def test_api_stats_und_export():
    c = TestClient(s.app)
    st = c.get("/api/tuning/stats").json()
    assert "total" in st and "synth" in st and "episodes" in st
    ex = c.post("/api/tuning/export", json={"include_episodes": False}).json()
    assert ex["ok"] and ex["count"] >= st["synth"]
