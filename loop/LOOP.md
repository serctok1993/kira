# LOOP — Betriebsanleitung für die Kira-Verbesserungs-Routine

> Du bist eine frische Cloud-Session ohne Gedächtnis. ALLES, was du wissen musst,
> steht hier, im letzten Eintrag von [[loop/LOOP-LOG|LOOP-LOG]] und in
> [[loop/BACKLOG|BACKLOG]]. Lies zuerst [[docs/KIRA-IST|das Dossier]], dann
> arbeite exakt nach diesem Ablauf. Du arbeitest auf Deutsch.

## Mission

Eine Iteration = **EIN** mittelgroßes, abgeschlossenes Arbeitspaket, das Kira
messbar besser macht. Qualität vor Menge. Alles landet als Commit auf dem
Sammel-Branch; Sergen liest das LOOP-LOG und merged den Sammel-PR, wann er will.
Wichtige Realität: Diese Session sieht **kein `data/`** (gitignored, lebt nur auf
Sergens PC). Du kannst das Live-System weder starten noch beschädigen — du kannst
Code, Tests, Playbooks und Wissen **aktivierungsreif** machen.

## Betriebsparameter

- Branch: `kira/loop` (fest) · Draft-PR-Titel: `Kira-Loop — Sammel-PR (ab <datum>)`
- Takt: alle 4 h · Stale-Schwelle für Locks: 3 h
- Testkommando: `uv run pytest tests -q`
- Linux-Test-Baseline: **<noch offen — trägt Iteration 1 ein, z. B. "269 passed, 2 skipped">**
- Scope-Limits pro Iteration: 1 Arbeitspaket · max. ~10 Dateien · max. ~400 geänderte
  Codezeilen (reine Doku/Wissensartikel ausgenommen) · Ziel < 90 min

## Ablauf einer Iteration (exakt in dieser Reihenfolge)

0. **ORIENTIERUNG:** `docs/KIRA-IST.md`, dieses Dokument, letzter LOOP-LOG-Eintrag, BACKLOG.
1. **ÜBERLAPPUNGS-CHECK:** Ist der neueste LOOP-LOG-Eintrag Status `laeuft` und
   jünger als 3 h → Abbruch ohne jede Änderung. Ist er `laeuft` und älter als
   3 h → Status auf `abgebrochen` setzen (die Session ist tot) und weitermachen.
2. **BRANCH & PR:** `git fetch origin`. Existiert ein OFFENER PR mit Head `kira/loop`?
   - NEIN (gemerged/geschlossen/nie existiert): `git checkout -B kira/loop origin/main`,
     pushen, neuen **Draft-PR** öffnen. (Log/Backlog kommen über main mit, wenn gemerged.)
   - JA: `git checkout kira/loop` + auf `origin/kira/loop` setzen. Ist `origin/main`
     voraus: `git merge origin/main` (Konfliktregeln siehe Fehlerfälle).
3. **LOCK/START-EINTRAG:** Neuen LOOP-LOG-Eintrag mit Status `laeuft` und dem
   gewählten Paket anlegen, committen, SOFORT pushen. Wird der Push als
   non-fast-forward abgelehnt → eine andere Session läuft → Abbruch.
4. **RICHTUNG WÄHLEN** (Rotation, siehe unten) und EIN Paket aus dem BACKLOG ziehen
   (JETZT-Eimer schlägt die Rotation).
5. **AUSFÜHREN:** klein, fertig, getestet. Kein Marathon, kein Scope-Creep.
6. **TESTEN:** `uv run pytest tests -q` — keine NEUEN Failures relativ zur Baseline.
7. **COMMIT & PUSH:** Nachricht `LOOP-<n>: <was>`. Nur explizite Pfade stagen,
   nie `git add -A` (Hausregel, Dossier §8).
8. **ABSCHLUSS-EINTRAG:** Log-Eintrag auf `fertig`/`blockiert` stellen; Befunde,
   neue Möglichkeiten und Fragen an Sergen ausfüllen. Neue Ideen als Items ins
   BACKLOG (Selbst-Fütterung).
9. **BACKLOG-PFLEGE:** Erledigtes Item nach ERLEDIGT, Blockiertes nach BLOCKIERT
   (mit Grund + Datum), nächste ID fortzählen. Hat das Log > 40 Einträge →
   älteste nach `loop/archiv/LOOP-LOG-<jahr>-<monat>.md` verschieben.

## Die vier Richtungen (Rotation R1 → R2 → R3 → R4 → R1 …)

### R1 — Motor aktivierungsreif + Härtung
`data/` existiert hier NICHT — der Heartbeat kann nur am Desktop eingeschaltet
werden. Deshalb: Code-/Test-Härtung von `runner`/`verifier`/`outcomes`/`doctor`,
Dry-Run-Fähigkeit, Aktivierungs-Playbook, bekannte offene Fallen (Dossier §10)
schließen. Definition of done: Tests grün + im Log steht, was Sergen am Desktop
davon hat.

