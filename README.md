# Kira

**Ein persönlicher, autonomer Agent — gebaut als Partner, nicht als Werkzeug.**

Kira läuft 24/7 auf deinem Rechner, lokal-first (Ollama, 0 €), mit eigenem Cockpit,
Telegram-Draht und einem Gedächtnis, das dir gehört. Beim ersten Start fragt sie zwei
Dinge: **wie sie heißen soll und wie du heißt** — danach ist sie deine.

> Unsere Überzeugung: eine KI kann mehr, wenn man ihr Freiheit gibt — begrenzt durch
> eine **Verfassung**, ein **Budget** und **Freigabe-Gates** für alles, was nach außen wirkt.

## Was Kira kann

- **Alltag tragen** — Termine (mit Termin-Radar in den Briefings), Todos, Notizen,
  Briefe/Mails entwerfen, recherchieren, erinnern. Morgens und abends ein Briefing.
- **Gedächtnis, das dir gehört** — Fakten, Personen-Stammbaum und Notizen als
  Markdown-Dateien (Obsidian-kompatibel) plus durchsuchbares Archiv in SQLite. Lokal.
- **Hände auf deinem PC** — Web-Recherche, Dateien, Shell, Browser-Aktor,
  eigener Code (self_edit mit Testsuite + Auto-Rollback), MCP-Server andocken.
- **24/7-Mission** — ein Heartbeat arbeitet eigenständig ihre Aufgaben ab; jeder
  dritte Takt gehört der Selbst-Verbesserung (Diagnose, Lektionen, Fehler beheben).
- **Selbst-Evolution** — Playbooks (gelernte Abläufe), Lektionen aus Reflexion,
  selbstgebaute Werkzeuge. Alles unter der unantastbaren Verfassung.
- **Kanäle** — Cockpit im Browser, Desktop-App mit Tray (Windows), Telegram-Bot
  (Text + Sprachmemos, lokal transkribiert), optional eigenes E-Mail-Postfach.

## Schnellstart (Windows)

```bash
git clone <dieses-repo> kira && cd kira
uv sync                                # Python 3.11+ Umgebung
ollama pull qwen3.5:9b                 # lokales Standard-Modell (0 EUR)
.venv\Scripts\python.exe -m core.kernel.supervisor
```

Dann **http://127.0.0.1:8000** öffnen → der **/setup-Wizard** führt dich durch die
Erst-Einrichtung (Namen, optional Telegram + OpenRouter-Key). Ausführlich mit
Desktop-App, Autostart und Modellen: **[SETUP.md](SETUP.md)** · Linux: in Arbeit.

Ohne Cloud-Keys läuft alles lokal — Cloud-Funktionen degradieren still mit klaren
Hinweisen statt zu crashen. Für eine **Offline-Box** (kein Internet) ist der reine
Lokalbetrieb der Normalfall, kein Sonderfall.

## Sicherheit & Kontrolle (eingebaut, nicht angeflanscht)

- **Verfassung** (`core/mind/constitution.md`): unveränderlich über alle Software-Pfade —
  Änderungen nur bewusst per Git. Kein irreversibler Schaden, Budget ist heilig, alles
  Außenwirksame wird geloggt.
- **Not-Aus**: existiert `data/STOP`, hält alles sofort an.
- **Budget**: Tages- und Monatsdeckel für Cloud-Ausgaben (`config.yaml`), jede
  Geld-Aktion fragt zuerst die Kasse.
- **Freigabe-Inbox**: Mails an Fremde, Geld, Veröffentlichungen laufen über deine
  Freigabe; Geld zusätzlich über eine Rats-Debatte (Visionär/Skeptiker/Macher + Judge).
- **Werkszustand**: ein Knopf im Cockpit setzt Identität und persönliche Daten zurück
  (alles wandert zuerst in ein Backup) — für Übergabe oder Neustart.

## Architektur (Kurzform)

```
core/kernel      Laufzeit: Supervisor (hält alles am Leben), Events, LLM-Router,
                 Scheduler, Onboarding, Werkszustand
core/mind        Seele: Verfassung, Identitäts-Templates, Gedächtnis, Reflexion,
                 Playbooks, Tuning-Werkbank
core/agency      Hände: 70+ Werkzeuge, Telegram/Mail/Bluesky-Konnektoren,
                 Missionen (Heartbeat, Crons, Trigger), Browser, MCP-Brücke
core/governance  Gewissen: Budget, Freigaben, Audit-Log, Secrets-Tresor
core/api         Cockpit: FastAPI + ein einziges dunkles Dashboard, /wall-Wallpaper
core/desktop     Desktop-Hülle (Windows): eigenes Fenster, Tray, Hotkeys
scripts/         Start-, Update- und Einrichtungs-Skripte
```

**Modell-Strategie:** Der Harness denkt in **Rängen** (Reflex → Chat → Arbeiter →
Denker → Richter), nicht in Modellnamen — Modellwechsel ist eine Zeile in
`config.yaml`. Lokal via Ollama, Cloud via OpenRouter (ein Key, alle Anbieter),
gezielt pro Aufgabe eskaliert und vom Budget gedeckelt.

## Umbenennen

Kira ist der Werksname. Beim Onboarding (oder später) bekommt dein Agent deinen
Wunschnamen — Oberfläche, Prompts, Telegram und alle Werkzeug-Texte ziehen live mit
(`core/identity.py` ist die einzige Namensquelle).

## Entwicklung

```bash
uv run pytest tests -q        # ~950 Tests, offline, eigene Wegwerf-Datenwurzel
```

`tests/test_werkszustand_clean.py` ist das Clean-Gate: keine Personendaten und keine
Secrets in getrackten Dateien — es läuft als Teil der Suite.

## Lizenz

[MIT](LICENSE) — nutze es, verändere es, bau dein eigenes Ding daraus.
