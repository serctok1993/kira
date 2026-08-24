#!/usr/bin/env bash
# Sichert den TB2-Job-Ordner rollback-fest ins Repo (tb-jobs/ ist gitignoriert,
# Container-Rollbacks vernichten sonst alle Messergebnisse). Grosse Logs bleiben
# draussen; result.json/config/trial.log reichen fuer Resume-Buchhaltung + Beleg.
set -euo pipefail
cd "$(dirname "$0")/.."
QUELLE=tb-jobs/kira-tb2-official
ZIEL=bench-logs/tb2/jobdir
[ -d "$QUELLE" ] || { echo "kein Job-Ordner: $QUELLE"; exit 1; }
rm -rf "$ZIEL"
mkdir -p "$ZIEL"
cp -a "$QUELLE/." "$ZIEL/"
# Grosse/fluechtige Artefakte aus der Kopie werfen (kein rsync im Container)
find "$ZIEL" -type d \( -name sessions -o -name artifacts \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$ZIEL" -type f \( -name '*.cast' -o -size +2M \) -delete 2>/dev/null || true
git add "$ZIEL" >/dev/null
if ! git diff --cached --quiet -- "$ZIEL"; then
  git commit -q -m "TB2-Messstand sichern ($(ls "$ZIEL" | wc -l) Eintraege)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SJ38Nvcpn1NXKhWj2N4zYy"
  git push -q -u origin claude/mobile-work-remote-5kw7z8
  echo "gesichert + gepusht"
else
  echo "nichts Neues"
fi
