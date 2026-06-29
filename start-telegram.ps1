# Startet Kyros' Telegram-Bot aus dem richtigen Verzeichnis.
# Doppelklick (Rechtsklick -> "Mit PowerShell ausfuehren") oder im Terminal: .\start-telegram.ps1
Set-Location -Path $PSScriptRoot
uv run python -m core.agency.connectors.telegram_bot
