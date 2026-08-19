# Zielmodell Qwen 3.8 — Harness-relevante Fakten (Stand 19.08.2026)

> Kuratiert aus Community-Meldungen vom 19.08. Vor dem Umbau am PC einzeln verifizieren.

## Lokal fahren (des Nutzers PC, RTX 3060 12 GB)

- **Unsloth Dynamic 3.0 GGUFs fuer Qwen3.8-27B**: `UD-Q2_K_XL` ~9,83 GB (passt in 12 GB
  VRAM, laut Unsloth "+8% top-1-Accuracy vs. naechstbeste 2-bit"), `UD-IQ2_S` ~8,4 GB,
  `UD-IQ1_S` ~6,2 GB (Notloesung, ~72% top-1). Bezug: `hf.co/unsloth/Qwen3.8-27B-GGUF`.
  -> Kandidat fuer den lokalen DENKER (loest den bisherigen Plan qwen3.6:35b-a3b ab,
  der 32 GB RAM wollte). Erst B-012-Benchmark bestehen, DANN auf 'reason' legen —
  gleiche Regel wie in config.yaml dokumentiert.
- **DFlash 2** (Block-Diffusion Speculative Decoding): bis 4,6x schnelleres Decoding bei
  identischem Output; Drafter fuer Qwen3.8-27B verfuegbar, nativ in llama.cpp/vLLM/SGLang.
  -> Fuer den Nachtdenker-Server (llama.cpp server_cmd) pruefen.

## Ansteuerung (Harness-Seite)

- **reasoning_effort** steuert Qwen 3.8 NUR ueber `chat_template_kwargs:
  {"reasoning_effort": "low|high|xhigh"}` im Request-Body (oMLX/llama.cpp bestaetigt);
  mindestens ein naheliegender Kanal funktioniert NICHT. -> Wenn der lokale 3.8-Endpunkt
  kommt: llm_router reasoning_level-Mapping darauf pruefen, nicht raten.
- **Chat-Template ist ein Hebel**: "Qwen-Sharp-Chat-Templates" (HF: peculiar-ragdoll/
  Qwen-Sharp-Chat-Templates) — Template-Tweak soll Faehigkeiten ohne Retraining heben.
  -> Im Bench messbar machen: gleiche Suite, Standard- vs. Sharp-Template.

## Cloud-Aequivalente fuer den Pruefstand (bis der PC steht)

- `qwen/qwen3.8-27b` auf OpenRouter: $0.45/M in, $3.20/M out, 1M ctx — teuer im Output
  (Reasoning-Tokens!), fuer gezielte Bestaetigungslaeufe, nicht fuer Iterationsschleifen.
- Free-Modelle als Iterations-Arbeitspferde in aehnlicher Staerke-Klasse:
  `nvidia/nemotron-3-ultra-550b-a55b:free` (bewaehrt, JSON-diszipliniert),
  `nvidia/nemotron-3-super-120b-a12b:free`, `z-ai/glm-5.2:free` (oft 429).
  Tagesquota beachtet der Pruefstand ohnehin (Crash-Sichtbarkeits-Events).

## DeepSeek Harness (13.08., MIT) — was abgeglichen wurde

Deren dokumentierte Tool-Pipeline (Validierung -> Berechtigung -> Ausfuehrung ->
Nachbearbeitung -> dauerhafte Protokollierung) entspricht 1:1 unserem
`_run_tool_guarded` (RBE-Guard, Arg-Pruefung, Executor, Spill, Events). Explizite
Retry-/Kleinmodell-Strategien dokumentieren sie NICHT — unsere Beweispflicht-Guards
gehen darueber hinaus. Uebernehmenswert mittelfristig: ihr Append-only-Event-Stream
traegt Replay/Resume/Forks — unsere events-DB koennte Bench-Laeufe nach Crash
FORTSETZEN statt neu starten (Backlog, kein Schnellschuss).
