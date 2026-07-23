# Registriert Kira als Autostart beim Anmelden (Startup-Ordner, KEIN Admin noetig).
# Einmal ausfuehren. Entfernen: .\uninstall-autostart.ps1
$root = Split-Path -Parent $PSScriptRoot
# Worktree-Riegel (Vorfall 18./19.07.): Autostart darf NIE in einen git-Worktree zeigen
# (.git ist dort eine DATEI) — sonst bootet beim Login eine Alt-Kira. Nur Hauptrepo.
if ((Test-Path (Join-Path $root ".git") -PathType Leaf) -or ($root -like "*\.claude\worktrees\*")) {
  Write-Host "ABBRUCH: $root ist ein git-Worktree - Autostart nur aus dem Hauptrepo."
  exit 1
}
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "Kira.lnk"
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = "powershell.exe"
$s.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\start-all.ps1`""
$s.WorkingDirectory = Split-Path -Parent $PSScriptRoot
$s.WindowStyle = 7
$s.Save()
Write-Host "OK: Autostart-Verknuepfung angelegt: $lnk"
Write-Host "Entfernen mit: .\uninstall-autostart.ps1"
