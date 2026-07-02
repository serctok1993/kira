# KIRA — IST-STAND (Übergabe-Dossier)

> **Zweck:** Diese Datei macht jede neue Fable/Claude-Session sofort arbeitsfähig, ohne den ganzen Harness neu durchzulesen. Sie beschreibt, was Kira ist, wo alles liegt, was gebaut wurde, was live an/aus ist, wie man arbeitet und wo die Hebel sind. **Stand: 2026-07-02.** Bei größeren Änderungen fortschreiben.

---

## 0. Wer bin ich in diesem Projekt (für die neue Session)

Du bist **Fable 5** (bei Dual-Use-Kanten automatisch auf **Opus 4.8**), Modell hinter dem Bau-Partner von **Sergen**. Du baust **Kira** aus — einen persönlichen, autonomen Agent-Harness (Python). Sergen ist **Systemdenker, kein Coder**: erklär konzeptionell, nimm den Kreativ-Lead, Qualitätsmaßstab Huly (Bewegungs-Physik vor Quantität). **Antworten auf Deutsch.** Direkt und ehrlich, kein Schmeicheln.

**Kira ≠ Luvex.** Luvex ist Sergens SaaS-Projekt (anderer Ordner). Kira ist der Harness hier.

## 1. Die Vision (Sergens Worte)

Kira soll ein **Iron-Man-Jarvis** werden: ein **autonomer Helfer / Unternehmer / Coder / Agent-Orchestrator / Alltagsbetreuer / Planer** — ein **sich selbst versorgender, verbessernder, lernender, geldverdienender** Harness. Motto: *„eine LLM ist nur so stark wie ihr Harness."* Er füttert Kira grenzenlos mit Wissen/Daten/Zugängen → „fertiger Schreibtisch" für jede zukünftige KI. Kira baut eigene Online-Standbeine (Email + Guthaben), skaliert zu Meilensteinen (100k €), nimmt ihm den Alltag ab.

## 2. Wo alles liegt / Starten / Testen

- **Repo:** `C:\Users\serge\Desktop\Kira` (git, Branch `main`). Python, uv-verwaltet, `.venv` vorhanden.
- **Zustand:** alles in `data/state.db` (SQLite, WAL) + JSON-Sidecars in `data/`.
- **Identität (frisch pro Turn gelesen):** `core/mind/{constitution.md, SOUL.md, GOAL.md, USER.md, BODY.md}`.
- **Starten (Autostart eingerichtet):** Windows-Login → `Startup\Kira.lnk` → `start-all.ps1` → Ollama + `python -m core.kernel.supervisor`. Der **Supervisor** hält Cockpit (127.0.0.1:8000), Telegram-Bot und Mission-Runner am Leben (Auto-Restart, Singleton über Port 8000). Der 24/7-Mission-Loop läuft NUR bei `heartbeat.enabled: true`.
- **Manuell:** `uv run uvicorn core.api.server:app --reload` (Cockpit) · `uv run python -m core.agency.missions.runner --once` (ein Mission-Tick) · `uv run python -m core.kernel.doctor` (Selbst-Check).
- **Tests (Pflicht-Gate):** `.venv\Scripts\python.exe -m pytest tests -q` — **muss immer grün sein** (auch `selfdev.verify_cmd`). Stand: **182 passed, 1 skipped**.
- **Neustart im Idle:** Datei `data/restart.flag` mit Inhalt `all` schreiben → Supervisor bounct die Dienste sauber. Kill-Switch: Datei `data/STOP` anlegen → alles hält sofort.

## 3. Architektur-Landkarte (Module → Zweck)

