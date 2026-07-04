# Radar: Lokale Modelle fuer den Kira-Harness (Stand 2026-07-04)

> Frage von Sergen: Taugen Qwen-AgentWorld-35B-A3B und WebWorld-32B als
> qwythos-Ersatz? Und welche HuggingFace-Modelle passen auf den PC und sind
> stark in GENAU unseren Aspekten (Tool-Calling, Anweisungstreue, JSON,
> langer Kontext, Deutsch)?

## Kurzantwort

1. Die beiden verlinkten Qwen-Modelle sind KEINE Assistenten, sondern
   "World Models" — sie simulieren die Umgebung (naechster Seitenzustand,
   naechste Terminal-Ausgabe), nicht den Agenten. Als qwythos-Ersatz
   ungeeignet.
2. Der beste Kandidat fuer den Harness ist **Qwen3.5-9B** (Instruct, sauber,
   ohne eingebrannte Persona) — dieselbe Familie, aus der qwythos geschmiedet
   wurde, nur offiziell und unverbogen.

## Die zwei angefragten Modelle

### Qwen/Qwen-AgentWorld-35B-A3B — NICHT als Kira-Gehirn

- 35B Parameter (MoE, nur 3B aktiv), Basis Qwen3.5-35B-A3B, Apache 2.0,
  262k Kontext, GGUF/Ollama-Quants vorhanden.
- Zweck: Es sagt voraus, wie eine UMGEBUNG auf eine Agenten-Aktion reagiert
  (MCP, Suche, Terminal, SWE, Android, Web, OS). Man benutzt es, um Agenten
  zu TRAINIEREN oder zu testen — als Simulator, nicht als Denker.
- Fuer Kira heisst das: Es beantwortet keine Chats, plant keine Aufgaben,
  ruft keine Werkzeuge. Falsche Werkzeugklasse.

### Qwen/WebWorld-32B — NICHT als Kira-Gehirn

- 32B dense, Basis Qwen3-32B, Apache 2.0, GGUF vorhanden.
- Zweck: simuliert Webseiten-Zustaende fuer das Training von Web-Agenten
  (1M+ echte Web-Trajektorien). Bekannte Schwaeche laut Model Card:
  Sycophancy-/Optimismus-Bias.
- Ausserdem 32B dense = zu gross fuer die 9-12B-Klasse des PCs.

Merksatz: "World Model" auf HuggingFace = Trainings-Simulator.
"Instruct" oder "Chat" = das, was Kira braucht.

## Kandidaten fuer den PC (9-12B-Klasse, unsere Aspekte)

### 1. Qwen3.5-9B — EMPFEHLUNG

- Genau die Familie von qwythos, aber sauberes offizielles Instruct.
- 256k Kontext, 201 Sprachen (Deutsch dabei), explizit auf Tool-Calling
  getrimmt (Nested-JSON-Parsing verbessert), Thinking-/Non-Thinking-Modus.
- Q4-Quant ~5 GB -> laeuft auf 8 GB VRAM. Ollama: `ollama pull qwen3.5:9b`
- Staerken decken sich 1:1 mit dem Harness: Werkzeug-Schemata, JSON-Plaene
  (`_make_plan`), lange Briefe (delegate), Deutsch.

### 2. Gemma 3 12B — Deutsch-Alternative

- Googles 12B, in Community-Tests konsistent stark auf Deutsch,
  hardware-freundlich. Schwaecher als Qwen3.5 bei Tool-Calling.
- Kandidat fuer Chat-/Text-Raenge (reflex, Journal-Verdichtung), nicht
  fuer den Werkzeug-Kern.

### 3. Ministral 3 8B / Mistral-Nemo 12B — Reserve

- Mistral-Familie, gutes Deutsch (europäisches Training), solide
  Anweisungstreue. Nemo 12B war lange der Geheimtipp fuer deutsche Texte.
- Reserve, falls Qwen3.5-9B im eigenen Benchmark schwaechelt.

### Optional, nur bei >=32 GB RAM: Qwen3.5-35B-A3B (Instruct!)

- MoE: 35B gesamt, 3B aktiv -> schnell trotz Groesse, braucht aber die
  vollen Gewichte im Speicher (~18-20 GB bei Q4).
- Das waere der "grosse Bruder" mit demselben Harness-Profil. NICHT mit
  dem AgentWorld-Derivat verwechseln — nur das normale Instruct nehmen.

## Welche Benchmarks fuer UNSEREN Harness zaehlen

- BFCL v4 (Function Calling): gorilla.cs.berkeley.edu/leaderboard.html
- IFEval (Anweisungstreue), strukturierte JSON-Ausgabe
- RULER / Long-Context (Plaene + Dossiers sind lang)
- Deutsch-Faehigkeit (kein Standard-Leaderboard — selbst testen)
- NICHT relevant: Mathe-Olympiade, Kreativ-Schreiben, MMLU-Trivia

## Naechste Schritte (Desktop)

1. `ollama pull qwen3.5:9b`
2. In config.yaml testweise `local_fallback` / `classify` auf
   `ollama_chat/qwen3.5:9b` stellen (eine Zeile pro Rang).
3. Eigener Mini-Benchmark statt fremder Leaderboards (B-012/B-026):
   dieselben 5 Kira-Aufgaben (Plan bauen, Werkzeug aufrufen, JSON liefern,
   deutsche Mail, Datei-Beweis) gegen qwythos laufen lassen — Outcome
   zaehlt, nicht Benchmark-Prosa.
4. Gewinner wird der neue lokale Standard; qwythos in Rente.

## Quellen

- huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B (Model Card)
- huggingface.co/Qwen/WebWorld-32B (Model Card)
- ollama.com/library/qwen3.5:9b · unsloth.ai/docs/models/qwen3.5
- gorilla.cs.berkeley.edu/leaderboard.html (BFCL v4)
- insiderllm.com/guides/qwen-models-guide · localaimaster.com (SLM-Ranking 2026)
