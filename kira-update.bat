@echo off
REM Kira aktualisieren — einfach doppelklicken. (Die eigentliche Logik wohnt in
REM scripts\kira-update.bat; dieser Wrapper bleibt hier, damit der gewohnte
REM Doppelklick im Kira-Ordner weiter funktioniert.)
call "%~dp0scripts\kira-update.bat"
