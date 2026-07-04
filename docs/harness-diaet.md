# Harness-Diät — sparsame Umgebung für schwache Modelle (Konzept)

> Sergens Leitsatz: **Der Harness muss für die Dummen gebaut sein, dann fliegen die Klugen.**
> DeepSeek-tauglich heute = GLM-lokal-tauglich morgen. Dieses Dokument ist die verbindliche
> Richtung; gebaut wird schrittweise (Verbesserungs-Loop R2 oder gezielte Sessions).

## Befund (gemessen am Live-Stand, 2026-07-04)

Was ein Modell pro Chat-Turn um die Ohren bekommt, BEVOR die Aufgabe anfängt:

| Ballast | Größe |
|---|---|
| 65 Werkzeuge als JSON-Schemas (Cloud) | ~30.000 Zeichen |
| 65 Werkzeuge als Text-Manifest (lokal) | ~17.800 Zeichen |
| Identität (Verfassung 2,1k + SOUL 3,5k + GOAL 7,9k + BODY-Kopf 1,5k + Persona 3,7k) | ~19.000 Zeichen |
| **Summe pro Cloud-Turn** | **~49.000 Zeichen ≈ 12.000 Tokens** |

Symptome (Live-Test Luvex-Auftrag, DeepSeek flash): Modell wählt falsche/keine Werkzeuge,
plaudert statt zu liefern, halluziniert Ergebnisse. Der Beweispflicht-Stempel (S: PR #10)
FÄNGT die Lüge — aber das Ziel ist, dass sie gar nicht erst entsteht. Ein schwaches Modell
muss aus 65 Optionen wählen UND Persona + Playbook-Router + Regeln im Kopf behalten UND
die Aufgabe lösen. Es ertrinkt. Vorbild ist der Claude-Code-Harness selbst: Kern-Werkzeuge
sofort, Spezial-Werkzeuge werden bei Bedarf NACHGELADEN (progressive disclosure).

## Die drei Bausteine

### 1. Werkzeug-Kern (65 → ~14) + Nachlade-Werkzeug
- `@tool(..., core=True)` markiert den Kern-Werkzeugkasten, ungefähr:
  `read_file, write_file, edit_datei, code_suche, datei_finden, list_dir, web_search,
  web_fetch, run_command, delegate, schwarm, remember_fact, todo_add, playbook_read`.
- Chat-/Arbeits-Turns bekommen NUR Kern-Schemas (~7k statt 30k Zeichen). Der Rest bleibt
  registriert und erreichbar über EIN Discovery-Werkzeug:
  `werkzeug_suchen(stichwort)` → liefert Name+Beschreibung+Argumente der Treffer, und der
  gefundene Name ist ab dem nächsten Schritt des Turns aufrufbar (Schemas des Turns um die
  Treffer erweitern — analog ToolSearch im Claude-Code-Harness).
- MCP-Tools zählen als Nicht-Kern (kommen über werkzeug_suchen).
- Erwartung: weniger Fehlgriffe, weil die Auswahl klein ist; Spezialfälle bleiben möglich.

### 2. Schlanke Arbeits-Identität
- Zwei Identitäts-Stufen statt einer:
  - **Gespräch mit Sergen** (act_chat direkt): volle Identität wie heute — Persönlichkeit
    ist hier der Sinn der Sache.
  - **Arbeits-Turns** (delegierte Unteragenten, Plan-Schritte, Missions-Tasks): kompakte
    Identität ~4k statt 19k — Verfassungs-Kurzfassung (die 6 Regeln, nicht der Volltext),
    Melde-Regeln (ehrlich, kein Erfolg ohne Beleg), Arbeits-Anweisungen, Auftrag. KEIN
    SOUL/GOAL/USER-Volltext, kein Playbook-Router (Playbooks via playbook_read bei Bedarf).
- Umsetzung: `_identity_lean()` neben `_identity()` in act.py; delegate_tools und
  plan-Schritte nutzen lean, act_chat behält voll. GOAL.md-Kürzung selbst wäre ein
  separates Thema (Evolution-Pipeline), NICHT Teil dieses Pakets.

### 3. Liefernachweis pro Plan-Schritt (Beweispflicht v2)
- Heute: Stempel am ENDE der Antwort (PR #10) — erkennt die Lüge, erzwingt aber nichts.
- Neu: JEDER Plan-Schritt, dessen Text einen Datei-Pfad behauptet, wird SOFORT geprüft
  (gleiche `_claim_stamp`-Mechanik, pro Schritt). Fehlt das Artefakt → EIN harter Retry
  desselben Schritts mit: "Die Datei existiert NICHT. Erzeuge sie JETZT mit write_file/
  edit_datei und antworte erst danach." Erst wenn das Artefakt existiert (oder der Retry
  verbraucht ist), geht es weiter — der Fehlschlag steht dann EHRLICH im Schritt-Ergebnis.
- Optional (v2.1): Plan-Schritte bekommen ein explizites Feld "liefert: <pfad>" aus dem
  Planner — dann ist der Check kein Raten mehr, sondern Vertrag.

## Prompting-Prinzipien (gelten für alle künftigen Prompt-Bausteine)

1. **Ein nächster Schritt, nicht zehn Optionen.** Jede Anweisung endet mit genau einer
   erwarteten Aktion.
2. **Verträge statt Appelle.** Nicht "bitte ehrlich melden", sondern "Schritt gilt als
   erledigt WENN <prüfbare Bedingung>". Der Harness prüft, nicht das Modell.
3. **Nachschlagen statt mitschleppen.** Alles, was nicht JEDEN Turn gebraucht wird,
   ist eine Datei/ein Werkzeug (INDEX, Playbooks, werkzeug_suchen) — kein Prompt-Block.
4. **Budgets pro Baustein + Test** (wie test_context_diet): jeder neue Prompt-Block
   bekommt eine Zeichen-Obergrenze und einen Test, der sie hält.
5. **Für flash schreiben, nicht für Fable.** Kurze Sätze, nummerierte Abläufe, keine
   Metaphern in Arbeits-Prompts.

## Umsetzungs-Reihenfolge (für Loop R2 / spätere Sessions)

1. **B: Liefernachweis pro Plan-Schritt** — kleinster Eingriff, größter Effekt gegen
   Halluzination (plan_and_execute + _claim_stamp wiederverwenden).
2. **A: Werkzeug-Kern + werkzeug_suchen** — Registry-Flag, Filter in manifest()/
   tool_schemas(), neues Discovery-Tool, Turn-lokale Erweiterung.
3. **C: Schlanke Arbeits-Identität** — _identity_lean() + Umstellung delegate/plan-Schritte.
4. Messen: Kosten/Turn und Fehlgriff-Quote vorher/nachher (llm_call-Events + Doctor).

## Erfolgs-Kriterien

- Luvex-Testauftrag mit DeepSeek flash: Dateien existieren wirklich, kein Stempel nötig.
- System-Ballast pro Arbeits-Turn < 15k Zeichen (heute ~49k).
- Testsuite grün; test_context_diet um Budgets für neue Blöcke erweitert.
