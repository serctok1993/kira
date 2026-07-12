@echo off
REM Kira aktualisieren: einfach doppelklicken.
REM
REM Modell: Der Cloud-Stand (GitHub) ist die Wahrheit fuer den CODE. Diese Datei setzt
REM deinen lokalen Code exakt darauf, damit das Update nie mehr an Kiras eigenen
REM Selbst-Edits scheitert ("would be overwritten by merge").
REM
REM SICHER fuer deine Sachen:
REM   - data/ und .env sind gitignored  -> git fasst sie NIE an (Gedaechtnis-DB, Secrets, Modelle).
REM   - Deine Charakter-Dateien (core/mind/*.md), der Stammbaum und projects/ sind seit
REM     W3 gitignored -> git fasst sie NIE an. Nur getrackte Notiz-Anteile (gedaechtnis-
REM     Regeln, playbooks) werden beiseitegelegt und danach wieder eingespielt.
REM   Es weichen nur lokale CODE-Aenderungen, die der Cloud-Stand ohnehin ersetzt.
cd /d %~dp0..
echo === Sichere deine Notizen und Charakter-Dateien ...
git stash push --quiet -- gedaechtnis playbooks
echo === Verwerfe Kiras lokale Code-Selbst-Edits ...
git checkout --quiet -- .
echo === Hole neuesten Cloud-Stand ...
git fetch origin main
git reset --hard --quiet origin/main
echo === Spiele deine Notizen zurueck ...
git stash pop --quiet
echo === Starte Kira sauber neu (Supervisor, ~20 Sekunden) ...
echo all> data\restart.flag
echo.
echo Fertig! Danach im Browser Strg+F5 druecken.
echo (Falls oben "CONFLICT" steht, sag Claude Bescheid - deine Notizen sind sicher im stash.)
timeout /t 15
rem Fenster schliesst sich nach 15s von selbst (vorher: pause = blieb ewig offen)