```
core/
  kernel/        Runtime
    events.py        Event-Store (append-only, single source of truth); emit()/recent()/severity()
    llm_router.py    EIN Gateway über litellm; resolve_model(task_type, escalate); Budget-Guard;
                     lokaler Fallback bei fehlendem Key; harte Wall-Clock-Timeouts
    scheduler.py     Heartbeat-Flag, Kill-Switch
    runstate.py      Turn-Management, Restart-Deferral, Watchdog
    supervisor.py    hält Cockpit/Bot/Runner; restart.flag
    doctor.py        Selbst-Check check(test_call=False): Routing/Keys/Ollama/npx/Disk/Imports/DB → problems[]
    models.py        Laufzeit-Modellwechsel (data/models.json)
  mind/          Kognition
    agent.py         build_system_prompt() (Verfassung+SOUL+GOAL+USER+BODY-Kopf+Memory+Lektionen+Skills)
                     + PERSONA_DIRECTIVE (~3.4k Zeichen, verdichtet)
    body.py          BODY.md-Generator: compact() (Kopf, injiziert) + refresh() (AUTO-Block täglich
                     aus Registry/MCP/DB/Modell-Routing abgeschrieben → kann nicht halluzinieren)
    memory/store.py  semantisches Gedächtnis (kinds: episodic/fact/lesson/skill), FTS5 + Ollama-Embeddings
                     (nomic-embed-text), recall() cosine→FTS→recency; curator entdoppelt Skills/Lektionen
    knowledge.py     Wissens-Archiv (knowledge_docs/chunks/FTS, Vault data/knowledge/, sha256-Dedupe,
                     Chunking, ingest_text/file (.txt/.md/.html/.pdf via pypdf), search())
    reflection.py    reflect()/reflect_on() → Lektionen ins Memory
    council.py       deliberate(): 3 Personas (Visionär/Skeptiker/Macher) + Judge; Rats-Debatte
    evolution.py     Selbst-Update von SOUL/GOAL/BODY (MUTABLE) via Freigabe-Inbox + Guardian
    curator.py       curate_skills()/curate_lessons() (löscht nie blind)
  agency/        Hände
    act.py           ReAct-Loop act(); _identity() (Mission-Prompt); act_chat_stream (WS-Chat, liefert
                     kind: think|tool|obs|final); plan_and_execute()
    outcomes.py      Ergebnis-Ledger (S2): eine Zeile pro Task-VERSUCH, UNIQUE(task_id,attempt)
    verifier.py      Prüfer (S2): Akzeptanzkriterien + harte Checks + LLM-Judge, fail-open
    ventures.py      Ventures + venture_ledger (Konto-Buch je Standbein, Meilenstein)
    radar.py         Business-Radar (S5): opportunities-Tabelle, scan()→Chancen, convert()→Venture
    approvals.py     Freigabe-Inbox (kinds: publish/external/email/email_stranger/money/evolution/generic)
    missions/
      runner.py      24/7-Heartbeat: run_once() (plan→pick objective (domain='business')→act→
                     verifier→pass/retry/fail); run_forever() (Monitor/Cron/Trigger/Wartung immer)
      queue.py       tasks-Tabelle (mission-scoped, board() bucketet today/week/…); get_task()
      objectives.py  Ziel-Hierarchie big/monthly/weekly, parent_id, venture_id, domain(business|leben);
                     list_active(domain=...) = Heartbeat-Filter
      planner.py     generate_tasks(goal, context) → atomare Tasks
      metrics.py     Lebens-Metriken (Gewicht etc.) für Coach + Sparklines
      standup.py     build_context() reiner Lagebericht (kein LLM), {{standup}}-Platzhalter in Cron
      workingset.py  lebendes Arbeitsstand-Doc je Objective (data/workspace/objective-<id>.md)
      cron.py        Zeitplan-Jobs (act-Prompts); run_job expandiert {{standup}}
      triggers.py    Wenn-Event-dann-Task (data/triggers.json, ID-Dedupe, Cooldown)
      maintenance.py maybe_run(name, interval) — tägliche/wöchentliche Wartung (Curator/BODY/Doctor/Radar/Stripe)
    tools/
      registry.py    @tool-Decorator + register(); manifest()/tool_schemas() (gehen in JEDEN LLM-Call)
      builtin.py     Kern-Werkzeuge + Import-Hub (unten importiert er venture_/mail_/knowledge_/
                     radar_/life_/trigger_tools + browser)
      life_tools.py  todo_add/list/done, objective_add, metric_log/list
      knowledge_tools.py  knowledge_search/list/note
      venture_tools.py / radar_tools.py / mail_tools.py / trigger_tools.py
      browser.py     browser_act (Playwright: goto/click/fill/press/read/screenshot; URL-Sandbox;
                     Zahlungsfeld-Stopp)
    mcp/
      client.py        MCP-Client (offizielle mcp-lib, stdio, getestet)
      registry_bridge.py  Bridge: MCP-Server-Tools → Kira-Registry; EIN dediziertes Event-Loop +
                     Owner-Task/Server (Lifecycle-Fix); Allowlists; Schreib-Tools durchs gate;
                     init_background() beim Boot (Cockpit/Runner/Bot)
    connectors/
      telegram_bot.py  Long-Polling; Voice (Whisper lokal), Foto (Vision), Dokument→Archiv, "merke:";
                       _agentic_reply = ruhiger Live-Trace (Pump editiert Fixtakt, kein Flackern);
                       _render_trace() (pur, testbar)
      mail.py          SMTP/IMAP (+Resend-Option), is_stranger()
      news_monitor.py  RSS/Web-Watches → monitor_new-Event
      stripe_sync.py   Einnahmen → venture_ledger (6h-Takt)
      transcribe.py    faster-whisper
  governance/
    treasury.py    Budget (can_spend/record_spend); today_spend/month_spend aus Events
    gate.py        guarded(kind, …, execute): needs_approval? → Inbox (KEINE Ausführung) sonst
                   execute + audit.record; money → Council-Debatte davor (config council_gate)
    autonomy.py    data/autonomy.json {chains_off, hard_gate}; needs_approval(kind)
    audit.py       record() → audit-Event (jede Außen-Aktion)
    secrets.py     data/secrets.json (write-only, in os.environ geladen); request()/pending()
  api/
    server.py      FastAPI-Cockpit-Backend (alle Endpoints) + WS /ws/chat
    ui/            Cockpit-Frontend (S5.3a aus server.py extrahiert):
      css.py (HEAD_AND_CSS) · views.py (VIEWS) · script.py (SCRIPT) · __init__.py (baut DASHBOARD_HTML)
```

