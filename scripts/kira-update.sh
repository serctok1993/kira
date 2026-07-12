#!/usr/bin/env bash
# Kira aktualisieren (Linux) — Gegenstueck zu scripts/kira-update.bat.
#
# Modell: Der Cloud-Stand (GitHub) ist die Wahrheit fuer den CODE. Dieses Skript setzt
# deinen lokalen Code exakt darauf.
# SICHER fuer deine Sachen: data/, .env, deine Charakter-Dateien (core/mind/*.md),
# der Stammbaum und projects/ sind gitignored -> git fasst sie NIE an. Nur getrackte
# Notiz-Anteile (gedaechtnis-Regeln, playbooks) werden beiseitegelegt und zurueckgespielt.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Sichere getrackte Notiz-Anteile ..."
git stash push --quiet -- gedaechtnis playbooks || true
echo "=== Verwerfe lokale Code-Selbst-Edits ..."
git checkout --quiet -- .
echo "=== Hole neuesten Cloud-Stand ..."
git fetch origin main
git reset --hard --quiet origin/main
echo "=== Spiele Notizen zurueck ..."
git stash pop --quiet || true
echo "=== Starte Kira sauber neu (Supervisor, ~20 Sekunden) ..."
printf 'all' > data/restart.flag
echo
echo "Fertig! Danach im Browser Strg+F5 druecken."
echo "(Falls oben CONFLICT steht: deine Notizen liegen sicher im stash.)"
