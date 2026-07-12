# SETUP — Kira unter Windows einrichten

Von Null auf laufende Kira in ~15 Minuten. Alles hier ist copy-paste-fähig;
wo ein Doppelklick reicht, steht es dabei. (Linux: SETUP-linux.md, in Arbeit.)

## 1. Voraussetzungen

| Was | Wozu | Woher |
|---|---|---|
| **Python 3.11+** | Laufzeit | https://python.org (oder kommt mit uv) |
| **uv** | Paket-/Umgebungsverwaltung | https://github.com/astral-sh/uv |
| **Git** | Code holen + Updates | https://git-scm.com |
| **Ollama** | lokale Modelle (0 €) | https://ollama.com |

Empfohlene Hardware: 16 GB RAM; eine NVIDIA-GPU (ab ~8 GB VRAM) macht die lokalen
Modelle deutlich schneller, ist aber keine Pflicht.

## 2. Installieren

```bash
git clone <dieses-repo> kira
cd kira
uv sync                      # legt .venv an + installiert alle Abhängigkeiten
ollama pull qwen3.5:9b       # lokales Standard-Modell (Chat/Klassifikation)
ollama pull nomic-embed-text # optional: Embeddings fürs Gedächtnis (0 €)
```

## 3. Starten + Erst-Einrichtung

```bash
.venv\Scripts\python.exe -m core.kernel.supervisor
```

Der **Supervisor** startet und bewacht alle drei Dienste (Cockpit, Telegram-Bot,
Mission-Runner) — stirbt einer, kommt er automatisch wieder.

Jetzt **http://127.0.0.1:8000** öffnen. Beim ersten Start landest du im
**/setup-Wizard**:

1. **Name deines Agenten** (Werksname: Kira — nimm gern deinen eigenen)
2. **Dein Name**
3. Optional: **Telegram** (Bot-Token von @BotFather + deine Chat-ID) und
   **OpenRouter-Key** (Cloud-Modelle; ohne läuft alles lokal)

Der Wizard personalisiert die Seelen-Dateien, legt deine Stammbaum-Wurzel an und
startet Bot + Runner neu. Danach: das Cockpit gehört dir.

> Zugänge lassen sich jederzeit im Cockpit nachtragen (Zugänge-Karte) — sie landen
> im lokalen Tresor `data/secrets.json` (gitignored), nie im Code.

## 4. Desktop-App + Autostart (optional, empfohlen)

| Doppelklick auf | Ergebnis |
|---|---|
| `scripts\kira-desktop.bat` | Cockpit als eigenes Fenster mit Tray-Symbol (kein Browser nötig) |
| `scripts\kira-einrichten.bat` | Logo → Icon, Desktop-Verknüpfung, Autostart der App |
| `scripts\install-autostart.ps1` | Kira (Supervisor) startet bei jedem Windows-Login |
| `scripts\uninstall-autostart.ps1` | beide Autostart-Einträge wieder entfernen |

Eigenes Logo: Bild als `data\kira-icon.png` ablegen, dann `scripts\kira-einrichten.bat`.

## 5. Betrieb

- **Updaten:** Doppelklick `scripts\kira-update.bat` — holt den neuesten Stand und
  startet sauber neu. Deine Daten (`data/`, Seelen-Dateien, Stammbaum, Notizen) sind
  gitignored und werden nie angefasst.
- **24/7-Mission scharf schalten:** Cockpit → Motor-Toggle (schreibt
  `data/heartbeat.flag`). Ohne Flag bleibt der Motor aus, egal was die Config sagt.
- **Not-Aus:** Datei `data/STOP` anlegen (oder Cockpit-Knopf) — alles hält sofort.
- **Budget:** `config.yaml` → `governance.budget` (Tages-/Monatsdeckel für Cloud).
- **Modelle wechseln:** `config.yaml` → `models:` (Ränge statt Modellnamen) oder im
  Cockpit unter Modelle. Ollama-Aufrufe laufen mit explizitem `num_ctx` (32768).

## 6. Offline-Box (kein Internet)

Kira ist dafür gebaut: ohne Keys und ohne Netz laufen Chat, Werkzeuge, Gedächtnis,
Missionen und Cockpit rein lokal über Ollama. Cloud-Funktionen (Telegram, Mail,
Web-Suche, Cloud-Modelle) melden sich mit klaren Hinweis-Texten ab, statt zu crashen.

## 7. Wenn etwas klemmt

- **Diagnose:** `uv run python -m core.kernel.doctor` (Routing, Dienste, Konfiguration)
- **Logs:** `data\logs\` (cockpit/bot/runner/supervisor)
- **Suite:** `uv run pytest tests -q` — offline, berührt deine Live-Daten nicht
- **Werkszustand:** Cockpit → Werkszustand (alles wandert zuerst in ein Backup unter
  `data\backups\`)