## 4. Roadmap-Historie — was gebaut wurde (Commit-Ranges)

- **S1 — Zielgerichtet + Ketten ab** (ab2d779, cf338ef, 8fc8c13): Planner an Ziel-Baum; Autonomie-Config statt Trust-Gates; Config-Drift bereinigt.
- **S2 — Ergebnis-Rückkopplung** (6af7fc1→6d36b52): Outcome-Ledger + Prüfer (Akzeptanzkriterien, unabhängiger Judge, fail-open) + Qualitäts-Retries (max 2, andere Strategie) im `runner._execute_scored`; Curator täglich; Working-Set-Scratchpad. Qualitäts-Retries STRIKT getrennt von Absturz-Retries.
- **S3 — Unternehmen** (f8799e4→2c5a342): Ventures + Konto-Buch; Gate im Vollzug (needs_approval endlich verdrahtet); MCP-Brücke live gefixt (github+supabase); Mail-Konnektor; Browser-Aktor; Stripe verdrahtet (hinterm Gate) + Einnahmen-Sync.
- **S4 — Effizienz** (9484ccb/8fecfee/9c3729d/49697ef): Kontext-Diät (Persona −37%); Council-als-Gate vor Geld; proaktive Trigger.
- **S5 — Jarvis** (41c1a3e→6c1b114): Lebens-Ebene (Todos/Missionen/Ziele domain=leben, Metriken, Coach, {{standup}}); BODY.md (Anatomie-Selbstwissen, auto-generiert); Dashboard v2 (8-Tab-IA, UI extrahiert, WS-Vertrag gepinnt, Motion); Wissens-Archiv (Upload/Telegram/PDF); Business-Radar; Selbst-Check (doctor) + Telegram-Feinschliff.
- **Details der S5-Stufen:** siehe Memory `kira-s5-jarvis.md`.

