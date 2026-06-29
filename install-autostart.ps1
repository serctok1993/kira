# Registriert Prometheus als Autostart beim Anmelden (Startup-Ordner, KEIN Admin noetig).
# Einmal ausfuehren. Entfernen: .\uninstall-autostart.ps1
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "Prometheus.lnk"
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = "powershell.exe"
$s.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\start-all.ps1`""
$s.WorkingDirectory = $PSScriptRoot
$s.WindowStyle = 7
$s.Save()
Write-Host "OK: Autostart-Verknuepfung angelegt: $lnk"
Write-Host "Entfernen mit: .\uninstall-autostart.ps1"
