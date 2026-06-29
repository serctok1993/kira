# Startet das ganze Prometheus-Oekosystem: Ollama + Cockpit + Telegram-Bot + Mission-Loop.
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

# 1) Kyros-Oekosystem
Start-Process -WindowStyle Minimized -FilePath "uv" -ArgumentList "run","uvicorn","core.api.server:app","--host","127.0.0.1","--port","8000"
Start-Process -WindowStyle Minimized -FilePath "uv" -ArgumentList "run","python","-m","core.agency.connectors.telegram_bot"
Start-Process -WindowStyle Minimized -FilePath "uv" -ArgumentList "run","python","-m","core.agency.missions.runner"
Write-Host "Prometheus gestartet -> Cockpit: http://127.0.0.1:8000"