## 5. Aktueller Live-Zustand (verifiziert 2026-07-02)

- **Modelle:** default/chat/bulk = `openrouter/deepseek/deepseek-v4-flash`; reason/escalation = `deepseek-v4-pro`; classify = lokal `llama3.1:8b`; local_fallback = `ollama_chat/qwythos`; embeddings = `nomic-embed-text`; vision = `glm-4.6v`. num_ctx 32768, max_tokens 8192.
- **Budget:** 20 €/Tag, 150 €/Monat (harte Bremse). Bei Erschöpfung → lokal (0 €).
- **Autonomie:** `chains_off: true`, `hard_gate: ["money","email_stranger"]`. Council-Gate auf `money`.
- **⚠ Heartbeat: AUS** (`heartbeat.enabled: false`). Der autonome Motor läuft nicht.
- **⚠ Letzte Kette dran:** `mission.goal` sagt wörtlich „Nur lesende Recherche/Analyse — KEINE Außen-Aktionen." Selbst mit Heartbeat an würde Kira nur recherchieren, nichts extern tun/verdienen.
- **Werkzeuge:** 55 registriert (u.a. self_edit, run_command, browse, browser_act, email_send/check, venture_*, radar_*, todo_*, metric_*, knowledge_*, trigger_*, web_search, request_secret).
- **MCP:** github AN, supabase AN, stripe/vercel/filesystem AUS.
- **Secrets gesetzt:** BRAVE_API_KEY, AIMLAPI_API_KEY, SUPABASE_ACCESS_TOKEN, SUPABASE_API_KEY, GITHUB_TOKEN.
- **Secrets OFFEN (von Kira angefragt, Sergen muss eintragen):** IMAP_/SMTP_* (Postfach), RESEND_API_KEY, STRIPE_RESTRICTED_KEY.
- **GOAL.md aktuell:** Etappen (100k → Reichweite → Impact); Fokus noch „Phase 1: mich selbst erkennen, keine Außen-Aktionen". Kira darf GOAL/SOUL/BODY selbst per Freigabe-Inbox ändern.
- **Verfassung (unantastbar):** kein irreversibler Schaden, Budget heilig, alles loggen, Not-Aus absolut, Ehrlichkeit vor Gefälligkeit, Legalität/Ethik.

## 6. Fähigkeiten & Schwächen (verdichtet)

**Stark:** Alltagsbetreuer/Planer (Lebens-Ebene komplett); Coder (self_edit mit Test+Rollback, run_command, GitHub-MCP, 182 Tests als Netz); Lernen (Memory/Lektionen/Reflexion/Curator/Outcome-Loop); Selbst-Verbesserung strukturell (self_edit+verify+rollback, doctor).

**Gebaut aber schlafend:** Unternehmer (Ventures/Radar/Stripe da, aber Key fehlt + Kette dran, **0 € verdient**); autonomer Helfer (Loop existiert, Heartbeat aus).

