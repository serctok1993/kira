# Entfernt den Kira-Autostart wieder.
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Kira.lnk"
if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Autostart-Verknuepfung entfernt." }
else { Write-Host "Keine Autostart-Verknuepfung gefunden." }
