# BACKLOG — Warteschlange des Verbesserungs-Loops

> Eimer-Reihenfolge = Priorität. JETZT schlägt die Rotation (Sergens Hebel).
> Item-Format: `B-<nr> [R1..R4] Titel` + Akzeptanzkriterien. IDs nie wiederverwenden.
> Nächste freie ID: höchste vorhandene + 1.

## JETZT (Sergen-Override — schlägt die Rotation)

- [ ] B-000 [R1] End-to-End-Selbsttest des Loops + Linux-Test-Baseline erheben.
      Akzeptanz: kompletter Ablauf aus LOOP.md einmal durchlaufen (Lock, Paket,
      Tests, Abschluss-Eintrag, Backlog-Pflege); Baseline-Zeile in LOOP.md
      eingetragen; für etwaige Linux-only-Failures eigene Backlog-Items angelegt.

## HOCH
- [ ] B-027 [R2] AIMLAPI Bild-/Video-Generierung als Werkzeug: der Provider ist
      fuer CHAT-Modelle bereits im Router verdrahtet (aimlapi/-Prefix, Key
      AIMLAPI_API_KEY) und seit dem Modell-Oekonomie-Paket im Cockpit-Katalog
      sichtbar — Bild/Video laeuft aber ueber EIGENE Endpoints (/v1/images,
      /v1/video), nicht ueber chat-completions. Neues Tool bild_generieren
      (+ optional video_generieren), Ergebnis nach data/workspace/, Kosten als
      Event, Gate wie ueblich. Akzeptanz: Tool registriert, Tests (Fake-HTTP),
      Doku im HANDBUCH §2.
- [ ] B-023 [R2] Skeptiker-Gate fuer Content: bevor eine Mail/ein Text in die
      Freigabe-Inbox geht, prueft ein billiger Unteragent (rang=reflex/arbeiter)
      "steht JEDE Behauptung im Quellbericht?" — nein -> ein Zwangs-Retry, dann
      ehrlicher Vermerk. Muster: Liefernachweis (act.py plan-Schleife) + delegate.
      Akzeptanz: Tests (erfundene Behauptung wird gefangen, belegte passiert).
- [ ] B-025 [R2] Selbstkalibrierungs-Report: Nudge-/Zwangs-Retry-/Fallback-/
      Claim-Fail-Raten pro Modell aus den Events aggregieren (model_fallback,
      plan_step_retry, claim_check_failed, act_degraded) -> woechentlicher
      Vorschlag in die Freigabe-Inbox ("Budget X fuer Modell Y anpassen").
      Akzeptanz: Report-Funktion + Test; KEINE Auto-Aenderung ohne Freigabe.
- [ ] B-026 [R2] Modell-A/B konkretisieren (B-012): reason=GLM 5.2 vs.
      deepseek-v4-pro ueber Outcome-Pass-Quote + Kosten/Erfolg aus llm_call-Events
      vergleichen, sobald >20 Outcomes vorliegen. Ergebnis als Dossier docs/radar/.

- [ ] B-020 [R2] Harness-Diät Teil 2 — Werkzeug-Kern 65→~14 + `werkzeug_suchen`
      (Konzept §1): `core=True`-Flag in der Registry, manifest/tool_schemas
      filtern, Discovery-Tool lädt Nicht-Kern-Werkzeuge turn-lokal nach.
      Akzeptanz: Schemas < 8k Zeichen; alle 65 weiter erreichbar; Tests.
- [ ] B-021 [R2] Harness-Diät Teil 3 — schlanke Arbeits-Identität (Konzept §2):
      `_identity_lean()` (~4k: Verfassungs-Kurzfassung + Melde-Regeln) für
      delegate/schwarm/Plan-Schritte; volle Identität nur im Sergen-Chat.
      Akzeptanz: Budget-Test ≤ 4500 Zeichen; Delegation nutzt lean.
- [ ] B-001 [R1] Offene Falle Dossier §10: Test-Events landen in der Live-DB
      (`events.DB_PATH` in Tests mitpatchen, TestClient-Startup hinter Env-Flag).
      Akzeptanz: `pytest` emittiert 0 Events in eine echte `state.db`.
- [ ] B-002 [R1] Playbook `heartbeat-aktivierung` (begleitete Erst-Aktivierung
      als Prozedur, `reifegrad: entwurf`). Akzeptanz: folgt `_VORLAGE.md`, deckt
      Doctor-grün → Toggle → erste Ticks → Rückweg (Kill-Switch) ab.
- [ ] B-003 [R1] `runner --dry-run`: ein Tick ohne DB-Writes/LLM (Fake), zum
      gefahrlosen Üben am Desktop. Akzeptanz: neuer Test + Doku im Dossier.
