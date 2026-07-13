"""Cockpit-Umbau Stufe 1a (Neon Minimal): einfarbiger Hintergrund, Farbwähler,
Me->Me, Research raus, Chat-Modus-Feedback.

Reine Marker-/Struktur-Tests gegen CSS/VIEWS/SCRIPT (die UI ist Vanilla, kein Framework).
"""
from __future__ import annotations

from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.views import VIEWS
from core.api.ui.script import SCRIPT


# ---- Hygiene: keine undefinierten Loader (loadNeeds war toter Code -> ReferenceError) ----

def test_live_transkription_lokal():
    # Sprache wird waehrend der Aufnahme live (chunk-weise) lokal transkribiert -> waechst ins Feld
    assert "function startLive(" in SCRIPT and "function stopLive(" in SCRIPT
    assert "mediaRec.start(1200)" in SCRIPT and "/api/transcribe" in SCRIPT and "growCin()" in SCRIPT


def test_keine_undefinierten_load_funktionen():
    import re

    defined = set(re.findall(r"function (load[A-Za-z0-9_]+)\s*\(", SCRIPT))
    defined |= set(re.findall(r"(load[A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(", SCRIPT))
    called = set(re.findall(r"\b(load[A-Za-z0-9_]+)\s*\(", SCRIPT))
    assert not (called - defined), f"loadX() aufgerufen aber nicht definiert: {sorted(called - defined)}"
    assert "loadNeeds(" not in SCRIPT   # der konkrete Altlast-AUFRUF ist raus (Kommentar-Erwaehnung ok)


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


# ---- Me -> Me (Label geändert, data-v bleibt) -----------------------------------------

def test_me_heisst_serc():
    # seit Werkbank PR 7 haengt der Freigaben-Badge hinter dem Namen;
    # seit W2 traegt der Tab das __USER__-Token (Server injiziert den echten Namen)
    assert '> __USER__ <b id="side-frei"' in VIEWS
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
    # default-aktive Subviews: v-puls (Kira) + v-tag (Me, Werkbank PR 7) — kein doppeltes 'on' pro Tab
    assert VIEWS.count('class="subview on"') == 2


# ---- Stufe 2a: Zentrale-Auftragskarte mit Voice + Schwarm -------------------------------

def test_zentrale_voice_und_schwarm():
    # Mikro + Schwarm-Toggle + Rang auf der Befehlskarte
    for m in ('id="dir-mic"', 'id="dir-schwarm"', 'id="dir-rang"'):
        assert m in VIEWS, f"Zentrale-Bedienelement fehlt: {m}"
    # Diktier-Helfer und Schwarm-Routing im JS (Runde V: alles liest aus #bc-in)
    assert "function simpleRecord(" in SCRIPT
    assert 'simpleRecord("#dir-mic","#bc-in")' in SCRIPT
    assert '"/schwarm "+rang+" "' in SCRIPT and 'nav("chat")' in SCRIPT


# ---- Stufe 2b: Chat-Engine-Leiste (Modell als Neon-Pille neben dem Modus) ---------------

def test_chat_engine_leiste():
    # S11: der Modell-Knopf (engine-pill) sitzt in der Werkzeugleiste, oeffnet den Katalog
    assert 'id="model-btn" class="chip engine-pill"' in VIEWS
    assert VIEWS.count('id="chat-model"') == 1          # nur noch der versteckte Speicher
    assert 'type="hidden" id="chat-model"' in VIEWS
    # Pille faerbt mit dem Modus (--chat-accent)
    assert ".engine-pill" in CSS and "var(--chat-accent)" in CSS


# ---- Stufe 2c: Me mit Kira-artigen Subtabs -------------------------------------------

def test_serc_subtabs():
    assert 'id="me-tabs"' in VIEWS
    for sub in ('id="v-todos"', 'id="v-freigaben"', 'id="v-routinen"', 'id="v-post"', 'id="v-metriken"'):
        assert sub in VIEWS, f"Me-Subview fehlt: {sub}"
    # die Panels sind unter die richtigen Subviews gewandert (IDs unveraendert)
    for panel in ("id=\"life-board\"", "id=\"inbox-list\"", "id=\"me-crons\"", "id=\"me-mails\"", "id=\"life-metrics\""):
        assert panel in VIEWS
    # me ist in der SUBTABS-Registry (gleiche Mechanik wie Kira)
    assert 'me:      {bar:"#me-tabs"' in SCRIPT
    assert "freigaben:()=>{loadInbox();loadTodoSecrets();}" in SCRIPT
    # genau EIN default-aktiver Me-Subview
    assert VIEWS.count('class="subview on"') == 2   # v-puls (Kira) + v-tag (Me, Werkbank PR 7)


