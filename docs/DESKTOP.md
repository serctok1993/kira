# Kira auf den Desktop bringen (Living Wallpaper)

Ziel: die Seite **`/wall`** läuft als lebendiges Wallpaper **hinter den Icons**, die
Taskleiste ist ausgeblendet — Kira wird Teil des Hintergrunds.

**Voraussetzung:** Kira läuft (Supervisor / `scripts\start-all.ps1`), das Cockpit ist erreichbar
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
> (`scripts\install-autostart.ps1` / `scripts\start-all.ps1`).

---

## 2 · Taskleiste durchsichtig (empfohlen) — TranslucentTB

Damit die Taskleiste **sichtbar bleibt, aber durchsichtig** ist (Wallpaper scheint durch,
Buttons bleiben) — das echte „durchgängiger Desktop"-Gefühl:

1. **Installieren:** `winget install --id 9PF4KZ2VN4W9`  (TranslucentTB, Open Source, MIT).
2. Rechtsklick aufs TranslucentTB-Tray-Icon → **Desktop → Clear** → Taskleiste ist komplett durchsichtig.
3. Läuft ab Autostart von selbst.

> Windows-Bordmittel allein geben nur eine leichte Acryl-Trübung (Einstellungen → Personalisierung
> → Farben → Transparenzeffekte), nicht wirklich klar — deshalb TranslucentTB.

### (Alternative) Taskleiste ganz ausblenden

Nur falls du sie wirklich WEG willst (nicht durchsichtig):

**Variante 1 — Auto-Ausblenden** (Windows-Bordmittel, kommt bei Mausberührung unten kurz zurück):
- Manuell: Rechtsklick auf die Taskleiste → *Taskleisteneinstellungen* → **„Taskleiste automatisch ausblenden"**.
- Oder: `powershell -ExecutionPolicy Bypass -File scripts\taskbar-autohide.ps1 on`  (rückgängig: `... off`).

**Variante 2 — dauerhaft weg (durchgängiger Desktop, empfohlen):** versteckt das Taskleisten-Fenster
komplett, poppt **nicht** bei Mausberührung auf. Deine Desktop-Icons bleiben sichtbar.
- **Am einfachsten:** Doppelklick auf **`scripts\taskleiste-weg.bat`** (zurück: **`scripts\taskleiste-an.bat`**).
- Oder von Hand: `powershell -ExecutionPolicy Bypass -File scripts\taskbar-hide.ps1 hide` / `... show`.
- Start-Menü geht weiter über die **Windows-Taste**.
- **Für „immer weg" (auch nach Neustart):** die Verknüpfung mit `hide` in den Autostart legen
  (`Win+R` → `shell:startup` → Verknüpfung auf `scripts\taskbar-hide.ps1` mit Argument `hide`).

---

## 3 · Interaktion (Chat) — Phase 4: Hotkey + Push-to-Talk ✓

Hinter den Icons ist die Ebene **ambient** — Windows lässt dort keine Klicks/Eingaben zu.
Deshalb holt ein **globaler Hotkey** das echte Chatfenster nach vorne (aus jeder App heraus):

- **`Alt + Space`** → Kira-Fenster nach vorn (auch wenn minimiert/versteckt).
- **`F9` HALTEN** → Push-to-Talk: Fenster kommt hoch, Mikro läuft solange du die Taste
  hältst; **loslassen** → Whisper transkribiert lokal und **sendet sofort** an Kira.
- Beide Tasten sind in `config.yaml` unter `desktop.hotkey` / `desktop.ptt_key` änderbar
  (Syntax des `keyboard`-Pakets, z.B. `"ctrl+alt+k"`).

Voraussetzungen: die **Desktop-App läuft** (`scripts\kira-desktop.bat`) und die Desktop-Extras sind
aktuell (`uv pip install -r requirements-desktop.txt` — einmalig, holt das `keyboard`-Paket).
Hinweis: `Alt+Space` überlagert das Windows-Fenstermenü; wenn dich das stört, einfach in
`config.yaml` eine andere Kombi eintragen.

---

## Alternative: ohne Fremd-Tool (nativ, self-contained)

Wenn du gar kein Drittprogramm willst, kann die Wallpaper-Einbettung direkt in die
`kira-desktop`-App gebaut werden (native WorkerW-Einbettung in Python — die Ebene hinter
den Icons). Sag Bescheid; Windows-only, Abnahme auf deinem PC.

---

## App-Logo

**Am einfachsten (empfohlen):** im Cockpit unter **Kira → Technik → Cockpit → „App-Logo → 🖼 Logo wählen"**
dein Bild hochladen. Es wird sofort **oben links im Cockpit**, als **/wall-Favicon** und (nach dem nächsten
Start der Desktop-App) als **Tray-/Taskleisten-Symbol** genutzt. Kein Datei-Geschiebe nötig.

Alternativ von Hand: das Bild als **`data/kira-icon.png`** (oder `.jpg`/`.webp`) in den Kira-Ordner legen.
`data/` ist gitignored → dein Bild bleibt lokal.

> Fehlt ein Logo, zeigt der Cockpit-Kopf den Neon-„KIRA"-Schriftzug — nichts bricht.
> Die Desktop-App startet **immer**, auch ohne Logo (das Fenster-/Taskleisten-Symbol nutzt nur ein
> `.ico`, das `scripts\kira-einrichten.bat` erzeugt; fehlt es, läuft die App einfach ohne eigenes Fenstersymbol).

## Ein-Klick-Einrichtung (Icon + Desktop-Verknüpfung + Autostart)

Wenn `data/kira-icon.png` liegt: **Doppelklick auf `scripts\kira-einrichten.bat`** (oder
`powershell -ExecutionPolicy Bypass -File scripts\desktop-setup.ps1`). Das macht in einem Rutsch:

1. **PNG → `.ico`** (`data/kira-icon.ico`) — Windows-Verknüpfungen brauchen ein Icon-Format.
2. Eine **schöne Verknüpfung `Kira` auf dem Desktop** mit deinem Logo — Doppelklick startet die App.
3. **Autostart der Desktop-App** (eigener Eintrag „Kira Desktop") → beim Anmelden kommen
   Tray-Symbol + Cockpit von selbst hoch (der Supervisor wird dabei mitgestartet).

Rückgängig: **`scripts\uninstall-autostart.ps1`** (entfernt beide Autostart-Einträge); das Desktop-Icon
einfach löschen.

## Node-Klick → Notiz in Obsidian

Wenn du `/wall` in einem **Browser-Tab** offen hast: **kurz auf einen Knoten klicken** öffnet die
Notiz direkt in Obsidian (`obsidian://open`). **Ziehen** verschiebt den Knoten (der Rest folgt).
Voraussetzung: `desktop.vault_paths` in `config.yaml` zeigt auf deinen Obsidian-Vault (der Ordnername
ist der Vault-Name).

## Farben / Optik anpassen

Alle Farben der `/wall`-Seite sind CSS-Variablen und **übernehmen deine Cockpit-Anpassung**
(Optik-Popover → `kira_custom`, gleiche Origin) — deine Optik gilt sofort auch am Desktop.
Der volle **Desktop-Editor** (Elemente ziehen, Stats wählen, Modus-Farben) kommt in **Phase 2**.
