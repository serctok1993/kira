"""P1 (Working-Modus): Auftrags-Store + todo-Werkzeuge — der Plan lebt im Harness.

Offline, eigener Store-Pfad (tmp), keine Live-Daten. Fehlertexte muessen LEHREN
(Trainings-Kategorie Schritt-Disziplin): jeder Fehlschlag nennt den naechsten
korrekten Aufruf.
"""
from __future__ import annotations

import pytest

from core.agency import auftrag
from core.agency.tools import registry
from core.agency.tools import todo_tools  # noqa: F401 -> registriert


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(auftrag, "_PATH", tmp_path / "auftrag.json")


def test_store_roundtrip_und_klartext():
    d = auftrag.set_plan("Report fertig", ["Daten sammeln", "Entwurf", "Korrektur"])
    assert [s["nr"] for s in d["schritte"]] == [1, 2, 3]
    d, err = auftrag.update(1, "fertig")
    assert not err and d["schritte"][0]["status"] == "fertig"
    kt = auftrag.klartext()
    assert "[x] 1." in kt and "-> Naechster Schritt: Nr. 2" in kt
    auftrag.clear()
    assert auftrag.get() == {}


def test_huerde_und_lehrende_fehler():
    auftrag.set_plan("Ziel", ["a", "b"])
    _, err = auftrag.update(2, "huerde")
    assert "notiz" in err and "todo_update(2" in err            # lehrt den korrekten Aufruf
    d, err = auftrag.update(2, "huerde", "API-Key fehlt")
    assert not err and d["huerde"] == "API-Key fehlt"
    d, err = auftrag.update(2, "fertig")                        # fertig raeumt die Huerde
    assert not err and d["huerde"] == ""
    _, err = auftrag.update(9, "fertig")
    assert "Gueltige Nummern: 1, 2" in err
    _, err = auftrag.update(1, "erledigt")
    assert "Erlaubt:" in err and "huerde" in err


def test_tools_registriert_und_flow():
    namen = [t.name for t in registry.all_tools(include_disabled=True)]
    for n in ("todo_plan", "todo_update", "plan_list"):
        assert n in namen, f"Tool fehlt im Manifest: {n}"
    assert "kein aktiver Auftrag" in todo_tools.plan_list()
    out = todo_tools.todo_plan("Report", "Daten sammeln\nEntwurf schreiben")
    assert out.startswith("Plan steht (2 Schritte).")
    # zweiter Plan ohne 'ersetzen' -> lehrender Fehler statt stillem Ueberschreiben
    out = todo_tools.todo_plan("Anderes", "x\ny")
    assert out.startswith("Fehlgeschlagen") and 'ersetzen="ja"' in out
    assert "[>]" in todo_tools.todo_update("1", "laeuft")       # nr als String toleriert
    out = todo_tools.todo_update("Schritt zwei", "fertig")
    assert out.startswith("Fehlgeschlagen") and "Zahl" in out   # lehrt das Zahlformat
    assert "-> Naechster Schritt" in todo_tools.plan_list()


def test_prompt_bekommt_auftrag_ans_ende(monkeypatch):
    # Ohne Auftrag: Block leer (byte-identischer Prompt — Golden-Test deckt das ab).
    assert auftrag.prompt_block() == ""
    auftrag.set_plan("Report fertig", ["Daten sammeln", "Entwurf"])
    from core.mind import agent
    from core.mind.memory import store as memory
    monkeypatch.setattr(memory, "recall", lambda *a, **k: [])
    monkeypatch.setattr(memory, "recall_lessons", lambda *a, **k: [])
    monkeypatch.setattr(memory, "recall_skills", lambda *a, **k: [])
    prompt = agent.build_system_prompt("Probe")
    assert prompt.rstrip().endswith("-> Naechster Schritt: Nr. 1")   # ans ENDE (+11 Punkte)
    assert "# DEIN AKTIVER AUFTRAG" in prompt
    assert prompt.index("# DEIN AKTIVER AUFTRAG") > prompt.index("Antworte auf Deutsch")
