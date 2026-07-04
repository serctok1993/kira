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

- [x] B-011 [R1] Agenten-Delegation v1 — direkt in einer Chat-Session gebaut
      (PR #7, gemergt): `delegate`/`schwarm` nach Rang (reflex/arbeiter/denker/
      richter), Richter-Dossier, Tiefen-Sperre, Deckel. Folgearbeit: B-018.
