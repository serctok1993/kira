"""Projekt-Chats (#15): eigener Chat je Projekt (Venture).

Session-ID 'venture-<id>' -> build_system_prompt haengt das Projekt-Briefing als Kontext an.
Frontend: ein Projekt-Waehler im Chat-Tab schaltet die Session um. Offline, kein LLM.
"""
from __future__ import annotations


def test_projekt_block_injiziert_briefing(monkeypatch):
    from core.mind import agent
    import core.agency.ventures as ventures

    monkeypatch.setattr(ventures, "get", lambda vid: {"name": "Luvex"} if vid == "abc" else None)
    monkeypatch.setattr(ventures, "briefing", lambda vid, max_chars=1500: "Zielgruppe: KMU, kein Onlineauftritt")

    b = agent._project_block("venture-abc")
    assert "AKTUELLES PROJEKT: Luvex" in b and "Zielgruppe: KMU" in b
    assert agent._project_block("cockpit-x") == ""        # normale Session -> kein Projekt-Block
    assert agent._project_block("venture-unbekannt") == ""  # Projekt gibt es nicht -> leer, kein Crash
    assert agent._project_block(None) == ""


def test_build_system_prompt_haengt_projekt_an(monkeypatch):
    from core.mind import agent
    import core.agency.ventures as ventures

    monkeypatch.setattr(ventures, "get", lambda vid: {"name": "QS-Transporte"})
    monkeypatch.setattr(ventures, "briefing", lambda vid, max_chars=1500: "Fokus: Direktkunden")
    p = agent.build_system_prompt("was steht an?", session_id="venture-xy")
    assert "AKTUELLES PROJEKT: QS-Transporte" in p and "Fokus: Direktkunden" in p
    # ohne Projekt-Session bleibt der Prompt frei davon
    assert "AKTUELLES PROJEKT" not in agent.build_system_prompt("hi", session_id="cockpit-1")


def test_chat_projekt_waehler_im_cockpit():
    from core.api.ui.views import VIEWS
    from core.api.ui.script import SCRIPT

    assert 'id="chat-project"' in VIEWS                              # Projekt-Wähler im Chat-Tab
    assert "function loadChatProjects(" in SCRIPT and "/api/ventures" in SCRIPT
    assert '"venture-"+id' in SCRIPT                                 # Umschalten auf Projekt-Session
    assert "loadChatProjects()" in SCRIPT                            # wird beim Chat-Öffnen geladen
