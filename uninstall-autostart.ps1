# Entfernt den Prometheus-Autostart wieder.
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Prometheus.lnk"
if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Autostart-Verknuepfung entfernt." }
else { Write-Host "Keine Autostart-Verknuepfung gefunden." }
