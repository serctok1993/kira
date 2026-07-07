# Kira-Desktop einrichten: App-Logo -> Icon, schoene Desktop-Verknuepfung, Autostart der App.
#
# Voraussetzung: du hast dein Logo als  data\kira-icon.png  abgelegt (der Kira-Ordner).
# Einmal ausfuehren (Doppelklick auf kira-einrichten.bat oder):
#     powershell -ExecutionPolicy Bypass -File desktop-setup.ps1
# Rueckgaengig (Autostart weg):  .\uninstall-autostart.ps1   (die Desktop-Verknuepfung einfach loeschen)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$ico  = Join-Path $root "data\kira-icon.ico"
$bat  = Join-Path $root "kira-desktop.bat"

# Logo-Quelle finden: egal ob .png, .jpg, .jpeg oder .webp (System.Drawing liest alle)
$png = $null
foreach ($ext in @("png","jpg","jpeg","webp")) {
  $cand = Join-Path $root "data\kira-icon.$ext"
  if (Test-Path $cand) { $png = $cand; break }
}

# --- 1) Logo -> ICO (fuer Verknuepfungs-Symbole; Windows-Shortcuts brauchen .ico) ----------
if ($png) {
  try {
    Add-Type -AssemblyName System.Drawing
    $src = [System.Drawing.Image]::FromFile($png)
    $bmp = New-Object System.Drawing.Bitmap 256,256
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.DrawImage($src, 0, 0, 256, 256)
    $g.Dispose(); $src.Dispose()
    $h = $bmp.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($h)
    $fs = [System.IO.File]::Create($ico)
    $icon.Save($fs); $fs.Close()
    $icon.Dispose(); $bmp.Dispose()
    Write-Host "OK: Icon erzeugt -> $ico"
  } catch {
    Write-Host "Hinweis: Konnte kein .ico erzeugen ($($_.Exception.Message)) - nutze das Standard-Symbol."
    $ico = $null
  }
} else {
  Write-Host "Hinweis: kein data\kira-icon.(png|jpg|jpeg|webp) gefunden - lege dein Logo dort ab und starte erneut, dann bekommt die Verknuepfung dein Bild."
  $ico = $null
}

try {
  $sh = New-Object -ComObject WScript.Shell

  # --- 2) Schoene Desktop-Verknuepfung (Doppelklick startet die App) -----------------------
  # GetFolderPath kann in manchen Prozess-Kontexten leer sein -> Fallback ueber %USERPROFILE%.
  $desktop = [Environment]::GetFolderPath("Desktop")
  if ([string]::IsNullOrEmpty($desktop)) { $desktop = Join-Path $env:USERPROFILE "Desktop" }
  if (-not (Test-Path $desktop)) { New-Item -ItemType Directory -Path $desktop -Force | Out-Null }
  $dlnk = Join-Path $desktop "Kira.lnk"
  $s = $sh.CreateShortcut($dlnk)
  $s.TargetPath = $bat
  $s.WorkingDirectory = $root
  $s.WindowStyle = 7                       # minimiert starten (kein Konsolenfenster im Weg)
  $s.Description = "Kira - Cockpit (Desktop-App)"
  if ($ico) { $s.IconLocation = "$ico,0" }
  $s.Save()
  Write-Host "OK: Desktop-Verknuepfung -> $dlnk"

  # --- 3) Autostart der Desktop-App (eigener Eintrag; Tray + Cockpit beim Anmelden) --------
  $startup = [Environment]::GetFolderPath("Startup")
  if ([string]::IsNullOrEmpty($startup)) { $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup" }
  if (-not (Test-Path $startup)) { New-Item -ItemType Directory -Path $startup -Force | Out-Null }
  $slnk = Join-Path $startup "Kira Desktop.lnk"
  $s2 = $sh.CreateShortcut($slnk)
  $s2.TargetPath = $bat
  $s2.WorkingDirectory = $root
  $s2.WindowStyle = 7
  $s2.Description = "Kira Desktop-App (Autostart)"
  if ($ico) { $s2.IconLocation = "$ico,0" }
  $s2.Save()
  Write-Host "OK: Autostart-Eintrag -> $slnk"

  Write-Host ""
  Write-Host "Fertig. Kira liegt als Icon auf dem Desktop und startet beim Anmelden (Tray-Symbol)."
  exit 0
} catch {
  Write-Host "FEHLER beim Anlegen der Verknuepfung: $($_.Exception.Message)"
  exit 1
}
