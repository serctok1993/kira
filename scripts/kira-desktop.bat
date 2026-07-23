@echo off
REM Kira als Desktop-App: das Cockpit im eigenen Fenster + Tray-Symbol (kein Browser noetig).
REM Beim allerersten Start werden die Desktop-Extras automatisch installiert.
cd /d %~dp0..
REM Worktree-Riegel (Vorfall 18./19.07.): in einem git-Worktree ist .git eine DATEI -
REM von dort bootet sonst eine Alt-Kira (leeres data\ -> setup_required). Nur Hauptrepo.
if exist ".git" if not exist ".git\*" (
  echo ABBRUCH: %CD% ist ein git-Worktree - Start nur aus dem Hauptrepo.
  exit /b 1
)
if not "%CD:.claude\worktrees=%"=="%CD%" (
  echo ABBRUCH: %CD% ist ein git-Worktree - Start nur aus dem Hauptrepo.
  exit /b 1
)
set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

REM Fehlt ein Desktop-Extra (auch neue wie keyboard/Phase 4)? -> nachziehen.
"%PY%" -c "import webview, keyboard" 2>nul
if errorlevel 1 (
  echo === Installiere/aktualisiere Desktop-Extras ^(pywebview, pystray, keyboard^) ...
  uv pip install -r requirements-desktop.txt
)

"%PY%" -m core.desktop.app