# ---- Chat/Coding-Werkbank: breiter Umschalter oben, Werkzeuge gebündelt, Modus-Farbe fix ----

def test_chat_werkbank():
    # Modus-Umschalter sitzt UNTEN-LINKS in der Werkzeugleiste (ueber dem "+"), vor dem Eingabeformular
    seg = VIEWS.index('id="chat-mode-seg"')
    log = VIEWS.index('id="log"')
    tools = VIEWS.index('id="chat-tools"')
    form = VIEWS.index('id="cform"')
    assert log < tools < seg < form
    # Mikro bleibt in der Werkbank; das Upload-"+" sitzt jetzt direkt am Eingabefeld
    mic = VIEWS.index('id="micbtn"')
    assert tools < mic < form                       # micbtn liegt im chat-tools-Block
    cform_block = VIEWS[form:VIEWS.index("</form>", form)]
    assert 'id="micbtn"' not in cform_block          # Mikro NICHT im Eingabeformular
    assert 'id="plusbtn"' in cform_block             # aber das "+" (Upload) schon
    # Modus-Farbe fix: Chat=Lila, Work=Grün, Coding=Rainbow(Cyan-Chrome), unabhängig vom Theme
    assert "--accent-chat:#b026ff" in CSS and "--work-accent:#39ff14" in CSS
    assert "#chat-main{--chat-accent:var(--accent-chat)}" in CSS
    assert '#chat-main[data-mode="coding"]{--chat-accent:var(--coding-accent)}' in CSS
    # Segmented-Slider: gleitende .pill, aktiver Teil folgt --i, unten links in der Werkzeugleiste
    assert "#chat-mode-seg{--i:0;position:relative" in CSS
    assert "#chat-mode-seg .pill{position:absolute" in CSS
    assert 'seg.style.setProperty("--i"' in SCRIPT   # Slider gleitet per JS


# ---- Chat-Politur: Gespräche nach rechts, Werkzeuge in eigener Box, kein Emoji-Wildwuchs ----

def test_chat_politur():
    # Gespräche rutschen per order:2 auf die RECHTE Seite (Chat rückt nach links)
    assert "order:2" in CSS
    assert "#sess-panel{width:0;margin-left:0;flex-shrink:0;order:2" in CSS  # zu = width:0 (sliden statt poppen)
    assert "#sess-panel.open{width:250px;margin-left:14px" in CSS           # auf = volle Breite
    # die vier Werkzeuge stecken jetzt in einer .toolbox statt lose in der Leiste
    assert '<span class="toolbox">' in VIEWS
    assert "#chat-tools .toolbox{display:inline-flex" in CSS
    # Vorlesen ohne Emoji davor
    assert "> 🔊 Vorlesen</label>" not in VIEWS
    assert "/> Vorlesen</label>" in VIEWS
    # Commands, Reasoning, Vorlesen & Sprechen liegen alle in der unteren Werkzeug-Box (vor dem Modell-Speicher)
    box_start = VIEWS.index('<span class="toolbox">')
    tools_end = VIEWS.index('id="chat-model"')
    for m in ('id="cmd-help"', 'id="chip-denk"', 'id="chip-tts"', 'id="micbtn"'):
        assert box_start < VIEWS.index(m) < tools_end, f"{m} fehlt in der Werkzeug-Box"
    # Mikro heisst jetzt "Sprechen" (kein Emoji mehr)
    assert ">Sprechen</button>" in VIEWS


# ---- Projekte-Tab entzerrt: Akte als eigener Kasten, Radar scrollt, kein "Venture" mehr ----

# ---- Ziele-Dashboard: Kennzahlen mit Ziel/Fortschritt, Kira schreibt selbst, Zentrale-Karte ----

