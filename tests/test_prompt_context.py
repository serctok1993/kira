"""P6 (Werkstatt-Vertrag): der System-Prompt als inspizierbares Sektions-Objekt.

Der Golden-Test beweist BYTE-IDENTITAET: tests/golden_system_prompt.txt wurde
VOR dem Umbau aus dem historischen build_system_prompt eingefroren (alle
nicht-deterministischen Bausteine festgenagelt, identity gemockt — kein
Personenname, maschinenunabhaengig). Bricht dieser Test, hat sich der
Prompt-Vertrag geaendert -> Werkstatt-Meldung PFLICHT vor dem Merge.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _nageln(monkeypatch):
    """Exakt die Fixierung, mit der die Golden-Datei erzeugt wurde."""
    from core import identity
    from core.mind import agent
    from core.mind.memory import store as memory   # agent.py bindet store AS memory

    monkeypatch.setattr(identity, "render", lambda s: s)
    monkeypatch.setattr(identity, "user_name", lambda: "PARTNER-PLATZHALTER")
    monkeypatch.setattr(agent, "jetzt_zeile", lambda: "JETZT: Mittwoch, 15.07.2026, 12:00 Uhr")
    monkeypatch.setattr(agent, "_read", lambda name: f"<<{name}>>")
    monkeypatch.setattr(agent, "_body_compact", lambda: "<<koerper>>")
    monkeypatch.setattr(agent, "_playbooks_block", lambda: "# PLAYBOOKS\n<<playbooks>>")
    monkeypatch.setattr(agent, "antrieb_direktive", lambda: "<<antrieb>>")
    monkeypatch.setattr(agent, "arbeitsweise_block", lambda: "<<arbeitsweise>>\n\n")
    monkeypatch.setattr(agent, "persona_text", lambda: "<<persona>>")
    monkeypatch.setattr(memory, "recall", lambda *a, **k: [
        {"role": "self", "text": "Fixe Erinnerung A"},
        {"role": "user", "text": "Fixe Erinnerung B"}])
    monkeypatch.setattr(memory, "recall_lessons", lambda *a, **k: ["Fixe Lektion 1"])
    monkeypatch.setattr(memory, "recall_skills", lambda *a, **k: ["Fixer Skill 1", "Fixer Skill 2"])


def test_golden_byte_identitaet(monkeypatch):
    from core.mind import agent

    _nageln(monkeypatch)
    golden = (Path(__file__).parent / "golden_system_prompt.txt").read_text(encoding="utf-8")
    assert agent.build_system_prompt("Golden-Probe Nachricht", session_id="golden") == golden


def test_kontext_objekt_traegt_alle_sektionen(monkeypatch):
    # Schluessel-Reihenfolge = Prompt-Reihenfolge (die Werkstatt verlaesst sich darauf)
    from core.mind import agent

    _nageln(monkeypatch)
    c = agent.prompt_context("Probe")
    assert list(c) == ["jetzt", "verfassung", "seele", "ziel", "partner", "koerper",
                       "playbooks", "lektionen", "skills", "erinnerungen",
                       "antrieb", "arbeitsweise", "persona", "user_name"]
    assert all(isinstance(v, str) for v in c.values())
    # der Zusammenbau nutzt GENAU dieses Objekt
    assert "<<constitution.md>>" in agent._prompt_zusammenbauen(c)


def test_dump_endpunkt_liefert_sektionen_und_prompt(monkeypatch):
    import core.api.server as s
    from core.mind import agent

    _nageln(monkeypatch)
    r = TestClient(s.app).get("/api/prompt/context", params={"message": "Probe"}).json()
    assert list(r["sections"]) == list(agent.prompt_context("Probe"))
    assert r["rendered"].startswith("JETZT: Mittwoch, 15.07.2026")
    assert "<<constitution.md>>" in r["rendered"]
