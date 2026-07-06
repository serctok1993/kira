"""Cockpit-Umbau Stufe 1a (Neon Minimal): einfarbiger Hintergrund, Farbwähler,
Me->Serc, Research raus, Chat-Modus-Feedback.

Reine Marker-/Struktur-Tests gegen CSS/VIEWS/SCRIPT (die UI ist Vanilla, kein Framework).
"""
from __future__ import annotations

from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.views import VIEWS
from core.api.ui.script import SCRIPT


# ---- Einfarbiger Hintergrund: Fläche = --bg, Kästen = --panel ---------------------------

def test_flaechen_einfarbig():
    # Sidebar + Topbar nicht mehr eigener Ton/Verlauf -> var(--bg)
    assert "linear-gradient(180deg,rgba(14,14,18" not in CSS
    assert "rgba(13,9,20" not in CSS
    assert "#side{background:var(--bg)}" in CSS
    # --panel2 ist auf --panel gemergt (keine dritte Fläche)
    assert "--panel2:var(--panel)" in CSS
    # Kästen tragen die EINE Kastenfarbe, kein milchiges rgba/blur mehr
    assert "rgba(16,16,20,.72)" not in CSS
    assert ".card{background:var(--panel)" in CSS


# ---- Farbwähler -------------------------------------------------------------------------

def test_farbwaehler_vorhanden():
    for m in ('id="col-bg"', 'id="col-panel"', 'id="col-accent"', 'id="col-reset"'):
        assert m in VIEWS, f"Farbwähler-Feld fehlt: {m}"
    for m in ("function applyCustom(", "kira_custom", 'setProperty("--bg"', 'setProperty("--panel"',
              'setProperty("--accent"', '#col-reset'):
        assert m in SCRIPT, f"Farbwähler-Logik fehlt: {m}"
    assert "#theme-pop .colrow" in CSS


# ---- Me -> Serc (Label geändert, data-v bleibt) -----------------------------------------

def test_me_heisst_serc():
    assert "> Serc</a>" in VIEWS
    assert 'data-v="me"' in VIEWS        # Hooks/Loader bleiben unangetastet
    assert "> Me</a>" not in VIEWS


# ---- Research raus ----------------------------------------------------------------------

def test_research_entfernt():
    assert 'data-m="research"' not in VIEWS
    assert 'data-m="chat"' in VIEWS and 'data-m="coding"' in VIEWS
    assert 'chatMode==="research"' not in SCRIPT   # toter Routing-Zweig entfernt


# ---- Chat-Modus-Feedback ----------------------------------------------------------------

def test_chat_modus_feedback():
    assert "function applyChatMode(" in SCRIPT
    assert 'setAttribute("data-mode"' in SCRIPT
    assert '#chat-main[data-mode="coding"]' in CSS   # Coding faerbt gruen
    assert "--chat-accent" in CSS


# ---- Stufe 1b: Config aufgelöst, Technik unter Kira -------------------------------------

def test_config_aufgeloest():
    # kein Config-Tab, keine eigene Leiste mehr
    assert 'data-v="config"' not in VIEWS
    assert 'id="sys-tabs"' not in VIEWS and 'id="v-config"' not in VIEWS
    # die Technik-Subtabs hängen jetzt an der Kira-Leiste
    for link in ('data-s="models"', 'data-s="steuer"', 'data-s="gov"', 'data-s="cron"',
                 'data-s="monitor"', 'data-s="log"', 'data-s="cockpit"'):
        assert link in VIEWS
    # und ihre Loader wohnen in SUBTABS.kira (config-Eintrag ist weg)
    assert "config:  {bar:" not in SCRIPT
    for ld in ("models:()=>loadModels()", "steuer:()=>loadSteuer()", "cron:()=>loadCron()",
               "cockpit:()=>loadDesktop()"):
        assert ld in SCRIPT
    # default-aktive Subviews: v-files (Kira) + v-todos (Serc) — kein doppeltes 'on' pro Tab
    assert VIEWS.count('class="subview on"') == 2


# ---- Stufe 2a: Zentrale-Auftragskarte mit Voice + Schwarm -------------------------------