def test_ziele_dashboard():
    # Me-Subtab heisst jetzt "Ziele", nicht mehr "Metriken"
    assert '>◎ Ziele</a>' in VIEWS          # Emoji-Sweep: flache Glyphe statt 🎯
    assert 'Metriken</a>' not in VIEWS
    assert "◈ ZIELE-DASHBOARD" in VIEWS
    # manuelles Eintragen + Zentrale-Karte fuer angeheftete Kennzahlen
    for m in ('id="zm-name"', 'id="zm-add"', 'id="z-ziele-panel"', 'id="z-ziele"'):
        assert m in VIEWS, f"Ziele-Element fehlt: {m}"
    # Dashboard-Renderer + Anheft-Logik + Zentrale-Loader
    assert "function loadZiele(" in SCRIPT and "function zieleCard(" in SCRIPT
    assert "async function loadZielePinned(" in SCRIPT
    assert "loadZielePinned()" in SCRIPT              # in der Zentrale aufgerufen
    assert 'metriken:()=>loadZiele()' in SCRIPT       # Loader umgehaengt
    assert '/api/metrics/meta' in SCRIPT              # Anheften/Ziel setzen


# ---- Automatisierungspanel: Uhrzeit/Intervall + freier Auftrag statt Ein-Knopf-Briefing ----

def test_automatisierungspanel():
    # der alte Morgen-Briefing-Einzelknopf ist weg, ein Panel ist da
    assert 'id="me-brief-setup"' not in VIEWS
    assert 'id="auto-panel"' in VIEWS
    for m in ('id="au-what"', 'id="au-time"', 'id="au-interval"', 'id="au-now"', 'id="au-add"'):
        assert m in VIEWS, f"Automatik-Feld fehlt: {m}"
    # Morgen-Briefing lebt als Schnell-Vorlage weiter (nicht mehr der einzige Weg)
    assert 'class="chip au-preset"' in VIEWS and 'Morgen-Briefing' in VIEWS
    # JS: legt eine Routine an (scope me), Preset fuellt das Feld
    assert '$("#au-add")' in SCRIPT and '"/api/cron/add"' in SCRIPT
    assert 'scope:"me"' in SCRIPT
    assert "$$('.au-preset')" in SCRIPT
    # der tote alte Handler ist raus
    assert '#me-brief-setup' not in SCRIPT


# ---- Radar konfigurierbar: der Nutzer sagt, wonach gesucht wird ----------------------------

# ---- Pro-Projekt-Uebersicht: auf einen Blick, was fuer Beispiel-Projekt getan wurde ----------------

# ---- Chat/Projekte-UX-Runde: 🗂 rechts, Befehls-Palette, Projekt klickt sich zu ----

def test_chatbutton_rechts_und_palette():
    # der 🗂-Umschalter sitzt jetzt rechts: nach dem Spacer im chatbar
    bar_start = VIEWS.index('id="chatbar"')
    bar_end = VIEWS.index("</div>", bar_start)
    bar = VIEWS[bar_start:bar_end]
    assert bar.index('flex:1') < bar.index('id="sess-toggle"'), "🗂 steht nicht rechts vom Spacer"
    # Befehls-Palette: Button + Popover + echte Befehle (mehr als die vier Chips)
    assert 'id="cmd-help"' in VIEWS and 'id="cmd-pop"' in VIEWS
    assert ".cmd-pop{position:absolute" in CSS
    assert "const CMDS=[" in SCRIPT and "function renderCmdPop(" in SCRIPT
    # /work & code: sind jetzt Modi (oben) — die Palette listet die uebrigen echten Befehle
    for cmd in ('"/plan ",', '"reason: ",', '"/model ",', '"/schwarm arbeiter'):
        assert cmd in SCRIPT, f"Befehl fehlt in der Palette: {cmd}"


# ---- Zentrale: Epicness statt grosser Emojis ----

def test_zentrale_epicness_ohne_grosse_emojis():
    # der Befehl-Header traegt keinen grossen Emoji mehr, sondern Glow/Typo
    assert "<h3>🎯 Befehl an __AGENT__</h3>" not in VIEWS
    # Runde V: der Befehl-Kasten ist im Board-Chat aufgegangen — der Header ist Geschichte
    assert "<h3>Befehl an __AGENT__</h3>" not in VIEWS
    assert ".direktive h3{margin:0 0 10px;color:var(--hud);text-transform:uppercase" in CSS
    # muted etwas heller fuer bessere Lesbarkeit (Inhalte verschwinden nicht mehr)
    assert "--muted:#9b97b0" in CSS


