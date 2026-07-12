# Taskleiste DAUERHAFT ausblenden - versteckt das Taskleisten-Fenster selbst (nicht das
# Auto-Ausblenden, das bei Mausberuehrung aufpoppt). Deine Desktop-Icons bleiben sichtbar
# -> durchgaengiger Desktop. Voll reversibel.
#
#   Ausblenden:  powershell -ExecutionPolicy Bypass -File taskbar-hide.ps1 hide
#   Zeigen:      powershell -ExecutionPolicy Bypass -File taskbar-hide.ps1 show
#
# Start-Menue geht weiterhin ueber die Windows-Taste. Nach Neustart/Explorer-Neustart kommt
# die Leiste zurueck -> fuer "immer weg" das Skript mit 'hide' in den Autostart legen
# (Win+R -> shell:startup -> Verknuepfung auf dieses Skript).
param([ValidateSet("hide","show")][string]$mode = "hide")

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class TB {
  [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string win);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
}
"@

$SW_HIDE = 0
$SW_SHOW = 5
$cmd = if ($mode -eq "hide") { $SW_HIDE } else { $SW_SHOW }

$primary = [TB]::FindWindow("Shell_TrayWnd", $null)         # Haupt-Taskleiste
if ($primary -ne [IntPtr]::Zero) { [TB]::ShowWindow($primary, $cmd) | Out-Null }

$secondary = [TB]::FindWindow("Shell_SecondaryTrayWnd", $null)   # Taskleiste 2. Monitor
if ($secondary -ne [IntPtr]::Zero) { [TB]::ShowWindow($secondary, $cmd) | Out-Null }

Write-Host "Taskleiste: $mode"
