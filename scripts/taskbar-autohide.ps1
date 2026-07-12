# Windows-Taskleiste automatisch ausblenden (an|aus) - reversibel.
# Nutzung:  powershell -ExecutionPolicy Bypass -File taskbar-autohide.ps1 on
#           powershell -ExecutionPolicy Bypass -File taskbar-autohide.ps1 off
param([ValidateSet("on","off")][string]$mode = "on")

$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3"
try {
    $s = (Get-ItemProperty -Path $key -Name Settings).Settings
    # Byte 8, Bit 0 steuert das Auto-Ausblenden der Taskleiste.
    if ($mode -eq "on") { $s[8] = ($s[8] -bor 0x01) } else { $s[8] = ($s[8] -band 0xFE) }
    Set-ItemProperty -Path $key -Name Settings -Value $s
    Stop-Process -Name explorer -Force   # Explorer neu starten -> Einstellung greift (Icons bleiben)
    Write-Host "Taskleiste Auto-Ausblenden: $mode"
} catch {
    Write-Host "Konnte die Einstellung nicht setzen: $_"
    Write-Host "Alternativ manuell: Rechtsklick auf die Taskleiste -> Einstellungen -> 'automatisch ausblenden'."
}