# ---- Zentrale-Schwarm-Baukasten: baut ein gueltiges /schwarm mit Items (nicht mehr leer) ----

def test_zentrale_schwarm_baut_items():
    # der kaputte Newline-Kollaps ('/schwarm rang auftrag' OHNE Items) ist raus
    assert 'p.replace(/\\s*\\n\\s*/g," ")' not in SCRIPT
    # neuer Baukasten: 1. Zeile = Vorlage, weitere Zeilen = Items -> "| a | b"
    assert 'const vorlage=lines[0],items=lines.slice(1)' in SCRIPT
    assert '"/schwarm "+rang+" "+vorlage+" | "+items.join(" | ")' in SCRIPT
    # ohne Ziele wird gewarnt statt einen leeren Schwarm abzuschicken
    assert "Schwarm braucht Ziele" in SCRIPT
    # der Toggle erklaert das Format (Placeholder mit {item})
    assert "1. Zeile = Auftrag mit {item}" in SCRIPT


# ---- Ehrlicher Live-Reasoning-Regler: Denk-Tiefe nur bei denk-faehigen Modellen ----

def test_denk_tiefe_regler_live():
    # der alte binaere "Reasoning"-Haken ist weg; stattdessen ein Denk-Tiefe-Select
    assert 'id="reason-on"' not in VIEWS
    assert 'id="reason-level"' in VIEWS and 'id="chip-denk"' in VIEWS
    # per Default versteckt (wird erst sichtbar, wenn das Modell denken kann)
    chip = VIEWS[VIEWS.index('id="chip-denk"'):VIEWS.index('id="chip-denk"')+240]
    assert "display:none" in chip
    # Live-Logik: Marker vom Server, Modell-Check, Show/Hide, denk:-Prefix beim Senden
    assert "function isReasoningModel(" in SCRIPT and "function syncDenk(" in SCRIPT
    assert "REASON_MARKERS=s.reasoning_markers" in SCRIPT
    assert 'syncDenk()' in SCRIPT
    assert 't="denk:"+rl.value+" "+t' in SCRIPT


# ---- Modell-Auswahl-Popover (alle Modelle, ehrliches Reasoning) + Upload-"+" am Eingabefeld ----

def test_modell_picker_und_plus_upload():
    # Modell-Knopf far right der Werkzeugleiste, oeffnet ein Popover; versteckter Speicher bleibt
    assert 'id="model-btn"' in VIEWS and 'id="model-pop"' in VIEWS
    assert 'type="hidden" id="chat-model"' in VIEWS
    # Popover laedt ALLE Modelle aus dem Katalog + zeigt Reasoning-Faehigkeit pro Modell
    assert "/api/model/catalog" in SCRIPT
    assert "function renderModelRows(" in SCRIPT
    assert "isReasoningModel(m.id)" in SCRIPT
    # Modellwahl setzt NUR die Chat-Rolle (nicht default -> reason/bulk bleiben unangetastet)
    assert "function useChatModel(" in SCRIPT and '"/api/model/role"' in SCRIPT
    assert 'role:"chat"' in SCRIPT
    assert ".model-pop{right:0" in CSS
    # das Upload-"+" sitzt links im Eingabeformular und traegt das Datei-Feld
    assert 'id="plusbtn"' in VIEWS and 'id="imgfile"' in VIEWS
    assert ".plus{flex-shrink:0" in CSS
    form = VIEWS.index('id="cform"')
    plus = VIEWS.index('id="plusbtn"')
    cin = VIEWS.index('id="cin"')
    assert form < plus < cin                          # "+" steht links VOR dem Eingabefeld


# ---- Chat-Werkbank 2.0: 3 Modi, ein Commands-Knopf, Reasoning-Popover, Stop-Button ----