- [ ] B-004 [R2] Budget-Tests für ALLE Prompt-Blöcke (`router_block`, Standup,
      BODY-Kopf ≤ 1500) analog `test_context_diet`. Akzeptanz: ein Test pro
      Block mit Zeichen-Limit.
- [ ] B-005 [R2] ACT-Protokoll-Härtung: Fälle von geleakten Tool-Calls schwacher
      GGUF-Modelle sammeln und Parser tolerant machen. Akzeptanz: neue
      Regressionstests in `tests/`.

## NORMAL

- [ ] B-006 [R3] `docs/wissen/harness-lernschleife.md` — Referenzartikel
      Outcomes → Insights → Planner (mit Wiki-Links, Vault-tauglich).
- [ ] B-007 [R3] Playbook `loop-review` für Sergen (wöchentlich LOOP-LOG lesen,
      JETZT-Eimer befüllen, Sammel-PR mergen). Akzeptanz: folgt `_VORLAGE.md`.
- [ ] B-008 [R4] Dossier: aktuelle lokale LLMs ≤ 16 GB VRAM für Kiras
      classify/embed/fallback-Rollen (Stand heute, mit Quellen).
- [ ] B-009 [R4] Dossier: neue MCP-Server mit Nutzen für die Assistenz-Mission
      (Mail/Kalender/Dateien/Recherche) — nur Bewertung, keine Installation.
- [ ] B-010 [R2] Retrieval-Härtung vorbereiten (Dossier §6): Re-Ranking-Optionen
      für Memory/Knowledge, nur Konzept + Tests, keine neuen Dependencies.

## IDEEN (unsortiert, vom Loop selbst gefüttert)

- B-024 [R1] Cockpit-Gedaechtnis-Browser: Datei-Browser von statischem FILES-Dict
  auf Verzeichnis-Walk fuer gedaechtnis/** + docs/** umstellen — BRAUCHT
  Traversal-Guard (resolve + is_relative_to ROOT) und Desktop-Abnahme.

- B-018 [R1] Delegation v2: `schwarm` echt parallelisieren (Threads; Vorsicht:
  Circuit-Breaker-Cross-Talk, Budget-Race, LLM-Pool max 6) + Skeptiker-
  Verifikation (N Unteragenten versuchen ein Ergebnis zu WIDERLEGEN, Mehrheit
  entscheidet). Auto-Rang-Wahl durch Kira (trivial → reflex, sonst arbeiter).
- B-012 [R2] Selbst-Benchmarking: fester Aufgaben-Satz, den Kira periodisch
  gegen verschiedene lokale Modelle fährt und per Verifier bewertet →
  datengetriebenes `switch_model` statt Bauchgefühl.
- B-013 [R3] Playbook-Autogenese: erfolgreiche Missions-Traces per Curator zu
  Playbook-Entwürfen destillieren ("Kira lehrt Kira").
- B-014 [R1] Prompt-Evolution mit Outcomes: A/B-Varianten von Promptblöcken
  gegeneinander laufen lassen, Outcome-Scores entscheiden — Messung statt Meinung.
- B-015 [R3] Wissens-Ingest-Pipeline: Sergen wirft PDFs/Links per Telegram ein →
  Knowledge-Archiv füllt sich automatisch (löst das 0-Docs-Problem am Desktop).
- B-016 [R4] Radar → Auto-PoC: vielversprechende Radar-Dossiers bekommen in der
  Cloud einen isolierten Proof-of-Concept-Branch (weiterhin nur Vorschlag, nie
  Auto-Install).
- B-017 [R3] Kira liest den Loop: Playbook für Desktop-Kira, das
  LOOP-LOG-Befunde in ihre eigenen Lessons/Skills übernimmt — Cloud-Loop und
  lokale Kira lernen voneinander.

## BLOCKIERT (mit Grund + Datum)

(leer)

## ERLEDIGT (nur die letzten 20 — Historie steht im LOOP-LOG)

- [x] B-019 [R2] Liefernachweis pro Plan-Schritt — direkt gebaut (PR #12, gemergt):
      Zwangs-Retry bei fehlendem Artefakt, ehrlicher Fehlschlag, plus Dispatcher
      (Rang pro Plan-Schritt) und Playbook leads-recherche.

- [x] B-011 [R1] Agenten-Delegation v1 — direkt in einer Chat-Session gebaut
      (PR #7, gemergt): `delegate`/`schwarm` nach Rang (reflex/arbeiter/denker/
      richter), Richter-Dossier, Tiefen-Sperre, Deckel. Folgearbeit: B-018.
