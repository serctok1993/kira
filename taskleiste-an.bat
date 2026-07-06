@echo off
REM Taskleiste wieder anzeigen - einfach doppelklicken. (Gegenstueck zu taskleiste-weg.bat)
cd /d %~dp0
powershell -ExecutionPolicy Bypass -File "%~dp0taskbar-hide.ps1" show
