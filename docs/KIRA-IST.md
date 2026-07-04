# KIRA — IST-STAND (Übergabe-Dossier)

> **Zweck:** Diese Datei macht jede neue Fable/Claude-Session sofort arbeitsfähig, ohne den ganzen Harness neu durchzulesen. Sie beschreibt, was Kira ist, wo alles liegt, was gebaut wurde, was live an/aus ist, wie man arbeitet und wo die Hebel sind. **Stand: 2026-07-03 (nach S9 + Bestandsaufnahme).** Bei größeren Änderungen fortschreiben.

---

## 0. Wer bin ich in diesem Projekt (für die neue Session)

Du bist **Fable 5** (bei Dual-Use-Kanten automatisch auf **Opus 4.8**), Modell hinter dem Bau-Partner von **Sergen**. Du baust **Kira** aus — einen persönlichen, autonomen Agent-Harness (Python). Sergen ist **Systemdenker, kein Coder**: erklär konzeptionell, nimm den Kreativ-Lead, Qualitätsmaßstab Huly (Bewegungs-Physik vor Quantität). **Antworten auf Deutsch.** Direkt und ehrlich, kein Schmeicheln.

**Kira ≠ Luvex.** Luvex ist Sergens SaaS-Projekt (anderer Ordner). Kira ist der Harness hier.

## 1. Die Vision (und ihre Re-Zentrierung in S8)

Ursprung: Kira soll ein **Iron-Man-Jarvis** werden — autonomer Helfer / Unternehmer / Coder / Planer, ein sich selbst verbessernder, lernender Harness. Motto: *„eine LLM ist nur so stark wie ihr Harness."*

**S8 hat den Kern neu geordnet (Sergens Entscheidung, verbindlich):**
1. **Assistenz für Sergen** — er trägt eine psychische Last und braucht echte Alltagshilfe: organisieren, Briefe, Todos, Termine, Lernen, Ordnen. Das zählt am meisten.
2. **Selbstoptimierung** — Schwächen/Bugs/fehlende Werkzeuge finden und beheben; robust bleiben (notfalls mit schwachem lokalem Modell).
3. **Geld ist NUR Mittel** — die 10k-Etappe finanziert Autonomie-Hardware und ist ein normales PROJEKT, kein Identitätskern. Kein Kasse/Meilenstein/ROI-Denken. Budget kalkuliert Sergen; Kira zeigt nur „Kosten bislang".

Dazu **Melde-Regeln** (in Persona + Mission verankert): jeder fertige Task wird knapp gemeldet; Fehler sofort und ehrlich; NIE Erfolg ohne Beleg behaupten; bei Unsicherheit das sagen.

## 2. Wo alles liegt / Starten / Testen

- **Repo:** `C:\Users\serge\Desktop\Kira` (git, Branch `main`). Python, uv-verwaltet, `.venv` vorhanden. Remote: `origin` = github.com/serctok1993/kira (PRIVAT, seit S11.5) — Handy-/Cloud-Sessions bauen auf Branches gegen dieses Remote; NUR die Desktop-Session fasst das Live-System an (state.db/Neustarts). Desktop-Workflow: `git pull` am Anfang, `git push` am Ende. data/, .env, Secrets sind gitignored und verlassen den PC nie.
- **Zustand:** alles in `data/state.db` (SQLite, WAL) + JSON-Sidecars in `data/` (seit S8.0 ALLE atomar via `core/kernel/fs.atomic_write`).
- **Identität (frisch pro Turn gelesen):** `core/mind/{constitution.md, SOUL.md, GOAL.md, USER.md, BODY.md}`. Änderungen an diesen Dateien wirken OHNE Neustart.
- **Starten (Autostart eingerichtet):** Windows-Login → `Startup\Kira.lnk` → `start-all.ps1` → Ollama + `python -m core.kernel.supervisor`. Der **Supervisor** hält Cockpit (127.0.0.1:8000), Telegram-Bot und Mission-Runner am Leben. Der Mission-Loop läuft NUR wenn `data/heartbeat.flag` ≠ off (das Flag überstimmt `config.heartbeat.enabled`).
- **Manuell:** `uv run uvicorn core.api.server:app --reload` (Cockpit) · `uv run python -m core.agency.missions.runner --once` (ein Tick) · `uv run python -m core.kernel.doctor` (Selbst-Check).
- **Tests (Pflicht-Gate):** `.venv\Scripts\python.exe -m pytest tests -q` — **muss immer grün sein**. Stand: **269 passed, 1 skipped** (inkl. `node --check`-Gate für das Cockpit-JS).
- **Neustart im Idle:** Datei `data/restart.flag` mit Inhalt `all` schreiben → Supervisor bounct sauber. Kill-Switch: Datei `data/STOP` → alles hält sofort. **Idle-Check und Neustart IMMER getrennte Schritte.**