def test_drei_modi_und_stop():
    # genau drei Modi im Slider: Chat / Work / Coding — mit generierten SVG-Icons (keine Emojis)
    assert 'data-m="chat" class="on">' in VIEWS
    _seg = VIEWS[VIEWS.index('id="chat-mode-seg"'):VIEWS.index("</div>", VIEWS.index('id="chat-mode-seg"'))]
    assert _seg.count('<svg class="mi"') == 3
    assert ">Chat</a>" in _seg and ">Work</a>" in _seg and ">Coding</a>" in _seg
    assert "💬" not in _seg and "⚙" not in _seg          # Emojis raus -> Icons
    assert 'data-m="plan"' not in VIEWS
    # Beschreibungstext neben den Buttons ist raus (der Nutzer kennt die Modi)
    assert 'id="mode-hint"' not in VIEWS
    # Work-Modus haengt "work:" an, Coding "code:" — beide im Send-Pfad
    assert 't="work: "+raw' in SCRIPT and 't="code: "+raw' in SCRIPT
    assert '--work-accent' in CSS and '#chat-main[data-mode="work"]' in CSS
    # die einzelnen Befehl-Chips sind weg; nur noch EIN Commands-Knopf + Palette
    for gone in ('id="chip-ziel"', 'id="chip-mission"', 'id="chip-status"', 'id="chip-plan"'):
        assert gone not in VIEWS, f"{gone} sollte weg sein"
    assert 'id="cmd-help"' in VIEWS and '⌘ Commands' in VIEWS
    # Stop-Button: Senden wird im Lauf zu Stop und bricht ab
    assert 'id="sendbtn"' in VIEWS
    assert "function setStreaming(" in SCRIPT and "function stopStream(" in SCRIPT
    assert 'if(streaming){stopStream();return;}' in SCRIPT
    assert "#sendbtn.stopping" in CSS
    # Stop nutzt reconnect(); der alte Socket wird stummgeschaltet -> kein Doppel-Socket beim Abbrechen
    assert "ws.onclose=null;ws.close()" in SCRIPT


def test_reasoning_popover_ehrlich():
    # Reasoning heisst "Reasoning" (nicht "Denken"), kein Emoji, eigenes Popover statt weissem Select
    assert 'Reasoning: Standard' in VIEWS
    assert 'Denken: Standard' not in VIEWS
    assert 'id="reason-pop"' in VIEWS and 'id="reason-level"' in VIEWS
    assert 'type="hidden" id="reason-level"' in VIEWS      # kein natives <select> mehr
    assert 'id="reason-level" style' not in VIEWS
    assert "function setReason(" in SCRIPT


# ---- Me/Kira-Subtableiste: durchgehend lila, weisse Schrift; aktiv = schwarz/lila ----

def test_subtab_leiste_lila():
    # Die prominente lila Leiste ist jetzt die GRUPPEN-Zeile (kira-groups); Me bleibt lila
    assert "#me-tabs,#kira-groups{background:var(--accent)" in CSS
    assert "#me-tabs a,#kira-groups a{color:#fff" in CSS
    assert "#me-tabs a.on,#kira-groups a.on{background:var(--bg);color:var(--accent)}" in CSS
    # Sub-Tabs sind dezent-sekundaer (nicht mehr vollflaechig lila)
    assert "#kira-tabs{background:transparent" in CSS


def test_kira_zwei_ebenen_navi():
    # S12 "4 klare Reiter": Puls · Kopf · Automatik · Maschinenraum (Klartext statt
    # Geist/Gewissen/Zustand). 'technik' bleibt tabu (lebt seit PR 3 im Einstellungen-Tab).
    assert 'id="kira-groups"' in VIEWS
    for g in ("puls", "kopf", "automatik", "maschine"):
        assert f'data-g="{g}"' in VIEWS
    assert 'data-g="technik"' not in VIEWS
    # JS: Gruppen filtern die Sub-Tabs; subnav fuehrt die aktive Gruppe mit
    assert "const KIRA_GROUPS=" in SCRIPT
    assert "function syncKiraGroup(" in SCRIPT and "function kiraGroup(" in SCRIPT
    assert 'tab==="kira"&&typeof syncKiraGroup==="function"' in SCRIPT
    # Alle KIRA-Sub-Tabs sind genau einer Gruppe zugeordnet; die Technik lebt im
    # Einstellungen-Tab (_SETTINGS_SUBS) weiter — nichts verloren.
    kg = SCRIPT[SCRIPT.index("const KIRA_GROUPS="):SCRIPT.index("function _kiraGroupOf")]
    for sub in ("files", "mem", "wissen", "gov", "cron", "monitor", "playbooks",
                "checkliste", "anatomie", "stats", "evolution", "log"):
        assert f'"{sub}"' in kg, f"Sub-Tab {sub} fehlt in KIRA_GROUPS"
    st = SCRIPT[SCRIPT.index("const _SETTINGS_SUBS="):]
    st = st[:st.index("]") + 1]
    for sub in ("models", "bench", "steuer", "keys", "cockpit", "wall"):
        assert f'"{sub}"' in st, f"Sub-Tab {sub} fehlt in _SETTINGS_SUBS"


