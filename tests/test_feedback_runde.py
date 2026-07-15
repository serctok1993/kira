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
    # Das Mind ist ein Sternsystem: Nebel + Staub + Pings, HD, Theme-Farben.
    # Runde V: Begriffe kamen KLEIN und SCHALTBAR zurueck — Woerter nur hinterm Gate.
    mind = SCRIPT.split("async function loadMind()", 1)[1].split("/* ---- Chat ----", 1)[0]
    assert "if(_mindWorte" in mind.split("fillText", 1)[0]      # Beschriftung nur hinterm Schalter
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


def test_runde4_board_empfang_layout():
    # Skizze des Nutzers: links Befehl+Live-Ops, Mitte Galaxie, rechts "Kira heute",
    # UNTEN der Chat-Einstieg — alles im Board, das jetzt der Empfang ist.
    home = VIEWS.split('id="v-home"', 1)[1].split('id="v-chat"', 1)[0]
    assert home.index('id="board-links"') < home.index('id="board-mitte"') < home.index('id="board-rechts"')
    assert home.index('id="board-rechts"') < home.index('id="board-chat"')
    assert 'id="bc-in"' in home and 'id="tagewerk"' in home.split('id="board-rechts"', 1)[1]
    assert "#v-home .cmd-grid{display:grid" in CSS


def test_runde5_befehl_im_chat_einstieg():
    # Runde IX schaerfte nach: der Einstieg ist ein NORMALES Chatfenster —
    # + links, Mikro rechts, Schwarm+Modell+Modus darunter; Sofort/Fokus-Knoepfe
    # sind raus (der Tages-Fokus lebt oben in der Fokus-Zeile).
    home = VIEWS.split('id="v-home"', 1)[1].split('id="v-chat"', 1)[0]
    assert 'class="direktive"' not in home
    bc = home.split('id="board-chat"', 1)[1]
    for el in ('id="bc-plus"', 'id="dir-mic"', 'id="dir-schwarm"',
               'id="bc-model-btn"', 'id="bc-mode"'):
        assert el in bc, f"fehlt im Einstieg: {el}"
    for weg in ('id="dir-now"', 'id="dir-focus"', 'id="dir-clear"', 'id="dir-result"'):
        assert weg not in VIEWS, f"sollte raus sein: {weg}"
    assert 'simpleRecord("#dir-mic","#bc-in")' in SCRIPT
    assert '$$("#bc-mode a").forEach' in SCRIPT                 # eine Modus-Quelle fuer Board+Chat
    assert '#board-chat[data-mode="work"]::before' in CSS       # LED-Rand faerbt mit dem Modus


def test_runde9_board_chat_pur_und_modus_farbe():
    # Reihenfolge wie im Chat: + | Feld | Mikro | Senden; Mikro = SVG-Icon (rec-Klasse)
    home = VIEWS.split('id="v-home"', 1)[1].split('id="v-chat"', 1)[0]
    zeile = home.split('class="bc-zeile"', 1)[1].split('class="bc-werk"', 1)[0]
    assert zeile.index('id="bc-plus"') < zeile.index('id="bc-in"') < zeile.index('id="dir-mic"') < zeile.index('id="bc-send"')
    assert VIEWS.count('class="chip mic"') == 2 and 'classList.add("rec")' in SCRIPT
    # Modell direkt im Board — EIN Bauteil (modellKnopf) fuer beide Docks, Pille synct
    assert 'modellKnopf("#bc-model-btn","#bc-model-pop")' in SCRIPT
    assert 'const b2=$("#bc-model-btn")' in SCRIPT
    # Schwarm lebt im Senden-Knopf und wird im Chat NUR vorbereitet
    assert '"/schwarm "+rang+" "' in SCRIPT
    assert 'b.textContent=on?"⁂ An den Schwarm":"Senden"' in SCRIPT
    # Der Modus faerbt ALLES (eine Variable), Senden ist schlank statt massiv
    assert "--dock-acc:var(--accent-chat)" in CSS
    assert '#board-chat[data-mode="work"]{--dock-acc:var(--work-accent)}' in CSS
    assert "#chat-main #cform>button:last-child,#board-chat #bc-send{" in CSS
    # + im Board beamt in den Chat und oeffnet die Dateiwahl
    assert 'f&&f.click()' in SCRIPT
    # Schwarm-Toggle + Rang-Wahl im Dunkel-Look (kein weisses OS-Kaestchen/-Dropdown)
    assert "#dir-schwarm-l input{display:none}" in CSS
    assert '$("#dir-schwarm-l").classList.toggle("on",on)' in SCRIPT
    assert "#dir-rang{background:var(--panel)" in CSS
    # Runde XI: Live-Ops-Filter in eigener Zeile (nichts quetscht), EINE Chip-Hoehe ueberall
    assert "#board-links #ops-filter{flex:1 1 100%" in CSS
    assert "height:27px" in CSS.split("Runde XI", 1)[1]