## 3. Architektur-Landkarte (Module → Zweck)

```
core/
  kernel/        Runtime
    events.py        Event-Store (append-only, single source of truth); emit()/recent()/severity()
    llm_router.py    EIN Gateway über litellm; resolve_model(task_type, escalate); Budget-Guard;
                     lokaler Fallback bei fehlendem Key; harte Wall-Clock-Timeouts
    fs.py            atomic_write(path, text) — Temp-Datei + os.replace (S8.0, alle Sidecars)
    scheduler.py     Heartbeat-Flag, Kill-Switch
    runstate.py      Turn-Management, Restart-Deferral, Watchdog
    supervisor.py    hält Cockpit/Bot/Runner; restart.flag
    doctor.py        Selbst-Check check(): Routing/Keys/Ollama/npx/Disk/Imports/DB → problems[]
    models.py        Laufzeit-Modellwechsel (data/models.json)
  mind/          Kognition
    agent.py         build_system_prompt() (Verfassung+SOUL+GOAL+USER+BODY-Kopf+Memory+Lektionen+Skills)
                     + PERSONA_DIRECTIVE (~3.7k Zeichen, Budget <3800; enthält Zweck-Hierarchie
                     + Melde-Regeln aus S8.1)
    body.py          BODY.md-Generator: compact() (Kopf ≤1500 Zeichen, in JEDEM Prompt) + refresh()
                     (AUTO-Block täglich aus Registry/MCP/DB/Routing abgeschrieben)
    memory/store.py  semantisches Gedächtnis (kinds: episodic/fact/lesson/skill), FTS5 + Ollama-
                     Embeddings; recall() cosine→FTS→recency; clear_session löscht NUR episodic
    knowledge.py     Wissens-Archiv (Vault data/knowledge/, sha256-Dedupe, Chunking, PDF via pypdf)
    reflection.py    reflect()/reflect_on() → Lektionen ins Memory
    council.py       deliberate(): 3 Personas + Judge; Rats-Debatte (Gate vor Geld)
    evolution.py     Selbst-Update NUR von MUTABLE={SOUL,GOAL,BODY}.md via data/proposals/ +
                     Freigabe-Inbox; constitution.md auf ALLEN Software-Pfaden schreibgeschützt
    curator.py       curate_skills()/curate_lessons() (löscht nie blind)
    playbooks.py     Playbook-System (S11): Prozeduren in playbooks/*.md (Frontmatter:
                     wann/reifegrad/zaehler + Schritte/Akzeptanzkriterien/Lektionen);
                     router_block() haengt NUR Kopfzeilen an beide Prompt-Pfade
                     (agent.build_system_prompt + act._identity), Details via playbook_read;
                     Reifegrade entwurf->begleitet->autonom: Befoerderung NUR via Freigabe-
                     Inbox (kind 'playbook', 5 Erfolge in Serie), Fehlschlag stuft sofort
                     zurueck; record_result/add_lesson schreiben in die DATEI zurueck
                     (Lernen in Dateien statt Gewichten); refresh_index() pflegt INDEX.md
                     (Vault-Einstieg im Root, taeglich via Wartung). Obsidian zeigt den
                     Repo-Ordner als Vault — Dateisystem = Schnittstelle, kein Sync.
  agency/        Hände
    act.py           ReAct-Loop act(); act_chat mit Prefixen: "reason:" → escalate (S9.2),
                     "plan:" → Plan-Modus, "/work" → Werkzeugbudget; _resolve_objective_token (@ziel:)
    outcomes.py      Ergebnis-Ledger: eine Zeile pro Task-VERSUCH, UNIQUE(task_id,attempt)
    verifier.py      Prüfer: Akzeptanzkriterien + harte Checks + LLM-Judge, fail-open
    insights.py      liest den Outcome-Ledger (Fehl-Muster, Kosten-pro-Erfolg, Kritik-Themen) →
                     speist Planner-Prompt, Standup, Wochen-Lektionen, /api/insights (S6.2)
    ventures.py      Projekte + Konto-Buch; seit S8.2: briefing/set_briefing/append_briefing
                     (data/workspace/venture-<id>-briefing.md), files_dir/list_files (Upload),
                     costs(vid) = LLM-Kosten je Projekt (Join outcomes→tasks→objectives)
    radar.py         wöchentlicher Ideen-Scan — seit S8.1 experimentell/unkonventionell, kein
                     Einkommens-Fokus; opportunities-Tabelle, convert()→Venture
    desktop_watch.py Desktop-Pflege (S8.5): scannt konfigurierte Ordner lokal (0 €), heuristische
                     Kategorien, legt EINEN Sortier-Vorschlag in die Inbox — verschiebt NIE selbst
    approvals.py     Freigabe-Inbox (kinds: publish/external/email/email_stranger/money/evolution/…)
    missions/
      runner.py      Heartbeat: run_once() plant/arbeitet/prüft; jeder 3. Tick (self_every) =
                     _self_improve_tick (Doctor+Insights+Fehler → an sich selbst arbeiten, S8.1);
                     Venture-Kontext = Projekt/Briefing/Kosten-bislang (KEIN Kasse/Meilenstein)
      queue.py       tasks-Tabelle (termin-bewusst: Überfälliges zuerst, Retry-first)
      objectives.py  Ziel-Hierarchie big/monthly/weekly, venture_id, domain(business|leben)
      planner.py     generate_tasks(goal, context); budget-bewusst (nur Schutzwarnung)
      metrics.py     Lebens-Metriken (Coach + Sparklines)
      standup.py     build_context() reiner Lagebericht (kein LLM), {{standup}} in Cron
      workingset.py  lebendes Arbeitsstand-Doc je Objective (data/workspace/objective-<id>.md)
      cron.py        Zeitplan-Jobs mit **scope** (me | projekt:<vid> | system, S8.4);
                     Morgen-Briefing als 1-Klick-Vorlage im Me-Bereich (startet AUS)
      triggers.py    Wenn-Event-dann-Task (Backoff bei Fehlschlägen)
      maintenance.py maybe_run(name, interval) + bump_counter (Selbst-Tick-Rotation)
    tools/           @tool-Registry; 58 builtin (+ MCP-Tools zur Laufzeit); Werkzeuge liefern
                     Strings, raisen nie; project_note (S8.2, fuzzy + Rückfrage), cron_add mit scope
      delegate_tools.py  Delegation nach RANG (reflex→classify lokal 0€ | arbeiter→worker Flash |
                     denker→reason | richter→escalation=stärkstes Modell): delegate (1 Unteragent =
                     frische act()-Schleife, Session sub-…, Schritt+Kosten-Deckel, Tiefen-Sperre)
                     + schwarm (Fan-out über Liste, v1 sequenziell, schwarm_max). Richter bekommt
                     Brief (Insights+Dossier) und schreibt data/workspace/richter-dossier.md fort.
                     Rang-Tabelle in config models.routing — Modellwechsel = eine Config-Zeile.
    mcp/             Client + registry_bridge (github/supabase AN; Schreib-Tools durchs Gate;
                     server_status() defensiv, Config-Writes atomar seit S8.0)
    connectors/
      telegram_bot.py  Long-Polling; Voice/Foto/Dokument; "merke:"; seit S8.0 exponentielles
                       Backoff (2s→60s) + Störungs-Bündelung (1 Event je Serie statt Spam)
      mail.py          SMTP/IMAP (+Resend-Option), is_stranger() — Postfach fehlt noch
      news_monitor.py  Watches → monitor_new-Events (füttern das Intel-Panel der Zentrale, S9.1)
      stripe_sync.py   Einnahmen → venture_ledger (Key fehlt noch)
  governance/
    treasury.py    Budget (can_spend/record_spend, SQL-Summen); Limits setzt Sergen (config)
    gate.py        guarded(kind, …): needs_approval? → Inbox, sonst execute + audit; money → Council
    autonomy.py    data/autonomy.json {chains_off, hard_gate} = die EINZIGE echte Kontrolle;
                   GET/POST /api/autonomy; Schalter-Karte im Cockpit (S8.3)
    trust.py       DEPRECATED (Barometer entfernt in S8.3 — nichts ruft es mehr)
    audit.py       record() → audit-Event (jede Außen-Aktion)
    secrets.py     data/secrets.json (write-only, nie im Chat); request()/pending()
  api/
    server.py      FastAPI (~90 Endpoints) + WS /ws/chat; Tages-Chat-Sessions cockpit-YYYY-MM-DD,
                   chat_meta.json (Archiv); /api/life/add (Me-Quick-Add); /api/monitor (Intel)
    ui/            Cockpit 2.0 als inline Strings OHNE Build-Step (self-editbar):
      css.py · views.py · script.py · __init__.py (baut DASHBOARD_HTML)
      Shell: EINE generische SUBTABS-Registry + subnav() — neue Bereiche/Unterreiter sind
      Registry-Eintrag + Div, kein Umbau (S7a). 6 Tabs: Zentrale/Chat/Projekte/Me/Kira/Config.
      Kein-Scroll-Disziplin ≥1050px: Views overflow:hidden, Panels scrollen intern (S9).
```

