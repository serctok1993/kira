@echo off
REM Kira als Desktop-App: das Cockpit im eigenen Fenster + Tray-Symbol (kein Browser noetig).
REM Beim allerersten Start werden die Desktop-Extras automatisch installiert.
cd /d %~dp0
set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

REM Fehlt pywebview? -> einmalig die Desktop-Extras nachziehen (danach nie wieder).
"%PY%" -c "import webview" 2>nul
if errorlevel 1 (
  echo === Erster Start: installiere Desktop-Extras ^(pywebview, pystray, pillow^) ...
  uv pip install -r requirements-desktop.txt
)

"%PY%" -m core.desktop.app
