@echo off
REM Taskleiste dauerhaft ausblenden (durchgaengiger Desktop) - einfach doppelklicken.
REM Desktop-Icons bleiben; Start-Menue geht weiter ueber die Windows-Taste.
cd /d %~dp0..
powershell -ExecutionPolicy Bypass -File "%~dp0taskbar-hide.ps1" hide