def test_bg_kein_cache():
    # /api/bg darf nie aus dem Cache -> sonst haengt ein altes Hintergrundbild nach dem Wechsel
    import inspect
    from core.api import server
    src = inspect.getsource(server.api_bg)
    assert 'Cache-Control' in src and 'no-store' in src


def test_avatar_kein_cache():
    # Gleiches Muster wie /api/bg: sonst springt der Avatar nach dem Wechsel/Reload zurueck.
    import inspect
    from core.api import server
    src = inspect.getsource(server.api_avatar)
    assert 'Cache-Control' in src and 'no-store' in src
    # Frontend haengt eine Version an (Cache-Buster), die sich beim Wechsel aendert
    assert 'avatarV=Date.now()' in SCRIPT
    assert '"/api/avatar?t="+avatarV' in SCRIPT
    # Markup laedt nicht mehr die feste (cachebare) URL — JS setzt die versionierte
    assert 'id="hero-av" alt=""/>' in VIEWS and 'src="/api/avatar"' not in VIEWS


# ---- Grosses Anpass-Panel: mehr Farbregler + Schriftart, alles live/persistent ----

def test_anpass_panel_gross():
    # neue Farbwaehler im Theme-Popover
    for m in ('id="col-hud"', 'id="col-ink"', 'id="col-muted"', 'id="col-line"', 'id="font-sel"'):
        assert m in VIEWS, f"Regler fehlt: {m}"
    # applyCustom setzt die neuen Variablen
    for prop in ('"--hud",c.hud', '"--ink",c.ink', '"--muted",c.muted', '"--line",c.line', '"--font",c.font'):
        assert prop in SCRIPT, f"applyCustom setzt {prop} nicht"
    # Bindings + Font-Auswahl
    assert 'bindColor("#col-ink","ink"' in SCRIPT and 'bindColor("#col-hud","hud"' in SCRIPT
    assert '$("#font-sel")' in SCRIPT
    # Schrift ist jetzt eine Variable (vorher hart) + Sidebar-Text folgt --ink
    assert "font-family:var(--font," in CSS
    assert "#side h1{" in CSS and "color:var(--ink)" in CSS


# ---- Heute-Karte voller: heute angefasste Dateien + Ausgaben ----

def test_heute_karte_voller():
    assert "d.artifacts&&d.artifacts.length" in SCRIPT      # heute angefasste Dateien
    assert "Ausgaben heute" in SCRIPT                        # Tagesausgabe
    assert "Noch ruhig heute" in SCRIPT                      # Leerzustand-Fallback


# ---- Fehler ehrlich: 7-Tage-Fenster statt All-Time, klickbar zum Protokoll ----

def test_fehler_fenster_klickbar():
    assert "st.errors_recent" in SCRIPT                      # HUD nutzt das Fenster
    assert 'id="hud-errs"' in SCRIPT and 'subnav("kira","log")' in SCRIPT
    assert "Fehler · 7 Tg" in SCRIPT


def test_count_since_backend(tmp_path, monkeypatch):
    import time as _t
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "e.db"))
    events.init_db()
    events.emit("turn_timeout", {}); events.emit("service_crash", {}); events.emit("user_message", {})
    types = ("turn_timeout", "llm_call_timeout", "service_crash", "act_degraded")
    assert events.count_since(types, _t.time() - 7 * 86400) == 2
    assert events.count_since(types, _t.time() + 999) == 0   # Zukunfts-Cutoff -> nichts
    assert events.count_since((), 0) == 0                    # keine Typen -> 0


