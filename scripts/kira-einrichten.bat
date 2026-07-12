@echo off
REM Kira-Desktop einrichten: App-Logo -> Icon, Desktop-Verknuepfung, Autostart der App.
REM Voraussetzung: dein Logo liegt als  data\kira-icon.png  im Kira-Ordner.
cd /d %~dp0..
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop-setup.ps1"
echo.
pause
