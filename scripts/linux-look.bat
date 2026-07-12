@echo off
REM Linux-Feeling: gibt allen Desktop-Ordnern ein flaches Linux-Style-Ordner-Icon.
REM (Selbst gezeichnet, kein Download noetig.) Rueckgaengig: linux-look-zurueck.bat
cd /d %~dp0..
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0linux-look.ps1"
echo.
pause
