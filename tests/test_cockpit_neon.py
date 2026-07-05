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
    # genau EIN default-aktiver Kira-Subview (v-files) — kein doppeltes 'on'
    assert VIEWS.count('class="subview on"') == 1


# ---- Stufe 2a: Zentrale-Auftragskarte mit Voice + Schwarm -------------------------------

def test_zentrale_voice_und_schwarm():
    # Mikro + Schwarm-Toggle + Rang auf der Befehlskarte
    for m in ('id="dir-mic"', 'id="dir-schwarm"', 'id="dir-rang"'):
        assert m in VIEWS, f"Zentrale-Bedienelement fehlt: {m}"
    # Diktier-Helfer und Schwarm-Routing im JS
    assert "function simpleRecord(" in SCRIPT
    assert 'simpleRecord("#dir-mic","#dir-text")' in SCRIPT
    assert '"/schwarm "+rang+" "' in SCRIPT and 'nav("chat")' in SCRIPT
