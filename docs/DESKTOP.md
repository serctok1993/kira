# Kira auf den Desktop bringen (Living Wallpaper)

Ziel: die Seite **`/wall`** läuft als lebendiges Wallpaper **hinter den Icons**, die
Taskleiste ist ausgeblendet — Kira wird Teil des Hintergrunds.

**Voraussetzung:** Kira läuft (Supervisor / `start-all.ps1`), das Cockpit ist erreichbar
unter `http://127.0.0.1:8000`. Test im Browser: `http://127.0.0.1:8000/wall`.

---

## 1 · `/wall` als Wallpaper — Lively (Open Source, empfohlen)

[Lively Wallpaper](https://github.com/rocksdanister/lively) rendert Webseiten als Wallpaper.
Open Source (MIT), läuft lokal, kein Cloud-Zwang — passt zum Prinzip „alles unabhängig".

1. **Installieren:** `winget install rocksdanister.LivelyWallpaper`
   (oder aus dem Microsoft Store / von GitHub).
2. **Lively öffnen** → **`+` (Add Wallpaper)** → oben die URL eintragen:
   `http://127.0.0.1:8000/wall` → Enter.
3. Die erzeugte Vorschau anklicken → als Wallpaper gesetzt. **Fertig** — Kira läuft im Hintergrund.
4. **Mehrere Monitore:** in den Lively-Einstellungen pro Monitor wählbar.

> Kira muss laufen, sonst zeigt Lively eine leere Seite. Der Autostart regelt das
> (`install-autostart.ps1` / `start-all.ps1`).

---

## 2 · Taskleiste ausblenden

Damit der Desktop „leer" wirkt:

- **Manuell (sicher, reversibel):** Rechtsklick auf die Taskleiste →
  *Taskleisteneinstellungen* → **„Taskleiste automatisch ausblenden"** einschalten.
- **Oder per Skript** (im Kira-Ordner):
  `powershell -ExecutionPolicy Bypass -File taskbar-autohide.ps1 on`
  Rückgängig: `... off`.

---

## 3 · Interaktion (Chat) — kommt in Phase 4

Hinter den Icons ist die Ebene **ambient** — Windows lässt dort keine Klicks/Eingaben zu.
Der Chat-Balken ist also zunächst nur **sichtbar**, nicht bedienbar. Die Bedienung kommt in
**Phase 4**: ein globaler Hotkey (`Alt/⌥ + Space`) holt das echte Chatfenster nach vorne.
Bis dahin chattest du über die **Desktop-App** (`kira-desktop.bat`) oder das Cockpit.

---

## Alternative: ohne Fremd-Tool (nativ, self-contained)

Wenn du gar kein Drittprogramm willst, kann die Wallpaper-Einbettung direkt in die
`kira-desktop`-App gebaut werden (native WorkerW-Einbettung in Python — die Ebene hinter
den Icons). Sag Bescheid; Windows-only, Abnahme auf deinem PC.

---

## Farben / Optik anpassen

Alle Farben der `/wall`-Seite sind CSS-Variablen und **übernehmen deine Cockpit-Anpassung**
(Optik-Popover → `kira_custom`, gleiche Origin) — deine Optik gilt sofort auch am Desktop.
Der volle **Desktop-Editor** (Elemente ziehen, Stats wählen, Modus-Farben) kommt in **Phase 2**.
