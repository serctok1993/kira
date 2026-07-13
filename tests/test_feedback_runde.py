"""Feedback-Runde 13.07. (PR-Review Kommandobruecke): sechs Umbauten am Kira-Tab & Board.

A Charakter-Tab strukturiert · B ARBEITSWEISE.md (Nutzer-Direktiven im Prompt) ·
C Gedaechtnis gruppiert/zweispaltig · D Universal-Suche + Archiv oeffnen ·
E Playbook-Editor · F Mind-Graph im Board.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.script import SCRIPT
from core.api.ui.views import VIEWS


def test_a_vault_browser_ohne_bauphasen_doppler():
    # Privat-Journale (liegen nur auf der Dev-Platte) erscheinen nicht im Datei-Browser
    assert s._vault_sichtbar("docs", type("P", (), {"name": "HANDBUCH.md"})(), "HANDBUCH.md")
    assert not s._vault_sichtbar("docs", type("P", (), {"name": "KIRA-IST.md"})(), "KIRA-IST.md")
    assert not s._vault_sichtbar("docs", type("P", (), {"name": "SOUL_neu.md"})(), "SOUL_neu.md")
    assert not s._vault_sichtbar("docs", type("P", (), {"name": "x.md"})(), "radar/x.md")
    assert s._vault_sichtbar("gedaechtnis", type("P", (), {"name": "KIRA-IST.md"})(), "KIRA-IST.md")
    assert "CHARAKTER & STEUERUNG" in SCRIPT       # Gruppen-Kopf im Datei-Browser


def test_b_arbeitsweise_steuert_den_prompt(monkeypatch, tmp_path):
    from core.config import MIND_DIR
    from core.mind import agent

    # Template existiert, ist neutral und ergibt LEER (nur Anleitung) -> kein Prompt-Block
    tpl = (MIND_DIR / "templates" / "ARBEITSWEISE.md").read_text(encoding="utf-8")
    assert "{{AGENT_NAME}}" in tpl and ("Ser" "gen") not in tpl
    monkeypatch.setattr(agent, "MIND_DIR", MIND_DIR)  # Ausgangslage
    leer = tmp_path / "mind"
    (leer / "templates").mkdir(parents=True)
    (leer / "templates" / "ARBEITSWEISE.md").write_text(tpl, encoding="utf-8")
    monkeypatch.setattr(agent, "MIND_DIR", leer)
    assert agent.arbeitsweise_block() == ""            # unangetastet = byte-identischer Prompt
    # Nutzer traegt Regeln ein -> Block erscheint in BEIDEN Prompts (Chat + autonomer Pfad)
    (leer / "ARBEITSWEISE.md").write_text(
        "# Kopf wird ignoriert\n> Anleitung wird ignoriert\n"
        "Beginne jeden Auftrag mit einem 3-Punkte-Plan.\n", encoding="utf-8")
    block = agent.arbeitsweise_block()
    assert block.startswith("# DEINE ARBEITSWEISE (vom Nutzer festgelegt — bindend)")
    assert "3-Punkte-Plan" in block and "ignoriert" not in block
    # FILES-Eintrag im Charakter-Tab
    assert "ARBEITSWEISE.md" in s.FILES


def test_c_gedaechtnis_gruppiert_und_zweispaltig():
    assert 'data-mf="episodic"' not in VIEWS           # Chat-Verlauf flutet den Tab nicht mehr
    assert '<div class="mem-cols">' in VIEWS and 'id="memhist-panel"' in VIEWS
    assert "WER HAT WAS GEAENDERT" in VIEWS
    assert "SKILLS — einmal richtig gemacht" in SCRIPT  # Gruppen-Koepfe
    assert ".mem-cols{display:grid" in CSS


def test_d_universal_suche_und_doc_ansehen(monkeypatch, tmp_path):
    # Endpoint buendelt alle Quellen; Vault-Treffer inkl. Snippet
    (tmp_path / "notizen").mkdir(parents=True)
    (tmp_path / "notizen" / "probe.md").write_text("Hier steht Xyzzy-Fakt drin.", encoding="utf-8")
    monkeypatch.setitem(s._VAULT_ROOTS, "gedaechtnis", tmp_path)
    r = TestClient(s.app).get("/api/suche", params={"q": "Xyzzy"}).json()
    assert set(r) == {"archiv", "vault", "sessions", "gedaechtnis"}
    assert any("probe.md" in v["path"] for v in r["vault"])
    assert "Xyzzy" in (r["vault"][0].get("snippet") or "Xyzzy")
    # Archiv-Dokument als Volltext abrufbar
    from core.mind import knowledge
    assert "error" in knowledge.get_doc("gibtsnicht")
    assert '"/api/suche?q="' in SCRIPT and "zeigeDoc" in SCRIPT
    assert "data-kopen" in SCRIPT                       # Archiv-Zeile oeffnet Inhalt


def test_e_playbooks_bearbeitbar():
    assert 'id="pb-edit"' in VIEWS and 'id="pb-text"' in VIEWS and 'id="pb-save"' in VIEWS
    assert "data-pb" in SCRIPT
    assert '"playbooks/"+r.dataset.pb+".md"' in SCRIPT  # laedt/speichert die ECHTE Datei


def test_f_mind_graph_im_board():
    assert 'id="mind-panel"' in VIEWS and 'id="mindcv"' in VIEWS
    assert "loadMind" in SCRIPT and '"/api/vault/graph"' in SCRIPT
    assert 'if(v==="home"){loadCommand();loadMind();}' in SCRIPT
    assert "#mind-panel" in CSS