# ---- Chat-Datei-Anhang: "+" nimmt auch PDF/Dateien, Text geht an Kira ----

def test_chat_attach_ui():
    # "+" akzeptiert jetzt auch Dokumente (nicht nur Bilder)
    assert 'accept="image/*,.pdf,.txt' in VIEWS
    # Routing: Bild -> Vision, sonst -> attachFile -> /api/chat/attach an Kira
    assert 'f.type.startsWith("image/")' in SCRIPT
    assert "function attachFile(" in SCRIPT and '"/api/chat/attach"' in SCRIPT
    assert "[Angehaengte Datei:" in SCRIPT


# ---- Hover-Chats: Drueberfahren oeffnet, Klick pinnt (Hover-Intent) ----

def test_gespraeche_hover_intent():
    # Hover oeffnet ueber mouseenter (nicht mehr nur onclick-Toggle)
    assert 'b.addEventListener("mouseenter",open)' in SCRIPT
    # Gnadenfrist gegen das Zuschnappen beim diagonalen Rueberziehen (400ms)
    assert "setTimeout(hide,400)" in SCRIPT
    # Panel haelt offen, solange die Maus drueber ist
    assert 'p.addEventListener("mouseenter",()=>clearTimeout(t))' in SCRIPT
    # Klick pinnt und merkt den Zustand (Touch-/Fallback-Weg bleibt)
    assert 'localStorage.setItem("kira_sess_open"' in SCRIPT
    assert 'b.classList.toggle("pinned"' in SCRIPT
    # sichtbarer Pin-Zustand am Button
    assert "#sess-toggle.pinned{" in CSS
    # sanftes Reinsliden: Breite wird animiert statt hartem display-Wechsel
    assert "transition:width .42s" in CSS and "#sess-panel{width:0" in CSS


# ---- Wordmark: KIRA gross in Audiowide mit Neon-Lila-Glow, Untertitel raus ----

def test_kira_wordmark_cyberpunk():
    # Schrift ist offline eingebettet (kein CDN) und nur fuer den Titel
    assert "@font-face{font-family:'Audiowide'" in CSS
    assert "data:font/woff2;base64," in CSS
    # Titel nutzt Audiowide, ist groesser + Verlauf-im-Text (background-clip) + drop-shadow-Glow
    # (der Schriftzug ist der Fallback .txt, wenn kein App-Logo /api/icon geladen wird)
    assert "#side h1 .txt{display:block;font-family:'Audiowide'" in CSS
    assert "font-size:33px" in CSS and "background-clip:text" in CSS
    assert "-webkit-text-fill-color:transparent" in CSS and "drop-shadow(" in CSS
    assert "@keyframes kiraflow{" in CSS       # Verlauf fliesst (Regenbogen in Lila)
    # Untertitel 'kira · cockpit' ist weg — Element UND JS-Schreiber
    assert 'id="who"' not in VIEWS and 'class="sub"' not in VIEWS
    assert "#who" not in SCRIPT


# ---- Dashboard-Entschlackung (Zentrale): PR 1 aus dem IA-Audit ----

def test_dashboard_entschlackt():
    # Befehl-an-Kira nicht mehr vollbreit (1120 -> 560)
    assert ".direktive{max-width:560px" in CSS and "max-width:1120px" not in CSS
    # HUD-Streifen: eine nicht-umbrechende Reihe (scrollt horizontal statt in 3 Reihen zu brechen)
    assert ".hud-strip{display:flex;flex-wrap:nowrap" in CSS
    # Scroll-Falle weg: der innere News-Scroll ist entfernt
    assert "#news-list{max-height:30vh" not in CSS
    # Hero flacher (Avatar 50 statt 74)
    assert "#hero-av{width:50px;height:50px" in CSS
    # Live-Ops: 'info'-Filter neu + Zaehler-Badges
    assert 'data-of="info"' in VIEWS and 'class="ofc"' in VIEWS
    assert "#ops-filter a[data-of=error] .ofc" in CSS
    # Filter rendert clientseitig aus Cache (kein Refetch pro Klick)
    assert "let _opsCache=" in SCRIPT and "function renderOps(" in SCRIPT
    assert 'x===a));renderOps();' in SCRIPT and 'x===a));loadOps();' not in SCRIPT
    # Werkbank PR 6: Schnellzugriff-Karte ist ersatzlos raus (Sidebar reicht),
    # Lektionen leben im 'Kira heute'-Panel, News nur noch als Laufband unterm HUD.
    assert '"Schnellzugriff"' not in SCRIPT
    assert "z-lektionen" in SCRIPT and "ZULETZT GELERNT" in SCRIPT
    assert "news-moretog" not in SCRIPT and 'id="news-list"' not in VIEWS