## 4. Roadmap-Historie — was gebaut wurde

- **S1–S5** (ab2d779 → 6c1b114): Ziel-Baum + Autonomie-Config; Outcome-Ledger + Prüfer + Qualitäts-Retries; Ventures/Gate/MCP/Mail/Browser/Stripe; Kontext-Diät + Council-Gate + Trigger; Lebens-Ebene, BODY.md, Dashboard v2, Wissens-Archiv, Radar, Doctor.
- **S6 — Härtung + Lernschleife** (14be811 → 4827286): Identitäts-Abgleich (10k-GOAL, SOUL/USER-Merge); Verfassung auf ALLEN Pfaden schreibgeschützt, Vorschläge werden konsumiert (10x-Apply-Bug), Freigaben idempotent; insights.py schließt die Lernschleife (Outcome-Ledger → Planner/Standup/Lektionen); Wochen-Zerlegung großer Ziele + Stall-Erkennung + @ziel:-Buchung; Cockpit v3 (Fehler sichtbar, EIN Poll-Scheduler, WS-Reconnect); Aktivierung vorbereitet (Gates statt Verbote; heartbeat.flag=off überstimmt bis zum Cockpit-Toggle).
- **S6.6–S7 — Cockpit 2.0** (1f15c25 → b0754a3): IA nach Sergens Zuschnitt, sicherer Markdown-Chat, Statistik (/api/insights), Avatar; Neon-Lila/Schwarz-Theme (Türkis raus, Karo raus); generische Tab/Subtab-Registry; 6-Tab-IA; Chat 2.0 (Tages-Sessions, Archiv, Modus-Schalter Chat/Research/Coding).
- **S8 — Re-Zentrierung** (0b99b4a → d7d68af): S8.0 Reparatur (atomic_write überall, Telegram-Backoff+Bündelung); S8.1 Identität & Takt (Zweck-Hierarchie, Melde-Regeln, Selbst-Tick jeder 3., Radar experimentell, /api/evolution + Evolution-Subtab); S8.2 Projekt-Gedächtnis (Briefing bindend in Planung+Task, project_note, Kosten je Projekt, Datei-Ablage, Projekt-Akte); S8.3 Autonomie-Schalter statt Vertrauensbarometer; S8.4 IA-Verschiebung (Zugänge→Kira, Cron-Scopes, Morgen-Briefing-Vorlage); S8.5 Desktop-Pflege (Vorschlag-first, lokal).
- **S9 — Dashboard-Feinschliff** (fbf2f42 → 9516726): Zentrale (Kiras kuratierte Monitor-News statt RSS, Ticker 140s, HUD erweitert, Dopplungen raus); Chat-Werkzeugleiste unten (Modell + Reasoning-Toggle „reason:" + Chips @ziel//mission//status//plan); Projekte = EINE Übersicht (Radar-Einbahn-Bug strukturell weg); Me = 3-Spalten-App-Layout + Quick-Add; Kein-Scroll-Disziplin überall.
- **S10 — Bestandsaufnahme**: BODY.md auf S8/S9-Realität, dieses Dossier, Kiras eigene Reflexion; S10.1: Kiras genehmigte GOAL/SOUL-Neufassung angewendet.
- **S11 — Playbook-System**: Vault-Struktur (INDEX.md + playbooks/ mit _VORLAGE, akquise-email, wochen-review); core/mind/playbooks.py (Router + Reifegrade + Lernschleife + Index-Refresh); 4 Werkzeuge (playbook_list/read/result/lesson); Beförderung über Freigabe-Inbox (kind playbook), Rückstufung automatisch; Cockpit: Kira→Playbooks + /api/playbooks; tägliche Index-Wartung im Runner.

## 5. Aktueller Live-Zustand (verifiziert 2026-07-03, read-only)

- **Modelle:** default/chat/bulk = `openrouter/deepseek/deepseek-v4-flash`; reason/escalation = `deepseek-v4-pro`; classify = lokal `llama3.1:8b`; embeddings = `nomic-embed-text`.
- **Budget:** 20 €/Tag, 150 €/Monat (harte Bremse, setzt Sergen). Monat bislang: ~40,6 €.
- **Autonomie:** `chains_off: true`, `hard_gate: ["money","email_stranger"]`, Council-Gate auf money. Steuerbar über die Schalter-Karte (Cockpit → Gewissen).
- **Motor:** `config heartbeat.enabled: true`, aber **`data/heartbeat.flag` = off → Motor AUS**. Die begleitete Erst-Aktivierung (Doctor grün → Cockpit-Toggle → erste Ticks beaufsichtigen) steht noch aus.
- **Werkzeuge:** 60 builtin registriert (S11: +4 Playbook-Werkzeuge); mit MCP-Brücke zur Laufzeit ~77 (Cockpit → Kira → Anatomie zeigt den gruppierten Werkzeugkasten).
- **MCP:** github AN, supabase AN, stripe/vercel/filesystem AUS.
- **Datenlage (state.db):** 36 Tasks (32 done, 4 pending — alle via Chat/Cron, **0 Outcomes: der bewertete Heartbeat-Pfad ist noch NIE gelaufen**); 2 aktive Monats-Ziele (Validierungs-Experimente); 3 Ventures (alle Status „idea"); 625+ Memory-Einträge (8 Lektionen, 6 Skills, seit S10 sechs Selbst-Fakten); Wissens-Archiv leer (0 Docs); 12 Radar-Opportunities.
- **Aktiv genutzt wird sie längst:** Telegram-Chat täglich; drei LIVE-Crons in data/cron.json — Sunrise Schlafzimmer 05:55 (steuert `core/tools/sunrise_hue.py`, Kiras eigenes Werk), Morgen-Briefing 08:00 (läuft, liefert per Telegram), Abend-Briefing 20:00. Crons laufen UNABHÄNGIG vom Heartbeat (run_forever: Monitor/Cron/Trigger/Wartung immer).
- **Offen bei Sergen:** ① Kiras GOAL.md-Neufassung wartet in der Freigabe-Inbox (`data/proposals/GOAL.md`, Me → „Von Kira"). ② Secrets: IMAP_/SMTP_* (Postfach), RESEND_API_KEY, STRIPE_RESTRICTED_KEY. ③ Begleitete Heartbeat-Aktivierung.
- **Verfassung (unantastbar, nur via Git):** kein irreversibler Schaden, Budget heilig, alles loggen, Not-Aus absolut, Ehrlichkeit vor Gefälligkeit, Legalität/Ethik.

## 6. Fähigkeiten & Schwächen (ehrlich, Stand S10)

**Stark (gebaut UND benutzt):** Chat-Assistenz mit dauerhaftem Gedächtnis (Telegram + Cockpit, Voice/Foto/Dokument); Lebens-Board/Coach; Coder-Werkzeuge (self_edit mit Test+Rollback, run_command, GitHub-MCP, 269 Tests als Netz); Governance (Gates, Audit, Budget-Bremse, Verfassungs-Schutz — real erprobt, Kira hat einmal versucht die Verfassung zu ändern und wurde technisch gestoppt); Cockpit 2.0 als vollwertige Bedienoberfläche.

**Gebaut, aber noch nie unter Realbedingungen gelaufen:** der autonome Motor (Heartbeat/Planner/Prüfer/Outcome-Lernschleife — 0 Outcomes); Projekt-Arbeit mit Briefings; Selbst-Tick; Desktop-Pflege (Default aus); E-Mail/Stripe (Secrets fehlen). *(Briefings dagegen laufen real — siehe §5.)*

**Echte Schwächen (Hebel), getaggt:**
- ① **Motor nie gelaufen** (Harness/Config) — größter Vision-Realität-Abstand; die ganze S6.2-Lernschleife (Outcomes→Insights→Planner) ist theoretisch korrekt, aber ungefüttert. Billigster Fix: begleitete Aktivierung.
- ② **Gehirn Mittelklasse** (Modell) — DeepSeek flash/pro trägt Prüfer/Council/self_edit; Router ist modell-agnostisch, wird nicht ausgereizt.
- ③ **Agent-Orchestrator: v1 gelöst** (Harness) — `delegate`/`schwarm` spawnen Unteragenten nach Rang (eigene Session/Budget/Modell, Tiefen-Sperre). Noch offen: echte Parallelität + Skeptiker-Verifikation (v2).
- ④ **Nie extern gehandelt** (Harness/Provider) — echter Push/Mail/Deploy nie end-to-end; Realzuverlässigkeit unbekannt.
- ⑤ **Wissens-Archiv leer** — die Infrastruktur (Vault/PDF/Suche) wartet auf Fütterung durch Sergen.
- ⑥ **Chat-Pfad ohne Outcome-Prüfung**; **Retrieval simpel** (6 Erinnerungen, lokale Embeddings, kein Re-Ranking).
- ⑦ **Approvals-decide ohne Doppelklick-Schutz auf API-Ebene** war S6.1 gefixt (idempotent + 409) — erledigt; als Falle dokumentiert in §10.

## 7. Nächste Schritte (Kandidaten fürs Fine-Tuning-Brainstorming mit Sergen)

1. **Begleitete Aktivierung** — Doctor grün → Cockpit-Toggle → erste Ticks gemeinsam beobachten (inkl. erster Selbst-Tick). Kleinster Aufwand, größter Realitätssprung; füttert erstmals die Lernschleife.
2. **GOAL.md-Entscheid** — Sergen genehmigt/verwirft Kiras Neufassung in der Inbox.
3. **Alltag scharf schalten** — Morgen-Briefing-Routine AN, erste echte Lebens-Todos/Termine über Kira laufen lassen; Desktop-Watch auf einen Testordner.
4. **Postfach** — IMAP/SMTP-Secrets → E-Mail-Kanal (Briefe/Behörden ist Kern der Assistenz-Mission).
5. **Modell-Upgrade der harten Rollen** (Prüfer/Council/self_edit/Planung) — Urteilskraft überall, Kostenabwägung mit Sergen.
6. **Wissens-Archiv füttern** — Dokumente/Briefe/Verträge rein, dann kann Kira ordnen und nachschlagen.
7. Später: Subagenten-Orchestrierung, TTS-Stimme, Retrieval-Härtung, Chat-Outcome-Loop.

## 8. Arbeitsweise & Regeln (verbindlich)

- **Live-System nur auf Ansage anfassen:** bauen + pytest offline ok, Commits ok. KEINE Neustarts, Live-Ticks, Tool-Probeläufe oder state.db-Schreibzugriffe ohne Sergens Go. Neuer Code wirkt beim nächsten angesagten Neustart — AUSNAHME: `core/mind/*.md` werden pro Turn frisch gelesen. **Idle-Check und Aktion IMMER getrennt.** Nach Neustart: Marker-Poll auf Auslieferung, bei UI-Änderungen Browser-Abnahme (claude-in-chrome).
- **Nach jeder Änderung:** `pytest -q` grün (inkl. node-Gate) → **neutraler Commit** (Identität `Sergen Tok <serc.tok1993@gmail.com>`, KEINE KI-Signatur/Co-Authored-By), Message-Stil `S<stufe>: …`. **Nur explizite Pfade, nie `git add -A`.**
- **Kira editiert per self_edit denselben Harness** — vor dem Bauen Git-Status + Idle prüfen.
- **Fehler immer taggen: Modell / Harness / Provider.**
- **Haus-Stil:** `_conn()`-Helper, `CREATE TABLE IF NOT EXISTS` + defensive `ALTER`, Modul-Funktionen, **deutsche Docstrings ohne Umlaute**, Werkzeuge liefern **Strings, raisen nie**, `events.emit()` überall, JSON-Sidecars NUR über `fs.atomic_write`. Kein Build-Schritt/npm fürs Cockpit. **In UI-Strings nur ASCII-Platzhalter** (NUL-Byte-Falle, §10).
- **Secrets sind write-only** — niemals Werte in Chat/Logs/Commits.

## 9. Test-Muster (für schnelles Weiterbauen)

- pytest offline, `tests/` im Root. Temp-DB: `monkeypatch.setattr(mod, "DB_PATH", str(tmp_path/"state.db"))` für JEDES beteiligte Modul (auch `objectives`/`events`/`approvals`, sonst Lock-Flakes + Hands-off-Verstoß).
- Fake-LLM: `monkeypatch.setattr(llm_router, "complete", fake)` — volle Dict-Form `{"text","cost_usd","model","fell_back","latency_s","escalated","tool_calls"}`.
- Cockpit-Smoke: `TestClient(server.app)`; WS-Chat-Vertrag gepinnt; **JS-Syntax via `node --check`** (test_dashboard, skippt ohne node). UI-Marker-Tests statt Pixel-Vergleich; finale Optik-Abnahme im Browser.
- Council-Gate in money-Tests stummschalten (`gate._council_kinds`), sonst ECHTE LLM-Calls.
- Test-Token nie hex-anfällig wählen (`@ziel:e` traf zufällig UUID-Präfixe).

## 10. Gelöste Bugs / Fallen (nicht neu reintreten)

- **NUL-Bytes in UI-Strings:** unsichtbare U+0000 in einem JS-Platzhalter machten script.py unimportierbar. Nur ASCII-Platzhalter (`@@NAME<n>@@`) verwenden; bei „Datei kaputt"-Verdacht erst mit read_file/Read verifizieren.
- **Typografische Anführungszeichen** („…") in doppelt-gequotetem JS-String = SyntaxError — das node-Gate fängt es; Text ohne Sonderquotes schreiben.
- **Grep-Tool-Artefakte:** Grep zeigte `<\span>`/`\api\...` obwohl die Datei korrekt war — Darstellungsfehler, IMMER mit Read verifizieren bevor man „Korruption" fixt.
- **CSS-Quell-Reihenfolge:** Fallback-Regel gleicher Spezifität NACH der @media-Query überstimmt sie (S9.5-fix: Basis-Regeln VOR die Query).
- **Flex-Quetsch-Falle:** Subtab-Leisten in Flex-Spalten brauchen `flex-shrink:0`, sonst quetscht ein großer Subview sie auf 2px (Tab-Wechsel unmöglich).
- **Cockpit-UI als raw-string extrahiert** → `\'`-Sequenzen brachen JS; `ast.literal_eval` reproduzierte die Semantik. Regressionswache in test_dashboard.
- **Telegram `{API}\deleteMessage`** (Backslash) → doppelte Transkripte. Gefixt + Regressionstest.
- **radar.scan:** Events erst NACH dem Transaktions-Block emittieren (DB-Lock).
- **mcp_servers.json transient korrupt** („Expecting value") — Ursache nicht-atomare Writes; seit S8.0 atomic_write überall + defensives server_status().
- **10x-GOAL-Apply:** Vorschläge werden beim Anwenden konsumiert, Freigaben idempotent (S6.1).
- **restart.flag mit BOM = stiller Leerlauf:** PowerShell 5.1 schreibt `-Encoding utf8` MIT BOM → Supervisor las `﻿all`, fand kein gültiges Ziel, konsumierte den Flag und bouncte NICHTS (kein Fehler sichtbar). Seit S11.1 liest der Supervisor `utf-8-sig`; Flags aus PowerShell trotzdem BOM-frei schreiben (`[IO.File]::WriteAllText(pfad,"all")`).
- **OFFEN — Test-Events im Live-Log:** einige Tests (autonomy-Roundtrip, cron-Scope) patchen zwar die Sidecar-Pfade, aber NICHT `events.DB_PATH` — pytest-Läufe emittieren `autonomy_changed`/`cron_added` in die echte state.db; zusätzlich bootet `TestClient(server.app)` beim Startup die ECHTE MCP-Brücke (`mcp_bridge_ready`-Events, npx-Prozesse). Verwirrt jede Audit-Sicht. Fix: events.DB_PATH konsequent mitpatchen + Startup-Hook hinter Env-Flag.

## 11. Nützliche Read-Only-Checks für den Einstieg

```
git log --oneline -15
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m core.kernel.doctor
type data\autonomy.json  &  type data\heartbeat.flag  &  type data\mcp_servers.json
REM Tools zählen:
.venv\Scripts\python.exe -c "import core.agency.tools.builtin; from core.agency.tools.registry import all_tools; print(len(all_tools()))"
REM DB read-only (URI-Modus verhindert versehentliche Writes):
.venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect('file:data/state.db?mode=ro',uri=True);print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")])"
```

Tabellen in state.db: events, memory(+fts), tasks, objectives, approvals, outcomes, ventures, venture_ledger, metrics, knowledge_docs, knowledge_chunks(+fts), opportunities.

## 12. Verwandte Memory-Dateien (im Session-Memory-Ordner)

`kira-s6-stand` (Stand-Historie), `heartbeat-flag-ueberstimmt-config`, `verfassung-nur-git` — plus ältere: `sergen-person`, `fehler-klassifikation`, `kira-live-hands-off`, `git-identitaet`.

---
*Ende KIRA-IST.md — bei größeren Änderungen fortschreiben.*