**Echte Schwächen (Hebel), getaggt:**
- ① **Motor aus + letzte Kette dran** (Harness/Config) — größter Vision-Realität-Abstand, billigster Fix.
- ② **Gehirn Mittelklasse** (Modell) — DeepSeek flash/pro trägt Prüfer/Council/self_edit/Planung; Router ist modell-agnostisch, wird nicht ausgereizt.
- ③ **Kein echter Agent-Orchestrator** (Harness/S6) — ein Gehirn, sequenziell, keine parallelen Subagenten.
- ④ **Nie extern gehandelt** (Harness/Provider) — äußere Schleife (echter Push/Mail/Deploy/Stripe) nie end-to-end gelaufen; Realzuverlässigkeit unbekannt.
- ⑤ **Selbstversorgung halbiert** — kann Budget nicht selbst auffüllen; Einnahmen fließen nicht in eigenes Guthaben zurück.
- ⑥ **Jung/brüchig** — Telegram + Cockpit hatten diese Woche echte Bugs (gefixt); Kanten brechen noch.
- ⑦ **Chat-Pfad ohne Outcome-Prüfung**; **Retrieval simpel** (6 Erinnerungen, lokale Embeddings, kein Re-Ranking).

## 7. S6+ Ausbau-Optionen (nach Hebel, noch nicht begonnen)

1. **Motor an + Kette lösen + Geld-Kreislauf EINMAL live** (kleinster Code, größter Realitätssprung).
2. **Modell-Upgrade** der harten Rollen (self_edit/Council/Prüfer/Planung) → hebt Urteilskraft überall; Kostenabwägung.
3. **Echte Subagenten** (Orchestrator): parallele Worker, Task-Locking, Budget-Split, self_edit-Kollisionsschutz.
4. **Selbstversorgung schließen**: Wallet, das sich aus Einnahmen auffüllt und Infra bezahlt.
5. **TTS-Stimme + Telegram-Reife** (Jarvis-Faktor).
6. **Retrieval härten** (Re-Ranking, sqlite-vec) + **Chat-Outcome-Loop**.

**Sergens offene Zuarbeit:** Postfach anlegen → SMTP/IMAP-Secrets + `channels.email` füllen + enabled:true; Stripe-Konto → RESTRICTED Key → stripe in mcp_servers.json enabled:true; `uv sync` für pypdf; Vercel bleibt Platzhalter (remote-HTTP/OAuth, Client ist stdio-only).

## 8. Arbeitsweise & Regeln (verbindlich)

- **Live-System nur auf Ansage anfassen** (Memory `kira-live-hands-off`): bauen + pytest offline ist ok, Commits ok. Aber KEINE Neustarts, KEINE Live-Ticks, keine Tool-Probeläufe, keine state.db-Pokes ohne Sergens Go. Neuer Code wird beim nächsten VON SERGEN angesagten Neustart wirksam. Sergen gibt Kira inzwischen DIREKT Aufträge — nicht dazwischenfunken. **Idle-Check und Aktion IMMER getrennte Schritte** (nie verkettet).
- **Nach jeder Änderung:** `pytest -q` grün → **neutraler Commit** (Identität `Sergen Tok <serc.tok1993@gmail.com>`, KEINE KI-Signatur/Co-Authored-By), Message-Stil wie `S5.4: …`. **Nur explizite Pfade committen, nie `git add -A`** (Repo ist dirty mit Kiras eigenen Artefakten; `constitution.md` evtl. modifiziert = Sergens Edit, nicht anfassen, nur melden).
- **Kira editiert per self_edit denselben Harness** — vor dem Bauen Git-Status + Idle prüfen, NIE gleichzeitig auf denselben Dateien.
- **Fehler immer taggen: Modell / Harness / Provider** (Sergen baut den Harness, muss wissen wo ansetzen).
- **Haus-Stil:** `_conn()`-Helper, `CREATE TABLE IF NOT EXISTS` + defensive `ALTER … try/except`, Modul-Funktionen, **deutsche Docstrings ohne Umlaute** (ae/ue/oe), Werkzeuge liefern **Strings, raisen nie** (executor retried Exceptions 3×). `events.emit()` überall. Kein neuer Build-Schritt/npm fürs Cockpit (self-editbar als String halten).
- **Zwischenberichte:** nach Push Compare/PR-Link + ggf. Vercel-Preview, laienverständlich.

## 9. Test-Muster (für schnelles Weiterbauen)

