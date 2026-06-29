# Startet das ganze Prometheus-Oekosystem: Cockpit + Telegram-Bot + Mission-Loop.
# Wird vom Autostart aufgerufen (oder manuell). Mission-Loop laeuft nur, wenn
# heartbeat.enabled in config.yaml = true gesetzt ist.
Set-Location -Path $PSScriptRoot
Start-Process -WindowStyle Minimized -FilePath "uv" -ArgumentList "run","uvicorn","core.api.server:app","--host","127.0.0.1","--port","8000"
Start-Process -WindowStyle Minimized -FilePath "uv" -ArgumentList "run","python","-m","core.agency.connectors.telegram_bot"
Start-Process -WindowStyle Minimized -FilePath "uv" -ArgumentList "run","python","-m","core.agency.missions.runner"
Write-Host "Prometheus gestartet -> Cockpit: http://127.0.0.1:8000"
