"""Cockpit-Markup: Sidebar-Navigation + alle View-Container.

S7a — Cockpit 2.0, modulare Shell (Sergens Redesign-Auftrag):
  Zentrale (home)      fester Kommandostand: Hero, HUD, Befehl, Live-Ops, Digest, News
  Chat (chat)          Hauptdialog (Chat 2.0 folgt in S7c)
  Me (me)              beides getrennt: deine Auftraege an Kira / was Kira von dir braucht
                       + Zugangs-Anfragen, E-Mail-Bereich (Empty-State bis Postfach), Metriken
  Kira (kira)          Subtabs: Seele & Dateien / Gedaechtnis / Wissen / Anatomie / Statistik
  Config (config)      rein technisch: Modelle / Zugaenge / Gewissen / Cron / Monitor /
                       Protokoll / Cockpit (Avatar, Optik, Icons, Neustart)
Shell-Prinzip: EINE Subtab-Mechanik (script.py SUBTABS-Registry); neuer Bereich oder
Unterreiter = Registry-Eintrag + <div class="subview" id="v-...">. Theme-Umschalter
sitzt als Icon+Popover in der Topbar (nicht mehr in der Nav). Panel-IDs sind stabil.
"""

VIEWS = r"""</head><body>
<div id="side">
  <h1 id="brand"><span class="txt">KIRA</span></h1>
  <a data-v="home" class="on" title="Kommandostand: Status, Befehl, Live-Ops, Digest"><i class="ti">◈</i> Zentrale</a>
  <a data-v="chat" title="Mit mir reden"><i class="ti">›</i> Chat</a>
  <a data-v="me" title="Dein Bereich: Todos, Freigaben, was Kira von dir braucht, deine Routinen"><i class="ti">☰</i> Serc <b id="side-frei" class="frei-badge" style="display:none"></b></a>
  <a data-v="kira" title="Wer ich bin: Seele, Gedaechtnis, Wissen, Gewissen, Automatik, Lernen"><i class="ti">✦</i> Kira</a>
  <a data-v="settings" title="Einstellungen: Modelle, Benchmark, Steuerpult, Zugaenge, Cockpit, Wallpaper"><i class="ti">⚙</i> Einstellungen</a>
  <div class="spacer"></div>
  <div class="kill" id="kill">Not-Aus: aus</div>
</div>
<div id="main">
  <div id="bar">
    <a id="burger" title="Menue">☰</a>
    <span class="live"></span>
    <span id="pulse" class="pulse">…</span>
    <span style="flex:1"></span>
    <span id="ws-dot" class="off" title="Chat-Verbindung"></span>
    <span class="muted"><b id="b-model">…</b></span>
    <span class="muted">heute <b id="b-spend">…</b></span>
    <span id="b-kill"></span>
    <a id="gear" title="Einstellungen (Modelle, Steuerpult, Zugänge, Cockpit, Wallpaper)" style="cursor:pointer;font-size:16px;padding:0 4px">⚙</a>
    <span id="theme-wrap">
      <a id="theme-btn" title="Optik anpassen">◐</a>
      <div id="theme-pop" class="look">
        <button class="thm on" data-theme="" title="Schwarz / Lila (Standard)"><span class="td" style="background:#8b5cf6"></span></button>
        <button class="thm" data-theme="gruen" title="Schwarz / Gruen"><span class="td" style="background:#22c55e"></span></button>
        <button class="thm" data-theme="blau" title="Schwarz / Blau"><span class="td" style="background:#3b82f6"></span></button>
        <button class="thm" data-theme="amber" title="Schwarz / Amber (Retro-Terminal)"><span class="td" style="background:#f59e0b"></span></button>
        <button class="thm" data-theme="rot" title="Schwarz / Rot (Crimson)"><span class="td" style="background:#f43f5e"></span></button>
        <button class="thm kira" id="thm-kira" data-theme="kira" title="Kira-Modus (Bild-Hintergrund)"></button>
        <label id="bgup" title="Hintergrund-Bild waehlen" style="cursor:pointer;color:var(--muted);font-size:15px">📷<input id="bgquick" type="file" accept="image/*" style="display:none"/></label>
        <div class="colrow">
          <label>BG<input type="color" id="col-bg" title="Hintergrund-Farbe"/></label>
          <label>Kästen<input type="color" id="col-panel" title="Kasten-Farbe"/></label>
          <label>Neon<input type="color" id="col-accent" title="Akzent/Neon-Farbe"/></label>
          <label>HUD<input type="color" id="col-hud" title="HUD/Ueberschriften-Farbe"/></label>
          <label>Text<input type="color" id="col-ink" title="Schrift-Farbe (auch Seitenleiste)"/></label>
          <label>Grau<input type="color" id="col-muted" title="Gedaempfte Schrift"/></label>
          <label>Linien<input type="color" id="col-line" title="Linien &amp; Rahmen"/></label>
          <a id="col-reset" title="Alles zuruecksetzen">↺</a>
        </div>
        <div class="colrow fontrow">
          <label style="flex-direction:row;gap:6px;font-size:10px;color:var(--muted)">Schrift
            <select id="font-sel" title="Schriftart fuers ganze Dashboard">
              <option value="">Standard (System)</option>
              <option value="Georgia,'Times New Roman',serif">Serif (Georgia)</option>
              <option value="'Segoe UI',system-ui,sans-serif">Segoe / Sans</option>
              <option value="'Trebuchet MS','Gill Sans',sans-serif">Trebuchet</option>
              <option value="Verdana,Geneva,sans-serif">Verdana</option>
              <option value="ui-monospace,Consolas,monospace">Mono</option>
            </select>
          </label>
        </div>
      </div>
    </span>
  </div>

  <!-- ================= ZENTRALE ================= -->
  <div class="view on" id="v-home">
    <div id="hero">
      <img id="hero-av" alt=""/>
      <div id="hero-txt">
        <div id="hero-name">KIRA</div>
        <div id="hero-status" class="muted">…</div>
      </div>
    </div>
    <div class="hud-strip" id="hud-strip"></div>
    <!-- Werkbank PR 6: Intel als 1-Zeilen-Laufband direkt unterm HUD (grosses Panel entfaellt) -->
    <div style="display:flex;align-items:center;gap:8px;margin:2px 0">
      <div class="ticker" id="news-ticker" style="flex:1;min-width:0"><span>… Intel wird geladen …</span></div>
      <a id="news-seed" class="muted" style="cursor:pointer;font-size:10px;white-space:nowrap">+ Quellen</a>
    </div>
    <!-- Feedback 09.07.: die Luecke neben dem Befehl gehoert den Widgets (Kira blendet
         hier per widget_add Kacheln ein — Follower, Kennzahlen, Listen) -->
    <div class="dir-row">
    <div class="direktive">
      <h3>Befehl an Kira</h3>
      <textarea id="dir-text" class="k" placeholder="Sag mir, worauf ich mich konzentrieren soll — oder gib mir einen Sofort-Auftrag…"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
        <button type="button" class="ghost" id="dir-mic" title="Auftrag diktieren (Voice)">🎤</button>
        <button id="dir-now">⚡ Sofort ausfuehren</button>
        <button class="ghost" id="dir-focus">🧭 Als Fokus setzen</button>
        <button class="ghost" id="dir-clear" title="Fokus loeschen">Fokus loeschen</button>
        <label class="chip tog" id="dir-schwarm-l" title="Als Schwarm-Auftrag an die Armee — landet im Chat, du drueckst Senden"><input type="checkbox" id="dir-schwarm"/> 🐝 Schwarm</label>
        <select id="dir-rang" title="Rang fuer den Schwarm" style="display:none">
          <option value="reflex">🐜 reflex</option><option value="arbeiter" selected>🔧 arbeiter</option><option value="denker">🧠 denker</option><option value="richter">⚖ richter</option>
        </select>
        <span class="muted" id="dir-hint" style="align-self:center"></span>
      </div>
      <div id="dir-result" style="margin-top:8px;white-space:pre-wrap;display:none;border-top:1px solid var(--line);padding-top:8px"></div>
    </div>
    <div id="widgets-home" class="wslot"></div>
    </div>
    <div class="cmd-grid">
      <div class="cmd-main">
        <div class="panel">
          <div class="panel-h">◈ Live-Ops <span class="live"></span><span class="sp"></span>
            <span class="seg" id="ops-filter"><a data-of="all" class="on">alle <b class="ofc"></b></a><a data-of="action">aktionen <b class="ofc"></b></a><a data-of="info">info <b class="ofc"></b></a><a data-of="chat">chat <b class="ofc"></b></a><a data-of="error">fehler <b class="ofc"></b></a></span>
          </div>
          <div id="ops-feed"><span class="muted" style="padding:10px 13px;display:block">…</span></div>
        </div>
      </div>
      <div class="cmd-side">
        <!-- Werkbank PR 6: EIN Erst-Blick-Panel — was Kira heute tat, was ansteht, was sie lernte -->
        <div class="panel">
          <div class="panel-h">◈ Kira heute <span class="sp"></span><a id="go-tagewerk" class="muted" style="cursor:pointer;font-size:10px">→ Detail</a></div>
          <div id="tagewerk" class="panel-b"><span class="muted">…</span></div>
          <div id="digest" class="panel-b" style="border-top:1px solid var(--line)"><span class="muted">…</span></div>
          <div id="z-lektionen" class="panel-b" style="display:none;border-top:1px solid var(--line)"></div>
        </div>
        <div class="panel" id="z-ziele-panel" style="display:none">
          <div class="panel-h">◈ Kennzahlen <span class="sp"></span><a id="go-ziele" class="muted" style="cursor:pointer;font-size:10px">→ Ziele</a></div>
          <div id="z-ziele" class="panel-b"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ================= CHAT ================= -->
  <div class="view" id="v-chat">
    <div id="chat-wrap">
      <div id="sess-panel">
        <div class="sp-h"><span class="muted" style="font-size:11px;letter-spacing:1px">GESPRAECHE</span>
          <span style="flex:1"></span><button type="button" class="ghost" id="sess-test" title="Test-Chat: zum gefahrlosen Ausprobieren — dieser Verlauf leckt NICHT in Kiras Langzeit-Gedaechtnis (andere Chats sehen ihn nie)" style="padding:4px 9px">🧪</button><button type="button" class="ghost" id="sess-new" title="Neue Unterhaltung (getrennt von der Tages-Session)" style="padding:4px 9px">＋</button></div>
        <div id="sess-items"><div class="muted" style="padding:10px">…</div></div>
        <div class="sp-f"><a id="sess-archtoggle" class="muted" style="cursor:pointer;font-size:11px">Archiv anzeigen</a></div>
      </div>
      <div id="chat-main">
        <div id="chatbar" style="display:flex;gap:8px;align-items:center;padding:0 0 8px;flex-wrap:wrap">
          <span style="flex:1"></span>
          <button type="button" class="ghost" id="sess-toggle" title="Drueberfahren = Gespraeche auf · Klick = angepinnt (bleibt offen)" style="padding:5px 12px;font-size:12px">Chats</button>
        </div>
        <div id="log"></div>
        <!-- Werkbank UNTEN: Modus-Slider links (direkt ueber dem "+") · Werkzeuge rechts -->
        <div id="chat-tools">
          <div id="chat-mode-seg" title="Chat = Dialog (DeepSeek) · Work = laengerer Auftrag mit vollem Werkzeug-Budget (GLM) · Coding = an Kira schrauben (Plan + Schritte + Diff-Review)">
            <span class="pill"></span>
            <a data-m="chat" class="on"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>Chat</a><a data-m="work"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>Work</a><a data-m="coding"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>Coding</a>
          </div>
          <span style="flex:1"></span>
          <span class="toolbox">
            <span style="position:relative;display:inline-block">
              <span class="chip" id="cmd-help" title="Alle Befehle anzeigen">⌘ Commands</span>
              <div id="cmd-pop" class="cmd-pop" style="display:none"></div>
            </span>
            <span style="position:relative;display:inline-block">
              <button type="button" class="chip tog" id="chip-denk" title="Reasoning-Tiefe — nur bei denk-faehigen Modellen (GLM, Fable). Steuert, wie gruendlich das Modell vor der Antwort denkt (Token-Hebel)." style="display:none">Reasoning: Standard</button>
              <div id="reason-pop" class="cmd-pop reason-pop" style="display:none">
                <div class="cmd-row" data-rl="">Standard</div>
                <div class="cmd-row" data-rl="aus">aus</div>
                <div class="cmd-row" data-rl="niedrig">niedrig</div>
                <div class="cmd-row" data-rl="hoch">hoch</div>
              </div>
              <input type="hidden" id="reason-level"/>
            </span>
            <label class="chip tog" id="chip-tts" title="Kira liest ihre Antworten laut vor (Stimme muss unter Kira → Zugaenge an sein)"><input type="checkbox" id="tts-on"/> Vorlesen</label>
            <button type="button" id="micbtn" class="chip" title="Sprachmemo aufnehmen — Kira hoert zu">Sprechen</button>
          </span>
          <span style="position:relative;display:inline-block">
            <button type="button" id="model-btn" class="chip engine-pill" title="Modell fuer diesen Chat — klick fuer alle Modelle">Modell</button>
            <div id="model-pop" class="cmd-pop model-pop" style="display:none"></div>
          </span>
          <input type="hidden" id="chat-model"/>
        </div>
        <form id="cform">
          <label id="plusbtn" class="plus" title="Bild oder Datei (PDF, txt, md, csv) hochladen">+<input id="imgfile" type="file" accept="image/*,.pdf,.txt,.md,.markdown,.csv,.log,.json,.yaml,.yml,.html,.htm" style="display:none"/></label>
          <textarea id="cin" rows="1" placeholder="Schreib mir…  (Enter sendet · Shift+Enter = neue Zeile)" autocomplete="off" autofocus></textarea>
          <button id="sendbtn">Senden</button>
        </form>
      </div>
    </div>
  </div>

  <!-- ================= ME (dein Bereich) ================= -->
  <div class="view" id="v-me">
    <div class="seg" id="me-tabs" style="margin-bottom:12px;display:inline-flex;flex-wrap:wrap">
      <a data-s="tag" class="on">☀ Tag</a><a data-s="todos">✅ Todos</a><a data-s="freigaben">🔔 Freigaben</a><a data-s="routinen">⏰ Routinen</a><a data-s="post">✉ Post</a><a data-s="metriken">🎯 Ziele</a>
    </div>

    <!-- Werkbank PR 7: Serc "Tag" — DEIN Erst-Blick (Kiras Erst-Blick ist der Puls).
         Heute faellig + heute erledigt + Routinen des Tages + Freigaben-Zaehler. -->
    <div class="subview on" id="v-tag">
      <div class="me-grid2">
        <div class="panel me-grow">
          <div class="panel-h">◈ HEUTE DRAN <span class="sp"></span><span id="tag-frei" style="font-size:11px"></span></div>
          <div id="tag-heute" class="panel-b me-scroll"><span class="muted">…</span></div>
        </div>
        <div class="panel me-grow">
          <div class="panel-h">◈ HEUTE ERLEDIGT</div>
          <div id="tag-done" class="panel-b me-scroll"><span class="muted">…</span></div>
        </div>
      </div>
      <div class="me-grid2" style="margin-top:12px">
        <div class="panel"><div class="panel-h">◈ ROUTINEN HEUTE</div>
          <div id="tag-routinen" class="panel-b me-scroll" style="max-height:26vh"><span class="muted">…</span></div></div>
        <div class="panel"><div class="panel-h">◈ KIRA HEUTE <span class="sp"></span><a id="tag-go-puls" class="muted" style="cursor:pointer;font-size:10px">→ Kira · Puls</a></div>
          <div id="tag-digest" class="panel-b"><span class="muted">…</span></div></div>
      </div>
      <!-- Phase 2: Kalender (im Chat eintragen — termin_add; ✕ hier loescht) -->
      <div class="panel" style="margin-top:12px">
        <div class="panel-h">◈ TERMINE <span class="sp"></span><span class="muted" style="font-size:10px">im Chat: „trag ein: Zahnarzt am 15.08.“</span></div>
        <div id="tag-termine" class="panel-b me-scroll" style="max-height:26vh"><span class="muted">…</span></div>
      </div>
      <div id="widgets-serc" class="wslot" style="margin-top:12px"></div>
    </div>

    <div class="subview" id="v-todos">
      <div class="me-grid2">
        <div class="panel me-grow">
          <div class="panel-h">◈ AN KIRA — deine Auftraege</div>
          <div class="panel-b" style="border-bottom:1px solid var(--line)">
            <div class="row"><input id="me-todo-in" placeholder="Todo/Auftrag… (Enter)" style="flex:1"/><button id="me-todo-add">+</button></div>
          </div>
          <div id="life-board" class="panel-b me-scroll"><span class="muted">…</span></div>
        </div>
        <div class="panel me-grow"><div class="panel-h">◈ MISSIONEN &amp; ZIELE</div>
          <div id="life-goals" class="panel-b me-scroll"><span class="muted">…</span></div></div>
      </div>
    </div>

    <div class="subview" id="v-freigaben">
      <div class="me-grid2">
        <div class="panel me-grow">
          <div class="panel-h">◈ VON KIRA — braucht dich <span class="live"></span><span class="sp"></span><span class="muted" id="inbox-count" style="font-size:11px"></span></div>
          <div id="inbox-list" class="panel-b me-scroll"><span class="muted">…</span></div>
        </div>
        <div class="panel">
          <div class="panel-h">◈ ZUGANGS-ANFRAGEN <span class="sp"></span><a id="go-keys" class="muted" style="cursor:pointer;font-size:10px">→ Kira · Zugaenge</a></div>
          <div id="todo-secrets" class="panel-b me-scroll" style="max-height:22vh"><span class="muted">…</span></div>
        </div>
      </div>
    </div>

    <div class="subview" id="v-routinen">
      <div class="panel">
        <div class="panel-h">◈ DEINE ROUTINEN <span class="sp"></span><span class="muted" style="font-size:10px">per Telegram diktierbar</span></div>
        <div id="me-crons" class="panel-b me-scroll" style="max-height:38vh"><span class="muted">…</span></div>
        <div class="panel-b" id="auto-panel" style="border-top:1px solid var(--line)">
          <div class="muted" style="font-size:11px;letter-spacing:1px;margin-bottom:6px">+ AUTOMATISIEREN</div>
          <input id="au-what" placeholder="Was soll Kira regelmaessig tun? (z.B. Follower zaehlen und ins Ziele-Dashboard eintragen)" style="width:100%"/>
          <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px;align-items:center">
            <input id="au-time" type="time" value="08:00" title="taeglich um dieser Uhrzeit" style="width:110px"/>
            <span class="muted" style="font-size:11px">taeglich — oder alle</span>
            <input id="au-interval" placeholder="6h / 30m" title="Intervall statt Uhrzeit" style="width:80px"/>
            <label class="chip" style="font-size:11px;display:inline-flex;align-items:center;gap:4px"><input type="checkbox" id="au-now"/> gleich aktiv</label>
            <button id="au-add">Einrichten</button>
            <span class="muted" id="au-hint" style="font-size:11px"></span>
          </div>
          <div style="margin-top:7px">
            <span class="muted" style="font-size:10px">Schnell:</span>
            <a class="chip au-preset" data-time="08:00" data-what="Erstelle mein Tages-Briefing aus dem Lagebericht: {{standup}} — 1) wie der Tag aussieht (Termine, faellige Todos), 2) was du heute vorhast, 3) EIN proaktiver Vorschlag. Warm, knapp, strukturiert — dann per Telegram senden.">☀ Morgen-Briefing</a>
          </div>
        </div>
      </div>
    </div>

    <div class="subview" id="v-post">
      <div class="panel me-grow">
        <div class="panel-h">◈ E-MAILS <span class="sp"></span><span class="muted" style="font-size:10px">antworten im Chat: „antworte auf die Mail von …“</span></div>
        <div id="me-mails" class="panel-b me-scroll"><div class="emptybox" style="min-height:80px;font-size:12px">Kein Postfach verbunden.<br>SMTP_USER/SMTP_PASS unter Einstellungen → Zugaenge, dann channels.email.enabled=true.</div></div>
      </div>
    </div>

    <div class="subview" id="v-metriken">
      <div class="panel">
        <div class="panel-h">◈ ZIELE-DASHBOARD <span class="sp"></span><span class="muted" style="font-size:10px">Kira traegt selbst ein · „Kira, tracke Follower — Ziel 10000, zeig&#39;s in der Zentrale“</span></div>
        <div class="panel-b">
          <div class="row" style="flex-wrap:wrap;gap:6px">
            <input id="zm-name" placeholder="Kennzahl (z.B. follower)" style="flex:1;min-width:130px"/>
            <input id="zm-val" placeholder="Wert" style="width:84px"/>
            <input id="zm-target" placeholder="Ziel" style="width:76px"/>
            <input id="zm-unit" placeholder="Einheit" style="width:88px"/>
            <button id="zm-add">+ eintragen</button>
          </div>
        </div>
        <div id="life-metrics" class="panel-b me-scroll" style="max-height:50vh"><span class="muted">…</span></div>
      </div>
    </div>
  </div>

  <!-- ================= KIRA (Persoenlichkeit & Specs) ================= -->
  <div class="view" id="v-kira">
    <!-- S12 "4 klare Reiter" (Sergens Entscheid 11.07.): EINE Gruppen-Leiste in Klartext.
         Die Sub-Leiste erscheint NUR, wenn die Gruppe mehr als einen Unterpunkt hat.
         Views/Loader unveraendert — nur Navigation und Benennung sind neu. -->
    <div class="seg" id="kira-groups" style="margin-bottom:12px">
      <a data-g="puls" class="on" title="Was Kira heute tut und lernt — der erste Blick">⚡ Puls</a><a data-g="kopf" title="Was in ihr steckt: Charakter, Gedaechtnis, Wissen, Playbooks">🧠 Kopf</a><a data-g="automatik" title="Was von allein laeuft: Routinen, Monitor, Freigabe-Regeln">⏰ Automatik</a><a data-g="maschine" title="Technik-Details fuer selten: Diagnose, Anatomie, Statistik, Protokoll">🔧 Maschinenraum</a>
    </div>
    <div class="seg" id="kira-tabs" style="margin-bottom:12px;display:inline-flex;flex-wrap:wrap">
      <a data-s="puls" class="on">⚡ Puls</a><a data-s="files">Charakter</a><a data-s="mem">Gedaechtnis</a><a data-s="wissen">Wissen</a><a data-s="playbooks">Playbooks</a><a data-s="cron">Routinen</a><a data-s="monitor">Monitor</a><a data-s="gov">Autonomie</a><a data-s="checkliste">Checkliste</a><a data-s="anatomie">Anatomie</a><a data-s="stats">Statistik</a><a data-s="evolution">Evolution</a><a data-s="log">Protokoll</a>
    </div>

    <div class="subview on" id="v-puls">
      <div class="card"><h3>⚡ Puls — was Kira heute tut und lernt</h3>
        <div class="muted">Erster Blick auf SIE: heute getan, zuletzt gelernt, Skills.
        Tiefer: 🧠 Kopf (Gedaechtnis, Wissen) · 🔧 Maschinenraum (Checkliste, Statistik).</div>
        <div id="puls-body" style="margin-top:10px"><span class="muted">…</span></div>
      </div>
    </div>

    <div class="subview" id="v-keys">
      <div class="card"><h3>🔊 Kira-Stimme (ElevenLabs)</h3>
        <div class="muted">Kira spricht auf Sprachnachrichten zurück. Key hier einfügen, Schalter an —
          fertig. Regel: Sprichst du, spricht sie; tippst du, bleibt's Text. <span id="voice-stat"></span></div>
        <div class="row" style="margin-top:8px">
          <input id="voice-key" type="password" placeholder="ElevenLabs API-Key hier einfügen"/>
          <button id="voice-key-save">Key speichern</button>
        </div>
        <div class="row" style="margin-top:8px;flex-wrap:wrap;gap:10px">
          <label class="chip tog"><input type="checkbox" id="voice-on"/> Sprachantworten an</label>
          <input id="voice-id" placeholder="Stimme-ID (leer = Standard)" style="min-width:220px"/>
          <button id="voice-save">Übernehmen</button>
          <button id="voice-test" class="ghost">🔊 Test</button>
          <span class="muted" id="voice-hint" style="align-self:center"></span>
        </div>
        <div id="voice-testout" class="muted" style="margin-top:6px"></div>
      </div>
      <div class="card"><h3>📱 Handy-Zugriff (PWA)</h3>
        <div class="muted">Cockpit als App auf dem Handy — empfohlener Weg: <b>Tailscale Serve</b> auf
          diesem PC (<code>tailscale serve --bg 8000</code>) → nur deine eigenen Geräte kommen ran, HTTPS
          inklusive. Das Token hier ist die zweite Schicht: am Handy einmal eingeben, dann
          „Zum Startbildschirm hinzufügen". Desktop/Wallpaper am PC bleiben unberührt.</div>
        <div class="row" style="margin-top:8px;flex-wrap:wrap;gap:10px;align-items:center">
          <button id="remote-toggle">…</button>
          <code id="remote-token" style="display:none;user-select:all;background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font-size:12px"></code>
          <button id="remote-copy" class="ghost" style="display:none">📋 Token kopieren</button>
          <span class="muted" id="remote-hint" style="font-size:12px"></span>
        </div>
      </div>
      <div class="card"><h3>Von Kira angefordert</h3><div id="k-pending" class="muted">…</div></div>
      <div class="card"><h3>Zugang eintragen / aktualisieren</h3>
        <div class="muted">Werte sind write-only — werden nie angezeigt oder protokolliert. NIEMALS im Chat eingeben.</div>
        <div class="row"><input id="k-name" placeholder="Name, z.B. OPENROUTER_API_KEY"/>
          <input id="k-val" type="password" placeholder="Wert / Key / Passwort"/>
          <button id="k-save">Speichern</button></div>
        <div id="k-sugg" class="muted" style="margin-top:8px"></div></div>
      <div class="card"><h3>Vorhandene Zugaenge</h3><div id="k-set"></div></div>
    </div>

    <div class="subview" id="v-files">
      <div class="cols">
        <div class="flist" id="flist"></div>
        <div class="fedit">
          <div class="frow"><b id="ftitle" class="muted">Datei waehlen…</b><span class="spacer" style="flex:1"></span>
            <button class="ghost" id="fsave" style="display:none">Speichern</button></div>
          <textarea id="farea" readonly placeholder="—"></textarea>
        </div>
      </div>
    </div>

    <div class="subview" id="v-mem">
      <div class="card"><h3>Erinnerung hinzufuegen</h3>
        <div class="muted">Gib mir gezielt Wissen mit (semantisch = dauerhaftes Faktenwissen).</div>
        <textarea id="mem-new" class="k" style="margin-top:8px" placeholder="z.B. Sergen bevorzugt kurze, direkte Antworten."></textarea>
        <div class="row" style="margin-top:8px"><button id="mem-add">+ Merken</button><span class="muted" id="mem-hint" style="align-self:center"></span></div>
      </div>
      <div class="muted" style="margin:6px 0 8px;max-width:980px">Was Kira sich merkt — 🧠 = sie selbst, 👤 = du. ✎ bearbeiten, ✕ loeschen. (Verfassung/Seele/Ziel sind Dateien und bleiben unberuehrt.)</div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 0 12px;max-width:980px">
        <!-- Gedaechtnis-Diaet (Sergens Fund): Standard = nur bewusst Gemerktes; der rohe
             Chat-Verlauf liegt hinter 'chat' und flutet die Liste nicht mehr -->
        <span class="seg" id="mem-filter"><a data-mf="wichtig" class="on">★ wichtig</a><a data-mf="fact">Fakten</a><a data-mf="lesson">Lektionen</a><a data-mf="skill">Skills</a><a data-mf="episodic">chat</a><a data-mf="partner">🧠 Kira</a><a data-mf="user">👤 Du</a><a data-mf="all">alles</a></span>
        <input id="mem-search" placeholder="🔍 suchen…" style="flex:1;min-width:150px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);outline:none"/>
      </div>
      <div id="mem-selbar" style="display:none;gap:10px;align-items:center;margin:0 0 10px;max-width:980px;
        background:var(--panel);border:1px solid var(--accent);border-radius:10px;padding:7px 12px">
        <b id="mem-selcount" style="font-size:13px">0 ausgewaehlt</b>
        <button class="ghost" id="mem-del-batch" style="font-size:12px">🗑 Auswahl loeschen</button>
        <a id="mem-sel-clear" class="muted" style="cursor:pointer;font-size:12px">abwaehlen</a>
      </div>
      <div id="memlist" style="max-width:980px"></div>
      <div class="panel" style="margin-top:16px;max-width:980px"><div class="panel-h">◈ Verlauf · Aenderungen (vorher → nachher)</div><div id="memhist" class="panel-b"><span class="muted">…</span></div></div>
    </div>

    <div class="subview" id="v-wissen">
      <div class="mgrid">
        <div class="panel"><div class="panel-h">◈ WISSEN FUETTERN — Datei oder Notiz</div>
          <div class="panel-b">
            <div class="row" style="flex-wrap:wrap">
              <label class="ghost" style="display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border:1px solid var(--line);border-radius:8px;cursor:pointer">📄 Datei waehlen<input id="kn-file" type="file" accept=".txt,.md,.markdown,.html,.htm,.pdf,.csv,.log,.json,.yaml,.yml" style="display:none"/></label>
              <span class="muted" id="kn-file-hint" style="align-self:center">txt · md · html · pdf (max 15 MB) — oder per Telegram schicken</span>
            </div>
            <input id="kn-title" placeholder="Titel der Notiz" style="margin-top:10px;width:100%"/>
            <textarea id="kn-text" class="k" style="margin-top:6px;min-height:90px" placeholder="… oder hier Text/Wissen einfuegen …"></textarea>
            <div class="row" style="margin-top:6px"><button id="kn-add">+ Ins Archiv</button><span class="muted" id="kn-hint" style="align-self:center"></span></div>
          </div>
        </div>
        <div class="panel"><div class="panel-h">◈ IM ARCHIV SUCHEN</div>
          <div class="panel-b">
            <input id="kn-q" placeholder="🔍 Was suchst du im Archiv?" style="width:100%"/>
            <div id="kn-results" style="margin-top:8px"><span class="muted">…</span></div>
          </div>
        </div>
      </div>
      <div class="panel"><div class="panel-h">◈ ARCHIV <span class="sp"></span><span class="muted" id="kn-count" style="font-size:11px"></span></div>
        <div id="kn-docs" class="panel-b"><span class="muted">…</span></div></div>
    </div>

    <div class="subview" id="v-playbooks">
      <div class="card"><h3>Playbooks — feste Ablaeufe, die durch Benutzung besser werden</h3>
        <div class="muted">Jedes Playbook ist eine Markdown-Datei in <code>playbooks/</code> (in Obsidian
        sichtbar und editierbar). Reifegrad: <b>entwurf</b> (nur Vorschlaege in deine Freigabe-Inbox)
        -&gt; <b>begleitet</b> (handelt + meldet) -&gt; <b>autonom</b> (handelt, meldet Ergebnis).
        Befoerderung NUR ueber deine Freigabe (5 Erfolge in Serie); ein Fehlschlag stuft automatisch
        zurueck. Lektionen schreibt Kira in die Datei zurueck.</div>
        <div id="pb-list" style="margin-top:12px"><span class="muted">…</span></div>
      </div>
    </div>

    <div class="subview" id="v-anatomie">
      <div class="mgrid">
        <div class="panel"><div class="panel-h">◈ ORGANE — wer zuletzt gearbeitet hat</div>
          <div id="ag-organs" class="panel-b"><span class="muted">…</span></div></div>
        <div class="panel"><div class="panel-h">◈ DIENSTE &amp; MCP &amp; WERKZEUGKASTEN</div>
          <div id="ag-infra" class="panel-b"><span class="muted">…</span></div></div>
      </div>
      <div class="panel" style="margin-top:14px"><div class="panel-h">◈ ÜBERGABE-CHECK — ist Kira startklar?</div>
        <div class="panel-b">
          <div class="muted" style="font-size:12px;margin-bottom:8px">Ein grüner Blick vor dem Start: Modell erreichbar, MCP-Server laufen, Abhängigkeiten da, Wissensbasis befüllt. So fällt ein fehlender Zugang <b>vorher</b> auf, nicht mitten im Projekt.</div>
          <button id="pf-run">Übergabe-Check starten</button>
          <span class="muted" id="pf-sum" style="margin-left:10px"></span>
          <div id="pf-list" style="margin-top:10px"></div>
        </div></div>
      <div class="panel" style="margin-top:14px"><div class="panel-h">◈ WERKSZUSTAND — Kira als Blanko übergeben</div>
        <div class="panel-b">
          <div class="muted" style="font-size:12px;margin-bottom:8px">Nach der Bauphase den Test-/Dev-Wildwuchs rauswerfen — Verfassung, Persona, USER.md, Zugänge und Config bleiben unangetastet. Jede Kategorie wird <b>vorher gesichert</b> (data/backups). Nichts passiert ohne dein ausdrückliches Ja.</div>
          <div id="fac-cats"><span class="muted">…</span></div>
          <div class="row" style="gap:10px;margin-top:10px;align-items:center">
            <button id="fac-reset" class="ghost" style="border-color:var(--danger);color:var(--danger)">Auf Werkszustand setzen</button>
            <span class="muted" id="fac-hint" style="font-size:12px"></span>
          </div>
        </div></div>
      <div class="panel" style="margin-top:14px"><div class="panel-h">◈ MCP-UNIVERSUM — Server einstöpseln</div>
        <div class="panel-b">
          <div class="muted" style="font-size:12px;margin-bottom:8px">Macht-Schritt 2: beliebige MCP-Server anschließen, ohne Code. Ein Klick aus dem Katalog (Zugang muss im Tresor liegen) — dann stehen ihre Werkzeuge sofort bereit. Schreibende Tools laufen automatisch durchs Freigabe-Gate.</div>
          <div id="mcp-catalog" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px"></div>
          <div id="mcp-setups"></div>
          <div id="mcp-list" style="margin-top:8px"><span class="muted">…</span></div>
          <details style="margin-top:12px"><summary class="muted" style="cursor:pointer;font-size:12px">Eigenen Server hinzufügen (Experten)</summary>
            <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:8px">
              <input id="mcp-name" placeholder="Name (z.B. meinserver)" style="flex:1;min-width:140px"/>
              <input id="mcp-cmd" placeholder="command (z.B. npx)" style="width:110px"/>
              <input id="mcp-args" placeholder='args, komma-getrennt (z.B. -y, @scope/paket)' style="flex:2;min-width:200px"/>
            </div>
            <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:6px">
              <input id="mcp-env" placeholder='env optional: KEY=$TRESOR_SCHLUESSEL' style="flex:2;min-width:220px"/>
              <input id="mcp-tools" placeholder='Tools-Allowlist optional, komma-getrennt' style="flex:2;min-width:200px"/>
              <button id="mcp-add-custom">Hinzufügen</button>
            </div>
            <div class="muted" id="mcp-hint" style="margin-top:6px;font-size:12px"></div>
          </details>
        </div></div>
    </div>

    <div class="subview" id="v-evolution">
      <div class="card"><h3>Was ich zuletzt an mir verbessert habe</h3>
        <div class="muted">Jeder 3. autonome Tick gehoert meiner Selbstoptimierung — Bugs beheben,
        Werkzeuge bauen, Skills lernen. Hier siehst du, woran ich zuletzt an MIR gearbeitet habe.</div>
        <div id="ev-timeline" style="margin-top:10px"><span class="muted">…</span></div>
      </div>
      <div class="mgrid">
        <div class="panel"><div class="panel-h">◈ GELERNTE SKILLS <span class="sp"></span><span class="muted" id="ev-skillcount" style="font-size:11px"></span></div>
          <div id="ev-skills" class="panel-b"><span class="muted">…</span></div></div>
        <div class="panel"><div class="panel-h">◈ LETZTE LEKTIONEN</div>
          <div id="ev-lessons" class="panel-b"><span class="muted">…</span></div></div>
      </div>
    </div>

    <div class="subview" id="v-checkliste">
      <div class="card"><h3>System-Checkliste — ist das Fundament gesund?</h3>
        <div class="muted">Die Paragraphen aus <b>docs/HANDBUCH.md</b> als Live-Ampeln.
        Gruen = laeuft · Gelb = wartet auf dich/Aufbau · Rot = klemmt.</div>
        <div id="ck-tagewerk" style="margin-top:10px"><span class="muted">…</span></div>
        <div id="ck-list" style="margin-top:12px"><span class="muted">…</span></div>
      </div>
      <div class="card"><h3>Selbstkalibrierung — wie oft musste das System nachhelfen?</h3>
        <div class="muted">Nudge-/Fehler-/Fallback-Raten pro Modell (letzte 7 Tage, aus dem
        Event-Log, 0 Token). Der Wochen-Report landet automatisch als Vorschlag in der Inbox.</div>
        <div id="ck-kalib" style="margin-top:10px;font-size:12.5px;white-space:pre-wrap"><span class="muted">…</span></div>
      </div>
    </div>

    <div class="subview" id="v-stats">
      <div class="card"><h3>Lern-Kurve — besteht Kira ihre eigene Pruefung?</h3>
        <div class="muted">Jeder Mission-Task wird gegen Akzeptanzkriterien geprueft (Score 0-100).
        Hier siehst du, ob sie <b>besser</b> wird — nicht nur fleissiger.</div>
        <div id="st-kpi" style="display:flex;gap:26px;flex-wrap:wrap;margin-top:12px"><span class="muted">…</span></div>
      </div>
      <div class="card"><h3>Token-Verbrauch heute</h3>
        <div class="muted" style="font-size:12px">Sichtbarkeit statt harter Limits: bei Gratis-Modellen zählt die €-Bremse nichts — hier siehst du die echte Menge je Rolle.</div>
        <div id="st-tokens" class="muted" style="margin-top:8px">…</div></div>
      <div class="card"><h3>Task-Arten — was klappt, was hakt</h3><div id="st-kinds" class="muted">…</div></div>
      <div class="card"><h3>Zaehe Ziele</h3><div id="st-objs" class="muted">…</div></div>
      <div class="card"><h3>Wiederkehrende Pruefer-Kritik</h3><div id="st-themes" class="muted">…</div></div>
      <div class="card"><h3>Strategien — lohnt Eskalation?</h3><div id="st-strats" class="muted">…</div></div>
      <div class="card"><h3>💶 Kosten je Modell (7 Tage)</h3><div id="st-costs" class="muted">…</div></div>
    </div>

  <!-- Config aufgeloest: die Technik-Unterreiter leben jetzt als Kira-Subtabs weiter -->
  <div class="subview" id="v-models">
    <div class="card"><h3>Aktives Modell</h3><div id="m-active" class="muted">…</div></div>
    <div class="card"><h3>Kontext &amp; Parameter</h3>
      <div id="m-loaded" class="muted">…</div>
      <div class="row">
        <input id="m-ctx" type="number" placeholder="num_ctx (z.B. 16384)" style="max-width:190px"/>
        <input id="m-maxtok" type="number" placeholder="max_tokens" style="max-width:160px"/>
        <button id="m-paramgo">Setzen</button>
      </div>
      <div style="margin-top:8px">Schnell-Kontext:
        <span class="pill" data-ctx="16384">16K</span>
        <span class="pill" data-ctx="32768">32K</span>
        <span class="pill" data-ctx="65536">64K</span>
        <span class="pill" data-ctx="131072">128K</span></div>
      <div class="muted" style="margin-top:6px">Größer = mehr VRAM. Nach „Setzen" lädt das Modell neu — bleibt „GPU 100%"? Falls Anteil sinkt (CPU-Spill = langsam), kleiner wählen.</div>
    </div>
    <div class="card"><h3>Verhalten &amp; System</h3>
      <div class="muted">Feineinstellungen. Temperatur/keep_alive wirken sofort; Sprache/Voice brauchen einen Neustart.</div>
      <div class="row" style="margin-top:8px;flex-wrap:wrap">
        <label class="muted" style="align-self:center">Temperatur</label>
        <input id="s-temp" type="number" step="0.1" min="0" max="2" style="max-width:100px"/>
        <label class="muted" style="align-self:center">keep_alive</label>
        <input id="s-keep" placeholder="z.B. 24h" style="max-width:100px"/>
        <button id="s-behav-save">Setzen (live)</button>
      </div>
      <div class="row" style="margin-top:8px;flex-wrap:wrap">
        <label class="muted" style="cursor:pointer;align-self:center"><input type="checkbox" id="s-voice"/> Sprachmemos transkribieren</label>
        <label class="muted" style="align-self:center">Whisper</label>
        <select id="s-whisper"><option>tiny</option><option>base</option><option>small</option><option>medium</option></select>
        <button id="s-sys-save">Speichern (Neustart)</button>
        <span class="muted" id="s-sys-hint" style="align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Lokal (Ollama) — klicken zum Wechseln</h3><div id="m-ollama"></div></div>
    <div class="card"><h3>OpenRouter-Modell direkt hinzufuegen</h3>
      <div class="muted">Modell-ID einfuegen (z.B. <b>anthropic/claude-sonnet-5</b>) — wird sofort aktives Modell.</div>
      <div class="row" style="margin-top:8px">
        <input id="m-or" placeholder="anbieter/modell-id" style="min-width:260px;flex:1"/>
        <button id="m-or-add">Aktivieren</button>
        <span class="muted" id="m-or-hint" style="align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Modell-Rollen — was denkt womit</h3>
      <div class="muted">Jede Aufgabe hat ihre eigene KI. Zum Aendern unten im Katalog ein Modell suchen und der Rolle zuweisen.</div>
      <div id="m-roles" style="margin-top:8px"></div>
    </div>
    <div class="card"><h3>Modell-Katalog (live: OpenRouter + AIMLAPI + lokal — neue Modelle erscheinen automatisch)</h3>
      <div class="row" style="margin-top:4px;flex-wrap:wrap">
        <label class="muted" style="align-self:center">Zuweisen an:</label>
        <select id="cat-role">
          <option value="chat">💬 Chat (Smalltalk)</option>
          <option value="reason">🧠 Denker (Reason/Coding)</option>
          <option value="bulk">⏰ Crons (einfach)</option>
          <option value="classify">🐜 Reflex (lokal, 0€)</option>
          <option value="worker">🔧 Arbeiter (Delegation)</option>
          <option value="escalation">⚡ Eskalation</option>
          <option value="default">★ Default (alles)</option>
        </select>
        <input id="cat-search" placeholder="🔍 suchen: deepseek, flash, claude, gemini, qwen …" style="min-width:240px;flex:1"/>
      </div>
      <div id="cat-list" style="max-height:340px;overflow:auto;margin-top:8px;font-size:12px"></div>
      <div class="muted" id="cat-hint" style="margin-top:6px"></div>
    </div>
  </div>

  <!-- ============ STEUERPULT: Sergens Riegel ueber die Schwarmintelligenz ============ -->
  <div class="subview" id="v-steuer">
    <div class="card"><h3>🎛 Steuerpult — dein Riegel über die Schwarmintelligenz</h3>
      <div class="muted">Kira arbeitet in <b>Rängen</b> (Reflex → Arbeiter → Denker → Richter). Hier bestimmst du,
      <b>welches Modell hinter jedem Rang steht</b>, wie viel ein Unteragent darf — und schickst der Armee
      <b>direkte Befehle</b>, ohne dass ein Modell mitreden muss. Im Chat geht dasselbe per
      <b>/delegiere</b> und <b>/schwarm</b>.</div>
    </div>
    <div class="card"><h3>Rang-Tafel — wer denkt auf welchem Rang</h3>
      <div class="muted">„gesetzt" = dein Befehl · „läuft real" = was gerade wirklich antwortet (Fallback sichtbar).
      Modell tippen (Vorschläge aus dem Live-Katalog) und zuweisen.</div>
      <div id="st-raenge" style="margin-top:8px"><span class="muted">…</span></div>
      <datalist id="st-modelle"></datalist>
      <div class="muted" id="st-rang-hint" style="margin-top:6px"></div>
    </div>
    <div class="card"><h3>Schwarm-Regler — wie viel deine Armee darf</h3>
      <div class="row" style="flex-wrap:wrap;gap:10px;margin-top:6px">
        <label class="muted" style="align-self:center">Schritte je Unteragent:</label>
        <label class="muted" style="align-self:center">🐜<input id="st-s-reflex" type="number" min="1" max="40" style="width:64px"/></label>
        <label class="muted" style="align-self:center">🔧<input id="st-s-arbeiter" type="number" min="1" max="40" style="width:64px"/></label>
        <label class="muted" style="align-self:center">🧠<input id="st-s-denker" type="number" min="1" max="40" style="width:64px"/></label>
        <label class="muted" style="align-self:center">⚖<input id="st-s-richter" type="number" min="1" max="40" style="width:64px"/></label>
      </div>
      <div class="row" style="flex-wrap:wrap;gap:10px;margin-top:8px">
        <label class="muted" style="align-self:center">Schwarm-Breite (max. Unteragenten)</label>
        <input id="st-breite" type="number" min="1" max="20" style="width:70px"/>
        <label class="muted" style="align-self:center">Kosten-Deckel je Delegation (€)</label>
        <input id="st-kosten" type="number" min="0" step="0.1" style="width:80px"/>
        <button id="st-regler-save">Übernehmen (sofort live)</button>
        <span class="muted" id="st-regler-hint" style="align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Rechner steuern — Kira sieht den Bildschirm &amp; bedient Maus/Tastatur</h3>
      <div class="muted" style="margin-top:4px;font-size:12px">Macht-Schritt 1: damit steuert Kira jedes Programm auf dem PC — auch ohne API (Photoshop, Desktop-Apps, Legacy-Tools). Jede Aktion landet im Protokoll; Not-Aus stoppt sie sofort. <b>Standard aus</b> — bewusst freischalten.</div>
      <label class="chip tog" id="st-cu-l" style="margin-top:10px;display:inline-flex"><input type="checkbox" id="st-cu"/> 🖥 Rechner-Steuerung erlauben</label>
      <span class="muted" id="st-cu-hint" style="margin-left:8px"></span>
    </div>
    <div class="card"><h3>Kommandobrücke — Auftrag direkt an die Armee</h3>
      <div class="row" style="flex-wrap:wrap;gap:10px;margin-top:6px">
        <label class="muted" style="align-self:center">Rang:</label>
        <select id="st-cmd-rang">
          <option value="reflex">🐜 Reflex (lokal, 0€)</option>
          <option value="arbeiter" selected>🔧 Arbeiter (billig)</option>
          <option value="denker">🧠 Denker</option>
          <option value="richter">⚖ Richter (teuer, selten!)</option>
        </select>
        <label class="chip tog" style="align-self:center"><input type="checkbox" id="st-cmd-schwarm"/> als Schwarm (Liste)</label>
      </div>
      <textarea id="st-cmd-auftrag" class="k" style="margin-top:8px;min-height:60px"
        placeholder="Der Auftrag — beim Schwarm mit {item} als Platzhalter, z.B.: Recherchiere kurz: {item}"></textarea>
      <textarea id="st-cmd-items" class="k" style="margin-top:8px;min-height:60px;display:none"
        placeholder="Schwarm-Liste: EIN Item pro Zeile (z.B. 5 Firmennamen)"></textarea>
      <div class="row" style="margin-top:8px">
        <button id="st-cmd-go">→ In den Chat legen</button>
        <span class="muted" style="align-self:center">Der Befehl landet im Chat-Eingabefeld — <b>du</b> drückst Senden. Finger am Abzug bleibt bei dir.</span>
      </div>
    </div>
  </div>

  <div class="subview" id="v-gov">
    <div class="card"><h3>Was ist das „Gewissen"?</h3>
      <div class="muted">Meine <b>Leitplanken</b> — womit du steuerst, wie weit ich gehen darf:
      <b class="ok">Budget</b> = wie viel Geld sie pro Tag/Monat ausgeben darf (danach faellt sie automatisch auf lokal/0&nbsp;€).
      <b class="ok">Autonomie</b> = welche Aktionsarten deine Freigabe brauchen. <b class="ok">Audit</b> = Protokoll ihrer Aussen-Aktionen.</div></div>
    <div class="card"><h3>Budget (Treasury)</h3><div id="g-budget" class="muted">…</div>
      <div class="row" style="margin-top:10px">
        <input id="g-day" type="number" step="0.5" placeholder="Tag €" style="max-width:120px"/>
        <input id="g-month" type="number" step="1" placeholder="Monat €" style="max-width:120px"/>
        <button id="g-budget-save">Speichern</button>
        <span class="muted" id="g-budget-hint" style="align-self:center"></span>
      </div></div>
    <div class="card"><h3>Autonomie — was braucht deine Freigabe?</h3>
      <div class="muted">Vertrauen entsteht durchs Nachpruefen, nicht durch ein Barometer. Hier stellst
      du ein, WAS Kira dir vorlegen MUSS — alles andere tut sie eigenstaendig (mit Audit-Spur unten).</div>
      <div id="au-box" style="margin-top:10px" class="muted">…</div>
      <div class="row" style="margin-top:10px">
        <button id="au-save">Speichern (greift sofort)</button>
        <span class="muted" id="au-hint" style="align-self:center"></span>
      </div></div>
    <div class="card"><h3>Audit — protokollierte Aussen-Aktionen</h3><div id="g-audit" class="muted">…</div></div>
    <div class="card"><h3>💶 Kosten-Aufschluesselung (heute · 7 Tage)</h3><div id="g-costs" class="muted">…</div></div>
  </div>

  <div class="subview" id="v-cron">
    <div class="card"><h3>Geplante Aufgaben (Cron)</h3>
      <div class="muted">Meine wiederkehrenden Aufgaben. Zeitplan: <b>30m</b>/<b>2h</b> (Intervall) oder <b>08:00</b> (taeglich) · zum Aendern auf <b>bearbeiten</b> beim Job klicken. Laufen, sobald der Runner aktiv ist.</div>
      <div class="row" style="margin-top:8px">
        <input id="cr-label" placeholder="Name" style="max-width:150px"/>
        <input id="cr-prompt" placeholder="Was Kira jeweils tun soll" style="min-width:260px"/>
        <input id="cr-sched" placeholder="z.B. 08:00 oder 2h" style="max-width:130px"/>
        <button id="cr-add">+ Planen</button>
      </div>
      <div class="muted" id="cr-hint" style="margin-top:6px"></div>
    </div>
    <div class="card"><h3>Aktive Jobs</h3><div id="cr-list" class="muted">…</div></div>
  </div>

  <div class="subview" id="v-monitor">
    <div class="card"><h3>Web-/News-Monitor (rein lesend)</h3>
      <div class="muted">Ich ueberwache Feeds &amp; Themen, fasse Neues zusammen und melde dir's per Telegram. Nur Lesen — sicher.</div>
      <div class="row" style="margin-top:8px">
        <select id="mo-kind"><option value="feed">RSS-Feed</option><option value="search">Web-Thema</option></select>
        <input id="mo-value" placeholder="RSS-URL  oder  Suchbegriff" style="min-width:240px"/>
        <input id="mo-label" placeholder="Label (optional)" style="max-width:150px"/>
        <button id="mo-add">+ Beobachten</button>
        <button class="ghost" id="mo-check">Jetzt pruefen</button>
      </div>
      <div class="muted" id="mo-hint" style="margin-top:6px"></div>
    </div>
    <div class="card"><h3>Beobachtungen</h3><div id="mo-list" class="muted">…</div></div>
    <div class="card"><h3>Zuletzt gemeldet</h3><div id="mo-recent" class="muted">…</div></div>
  </div>

  <div class="subview" id="v-log">
    <div id="log-filters" style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap">
      <a href="#" data-f="all" class="pill on">Alles</a>
      <a href="#" data-f="error" class="pill">⚠ Fehler</a>
      <a href="#" data-f="action" class="pill">⚡ Aktionen</a>
      <a href="#" data-f="chat" class="pill">💬 Chat</a>
    </div>
    <div id="evlog"></div>
    <div style="text-align:center;margin-top:12px"><button class="ghost" id="log-more">mehr laden ↓</button></div>
  </div>

  <div class="subview" id="v-bench">
    <div class="card"><h3>🧬 Tuning-Werkbank — unser eigenes LLM</h3>
      <div class="muted" style="font-size:12px;margin-top:4px">Kira sammelt bei jeder echten Unterhaltung still Trainingsmaterial und generiert Struktur-Beispiele live aus ihrer Werkzeug-Registry. Der Export ist ein Standard-JSONL — das Training selbst läuft <b>außerhalb</b> von Kira (Anleitung: docs/TUNING.md). Das getunte Modell erscheint danach einfach als weiteres Ollama-Modell im Dropdown; Cloud-Modelle bleiben unberührt.</div>
      <div id="tun-stats" style="margin-top:8px"><span class="muted">…</span></div>
      <div class="row" style="gap:10px;margin-top:8px;align-items:center">
        <button id="tun-export">Datensatz exportieren (JSONL)</button>
        <span class="muted" id="tun-hint" style="font-size:12px"></span>
      </div>
    </div>
    <div class="card"><h3>🏁 Coding-Benchmark</h3>
      <div class="muted"><b>HumanEval</b> = der internationale Standard (164 genormte Python-Aufgaben,
      pass@1 — direkt vergleichbar mit publizierten Scores: Frontier-Modelle ~90 %+, starke offene
      Modelle grob 70–90 %). Misst das <b>Modell</b> auf der gewählten Rolle. <b>SWE-bench Lite</b> =
      der internationale <b>Harness</b>-Test (echte GitHub-Issues, Kira löst sie mit ihrem kompletten
      Coding-Kreis; „bestanden" = Prognose per Datei-Treffer, der amtliche Score kommt aus der
      erzeugten predictions.jsonl — dauert Minuten pro Aufgabe, klein anfangen!). <b>Harness-Smoke</b> =
      Pipeline-Test (Kira löst Aufgaben im isolierten Wegwerf-Arbeitsbaum — beweist die Kette, misst
      keine Leistung). Alles live, nichts berührt Repo oder Gedächtnis.</div>
      <div class="row" style="margin-top:10px;align-items:center;gap:12px;flex-wrap:wrap">
        <button id="bench-start">▶ Benchmark starten</button>
        <button id="bench-stop" class="ghost" style="display:none">■ Stopp</button>
        <select id="bench-suite" title="Welcher Test">
          <option value="humaneval" selected>HumanEval (international)</option>
          <option value="swebench">SWE-bench Lite (Harness, Prognose)</option>
          <option value="harness">Harness-Smoke (Pipeline)</option>
        </select>
        <select id="bench-role" title="Welche Modell-Rolle wird gemessen">
          <option value="reason" selected>Denker (reason)</option>
          <option value="bulk">Massen (bulk)</option>
          <option value="chat">Chat</option>
          <option value="classify">Lokal (classify)</option>
        </select>
        <label class="muted" style="font-size:12px">Aufgaben <input id="bench-limit" type="number" value="20" min="1" max="164" style="width:64px"></label>
        <input id="bench-model-pick" list="bench-model-list" placeholder="Modell direkt (leer = Rolle)" title="Direktwahl: exakt DIESES Modell testen — beliebige OpenRouter-ID (auch neue) oder ollama_chat/... Leer lassen = die gewaehlte Rolle zaehlt." style="min-width:250px"/>
        <datalist id="bench-model-list"></datalist>
        <label class="muted" style="font-size:12px;display:inline-flex;align-items:center;gap:6px">
          <input type="checkbox" id="bench-allow-llm" checked> echtes Modell (statt lokal)</label>
        <span class="muted" id="bench-model" style="font-size:12px"></span>
      </div>
      <div class="muted" style="margin-top:6px;font-size:11.5px">Tipp: 20 Aufgaben ≈ schneller Eindruck (±10 %), alle 164 ≈ belastbare Zahl. Rolle wechseln → Modelle direkt vergleichen. Cloud-Rollen kosten pro Aufgabe wenige Cent oder weniger.</div>
      <div id="bench-score" style="margin-top:12px;font-size:20px;font-weight:600"></div>
    </div>
    <div class="card"><h3>🏆 Leaderboard — deine Läufe</h3>
      <div class="row" style="align-items:center;gap:10px;margin-bottom:8px">
        <button id="bench-copy" class="ghost">📋 Als Tabelle kopieren</button>
        <span class="muted" id="bench-copy-hint" style="font-size:12px"></span>
      </div>
      <div id="bench-results" class="muted" style="overflow-x:auto">…</div>
    </div>
    <div class="card"><h3>Live-Verlauf</h3>
      <div id="bench-log" style="font-size:13px;max-height:60vh;overflow:auto"><div class="muted">Noch kein Lauf. Drück „Benchmark starten".</div></div>
    </div>
  </div>

  <div class="subview" id="v-wall">
    <div class="card"><h3>🖥 Wallpaper-Editor</h3>
      <div class="muted">Stellt die Desktop-Seite <b>/wall</b> (Lively-Wallpaper) live ein: welche Stats oben
      erscheinen, Bewegung/Worte, Farbe, Position, Größe und die Modus-Farben. Wird serverseitig
      gespeichert — das Wallpaper zieht in ~3&nbsp;s nach.</div>
      <div class="row" style="margin-top:12px;gap:18px;flex-wrap:wrap;align-items:flex-start">
        <div style="flex:1;min-width:320px">
          <div class="muted" style="font-size:11px;letter-spacing:1px;margin-bottom:4px">LIVE-VORSCHAU</div>
          <div style="position:relative;width:100%;padding-top:56.25%;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#000">
            <iframe id="wp-prev" src="/wall" title="Wallpaper-Vorschau"
              style="position:absolute;top:0;left:0;width:200%;height:200%;transform:scale(.5);transform-origin:top left;border:0"></iframe>
          </div>
          <button class="ghost" id="wp-open" style="margin-top:6px">↗ /wall in neuem Tab öffnen</button>
        </div>
        <div style="flex:1;min-width:280px;display:flex;flex-direction:column;gap:12px">
          <div>
            <div class="muted" style="font-size:11px;letter-spacing:1px;margin-bottom:6px">STATS OBEN (anhaken = sichtbar)</div>
            <div id="wp-stats" class="row" style="flex-wrap:wrap;gap:6px 14px"></div>
          </div>
          <div class="row" style="flex-wrap:wrap;gap:10px 18px;align-items:center">
            <label class="muted" style="cursor:pointer"><input type="checkbox" id="wp-labels"/> Worte (Labels)</label>
            <label class="muted" style="cursor:pointer"><input type="checkbox" id="wp-motion"/> Bewegung</label>
            <label class="muted" style="cursor:pointer" title="Aktivitaets-Stream unten links auf dem Desktop: was Kira gerade tut"><input type="checkbox" id="wp-ticker"/> Live-Ticker</label>
            <label class="muted">Farbe <select id="wp-color"><option value="vault">Vault</option><option value="modus">Modus</option><option value="mono">Mono</option></select></label>
            <label class="muted">Position <select id="wp-pos"><option value="links">Links</option><option value="mitte">Mitte</option><option value="rechts">Rechts</option></select></label>
            <label class="muted">Höhe <select id="wp-posy"><option value="oben">Oben</option><option value="mitte">Mitte</option><option value="unten">Unten</option></select></label>
            <label class="muted">Größe <select id="wp-size"><option value="klein">Klein</option><option value="mittel">Mittel</option><option value="gross">Groß</option><option value="riesig">Riesig</option></select></label>
          </div>
          <div>
            <div class="muted" style="font-size:11px;letter-spacing:1px;margin-bottom:6px">MODUS-FARBEN</div>
            <div class="row" style="gap:16px;flex-wrap:wrap;align-items:center">
              <label class="muted" style="display:inline-flex;align-items:center;gap:6px">Chat <input type="color" id="wp-c-chat" value="#b026ff"/></label>
              <label class="muted" style="display:inline-flex;align-items:center;gap:6px">Work <input type="color" id="wp-c-work" value="#39ff14"/></label>
              <label class="muted" style="display:inline-flex;align-items:center;gap:6px">Coding <input type="color" id="wp-c-coding" value="#00e5ff"/></label>
            </div>
          </div>
          <div class="row" style="gap:8px;align-items:center">
            <button id="wp-save">Speichern</button>
            <button class="ghost" id="wp-reset">Standard</button>
            <span class="muted" id="wp-status" style="font-size:12px"></span>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="subview" id="v-cockpit">
    <div class="card"><h3>App-Logo</h3>
      <div class="muted">Dein Kira-Logo — genutzt als <b>Browser-Tab-Symbol</b> von /wall und (nach einem
      App-Neustart) als <b>Fenster-Symbol</b> (Titelleiste oben links) und <b>Taskleisten-Symbol</b> der
      Desktop-App. <i>Nicht</i> im Cockpit-Kopf (der bleibt der „KIRA"-Schriftzug). Einfach hier hochladen —
      es wird automatisch ins Windows-Icon-Format (.ico) umgewandelt, kein Datei-Geschiebe nötig.</div>
      <div class="row" style="margin-top:8px;align-items:center;gap:12px">
        <img id="logo-prev" src="/api/icon" alt="" onerror="this.style.visibility='hidden'"
          style="width:46px;height:46px;border-radius:10px;object-fit:cover;border:1px solid var(--line)"/>
        <label class="ghost" style="display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border:1px solid var(--line);border-radius:8px;cursor:pointer">🖼 Logo waehlen<input id="set-logo" type="file" accept="image/png,image/jpeg,image/webp" style="display:none"/></label>
        <button class="ghost" id="set-logo-clear">Entfernen</button>
        <span class="muted" id="set-logo-hint" style="align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Desktop-Verknüpfung</h3>
      <div class="muted">Legt ein <b>Kira-Icon auf deinen Desktop</b> (mit deinem Logo) — Doppelklick
      startet die App — und richtet den <b>Autostart</b> ein. Danach das laufende Fenster per
      <b>Rechtsklick → „An Taskleiste anheften"</b>. Ein Klick, kein Ordner. (Nur Windows.)</div>
      <div class="row" style="margin-top:8px;align-items:center;gap:10px">
        <button id="make-shortcut">🖥 Desktop-Icon erstellen</button>
        <span class="muted" id="make-shortcut-hint" style="font-size:12px;align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Sauberer Neustart</h3>
      <div class="muted">Setzt den <b>gesamten Chat-Verlauf auf null</b> (alle Sessions) — für einen
      frischen Anfang, wenn alte Gespräche die Antworten verwässern. Deine <b>Fakten &amp; Skills
      bleiben</b>, und alles Gelöschte wird vorher gesichert (<code>data/backups/</code>).</div>
      <div class="row" style="margin-top:8px;align-items:center;gap:10px">
        <button id="reset-episodic" style="border-color:var(--danger);color:var(--danger)">🧹 Chat-Verlauf zurücksetzen</button>
        <span class="muted" id="reset-episodic-hint" style="font-size:12px;align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Kira-Avatar</h3>
      <div class="muted">Ihr Gesicht im Cockpit: gross in der Zentrale, klein an ihren Chat-Antworten.
      Erzeuge Bilder z.B. in <b>Higgsfield</b> und lade sie hier hoch (quadratisch wirkt am besten).</div>
      <div class="row" style="margin-top:8px">
        <label class="ghost" style="display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border:1px solid var(--line);border-radius:8px;cursor:pointer">🖼 Avatar waehlen<input id="set-avatar" type="file" accept="image/*" style="display:none"/></label>
        <button class="ghost" id="set-avatar-clear">Avatar entfernen</button>
        <span class="muted" id="set-avatar-hint" style="align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Optik</h3>
      <div class="muted">Farbschema + Hintergrund-Bild wechselst du oben rechts ueber das ◐-Icon.
      Der <b>Kira-Modus</b> nutzt dein hochgeladenes Bild als Hintergrund.</div>
      <div class="row" style="margin-top:8px">
        <button class="ghost" id="set-bg-clear">Hintergrundbild entfernen</button>
        <span class="muted" id="set-optik-hint" style="align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Tab-Icons</h3>
      <div class="muted">Ein Zeichen/Emoji pro Bereich (wird lokal im Browser gespeichert).</div>
      <div class="row" style="margin-top:8px;flex-wrap:wrap" id="icon-row">
        <input data-ic="home" placeholder="Zentrale" style="max-width:110px"/>
        <input data-ic="chat" placeholder="Chat" style="max-width:110px"/>
        <input data-ic="me" placeholder="Serc" style="max-width:110px"/>
        <input data-ic="kira" placeholder="Kira" style="max-width:110px"/>
        <button id="icons-save">Icons speichern</button>
        <button class="ghost" id="icons-reset">Zuruecksetzen</button>
      </div>
    </div>
    <div class="card"><h3>Desktop-Pflege</h3>
      <div class="muted">Ich sehe mir taeglich lose Dateien in deinen Ordnern an und schlage eine
      Einsortierung vor — <b>verschoben wird nichts ohne deine Freigabe</b> (Vorschlag landet in „Von Kira").
      Lokal, 0&nbsp;€.</div>
      <div class="row" style="margin-top:8px;flex-wrap:wrap">
        <label class="muted" style="cursor:pointer;align-self:center"><input type="checkbox" id="dw-enabled"/> aktiv</label>
        <input id="dw-folders" placeholder="Ordner (mit ; trennen)" style="flex:1;min-width:240px"/>
        <button id="dw-save">Speichern</button>
        <button class="ghost" id="dw-scan">Jetzt scannen</button>
      </div>
      <div class="muted" id="dw-status" style="margin-top:8px;font-size:12px">…</div>
    </div>
    <div class="card"><h3>System</h3>
      <div class="muted">Neustart bounct Cockpit, Telegram-Bot und Runner sauber (~20 s). Der Not-Aus unten links haelt alles sofort an.</div>
      <div class="row" style="margin-top:8px">
        <button class="ghost" id="set-restart">↻ Kira neu starten</button>
        <span class="muted" id="set-restart-hint" style="align-self:center"></span>
      </div>
    </div>
  </div>
  </div>

  <!-- ================= EINSTELLUNGEN (Werkbank PR 3: Technik zieht aus dem Kira-Tab aus).
       Die 6 Subview-Divs bleiben physisch oben definiert und ziehen beim Boot per DOM-Move
       hierher um (script.py) — kleinster Eingriff in den Monolith. ================= -->
  <div class="view" id="v-settings">
    <div class="seg" id="settings-tabs" style="margin-bottom:12px;display:inline-flex;flex-wrap:wrap">
      <a data-s="models" class="on">⚙ Modelle</a><a data-s="bench">🏁 Benchmark</a><a data-s="steuer">🎛 Steuerpult</a><a data-s="keys">Zugaenge</a><a data-s="cockpit">Cockpit</a><a data-s="wall">🖥 Wallpaper</a>
    </div>
  </div>
</div>
"""
