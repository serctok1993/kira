"""Cockpit-Markup: Sidebar-Navigation + alle View-Container.

S7a — Cockpit 2.0, modulare Shell (Sergens Redesign-Auftrag):
  Zentrale (home)      fester Kommandostand: Hero, HUD, Befehl, Live-Ops, Digest, News
  Chat (chat)          Hauptdialog (Chat 2.0 folgt in S7c)
  Projekte (projekte)  Subtabs: Standbeine (Ventures) / Ziele & Aufgaben / Radar
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
  <h1>KIRA</h1><div class="sub" id="who">cockpit</div>
  <a data-v="home" class="on" title="Kommandostand: Status, Befehl, Live-Ops, Digest"><i class="ti">◈</i> Zentrale</a>
  <a data-v="chat" title="Mit mir reden"><i class="ti">›</i> Chat</a>
  <a data-v="projekte" title="Projekte, Ziele, Radar-Chancen"><i class="ti">◈</i> Projekte</a>
  <a data-v="me" title="Dein Bereich: Todos beidseitig, Mails, Metriken"><i class="ti">☰</i> Me</a>
  <a data-v="kira" title="Wer ich bin: Seele, Gedaechtnis, Wissen, Anatomie, Lernkurve"><i class="ti">✦</i> Kira</a>
  <a data-v="config" title="Technik: Modelle, Zugaenge, Gewissen, Cron, Monitor, Protokoll"><i class="ti">⚙</i> Config</a>
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
    <span id="theme-wrap">
      <a id="theme-btn" title="Optik anpassen">◐</a>
      <div id="theme-pop" class="look">
        <button class="thm on" data-theme="" title="Schwarz / Lila (Standard)"><span class="td" style="background:#8b5cf6"></span></button>
        <button class="thm" data-theme="gruen" title="Schwarz / Gruen"><span class="td" style="background:#22c55e"></span></button>
        <button class="thm" data-theme="blau" title="Schwarz / Blau"><span class="td" style="background:#3b82f6"></span></button>
        <button class="thm kira" id="thm-kira" data-theme="kira" title="Kira-Modus (Bild-Hintergrund)"></button>
        <label id="bgup" title="Hintergrund-Bild waehlen" style="cursor:pointer;color:var(--muted);font-size:15px">📷<input id="bgquick" type="file" accept="image/*" style="display:none"/></label>
      </div>
    </span>
  </div>

  <!-- ================= ZENTRALE ================= -->
  <div class="view on" id="v-home">
    <div id="hero">
      <img id="hero-av" alt="" src="/api/avatar"/>
      <div id="hero-txt">
        <div id="hero-name">KIRA</div>
        <div id="hero-status" class="muted">…</div>
      </div>
    </div>
    <div class="hud-strip" id="hud-strip"></div>
    <div class="direktive">
      <h3>🎯 Befehl an Kira</h3>
      <textarea id="dir-text" class="k" placeholder="Sag mir, worauf ich mich konzentrieren soll — oder gib mir einen Sofort-Auftrag…"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
        <button id="dir-now">⚡ Sofort ausfuehren</button>
        <button class="ghost" id="dir-focus">🧭 Als Fokus setzen</button>
        <button class="ghost" id="dir-clear" title="Fokus loeschen">Fokus loeschen</button>
        <span class="muted" id="dir-hint" style="align-self:center"></span>
      </div>
      <div id="dir-result" style="margin-top:8px;white-space:pre-wrap;display:none;border-top:1px solid var(--line);padding-top:8px"></div>
    </div>
    <div class="cmd-grid">
      <div class="cmd-main">
        <div class="panel">
          <div class="panel-h">◈ Live-Ops <span class="live"></span><span class="sp"></span>
            <span class="seg" id="ops-filter"><a data-of="all" class="on">alle</a><a data-of="action">aktionen</a><a data-of="chat">chat</a><a data-of="error">fehler</a></span>
          </div>
          <div id="ops-feed"><span class="muted" style="padding:10px 13px;display:block">…</span></div>
        </div>
      </div>
      <div class="cmd-side">
        <div class="panel">
          <div class="panel-h">◈ Heute <span class="sp"></span><a id="go-todo" class="muted" style="cursor:pointer;font-size:10px">→ Me</a></div>
          <div id="digest" class="panel-b"><span class="muted">…</span></div>
        </div>
        <div class="panel">
          <div class="panel-h">◈ Intel · KI-News <span class="sp"></span><a id="news-seed" class="muted" style="cursor:pointer;font-size:10px">+ Quellen</a></div>
          <div class="ticker" id="news-ticker"><span>… Intel wird geladen …</span></div>
          <div id="news-list" class="panel-b"><span class="muted">…</span></div>
        </div>
        <div class="home-side" id="home"></div>
      </div>
    </div>
  </div>

  <!-- ================= CHAT ================= -->
  <div class="view" id="v-chat">
    <div id="chat-wrap">
      <div id="sess-panel">
        <div class="sp-h"><span class="muted" style="font-size:11px;letter-spacing:1px">GESPRAECHE</span>
          <span style="flex:1"></span><button type="button" class="ghost" id="sess-new" title="Neue Unterhaltung (getrennt von der Tages-Session)" style="padding:4px 9px">＋</button></div>
        <div id="sess-items"><div class="muted" style="padding:10px">…</div></div>
        <div class="sp-f"><a id="sess-archtoggle" class="muted" style="cursor:pointer;font-size:11px">Archiv anzeigen</a></div>
      </div>
      <div id="chat-main">
        <div id="chatbar" style="display:flex;gap:8px;align-items:center;padding:4px 0 8px;flex-wrap:wrap">
          <button type="button" class="ghost" id="sess-toggle" title="Gespraeche ein-/ausklappen" style="padding:5px 10px">🗂</button>
          <span class="seg" id="chat-mode-seg" title="Modus: Chat = Dialog · Research = volles Werkzeug-Budget (lesend) · Coding = erst Plan, dann Schritte mit starkem Modell">
            <a data-m="chat" class="on">💬 Chat</a><a data-m="research">🔍 Research</a><a data-m="coding">🛠 Coding</a>
          </span>
          <span style="flex:1"></span>
          <span class="muted" id="mode-hint" style="font-size:11px">Dialog — kurz &amp; direkt.</span>
        </div>
        <div id="log"></div>
        <!-- S9.2: Werkzeug-Leiste UNTER dem Verlauf (wie ChatGPT/Claude): Befehle, Reasoning, Modell -->
        <div id="chat-tools">
          <span class="chip" id="chip-ziel" title="Arbeit einem Ziel zuordnen">@ziel:</span>
          <span class="chip" id="chip-mission" title="Kiras Missions-/Ziel-Lage abfragen">/mission</span>
          <span class="chip" id="chip-status" title="Status &amp; Selbst-Check">/status</span>
          <span class="chip" id="chip-plan" title="Erst Plan, dann Schritte">/plan</span>
          <span style="flex:1"></span>
          <label class="chip tog" id="chip-reason" title="Reasoning: staerkeres Modell, denkt gruendlicher"><input type="checkbox" id="reason-on"/> 🧠 Reasoning</label>
          <select id="chat-model" title="Modell fuer diesen Chat" style="max-width:190px"></select>
        </div>
        <form id="cform">
          <input id="cin" placeholder="Schreib mir…" autocomplete="off" autofocus/>
          <button type="button" id="micbtn" class="ghost" title="Sprachmemo aufnehmen">🎤</button>
          <label id="imgbtn" class="ghost" title="Bild an Kira" style="display:flex;align-items:center;padding:0 14px;border-radius:10px;cursor:pointer">📎<input id="imgfile" type="file" accept="image/*" style="display:none"/></label>
          <button>Senden</button>
        </form>
      </div>
    </div>
  </div>

  <!-- ================= PROJEKTE (S9.3: eine Uebersicht, kein Subtab-Umweg) ================= -->
  <div class="view" id="v-projekte">
    <div class="panel" id="proj-top">
      <div class="panel-h">◈ PROJEKTE <span class="sp"></span><span class="muted" id="vent-sum" style="font-size:11px"></span>
        <a id="obj-new-btn" class="muted" style="cursor:pointer;font-size:11px;margin-left:10px">+ Ziel</a></div>
      <div id="vent-list" class="panel-b"><span class="muted">…</span></div>
      <div id="vent-detail" class="panel-b" style="display:none;border-top:1px solid var(--line)"></div>
      <div class="panel-b" id="obj-form" style="display:none;border-top:1px solid var(--line)">
        <div class="row" style="flex-wrap:wrap">
          <input id="obj-title" placeholder="Ziel/Projekt-Titel" style="flex:1;min-width:180px"/>
          <select id="obj-kind"><option value="big">Big Project</option><option value="monthly">Monatsziel</option><option value="weekly" selected>Wochenziel</option></select>
          <input id="obj-date" type="date" title="Zieldatum"/>
          <button id="obj-add">Anlegen</button>
        </div>
      </div>
    </div>
    <div class="proj-cols">
      <div class="panel">
        <div class="panel-h">◈ ZIELE / PROJEKTE</div>
        <div id="obj-list" class="panel-b"><span class="muted">…</span></div>
      </div>
      <div class="panel">
        <div class="panel-h">◈ BACKLOG <span class="sp"></span><a id="todo-new-btn" class="muted" style="cursor:pointer;font-size:11px">+ Aufgabe</a></div>
        <div class="panel-b" id="todo-form" style="display:none">
          <div class="row" style="flex-wrap:wrap">
            <input id="todo-desc" placeholder="Was zu tun ist" style="flex:1;min-width:150px"/>
            <select id="todo-prio"><option value="1">P1</option><option value="2">P2</option><option value="3" selected>P3</option><option value="4">P4</option></select>
            <input id="todo-due" type="date" title="faellig"/>
            <button id="todo-add">+</button>
          </div>
          <div class="muted" style="margin-top:5px;font-size:11px">Ziel zuordnen: <select id="todo-obj"><option value="">— keins —</option></select></div>
        </div>
        <div id="todo-board" class="panel-b"><span class="muted">…</span></div>
      </div>
      <div class="panel">
        <div class="panel-h">◈ RADAR <span class="sp"></span><a id="rd-scan" class="muted" style="cursor:pointer;font-size:11px">⚡ scannen</a></div>
        <div id="rd-list" class="panel-b"><span class="muted" id="rd-hint">Woechentlicher Chancen-Scan. Convert = Projekt draus machen.</span></div>
      </div>
    </div>
  </div>

  <!-- ================= ME (dein Bereich) ================= -->
  <div class="view" id="v-me">
    <div class="me-grid">
      <!-- Spalte 1: was DU zu tun gibst -->
      <div class="me-col">
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
      <!-- Spalte 2: was KIRA von dir braucht -->
      <div class="me-col">
        <div class="panel me-grow">
          <div class="panel-h">◈ VON KIRA — braucht dich <span class="live"></span><span class="sp"></span><span class="muted" id="inbox-count" style="font-size:11px"></span></div>
          <div id="inbox-list" class="panel-b me-scroll"><span class="muted">…</span></div>
        </div>
        <div class="panel">
          <div class="panel-h">◈ ZUGANGS-ANFRAGEN <span class="sp"></span><a id="go-keys" class="muted" style="cursor:pointer;font-size:10px">→ Kira · Zugaenge</a></div>
          <div id="todo-secrets" class="panel-b me-scroll" style="max-height:22vh"><span class="muted">…</span></div>
        </div>
      </div>
      <!-- Spalte 3: Routine, Mails, Metriken (schlank) -->
      <div class="me-col">
        <div class="panel">
          <div class="panel-h">◈ DEINE ROUTINEN <span class="sp"></span><span class="muted" style="font-size:10px">per Telegram diktierbar</span></div>
          <div id="me-crons" class="panel-b me-scroll" style="max-height:20vh"><span class="muted">…</span></div>
          <div class="panel-b" style="border-top:1px solid var(--line)">
            <button class="ghost" id="me-brief-setup" style="font-size:12px">☀ Morgen-Briefing (08:00, aus)</button>
            <span class="muted" id="me-brief-hint" style="font-size:11px;margin-left:6px"></span>
          </div>
        </div>
        <div class="panel me-grow">
          <div class="panel-h">◈ E-MAILS <span class="sp"></span><span class="muted" style="font-size:10px">bald</span></div>
          <div id="me-mails" class="panel-b me-scroll"><div class="emptybox" style="min-height:80px;font-size:12px">Kein Postfach verbunden.<br>IMAP/SMTP unter Kira → Zugaenge eintragen.</div></div>
        </div>
        <div class="panel">
          <div class="panel-h">◈ METRIKEN <span class="sp"></span><span class="muted" style="font-size:10px">„Gewicht heute 91.4“</span></div>
          <div id="life-metrics" class="panel-b me-scroll" style="max-height:20vh"><span class="muted">…</span></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ================= KIRA (Persoenlichkeit & Specs) ================= -->
  <div class="view" id="v-kira">
    <div class="seg" id="kira-tabs" style="margin-bottom:12px;display:inline-flex;flex-wrap:wrap">
      <a data-s="files" class="on">✦ Seele &amp; Dateien</a><a data-s="mem">Gedaechtnis</a><a data-s="wissen">Wissen</a><a data-s="playbooks">Playbooks</a><a data-s="anatomie">Anatomie</a><a data-s="evolution">Evolution</a><a data-s="stats">Statistik</a><a data-s="keys">Zugaenge</a><a data-s="checkliste">Checkliste</a>
    </div>

    <div class="subview" id="v-keys">
      <div class="card"><h3>Von Kira angefordert</h3><div id="k-pending" class="muted">…</div></div>
      <div class="card"><h3>Zugang eintragen / aktualisieren</h3>
        <div class="muted">Werte sind write-only — werden nie angezeigt oder protokolliert. NIEMALS im Chat eingeben.</div>
        <div class="row"><input id="k-name" placeholder="Name, z.B. OPENROUTER_API_KEY"/>
          <input id="k-val" type="password" placeholder="Wert / Key / Passwort"/>
          <button id="k-save">Speichern</button></div>
        <div id="k-sugg" class="muted" style="margin-top:8px"></div></div>
      <div class="card"><h3>Vorhandene Zugaenge</h3><div id="k-set"></div></div>
    </div>

    <div class="subview on" id="v-files">
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
        <span class="seg" id="mem-filter"><a data-mf="all" class="on">alle</a><a data-mf="partner">🧠 Kira</a><a data-mf="user">👤 Du</a><a data-mf="fact">facts</a><a data-mf="lesson">lessons</a><a data-mf="skill">skills</a></span>
        <input id="mem-search" placeholder="🔍 suchen…" style="flex:1;min-width:150px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);outline:none"/>
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
        <div id="ck-list" style="margin-top:12px"><span class="muted">…</span></div>
      </div>
    </div>

    <div class="subview" id="v-stats">
      <div class="card"><h3>Lern-Kurve — besteht Kira ihre eigene Pruefung?</h3>
        <div class="muted">Jeder Mission-Task wird gegen Akzeptanzkriterien geprueft (Score 0-100).
        Hier siehst du, ob sie <b>besser</b> wird — nicht nur fleissiger.</div>
        <div id="st-kpi" style="display:flex;gap:26px;flex-wrap:wrap;margin-top:12px"><span class="muted">…</span></div>
      </div>
      <div class="card"><h3>Task-Arten — was klappt, was hakt</h3><div id="st-kinds" class="muted">…</div></div>
      <div class="card"><h3>Zaehe Ziele</h3><div id="st-objs" class="muted">…</div></div>
      <div class="card"><h3>Wiederkehrende Pruefer-Kritik</h3><div id="st-themes" class="muted">…</div></div>
      <div class="card"><h3>Strategien — lohnt Eskalation?</h3><div id="st-strats" class="muted">…</div></div>
      <div class="card"><h3>💶 Kosten je Modell (7 Tage)</h3><div id="st-costs" class="muted">…</div></div>
    </div>
  </div>

  <!-- ================= CONFIG (rein technisch) ================= -->
  <div class="view" id="v-config">
    <div class="seg" id="sys-tabs" style="margin-bottom:12px;display:inline-flex;flex-wrap:wrap">
      <a data-s="models" class="on">⚙ Modelle</a><a data-s="gov">Gewissen</a><a data-s="cron">Cron</a><a data-s="monitor">Monitor</a><a data-s="log">Protokoll</a><a data-s="cockpit">Cockpit</a>
    </div>

  <div class="subview on" id="v-models">
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
    <div class="card"><h3>Modell-Katalog (live: alle OpenRouter + lokal)</h3>
      <div class="row" style="margin-top:4px;flex-wrap:wrap">
        <label class="muted" style="align-self:center">Zuweisen an:</label>
        <select id="cat-role">
          <option value="chat">💬 Chat (Smalltalk)</option>
          <option value="reason">🧠 Reason / Coding</option>
          <option value="bulk">⏰ Crons (einfach)</option>
          <option value="escalation">⚡ Eskalation</option>
          <option value="default">★ Default (alles)</option>
        </select>
        <input id="cat-search" placeholder="🔍 suchen: deepseek, flash, claude, gemini, qwen …" style="min-width:240px;flex:1"/>
      </div>
      <div id="cat-list" style="max-height:340px;overflow:auto;margin-top:8px;font-size:12px"></div>
      <div class="muted" id="cat-hint" style="margin-top:6px"></div>
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

  <div class="subview" id="v-cockpit">
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
        <input data-ic="projekte" placeholder="Projekte" style="max-width:110px"/>
        <input data-ic="me" placeholder="Me" style="max-width:110px"/>
        <input data-ic="kira" placeholder="Kira" style="max-width:110px"/>
        <input data-ic="config" placeholder="Config" style="max-width:110px"/>
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
</div>
"""
