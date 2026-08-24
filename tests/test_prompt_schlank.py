"""Entfesselung 22.08.: Der Live-Prompt ist der Kompakt-Kern (prompt.schlank, Default AN) —
ohne Kanon-Bloecke, ohne Reversibilitaets-Reflex, mit expliziter Arbeitsbereichs-Freiheit.
Der historische Vollprompt bleibt via prompt.schlank: false erhalten (Golden-Test)."""
from __future__ import annotations

from tests.test_prompt_context import _nageln


def test_schlank_prompt_ist_default_und_entfesselt(monkeypatch):
    from core.mind import agent

    _nageln(monkeypatch)
    monkeypatch.setattr(agent, "_schlank_aktiv", lambda: True)
    p = agent.build_system_prompt("Probe", session_id="golden")
    assert "ohne Rueckfrage-Reflex" in p and "Arbeitsbereich" in p
    assert "Not-Aus" in p and "Kasse" in p            # harte Grenzen bleiben
    assert "# DEINE VERFASSUNG" not in p and "<<SOUL.md>>" not in p
    assert "irreversib" not in p.lower() and "unumkehr" not in p.lower()
    assert "JETZT: Mittwoch, 15.07.2026" in p         # dynamischer Schwanz bleibt
    # deutlich schlanker als der Vollprompt
    voll = agent._prompt_zusammenbauen(agent.prompt_context("Probe"))
    assert len(p) < len(voll)


def test_schlank_flag_kommt_aus_der_config(monkeypatch):
    from core.mind import agent

    monkeypatch.setattr("core.mind.agent.CONFIG", {"prompt": {"schlank": False}},
                        raising=False)
    # _schlank_aktiv liest CONFIG frisch aus core.config — dort patchen
    import core.config as cfg
    monkeypatch.setattr(cfg, "CONFIG", {"prompt": {"schlank": False}})
    assert agent._schlank_aktiv() is False
    monkeypatch.setattr(cfg, "CONFIG", {})
    assert agent._schlank_aktiv() is True   # Default: entfesselt


def test_hard_gate_default_leer(monkeypatch, tmp_path):
    """Voll-Entfesselung 23.08. (Besitzer-Entscheid): KEIN Default-Gate mehr — die
    Grenzen sind Budget (Treasury), Kill-Switch und eigene Prompts; Audit bleibt."""
    from core.governance import autonomy

    monkeypatch.setattr(autonomy, "_PATH", tmp_path / "autonomy.json")
    assert autonomy.needs_approval("money") is False
    assert autonomy.needs_approval("email_stranger") is False
    assert autonomy.needs_approval("publish") is False
    # Eigene Gates in data/autonomy.json wirken weiterhin
    (tmp_path / "autonomy.json").write_text('{"hard_gate": ["money"]}', encoding="utf-8")
    assert autonomy.needs_approval("money") is True