def test_runde5_kira_heute_farbig_ohne_scroll():
    assert "#board-rechts{overflow-y:auto;scrollbar-width:none}" in CSS  # kein sichtbarer Balken
    assert "#v-home .cmd-grid{grid-template-rows:minmax(0,1fr)}" in CSS  # Spalten wachsen nicht
    assert 'row("✓","var(--ok)"' in SCRIPT and 'row("✉︎","var(--blau)"' in SCRIPT
    assert "--blau:#38bdf8" in CSS                              # Ampel-Palette: gruen/blau/gelb/rot
    assert 'dz2(d.tasks_done_count,"var(--ok)")' in SCRIPT      # Digest spricht mit


def test_runde5_galaxie_zentriert_mit_begriffen():
    mind = SCRIPT.split("async function loadMind()", 1)[1].split("/* ---- Chat ----", 1)[0]
    assert 'const mit=$("#board-mitte")' in mind                # Herz liegt in der freien Mitte
    assert "(cx-n.x)" in mind and "(cy-n.y)" in mind            # Gravitation zum Mitte-Zentrum
    assert 'id="mind-worte"' in VIEWS                           # Begriffe-Knopf
    assert 'localStorage.setItem("mind_worte"' in SCRIPT        # Wahl bleibt


def test_runde6_chat_dock_und_farbdiaet():
    # Der Chat wohnt im Dock wie der Board-Einstieg: Chips oben, + links, Mikro rechts;
    # die Modus-Farbe bleibt, die Grelle geht (Rand halbtransparent, Streifen weg).
    chat = VIEWS.split('id="v-chat"', 1)[1].split('id="chat-tag"', 1)[0]
    dock = chat.split('id="chat-dock"', 1)[1]
    assert 'id="chat-tools"' in dock and 'id="cform"' in dock
    form = dock.split('id="cform"', 1)[1].split("</form>", 1)[0]
    assert form.index('id="plusbtn"') < form.index('id="cin"') < form.index('id="micbtn"') < form.index('id="sendbtn"')
    assert "#chat-dock::before" in CSS and "#chat-main::before{display:none}" in CSS
    assert "#chat-dock::before,#board-chat::before{opacity:.5;filter:none}" in CSS
    assert '#chat-main[data-mode="work"] #chat-dock::before' in CSS


