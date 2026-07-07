# FABLE-REVIEW — To-dos für die große Analyse

> Stichpunkt-Sammlung (kein fertiger Prompt). Sergen schreibt den eigentlichen Prompt selbst;
> das hier ist die Übersicht der Punkte, die wir an ein Fable-Agententeam übergeben wollen.
> Ziel: EIN gründlicher Durchgang durch Code + Struktur + Modell-Nutzung → Bewertung + Empfehlung.

## 1 · Modell-Setup (Kern-Frage)
- Für welche Modelle ist der Harness gebaut? Kann man fast jedes einstöpseln oder braucht es eine Grundstärke?
- Agnostisch bleiben vs. auf eine Klasse spezialisieren (GLM-Klasse: Preis/Leistung, open-source, self-hostbar).
- Lokal vs. Cloud; welches Modell pro Rolle (chat/bulk/reflex/reason/escalation)?
- Datenbasis: Benchmark-Zahlen (HumanEval, SWE-bench-Subset) je Modell × Coding-Erfolg × Kosten.
- Ergebnis: klare Empfehlung + „Zwischenweg" (agnostischer Kern + GLM als Anker).

## 2 · Coding-Basis (kritischster Punkt)
- Review gegen OpenCode + die zwei weiteren Claude-Code-Klone auf GitHub.
- Was haben die, das uns fehlt? Das Beste aus allen dreien übernehmen.
- Coding-Zuverlässigkeit end-to-end: Coding-Guard + Eskalation (Regel: `escalation_model` = STÄRKSTES Modell, sonst codet sie aufs Gratis-Modell), keine stillen Downgrades.

## 3 · Persona-Kohärenz (Charakter-Ebene)
- Verfassung / SOUL / GOAL / USER / PERSONA / Rats-Stimmen (council): Redundanzen? Ton-Brüche? konsistentes Selbstbild?
- Ist die Trennung „Charakter-Ebene (editierbar) vs. Code-Ebene" sauber?

## 4 · App-/Settings-Architektur
- Wie Config-Panels strukturieren, damit die App bei wachsenden Reitern (Charakter, Benchmark, …) nicht überladen wird.
- Klare „Einstellungen"-Ebene mit Knöpfen statt endloser Reiter-Leiste.

## 5 · Report-/Verdichtungs-Motor (Langzeit-Gedächtnis)
- Journal-Kette täglich → wöchentlich → monatlich → **jährlich** läuft aktuell NICHT autonom (Playbooks = Entwurf, an manuelle Crons gebunden).
- „Interessen-Watch"-Schicht: beiläufig Gesagtes (Termin, Kaufwunsch, Behörden-Thema) automatisch merken + in freien Stunden dranbleiben.
- Konzept + Umsetzung bewerten, Vorschlag für den Motor.

## 6 · Robustheit / 24-7
- Watchdog + `busy_timeout` gegenprüfen.
- Budget-Bremse ist $-basiert → bei Gratis-Modellen unbegrenzt; auf Rate-Limits statt Kosten achten (greift der Lokal-Fallback sauber?).

## 7 · Audit-Reste (klein, im selben Durchgang)
- `_AKTIV`-Global-Kollision (Heartbeat + Chat teilen sich einen Bool).
- Supervisor: Crash-Loop-Backoff fehlt.
- `synthesize` nicht als Tool exponiert.
- Prüfen, ob cron/objective-Lücken jetzt geschlossen sind (`cron_remove`/`objective_list` sind drin).

## 8 · Testumgebung / Benchmark (Grundsetup steht)
- Sandbox (Worktree) + Firewall + Live-Benchmark im Cockpit sind gebaut.
- Ausbauen: HumanEval-Adapter (vergleichbare Zahlen) → SWE-bench-Subset (agentische Fähigkeit).

---

## Sergens Entscheidungen zum Review (07.07.2026)
1. **Eskalation bleibt frei wählbar** (Cockpit-Buttons; kein Modell festgenagelt — GLM 5.3 & Co.
   sollen jederzeit einsetzbar sein). Stattdessen: **Doctor-Warnung**, wenn die Spitze das
   Massen-/Lokal-Modell ist. ✔ umgesetzt
2. **Mission aus der Verfassung nach GOAL.md** — Verfassung trägt nur noch den zeitlosen Kompass;
   die lebende Mission (Prioritäten/Zahlen) lebt in GOAL.md, GOAL schlägt Alt-Stände. ✔ umgesetzt
3. **Keine harten Mengen-Limits** — stattdessen **Token-Verbrauch als Statistik** im Cockpit
   (heute je Rolle: Calls/Tokens/$). ✔ umgesetzt
4. **Heartbeat: Go** — begleitete Aktivierung, sobald dieser Block gemerged + Eskalation am PC
   zurück auf GLM steht.
5. **qwen3.6:35b zu schwer** für den PC (9-10 GB VRAM / 32 GB RAM) — lokal bleibt qwen3.5:9b,
   Grind auf Flash/GLM. Kein Benchmark-Zwang.
6. **Handy:** aktuell Telegram; später PWA (Cockpit als installierbare App via Tailscale) —
   Token-Middleware kommt dann VORHER.
7. **Maximale Freiheit, aber nie selbst zerschießen:** Dirty-Check statt reset --hard auf
   Sergens Arbeit (code:-Lauf startet live nur auf sauberem Baum). ✔ umgesetzt — keine neuen
   Genehmigungs-Zäune darüber hinaus.
8. **⚙ Einstellungen-Ebene:** Technik-Gruppe = Einstellungen (Modelle/Steuerpult/Zugänge/
   Cockpit/Wallpaper), Zahnrad-Shortcut in der Topbar. Nur echte Settings dort — Kira-Inhalte
   bleiben bei Kira. ✔ umgesetzt
- **Judge ≠ Actor:** verifier_task_type auf reason (Denker benotet, nicht das Massen-Modell). ✔
- **Motor liest eigene Lektionen:** recall_lessons/skills jetzt auch in act._identity(). ✔
- **Priorität der Modell-Wahl: maximale Qualität** innerhalb der Kostenrealität; Anker = GLM-Klasse
  (offen, self-hostbar), Ziel in 6–24 Monaten GLM lokal.