def test_zentrale_voice_und_schwarm():
    # Mikro + Schwarm-Toggle + Rang auf der Befehlskarte
    for m in ('id="dir-mic"', 'id="dir-schwarm"', 'id="dir-rang"'):
        assert m in VIEWS, f"Zentrale-Bedienelement fehlt: {m}"
    # Diktier-Helfer und Schwarm-Routing im JS
    assert "function simpleRecord(" in SCRIPT
    assert 'simpleRecord("#dir-mic","#dir-text")' in SCRIPT
    assert '"/schwarm "+rang+" "' in SCRIPT and 'nav("chat")' in SCRIPT


# ---- Stufe 2b: Chat-Engine-Leiste (Modell als Neon-Pille neben dem Modus) ---------------

def test_chat_engine_leiste():
    # genau EIN Modell-Select, jetzt als Engine-Pille (nicht mehr grau im Werkzeug-Bereich)
    assert VIEWS.count('id="chat-model"') == 1
    assert 'id="chat-model" class="engine-pill"' in VIEWS
    assert 'id="chat-model" title="Modell fuer diesen Chat" style="max-width:190px"' not in VIEWS
    # steht in der Modus-Leiste (nach dem Umschalter, vor dem Spacer)
    seg = VIEWS.index('id="chat-mode-seg"')
    mod = VIEWS.index('id="chat-model"')
    assert seg < mod
    # Pille faerbt mit dem Modus (--chat-accent)
    assert "select.engine-pill" in CSS and "var(--chat-accent)" in CSS


# ---- Stufe 2c: Serc mit Kira-artigen Subtabs -------------------------------------------

def test_serc_subtabs():
    assert 'id="me-tabs"' in VIEWS
    for sub in ('id="v-todos"', 'id="v-freigaben"', 'id="v-routinen"', 'id="v-post"', 'id="v-metriken"'):
        assert sub in VIEWS, f"Serc-Subview fehlt: {sub}"
    # die Panels sind unter die richtigen Subviews gewandert (IDs unveraendert)
    for panel in ("id=\"life-board\"", "id=\"inbox-list\"", "id=\"me-crons\"", "id=\"me-mails\"", "id=\"life-metrics\""):
        assert panel in VIEWS
    # me ist in der SUBTABS-Registry (gleiche Mechanik wie Kira)
    assert 'me:      {bar:"#me-tabs"' in SCRIPT
    assert "freigaben:()=>{loadInbox();loadTodoSecrets();}" in SCRIPT
    # genau EIN default-aktiver Serc-Subview
    assert VIEWS.count('class="subview on"') == 2   # v-files (Kira) + v-todos (Serc)


# ---- Chat/Coding-Werkbank: breiter Umschalter oben, Werkzeuge gebündelt, Modus-Farbe fix ----

def test_chat_werkbank():
    # Modus-Umschalter steht VOR der Werkzeugleiste und dem Eingabeformular
    seg = VIEWS.index('id="chat-mode-seg"')
    tools = VIEWS.index('id="chat-tools"')
    form = VIEWS.index('id="cform"')
    assert seg < tools < form
    # Mikro + Anhang sind in die Werkbank gewandert; cform hat sie nicht mehr
    mic = VIEWS.index('id="micbtn"')
    assert tools < mic < form                       # micbtn liegt im chat-tools-Block
    # cform enthält nur noch Eingabe + Senden (kein micbtn/imgbtn dazwischen)
    cform_block = VIEWS[form:VIEWS.index("</form>", form)]
    assert 'id="micbtn"' not in cform_block and 'id="imgbtn"' not in cform_block
    # Modus-Farbe fix: Chat=Violett, Coding=Grün, unabhängig vom Theme
    assert "--accent-chat:#b026ff" in CSS and "--coding-accent:#39ff14" in CSS
    assert "#chat-main{--chat-accent:var(--accent-chat)}" in CSS
    assert '#chat-main[data-mode="coding"]{--chat-accent:var(--coding-accent)}' in CSS
    # breiter, gefüllter Aktiv-Tab
    assert "#chat-mode-seg{display:flex;width:100%" in CSS
    assert "#chat-mode-seg a.on{color:#fff;background:color-mix" in CSS
