# SETUP — Kira unter Linux einrichten (Ubuntu/Debian)

Von Null auf laufende Kira in ~15 Minuten. Getestet gegen Ubuntu 22.04+;
andere Distributionen funktionieren analog. (Windows: [SETUP.md](SETUP.md).)

## 1. Voraussetzungen

```bash
sudo apt update && sudo apt install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv (Python-Verwaltung)
curl -fsSL https://ollama.com/install.sh | sh            # Ollama (lokale Modelle, 0 EUR)
```

Empfohlene Hardware: 16 GB RAM; eine NVIDIA-GPU (ab ~8 GB VRAM, z.B. RTX 3060)
macht die lokalen Modelle deutlich schneller — Ollama nutzt sie automatisch
(NVIDIA-Treiber vorausgesetzt: `sudo ubuntu-drivers autoinstall`).

## 2. Installieren

```bash
git clone <dieses-repo> ~/kira && cd ~/kira
uv sync                      # legt .venv an + installiert alle Abhaengigkeiten
ollama pull qwen3.5:9b       # lokales Standard-Modell
ollama pull nomic-embed-text # optional: Embeddings fuers Gedaechtnis
chmod +x scripts/*.sh
```

## 3. Starten + Erst-Einrichtung

```bash
scripts/start-all.sh
```

Dann **http://127.0.0.1:8000** im Browser oeffnen → der **/setup-Wizard** fragt
Agent-Name + deinen Namen (optional Telegram + OpenRouter-Key). Danach gehoert
das Cockpit dir. Eine Desktop-Huelle braucht es unter Linux nicht — das Cockpit
im Browser ist vollwertig (Tipp: im Browser „App installieren“/PWA nutzen).

## 4. Autostart (systemd, ohne Root)

```bash
scripts/install-autostart.sh     # kopiert scripts/kira.service als user-Unit + aktiviert sie
systemctl --user status kira     # Status
journalctl --user -u kira -f     # Live-Logs
scripts/uninstall-autostart.sh   # wieder entfernen
```

## 5. Betrieb

- **Updaten:** `scripts/kira-update.sh` — holt den neuesten Stand, startet sauber neu.
  Deine Daten (`data/`, Seelen-Dateien, Stammbaum, Notizen) sind gitignored und
  werden nie angefasst.
- **24/7-Mission scharf schalten:** Cockpit → Motor-Toggle (`data/heartbeat.flag`).
- **Not-Aus:** Datei `data/STOP` anlegen — alles haelt sofort.
- **Budget/Modelle:** `config.yaml` (`governance.budget`, `models:` — Raenge statt
  Modellnamen; Ollama laeuft mit explizitem `num_ctx`).

## 6. Offline-Box (kein Internet — z.B. Laptop nur mit Strom)

Kiras Ziel-Szenario: einmal online einrichten (Klon, `uv sync`, `ollama pull`),
dann Netz ab. Chat, Werkzeuge, Gedaechtnis, Missionen und Cockpit laufen rein
lokal ueber Ollama. Cloud-Funktionen (Telegram, Mail, Web-Suche, Cloud-Modelle)
melden sich mit klaren Hinweis-Texten ab, statt zu crashen.

Fuer Start ohne Login (Box haengt nur am Strom):
```bash
sudo loginctl enable-linger $USER    # user-Units starten schon beim Boot
```

## 7. Wenn etwas klemmt

- **Diagnose:** `uv run python -m core.kernel.doctor`
- **Logs:** `journalctl --user -u kira -f` und `data/logs/`
- **Suite:** `uv run pytest tests -q` — offline, beruehrt deine Live-Daten nicht
- **Werkszustand:** Cockpit → Werkszustand (alles wandert zuerst in ein Backup)
