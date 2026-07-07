# Linux-Feeling am Desktop: gibt deinen Desktop-Ordnern ein flaches Linux-Style-Ordner-Icon.
#
# Erzeugt EINMALIG ein Ordner-Icon (data\linux-folder.ico, flach/Papirus-artig, selbst gezeichnet -
# kein Download noetig) und setzt es per desktop.ini auf jeden Ordner, der direkt auf dem Desktop liegt.
# Sicher & reversibel (kein System-Patch): jeder Ordner bekommt nur seine eigene desktop.ini.
#
# Anwenden:      powershell -ExecutionPolicy Bypass -File linux-look.ps1
# Nur bestimmte: powershell ... -File linux-look.ps1 -Folders "C:\...\Projekte","C:\...\Kira"
# Rueckgaengig:  powershell -ExecutionPolicy Bypass -File linux-look.ps1 -Reset
#
# Maus-Cursor & Startmenue: siehe docs\LINUX-LOOK.md (Open-Source-Tools, keine System-Patches).

param(
  [string[]]$Folders,          # welche Ordner? leer = alle direkt auf dem Desktop
  [switch]$Reset,              # Icons wieder entfernen
  [string]$Color = "5aa2b4"    # Ordnerfarbe (Hex, Papirus-Teal). z.B. "b026ff" fuer Kira-Lila
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$ico  = Join-Path $root "data\linux-folder.ico"

# --- Ziel-Ordner bestimmen -------------------------------------------------------------
if (-not $Folders -or $Folders.Count -eq 0) {
  $desk = [Environment]::GetFolderPath("DesktopDirectory")
  $Folders = Get-ChildItem -LiteralPath $desk -Directory -Force | ForEach-Object { $_.FullName }
}

function Reset-FolderIcon($folder) {
  $ini = Join-Path $folder "desktop.ini"
  if (Test-Path $ini) { attrib -h -s $ini 2>$null; Remove-Item $ini -Force }
  attrib -s $folder 2>$null
}

if ($Reset) {
  foreach ($f in $Folders) { Reset-FolderIcon $f; Write-Host "zurueckgesetzt: $f" }
  Write-Host "Fertig. (Ab-/Anmelden oder Explorer neu starten, falls das alte Icon noch haengt.)"
  return
}

# --- 1) Flaches Linux-Style-Ordner-Icon zeichnen (einmalig) ----------------------------
function New-FolderIcon($path, $hex) {
  Add-Type -AssemblyName System.Drawing
  $r = [Convert]::ToInt32($hex.Substring(0,2),16)
  $g = [Convert]::ToInt32($hex.Substring(2,2),16)
  $b = [Convert]::ToInt32($hex.Substring(4,2),16)
  $front = [System.Drawing.Color]::FromArgb(255, $r, $g, $b)
  $back  = [System.Drawing.Color]::FromArgb(255, [Math]::Max(0,$r-34), [Math]::Max(0,$g-34), [Math]::Max(0,$b-34))
  $bmp = New-Object System.Drawing.Bitmap 256,256
  $gfx = [System.Drawing.Graphics]::FromImage($bmp)
  $gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $bBack  = New-Object System.Drawing.SolidBrush $back
  $bFront = New-Object System.Drawing.SolidBrush $front
  # hinteres Blatt + Tab (der ueberstehende Reiter oben links)
  $gfx.FillRectangle($bBack, 26, 70, 204, 132)
  $gfx.FillRectangle($bBack, 26, 58, 96, 26)
  # vordere Klappe (flach, etwas heller) -> klar als Ordner erkennbar, Linux-flat
  $gfx.FillRectangle($bFront, 26, 92, 204, 110)
  $gfx.Dispose(); $bBack.Dispose(); $bFront.Dispose()
  $h = $bmp.GetHicon()
  $icon = [System.Drawing.Icon]::FromHandle($h)
  $dir = Split-Path $path -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  $fs = [System.IO.File]::Create($path); $icon.Save($fs); $fs.Close()
  $icon.Dispose(); $bmp.Dispose()
}

try {
  New-FolderIcon $ico $Color
  Write-Host "OK: Ordner-Icon erzeugt -> $ico"
} catch {
  Write-Host "Fehler beim Zeichnen des Icons: $($_.Exception.Message)"
  return
}

# --- 2) Icon per desktop.ini auf jeden Ordner setzen -----------------------------------
function Set-FolderIcon($folder, $icoPath) {
  $ini = Join-Path $folder "desktop.ini"
  if (Test-Path $ini) { attrib -h -s $ini 2>$null; Remove-Item $ini -Force }
  $txt = "[.ShellClassInfo]`r`nIconResource=$icoPath,0`r`nConfirmFileOp=0`r`n"
  Set-Content -LiteralPath $ini -Value $txt -Encoding Unicode
  attrib +h +s $ini 2>$null      # desktop.ini versteckt+system
  attrib +s $folder 2>$null      # Ordner als system markieren -> Windows liest die desktop.ini
}

$n = 0
foreach ($f in $Folders) {
  try { Set-FolderIcon $f $ico; Write-Host "Icon gesetzt: $f"; $n++ }
  catch { Write-Host "uebersprungen ($($_.Exception.Message)): $f" }
}
# Icon-Cache anstupsen, damit die neuen Icons sofort erscheinen
try { ie4uinit.exe -show 2>$null } catch {}
Write-Host ""
Write-Host "Fertig: $n Ordner mit Linux-Style-Icon. Rueckgaengig: linux-look.ps1 -Reset"
Write-Host "Andere Farbe? z.B.:  ...-File linux-look.ps1 -Color b026ff   (Kira-Lila)"