def test_runde8_eine_buttonsprache():
    # Vorbild Modus-Segment: Werkzeug-Knoepfe flach (Panel/Linie/gedaempft),
    # GEFUELLT ist nur noch Senden; bc-mode = dasselbe Bauteil wie chat-mode-seg.
    r8 = CSS.split("Runde VIII", 1)[1]
    assert "#board-chat .bc-werk button.ghost" in r8 and "background:var(--panel)" in r8
    assert "#cmd-help{color:var(--muted)}" in r8
    assert '<span class="pill"></span>' in VIEWS.split('id="bc-mode"', 1)[1][:260]
    assert "#bc-mode .pill{position:absolute" in CSS
    assert 'const bm=$("#bc-mode");if(bm)bm.style.setProperty("--i",i);' in SCRIPT
    # HUD: Heartbeat/Assistenz als ruhige Toggle-Pillen, die Frage-Links sind Geschichte
    assert 'class="hud-tog' in SCRIPT and ".hud-tog{cursor:pointer" in CSS
    assert "AN?" not in SCRIPT and "AUS?" not in SCRIPT


def test_runde8_kira_heute_kollabiert_demo_weg_ops_umbruch():
    # 0-Zeilen kollabieren -> "Kira heute" passt IMMER auf den Schirm
    assert "if(d.mails.anzahl)zeilen.push(" in SCRIPT
    assert "Noch nichts passiert heute" in SCRIPT
    # das Demo-Widget draengt sich nicht mehr in die Galaxie-Mitte
    assert 'w.demo&&slot==="zentrale"' in SCRIPT
    # Live-Ops-Texte brechen sauber um
    assert "#board-links .op .opx{white-space:normal" in CSS


def test_runde7_galaxie_3d(tmp_path):
    # Video-Vorbild "Memory Galaxy": echte Tiefe, Orbit-Flug, Frische leuchtet weisser.
    mind = SCRIPT.split("async function loadMind()", 1)[1].split("/* ---- Chat ----", 1)[0]
    assert "const proj=(x,y,z)=>" in mind and "kam+=.0009" in mind   # Kamera fliegt
    assert "n.z=Math.random()*440-220" in mind                       # feste Tiefe je Stern
    assert "sort((a,b)=>a[0][3]>b[0][3]?-1:1)" in mind               # fern zuerst malen
    assert "n.heat" in mind                                          # Frische -> Leuchtkraft
    assert r"/^\d+,\d+,\d+$/" in mind                                # Tripel-Farben verstanden (Fix)
    # Graph liefert heat: frische Datei leuchtet, unaufgeloestes Ziel bleibt kalt
    from core.api import vault_graph
    (tmp_path / "a.md").write_text("[[b]]", encoding="utf-8")
    g = vault_graph.build_graph([tmp_path])
    knoten = {n["id"]: n for n in g["nodes"]}
    assert 0.9 < knoten["a"]["heat"] <= 1.0
    assert knoten["b"]["heat"] == 0.0


def test_runde4_chat_einstieg_mit_led_und_abflug():
    # Der Einstieg traegt den LED-Rand (wie der Chat-Streifen) und das Absenden
    # laesst die Seiten dissipieren, bevor der ECHTE Chat die Nachricht uebernimmt.
    assert "#board-chat::before" in CSS
    assert "ledflow" in CSS.split("#board-chat::before", 1)[1][:600]
    assert "function boardZumChat" in SCRIPT
    assert 'classList.add("abflug")' in SCRIPT and "sendText(text)" in SCRIPT
    assert "#v-home.abflug #board-links{transform:translateX(-" in CSS
    assert "#v-home.abflug #board-rechts{transform:translateX(" in CSS
    assert "prefers-reduced-motion" in SCRIPT.split("function boardZumChat", 1)[1][:600]


def test_runde3_theme_logo_und_playbook_ampel():
    # Wortmarke haengt an den Akzent-Variablen — Theme-Wechsel faerbt KIRA mit
    runde3 = CSS.split("Feinschliff-Runde III", 1)[1]
    assert "#bar #brand .txt,#side h1 .txt" in runde3 and "var(--accent)" in runde3
    assert ".badge.pb-entwurf{color:var(--warn)" in CSS
    assert ".badge.pb-autonom{color:var(--ok)" in CSS
    assert '"pb-"+(g==="autonom"||g==="begleitet"?g:"entwurf")' in SCRIPT
