@echo off
REM Kira als Desktop-App starten: das Cockpit im eigenen Fenster + Tray-Symbol (kein Browser noetig).
REM Beim ersten Mal die Desktop-Extras installieren:  uv sync --extra desktop
cd /d %~dp0
set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -m core.desktop.app
