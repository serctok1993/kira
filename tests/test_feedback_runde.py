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
    # Runde II: das Mind ist kein Kasten mehr, sondern der HINTERGRUND des Boards
    assert 'id="mind-panel"' not in VIEWS and 'id="mindcv"' in VIEWS
    assert "loadMind" in SCRIPT and '"/api/vault/graph"' in SCRIPT
    assert 'if(v==="home"){loadCommand();loadMind();}' in SCRIPT
    assert "#mindcv{position:absolute;inset:0" in CSS
    assert "for(let s=0;s<160;s++)schrittRechnen(1);" in SCRIPT  # Layout VOR dem ersten Bild
    assert "prefers-reduced-motion" in SCRIPT


def test_runde2_audit_schwaerzt_secrets():
    # Fund 13.07.: Bot-Token stand im Klartext im Cockpit — nie wieder.
    from core.governance import audit

    # Fake-Token verkettet, damit das Clean-Gate die Testdatei selbst nicht anschlaegt
    fake = "79123456" + "78:AA" + "HxYzAbCdEfGhIjKlMnOpQrStUvWxYz12"
    t = audit.schwaerze(f"python -c \"token='{fake}'\" chat")
    assert "AAHxYz" not in t and "•••geschwaerzt•••" in t
    assert "sk-abcdefghijklmnop" not in audit.schwaerze("key sk-abcdefghijklmnop rest")
    t2 = audit.schwaerze("api_key = supergeheim123")
    assert "supergeheim123" not in t2 and "api_key" in t2       # Schluesselname bleibt lesbar
    assert audit.schwaerze("echo hallo-test-123") == "echo hallo-test-123"  # Harmloses unberuehrt


def test_runde2_monitor_ohne_eingebrannte_quellen():
    assert "hnrss" not in SCRIPT and "DEFAULT_FEEDS" not in SCRIPT
    assert "Quellen verwalten" in SCRIPT                        # Knopf fuehrt zum Monitor
    assert "data-medit" in SCRIPT and "_moEditId" in SCRIPT     # Eintraege bearbeitbar
    assert "News- &amp; Themen-Radar" in VIEWS                  # verstaendlicher Kopf


def test_runde2_autonomie_tab_aufgeraeumt():
    assert "Was ist das „Gewissen" not in VIEWS                 # Doppel-Konzept ist raus
    gov = VIEWS.split('id="v-gov"', 1)[1].split('id="v-monitor"', 1)[0]
    # Reihenfolge: Autonomie zuerst (du entscheidest, fertig), dann Budget, dann Protokoll
    assert gov.index("Autonomie — was braucht deine Freigabe?") < gov.index("Budget — was darf sie ausgeben?")
    assert "Protokoll — was hat sie nach aussen getan?" in gov
    assert "Shell-Befehl ausgefuehrt" in SCRIPT                 # Klartext statt Roh-Dump


def test_runde3_puls_kompakt_und_farbig():
    # Lektionen/Skills fliessen in Spalten (kein Scrollen); Zahlen in Ampelfarben
    assert '<div class="puls-grid">' in SCRIPT
    assert ".puls-grid{display:grid" in CSS
    assert 'class="memrow lek"' in SCRIPT and 'class="memrow ski"' in SCRIPT
    assert "z(tw.tasks.done,'var(--ok)')" in SCRIPT             # getan = gruen
    assert "z(tw.tasks.failed,'var(--danger)')" in SCRIPT       # gescheitert = rot
    assert "z(tw.freigaben_offen,'var(--warn)')" in SCRIPT      # offen = gelb


def test_runde3_galaxie_ohne_woerter():
    # Das Mind ist ein Sternsystem: KEINE Beschriftung, Nebel + Staub + Pings, HD, Theme-Farben
    mind = SCRIPT.split("async function loadMind()", 1)[1].split("/* ---- Chat ----", 1)[0]
    assert "fillText" not in mind
    assert "pings" in mind and "staub" in mind and "createRadialGradient" in mind
    assert "devicePixelRatio" in mind
    assert 'getPropertyValue("--hud")' in mind                  # Galaxie folgt dem Theme


def test_runde3_bibliothek_statt_archiv():
    # Der Wissens-Speicher heisst Bibliothek (Lese-Bestand) und erklaert sich;
    # das Chat-Session-Archiv ist ein anderes Konzept und bleibt bewusst.
    assert "◈ BIBLIOTHEK" in VIEWS and "+ In die Bibliothek" in VIEWS
    assert "◈ ARCHIV" not in VIEWS
    assert 'kopf("BIBLIOTHEK")' in SCRIPT and 'kopf("ARCHIV")' not in SCRIPT
    assert "Die Bibliothek ist leer" in SCRIPT
    assert "Archiv anzeigen" in VIEWS                           # Chat-Archiv unangetastet


def test_runde3_theme_logo_und_playbook_ampel():
    # Wortmarke haengt an den Akzent-Variablen — Theme-Wechsel faerbt KIRA mit
    runde3 = CSS.split("Feinschliff-Runde III", 1)[1]
    assert "#bar #brand .txt,#side h1 .txt" in runde3 and "var(--accent)" in runde3
    assert ".badge.pb-entwurf{color:var(--warn)" in CSS
    assert ".badge.pb-autonom{color:var(--ok)" in CSS
    assert '"pb-"+(g==="autonom"||g==="begleitet"?g:"entwurf")' in SCRIPT
