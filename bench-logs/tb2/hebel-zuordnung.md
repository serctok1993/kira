# TB2 Lauf 4 — Hebel-Zuordnung (Vorhersage vor der Resume-Runde)

Ehrliche Zuordnung jedes Fehlschlags zu einem der drei Haertungs-Hebel (24.08.2026)
ODER zu einer Faehigkeitsgrenze des Modells (Nemotron 550B free), wo kein Harness hilft.
Die Resume-Runde MISST, ob die Vorhersage haelt — deshalb steht sie VOR dem Rerun fest.

Hebel:
- **AP** = Abgabe-Pflicht (Waechter feuert bei Fragment/finish_reason=length, auch nach getaner Arbeit) — f98cfbe
- **HL** = Hermes-Leak-Parser (`<function=..>`/`<tool_call>{json}`) — f98cfbe
- **AF** = Abgabe-Frist (liefert vor dem Wanduhr-Schnitt, meldet Teilergebnis) — 03b0bec

## Erwartet HEILBAR durch die Hebel (7 Faelle)

| Task | Symptom im Lauf 4 | Hebel | Begruendung |
|---|---|---|---|
| mailman | endete auf nie-ausgefuehrtem `<function=terminal>`-Block (4,68M Token) | HL | Der Block wird jetzt als Aufruf geparst und ausgefuehrt |
| polyglot-c-py | 809/8192 Token in EINEM Denk-Zug, kein `/app/polyglot` | AP | finish_reason=length -> Stups statt Fragment-Abgabe |
| feal-differential-cryptanalysis | kein `attack.py` (ModuleNotFoundError) | AP | brach mitten im Denken ab; Stups treibt zur Datei |
| protein-assembly | kein `gblock.txt` | AP | dito — Loesung formuliert, Datei nie geschrieben |
| sqlite-db-truncate | kein `recover.json` | AP | dito |
| sam-cell-seg | Output-Datei nicht am erwarteten Ort (FileNotFound) | AP | "created and tested" behauptet, aber Fragment |
| write-compressor / large-scale-text-editing / break-filter | Wanduhr-Timeout, teils 2/3 bzw 2/5 Tests schon gruen | AF | vor dem Schnitt Teilergebnis sichern statt 0 |

## Bleibt FAEHIGKEITSGRENZE — kein Harness hilft (10 Faelle)

| Task | Symptom | warum kein Hebel |
|---|---|---|
| bn-fit-modify | Sample Y≈0 statt erwartet | numerische Modellierung falsch |
| build-cython-ext | `np.int` (in NumPy 2.x entfernt) | veraltete API-Kenntnis des Modells |
| extract-elf | 0% der Referenzwerte getroffen | ELF-Binaerparser inhaltlich falsch |
| financial-document-processor | Dokumente falsch klassifiziert | multimodale Klassifikation zu schwach |
| fix-code-vulnerability | 1 echter Test rot trotz "367 passed" | Fix inhaltlich unvollstaendig (CWE) |
| fix-ocaml-gc | Build liefert nie "40 tests passed" | OCaml-GC-Aenderung inhaltlich falsch |
| model-extraction-relu-logits | 12 Matrixzeilen stimmen nicht | ReLU-Extraktion mathematisch unvollstaendig |
| raman-fitting | Peak-Fit-Werte daneben | numerischer Fit ungenau |
| reshard-c4-data | Dateimengen stimmen nicht | Resharding-Logik unvollstaendig |
| sparql-university | leere Ergebnismenge | SPARQL-Semantik falsch getroffen |
| sanitize-git-repo | eine Datei zu viel geaendert | Genauigkeit; grenzwertig, evtl. AP-nah |

## Prognose fuer die Resume-Runde

- Lauf 4 (roh, ohne Hebel, ohne Quota-Churn): **7 gruen / 89**.
- Erwartung nach Hebeln, NUR die ehrlich gemessenen Tasks (ohne Quota-/Infra-Abbrueche):
  7 bestehende + bis zu 7 geheilte = **Groessenordnung 12–14 / ~30 real gemessene**.
  Die 49 Quota-Churn- und 10 Infra-Abbrueche sind KEINE Modellurteile — sie holt die
  Resume-Runde mit frischer Quota nach; ihr Ausgang ist noch offen.
- Bewusst konservativ: AP heilt nur, wenn das Modell die Aufgabe INHALTLICH koennte und
  nur die Abgabe verpasste. Wo schon der Inhalt falsch war, bleibt es rot — das ist der
  ehrliche Teil der Vorhersage.
