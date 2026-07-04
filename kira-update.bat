@echo off
REM Kira aktualisieren: holen, zurueckschieben, sicher neu starten.
REM Einfach doppelklicken. Fenster schliesst sich nach Tastendruck.
cd /d %~dp0
echo === Hole neuesten Stand von GitHub ...
git pull --no-edit
echo === Schicke lokale Arbeit (Kiras Commits) zurueck ...
git push
echo === Starte Kira sauber neu (Supervisor, ~20 Sekunden) ...
echo all> data\restart.flag
echo.
echo Fertig! Kira laedt den neuen Stand.
pause
