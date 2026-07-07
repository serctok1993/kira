# Linux-Feeling am Desktop (Maus · Ordner-Icons · Startmenü)

Alles mit **Open-Source-Mitteln**, **keine System-Patches** (nichts an Windows-DLLs), alles
reversibel. Die Skripte liegen im Kira-Ordner; die Grafik-Packs (Cursor) lädst du einmal aus den
verlinkten freien Quellen.

---

## 1 · Maus-Cursor — rund, smooth, „Lacklook" (schwarz)

Genau der Look, den du meinst (glänzend, abgerundet, weich) ist **Bibata Modern Classic**
(schwarz) — ein Open-Source-Cursor (MIT), der systemweit läuft.

1. **Laden:** [Bibata-Cursor Releases](https://github.com/ful1e5/Bibata_Cursor/releases) →
   die **Windows-Variante** von **`Bibata-Modern-Classic`** (schwarz, rund) herunterladen und entpacken.
2. Im entpackten Ordner **Rechtsklick auf `install.inf` → „Installieren"**.
3. **Windows-Einstellungen → Bluetooth und Geräte → Maus → Weitere Mauseinstellungen →
   Reiter „Zeiger" → Schema:** `Bibata-Modern-Classic` wählen → **Übernehmen**.
4. Zurück: im selben Dialog wieder `Windows-Standard` (oder „Keine") wählen.

> **Hinweis zu custom-cursor.com:** Das ist eine **Browser-Erweiterung** — sie ändert den Cursor
> **nur im Browser**, nicht systemweit auf dem Desktop. Für „überall" brauchst du ein echtes
> Cursor-Pack wie Bibata (oben). Der schwarze runde Bibata-Look kommt dem Pack von der Seite sehr nah.
>
> Alternativen im gleichen Stil: **Breeze** (KDE) oder **Adwaita** (GNOME) als Windows-Cursor-Pack.

---

## 2 · Ordner-Icons — flach im Linux-Style

**Doppelklick auf `linux-look.bat`** → jeder Ordner, der direkt auf deinem **Desktop** liegt
(Projekte, Kira, Programme, Luvex …), bekommt ein flaches Linux-artiges Ordner-Icon.

- Das Icon wird **selbst gezeichnet** (`data/linux-folder.ico`) — **kein Download nötig**.
- **Sicher & reversibel:** jeder Ordner bekommt nur seine eigene `desktop.ini` (kein System-Eingriff).
- **Zurück:** Doppelklick auf **`linux-look-zurueck.bat`**.
- **Andere Farbe?** z. B. Kira-Lila:
  `powershell -ExecutionPolicy Bypass -File linux-look.ps1 -Color b026ff`
  (Standard ist Papirus-Teal `5aa2b4`.)
- **Nur bestimmte Ordner:**
  `... -File linux-look.ps1 -Folders "C:\Users\serge\Desktop\Projekte","C:\Users\serge\Desktop\Kira"`

> Hängt noch das alte Icon? Einmal ab-/anmelden oder den Explorer neu starten — Windows cached Icons.
> Für **echte Papirus/Yaru-Ordner-Grafiken** (statt der selbst gezeichneten): eine `.ico` aus
> [Papirus](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme) nehmen und mit
> `-Icon "pfad\zur\ordner.ico"` übergeben.

---

## 3 · Startmenü — Linux-artig (Open-Shell)

Das Windows-Startmenü lässt sich mit **Open-Shell** (Open Source, MIT — Nachfolger von Classic Shell)
komplett ersetzen und dunkel/linuxartig gestalten. Kein System-Patch, jederzeit deinstallierbar.

1. **Installieren:** `winget install Open-Shell.Open-Shell-Menu`
   (nur „Classic Start Menu" auswählen; „Classic Explorer"/„IE" kannst du abwählen).
2. **Start-Button anklicken → Settings:** Stil **„Windows 7 / classic"**, dann unter **„Skin"** ein
   dunkles Skin wählen. Unter **„Start Menu Style → Replace Start button → Custom** kannst du ein
   eigenes Bild setzen — z. B. dein **Kira-Logo** (`data/kira-icon.png`) als Start-Knopf.
3. Zurück: Open-Shell deinstallieren → Windows-Startmenü ist wieder da.

> Ein echtes GNOME/KDE-Launcher-Gefühl gibt es unter Windows nur begrenzt — Open-Shell + dunkles
> Skin + Kira-Logo kommt dem am nächsten, ohne Windows anzufassen.

---

## Warum kein „alle Ordner systemweit auf einmal"?

Das ginge nur mit Tools, die Windows-System-DLLs patchen (7tsp, CustomizerGod). Das ist **riskant**
(bricht bei Windows-Updates, schwer sauber rückgängig) und widerspricht dem Prinzip „alles sauber &
unabhängig". Der Pro-Ordner-Weg oben macht genau die Ordner schön, die du auf dem Desktop siehst —
ohne Risiko.
