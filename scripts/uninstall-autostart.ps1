# Entfernt den Kira-Autostart wieder (Supervisor UND Desktop-App).
$startup = [Environment]::GetFolderPath("Startup")
$found = $false
foreach ($name in @("Kira.lnk", "Kira Desktop.lnk")) {
  $lnk = Join-Path $startup $name
  if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Autostart entfernt: $name"; $found = $true }
}
if (-not $found) { Write-Host "Keine Autostart-Verknuepfung gefunden." }
