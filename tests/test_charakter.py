"""Charakter-Editor: die charakter-praegenden Prompts sind editierbare Textdateien (kein Code),
in der App als 'Charakter'-Reiter mit Erklaerung + Feld + Speichern. PERSONA wurde aus dem Code
in PERSONA.md ausgelagert und wird frisch pro Turn gelesen (Aenderung wirkt sofort).
"""
from __future__ import annotations


def test_persona_datei_existiert_mit_markern():
    from core.config import MIND_DIR
    t = (MIND_DIR / "PERSONA.md").read_text(encoding="utf-8")
    for m in ("WER DU BIST", "WIE DU MITDENKST", "WO DU NACHSCHAUST", "WIE DU SPRICHST"):
        assert m in t, m


def test_persona_text_liest_frisch(monkeypatch):
    from core.mind import agent
    assert "WER DU BIST" in agent.persona_text()  # Default aus PERSONA.md
    # simuliert eine Charakter-Aenderung in der Datei -> wirkt sofort (kein Neustart)
    monkeypatch.setattr(agent, "_read",
                        lambda name: "NEUER TON" if name == "PERSONA.md" else "")
    assert agent.persona_text() == "NEUER TON"


def test_persona_directive_bleibt_string():
    # Rueckwaerts-kompatibel: der Modul-Konstante-Zugriff funktioniert weiter (Tests/_identity)
    from core.mind import agent
    assert isinstance(agent.PERSONA_DIRECTIVE, str) and len(agent.PERSONA_DIRECTIVE) > 100


def test_files_hat_persona_editierbar():
    from core.api import server
    assert "PERSONA.md" in server.FILES and server.FILES["PERSONA.md"]["editable"] is True


def test_cockpit_hat_charakter_reiter():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="v-charakter"' in html and 'data-s="charakter"' in html
    assert "loadCharakter" in html and "PERSONA.md" in html


def test_neue_subtabs_sind_in_kira_gruppen_sichtbar():
    """Regressionsschutz (Fable-Review-Fund): syncKiraGroup blendet jeden Subtab aus, der in
    KEINER KIRA_GROUPS-Gruppe steht — neue Reiter muessen dort eingetragen sein, sonst sind
    sie im Cockpit unsichtbar, obwohl HTML/Loader existieren."""
    import re
    from core.api.ui import script
    m = re.search(r"const KIRA_GROUPS=\[(.*?)\];", script.SCRIPT, re.DOTALL)
    assert m, "KIRA_GROUPS nicht gefunden"
    gruppen = m.group(1)
    # JEDER data-s-Subtab der Kira-Leiste muss in einer Gruppe auftauchen
    from core.api.ui import views
    bar = re.search(r'id="kira-tabs".*?</div>', views.VIEWS if hasattr(views, "VIEWS") else "", re.DOTALL)
    subs = re.findall(r'data-s="([a-z]+)"', bar.group(0)) if bar else []
    if not subs:  # Fallback: bekannte Pflicht-Subtabs pruefen
        subs = ["charakter", "bench"]
    fehlend = [s2 for s2 in subs if f'"{s2}"' not in gruppen]
    assert not fehlend, f"Subtabs ohne Gruppe (unsichtbar!): {fehlend}"


def test_fable_review_notiz_vorhanden():
    from core.config import ROOT
    t = (ROOT / "docs" / "FABLE-REVIEW.md").read_text(encoding="utf-8")
    for m in ("Modell-Setup", "Coding-Basis", "Persona-Kohärenz", "Report-", "Audit-Reste"):
        assert m in t, m
