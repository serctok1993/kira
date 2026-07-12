@echo off
REM Macht die Linux-Style-Ordner-Icons wieder rueckgaengig (Standard-Windows-Ordner).
cd /d %~dp0..
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0linux-look.ps1" -Reset
echo.
pause