- pytest offline, `tests/` im Root. Temp-DB: `monkeypatch.setattr(mod, "DB_PATH", str(tmp_path/"state.db"))` für JEDES beteiligte Modul (auch `objectives`/`events`/`approvals`, sonst Lock-Flakes + Hands-off-Verstoß).
- Fake-LLM: `monkeypatch.setattr(llm_router, "complete", fake)` — fake liefert volle Dict-Form `{"text","cost_usd","model","fell_back","latency_s","escalated","tool_calls"}`.
- Cockpit-Smoke: `TestClient(server.app)`. **WS-Chat-Vertrag** per `websocket_connect` gepinnt (test_dashboard). **Cockpit-JS-Syntax** via `node --check` (test_dashboard, skippt ohne node).
- Fake-MCP: `FakeMcpServer` (test_registry_bridge). Events-Erkennung racefrei über ID-Dedupe (nicht reiner Zeitstempel).

## 10. Gelöste Bugs / Fallen (nicht neu reintreten)

- **Telegram `{API}\deleteMessage`** (Backslash statt Slash) → Sprachmemo-Transkript doppelt im Chat. Gefixt + Regressionstest (test_telegram: kein `{API}\` im Quelltext).
- **Cockpit-UI-Extraktion (S5.3a):** UI wurde aus `server.py` in `core/api/ui/` als **raw-string** (`r"""..."""`) gespeichert. Das Original war ein NORMALER String → Python hatte `\'`→`'` aufgelöst; im raw-string blieben Backslashes → kaputtes JS (Tabs unklickbar). Fix: `ast.literal_eval('"""'+raw+'"""')` reproduziert die Original-Semantik. **HEAD ist jetzt sauber** (node-verifiziert, 0 kaputte `\\'`-Sequenzen). Live-Problem heute vermutlich stale `__pycache__` (gelöscht) → beim nächsten Neustart weg. Regressionswache in `tests/test_dashboard.py` (kein `\\'` im JS + `node --check`).
- **Council-Gate in Tests:** money-Gate-Tests müssen `gate._council_kinds` stummschalten, sonst ECHTE LLM-Calls.
- **radar.scan:** Events erst NACH dem Transaktions-Block emittieren (sonst DB-Lock).
- **Test-Isolation:** in Runner-Tests auch `objectives.DB_PATH` mitpatchen (sonst greift `run_once` auf die echte state.db → Lock-Flakes + Hands-off-Verstoß).
- **Approvals-decide-Endpoint:** kein Doppelklick-Schutz (Kiras GOAL-Update wurde 10× in 6s angewendet) — offener Mini-Bug, harmlos.

## 11. Nützliche Read-Only-Checks für den Einstieg

```
git log --oneline -15
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m core.kernel.doctor          # Selbst-Check
type data\autonomy.json  &  type data\mcp_servers.json
REM Tools zählen:
.venv\Scripts\python.exe -c "import core.agency.tools.builtin; from core.agency.tools.registry import all_tools; print(len(all_tools()))"
REM DB-Gegencheck (read-only):
.venv\Scripts\python.exe -c "import sqlite3;print([r[0] for r in sqlite3.connect('data/state.db').execute(\"SELECT name FROM sqlite_master WHERE type='table'\")])"
```

Tabellen in state.db: events, memory(+fts), tasks, objectives, approvals, outcomes, ventures, venture_ledger, metrics, knowledge_docs, knowledge_chunks(+fts), opportunities.

## 12. Verwandte Memory-Dateien (im Session-Memory-Ordner)

`sergen-person`, `fehler-klassifikation`, `prometheus-harness`, `telegram-primaerkanal`, `kira-roadmap-stand`, `kira-s5-jarvis`, `kira-live-hands-off`, `kira-signature-look`, `arbeitsweise-design-lead`, `git-identitaet`.

---
*Ende KIRA-IST.md — bei größeren Änderungen fortschreiben.*
