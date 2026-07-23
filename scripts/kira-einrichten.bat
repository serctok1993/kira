@echo off
REM Kira-Desktop einrichten: App-Logo -> Icon, Desktop-Verknuepfung, Autostart der App.
REM Voraussetzung: dein Logo liegt als  data\kira-icon.png  im Kira-Ordner.
cd /d %~dp0..
REM Worktree-Riegel (Vorfall 18./19.07.): in einem git-Worktree ist .git eine DATEI -
REM Setup/Verknuepfungen nur aus dem Hauptrepo (sonst zeigt der LNK auf eine Alt-Kira).
if exist ".git" if not exist ".git\*" (
  echo ABBRUCH: %CD% ist ein git-Worktree - Setup nur aus dem Hauptrepo.
  exit /b 1
)
if not "%CD:.claude\worktrees=%"=="%CD%" (
  echo ABBRUCH: %CD% ist ein git-Worktree - Setup nur aus dem Hauptrepo.
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop-setup.ps1"
echo.
pause