# ---- Chat-Politur v2: Thinking-Klappe gefixt + Typewriter ----

def test_thinking_klappe_und_typewriter():
    # Bug war: Einklappen setzte display:none auf den GANZEN Block inkl. Kopf -> gebunden.
    assert "white-space:pre-wrap;display:block}" in CSS       # .think bleibt immer sichtbar
    assert ".think.show{display:block}" not in CSS            # der alte Verschwind-Toggle ist raus
    # Eingeklappt = Peek der ersten ~4 Zeilen (max-height + Fade), ausgeklappt = voll, smooth
    assert ".think .c{white-space:normal;overflow:hidden;max-height:5.4em" in CSS
    assert ".think.show .c{max-height:9999px" in CSS
    assert ".think .chev{" in CSS and 'class="chev"' in SCRIPT   # Chevron dreht beim Klappen
    # Denkstrom tippt sich rein (Typewriter via rAF) statt als Block zu spawnen
    assert "curThinkLine._buf" in SCRIPT and "requestAnimationFrame(tick)" in SCRIPT


def test_denk_status_neon_rainbow():
    # Der Denk-Status ("kocht…/denkt…") fliesst im Neon-Rainbow — dort wo Textfarbe geht (Web)
    assert "@keyframes rainflow{" in CSS
    assert ".tx.live{background:linear-gradient(90deg,#b026ff,#ff2d95" in CSS
    assert "animation:rainflow" in CSS
    # der Live-Status ist auch die Ueberschrift des Denk-Traces (rotierende Phrase, EIN Timer)
    assert "function refreshPhrase(" in SCRIPT and '.tx.live' in SCRIPT
    assert '<span class="tx live">' in SCRIPT          # Trace-Ueberschrift traegt den Rainbow-Status


# ---- Chat-Layout-Fix: LED-Balken oben, Slider unten links, Trace klappt zu, kein Ueberlappen ----

def test_led_bar_und_slider_unten():
    # der obere Modus-Balken rotiert die Farben wie eine LED-Tastatur (kein Puls/Flackern mehr)
    assert "@keyframes ledflow{" in CSS
    assert "#chat-main::before{" in CSS and "animation:ledflow" in CSS
    assert "@keyframes beatglow{" not in CSS            # der alte Puls ist raus
    # dicker Balken (5px) + per Modus eigene LED-Farbwelt: Chat=Lila, Work=Gruen, Coding=Rainbow
    assert "right:0;height:5px" in CSS
    assert '#chat-main[data-mode="work"]::before{background-image:linear-gradient(90deg,#0aff9d,#39ff14' in CSS
    assert '#chat-main[data-mode="coding"]::before{background-image:linear-gradient(90deg,#ff004d,#ff8a00' in CSS
    # Slider sitzt wieder UNTEN links in der Werkzeugleiste
    assert "#chat-tools #chat-mode-seg{flex:0 0 auto" in CSS


def test_trace_klappt_bei_neuem_schritt_zu():
    # Denk-Trace startet eingeklappt (Peek) und klappt bei jedem neuen Schritt automatisch wieder zu
    assert 'curThink.className="think"' in SCRIPT          # kein "show" default -> eingeklappt
    assert "function traceLive(" in SCRIPT
    assert "function settleTrace(" in SCRIPT               # nach dem Lauf: Rainbow beruhigt sich
    assert 'curThink.classList.contains("show"))curThink.classList.remove("show")' in SCRIPT


def test_chat_kein_ueberlappen():
    # Ueberlappen von Chat-Ende und Werkzeugleiste: der Log-Flex darf schrumpfen (min-height:0),
    # sonst waechst er ueber die Leiste hinweg statt intern zu scrollen
    assert "#log{flex:1;min-height:0;overflow:auto" in CSS
    assert "#chat-main{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0}" in CSS