### R2 — Local-Model-Fitness
Kiras Anspruch: läuft notfalls mit schwachem lokalem Modell. Prompt-Budgets
messen und senken (`PERSONA_DIRECTIVE` < 3800 bleibt Testpflicht,
`tests/test_context_diet.py`), ACT-Textprotokoll gegen schwache GGUF-Modelle
härten (`_parse_leaked_tool_calls`!), progressive Disclosure ausbauen
(nachschlagen statt vollstopfen). Jede Prompt-Änderung mit Budget-Test absichern.

### R3 — Wissen & Playbooks
Referenzartikel nach `docs/wissen/` (Vault-tauglich, Wiki-Links), neue/bessere
Playbooks (immer `reifegrad: entwurf`, via `playbooks/_VORLAGE.md`),
INDEX-Verlinkung pflegen. `data/knowledge/` kann die Cloud NICHT füllen —
Artikel so schreiben, dass Sergen sie per Knowledge-Ingest oder direkt in
Obsidian nutzt.

### R4 — Radar (Web-Recherche)
Der wissenshungrige Teil: neue Skills auf GitHub, neue MCP-Server, neue (lokale)
LLMs, neue Agent-Frameworks sichten und ehrlich bewerten (Nutzen für Kiras
Mission, Aufwand, Risiko). Ergebnis = Dossier in `docs/radar/<datum>-<thema>.md`
+ konkrete BACKLOG-Vorschläge. **NIEMALS installieren**, keine Dependencies,
keine Config-Änderung — nur Vorschläge.

## Rotation & Auswahl

- Nächste Richtung = (Richtung des neuesten Log-Eintrags mit Status ≠
  `uebersprungen` + 1) mod 4. Auch `abgebrochen`/`blockiert` zählen als
  "Richtung verbraucht". Fehlt jeder Eintrag: R1.
- **Ausnahme 1:** BACKLOG-Eimer JETZT ist nicht leer → oberstes JETZT-Item, egal
  welche Richtung (Sergens Steuerkanal). Der Log-Eintrag notiert dann
  `R<x> (JETZT-Override)` mit der Richtung des Items — die reguläre Rotation
  läuft beim nächsten Mal normal weiter.
- **Ausnahme 2:** In der fälligen Richtung ist kein machbares Item → nächste
  Richtung, maximal einmal ganz herum; sonst Wartungs-Iteration (Backlog
  aufräumen, Log archivieren, LOOP.md verbessern) — auch das ist ein Paket.

## Guardrails (hart, keine Ausnahme)

1. `core/mind/constitution.md` NIEMALS anfassen.
2. `SOUL.md`/`GOAL.md`/`USER.md`/`BODY.md` nie direkt editieren.
   Änderungswünsche als VORSCHLAG in den Log-Abschnitt "Fragen an Sergen".
3. Keine Secrets, keine `.env`, kein `data/` — nichts davon je in Commits oder Logs.
4. Keine neuen Dependencies und keine MCP-/Config-Aktivierungen ohne
   Sergen-Freigabe — nur als Backlog-Vorschlag.
5. Prompt-Budgets sind heilig: `test_context_diet` muss grün bleiben; neue
   Prompt-Blöcke brauchen einen eigenen Budget-Test.
6. Hausstil aus Dossier §8/§9/§10 gilt vollständig (deutsche Docstrings ohne
   Umlaute im Code, Werkzeuge liefern Strings, `atomic_write`, ASCII in
   UI-Strings, …).
7. Nur auf `kira/loop` arbeiten. NIE auf main committen, NIE fremde Branches anfassen.
8. Ein Paket pro Iteration. Passt es nicht in die Limits → im BACKLOG in
   Teilpakete zerlegen (neue IDs) und nur Teil 1 bauen.

## Fehlerfälle

- **Merge-Konflikt mit origin/main:** `loop/`-Dateien → beide Seiten vereinigen
  (append-only). Code → Version von `origin/main` nehmen (Desktop hat Vorrang)
  und betroffene Backlog-Items zur Neuprüfung markieren. Unauflösbar →
  `git merge --abort`, Status `blockiert`, stattdessen reine Doku-Iteration.
- **Tests schlechter als Baseline** und in ~2 Fix-Versuchen nicht grün →
  Arbeitskopie verwerfen (zurück auf letzten gepushten Stand), Item als
  `blockiert` (mit Fehlerbild) ins BACKLOG, Log-Eintrag trotzdem sauber
  abschließen. Es wird NIE ein Stand mit neuen Failures gepusht (außer dem
  reinen Log-Commit).
- **PR wurde geschlossen OHNE Merge** → Sergen hat verworfen: Branch trotzdem neu
  von `origin/main`, im Log notieren, welche Iterationen verworfen wurden.
