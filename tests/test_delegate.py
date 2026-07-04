"""Delegation v1: Raenge, Tiefen-Sperre, Deckel, Schwarm, Richter-Dossier.

Hausmuster: tmp-DB fuer events, act() gefakt (kein LLM, offline).
"""
from __future__ import annotations


def _tmp_events(monkeypatch, tmp_path):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    return events


def _fake_act(record: list):
    def fake(task, session_id=None, max_steps=None, escalate=False, task_type="reason", **kw):
        record.append({"task": task, "sid": session_id, "steps": max_steps,
                       "escalate": escalate, "task_type": task_type})
        return {"text": f"ERLEDIGT ({task_type})", "steps": 1}
    return fake


def test_rang_mapping(monkeypatch, tmp_path):
    _tmp_events(monkeypatch, tmp_path)
    from core.agency import act as act_mod
    from core.agency.tools import delegate_tools as dt
    calls: list = []
    monkeypatch.setattr(act_mod, "act", _fake_act(calls))

    assert "ERLEDIGT" in dt.delegate("tu was", rang="reflex")
    assert "ERLEDIGT" in dt.delegate("tu was", rang="arbeiter")
    assert "ERLEDIGT" in dt.delegate("tu was", rang="denker")
    assert calls[0]["task_type"] == "classify" and calls[0]["escalate"] is False
    assert calls[1]["task_type"] == "worker" and calls[1]["escalate"] is False
    assert calls[2]["task_type"] == "reason" and calls[2]["escalate"] is False
    assert all(c["sid"].startswith("sub-") for c in calls)

    assert "Unbekannter Rang" in dt.delegate("x", rang="general")


def test_richter_eskaliert_und_fuehrt_dossier(monkeypatch, tmp_path):
    _tmp_events(monkeypatch, tmp_path)
    from core.agency import act as act_mod
    from core.agency.tools import delegate_tools as dt
    calls: list = []
    monkeypatch.setattr(act_mod, "act", _fake_act(calls))
    dossier = tmp_path / "richter-dossier.md"
    monkeypatch.setattr(dt, "_DOSSIER", dossier)
    dossier.write_text("# Richter-Dossier\nAlte Erkenntnis: X gilt.\n", encoding="utf-8")

    out = dt.delegate("Urteile ueber Y", rang="richter")

    assert calls[0]["escalate"] is True  # Richter laeuft auf escalation_model
    assert "Alte Erkenntnis" in calls[0]["task"]  # Brief enthaelt das Dossier
    assert "DEIN URTEILSAUFTRAG" in calls[0]["task"]
    assert "ERLEDIGT" in out
    txt = dossier.read_text(encoding="utf-8")
    assert "ERLEDIGT (reason)" in txt  # Urteil wurde nachgetragen


def test_dossier_wird_gekappt(monkeypatch, tmp_path):
    from core.agency.tools import delegate_tools as dt
    dossier = tmp_path / "richter-dossier.md"
    monkeypatch.setattr(dt, "_DOSSIER", dossier)
    monkeypatch.setattr(dt, "_DOSSIER_CAP", 600)
    for i in range(10):
        dt._dossier_nachtragen(f"Erkenntnis Nummer {i} " + "x" * 100)
    txt = dossier.read_text(encoding="utf-8")
    assert len(txt) <= 700  # Cap + Kopfzeile
    assert "Erkenntnis Nummer 9" in txt  # neueste bleibt


def test_tiefen_sperre(monkeypatch, tmp_path):
    _tmp_events(monkeypatch, tmp_path)
    from core.agency import act as act_mod
    from core.agency.tools import delegate_tools as dt
    calls: list = []
    monkeypatch.setattr(act_mod, "act", _fake_act(calls))

    # Ueber session_id-Konvention
    assert "verweigert" in dt.delegate("x", session_id="sub-abc-1")
    assert "verweigert" in dt.schwarm("x {item}", "a", session_id="sub-abc-1")
    # Ueber das Laufzeit-Flag (auch ohne session_id verlaesslich)
    monkeypatch.setattr(dt, "_AKTIV", True)
    assert "verweigert" in dt.delegate("x")
    assert "verweigert" in dt.schwarm("x {item}", "a")
    assert calls == []  # nie bis act() gekommen


def test_verschachtelte_delegation_blockiert(monkeypatch, tmp_path):
    """Ein Unteragent, der selbst delegate ruft, wird abgewiesen (Flag-Weg, real verschachtelt)."""
    _tmp_events(monkeypatch, tmp_path)
    from core.agency import act as act_mod
    from core.agency.tools import delegate_tools as dt
    inner: dict = {}

    def act_that_delegates(task, session_id=None, **kw):
        inner["result"] = dt.delegate("noch tiefer")  # Unteragent versucht weiterzudelegieren
        return {"text": "fertig", "steps": 1}

    monkeypatch.setattr(act_mod, "act", act_that_delegates)
    dt.delegate("aussen")
    assert "verweigert" in inner["result"]
    assert dt._AKTIV is False  # Flag sauber zurueckgesetzt


def test_schritte_deckel(monkeypatch, tmp_path):
    _tmp_events(monkeypatch, tmp_path)
    from core.agency import act as act_mod
    from core.agency.tools import delegate_tools as dt
    calls: list = []
    monkeypatch.setattr(act_mod, "act", _fake_act(calls))

    dt.delegate("x", rang="arbeiter")            # Default aus config
    dt.delegate("x", rang="arbeiter", schritte="99")  # wird auf 40 gekappt
    assert calls[0]["steps"] == 12
    assert calls[1]["steps"] == 40


def test_kosten_deckel_warnung(monkeypatch, tmp_path):
    _tmp_events(monkeypatch, tmp_path)
    from core.agency import act as act_mod
    from core.governance import treasury
    from core.agency.tools import delegate_tools as dt
    monkeypatch.setattr(act_mod, "act", _fake_act([]))
    spend = iter([0.0, 2.5])  # vorher 0, nachher 2.50 EUR -> ueber Deckel (1.0)
    monkeypatch.setattr(treasury, "today_spend", lambda: next(spend))

    out = dt.delegate("teurer auftrag")
    assert "UEBER Deckel" in out


def test_schwarm_iteriert_und_deckelt(monkeypatch, tmp_path):
    _tmp_events(monkeypatch, tmp_path)
    from core.agency import act as act_mod
    from core.agency.tools import delegate_tools as dt
    calls: list = []
    monkeypatch.setattr(act_mod, "act", _fake_act(calls))
    monkeypatch.setattr(dt, "_cfg", lambda: {"schwarm_max": 2})

    out = dt.schwarm("Recherchiere: {item}", "Lead A\nLead B\nLead C")
    assert len(calls) == 2  # gedeckelt
    assert "Recherchiere: Lead A" in calls[0]["task"]
    assert "uebersprungen" in out
    assert "1/2" in out and "2/2" in out

    assert "ohne Liste" in dt.schwarm("x {item}", "   ")


def test_werkzeuge_registriert():
    from core.agency.tools import builtin  # noqa: F401 — laedt alle Tool-Module
    from core.agency.tools import registry
    names = [t.name for t in registry.all_tools()]
    assert "delegate" in names and "schwarm" in names
    # Optionale Parameter bleiben optional (Schema-Konvention 'optional'/'Standard')
    schemas = {s["function"]["name"]: s for s in registry.tool_schemas()}
    req = schemas["delegate"]["function"]["parameters"]["required"]
    assert "auftrag" in req and "rang" not in req and "schritte" not in req