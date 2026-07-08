# Startet das ganze Kira-Oekosystem: Ollama + Cockpit + Telegram-Bot + Mission-Loop.
# Wird vom Autostart aufgerufen (oder manuell). Mission-Loop laeuft nur, wenn
# heartbeat.enabled in config.yaml = true gesetzt ist.
Set-Location -Path $PSScriptRoot

# 0) Ollama (Modell-Backend) sicherstellen
$ollamaUp = $false
try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:11434/api/tags" | Out-Null; $ollamaUp = $true } catch {}
if (-not $ollamaUp) {
  $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
  if (-not $ollama) { $ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe" }
  if (Test-Path $ollama) {
    Start-Process -WindowStyle Hidden -FilePath $ollama -ArgumentList "serve"
    Start-Sleep -Seconds 5
  }
}

# 1) Kira ueber den Supervisor (haelt Cockpit/Bot/Runner am Leben; auto-restart; Singleton ueber Port 8000)
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$logs = Join-Path $PSScriptRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
# stderr/stdout des Supervisors mitschreiben -> ein Crash beim Start (z.B. kaputte config) ist sichtbar
# Hidden statt Minimized: KEIN Konsolen-Fenster mehr in der Taskleiste - Diagnose laeuft ueber die Logs
Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList "-m","core.kernel.supervisor" -WorkingDirectory $PSScriptRoot -RedirectStandardError (Join-Path $logs "supervisor.err.log") -RedirectStandardOutput (Join-Path $logs "supervisor.out.log")
Write-Host "Kira (Supervisor) gestartet -> Cockpit: http://127.0.0.1:8000"
