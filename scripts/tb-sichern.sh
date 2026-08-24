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
# Key-artige Tokens redigieren (Tasks wie sanitize-git-repo enthalten Fake-
# Credentials; der Privatsphaere-Waechter unterscheidet fake nicht von echt —
# zu Recht). Die Redaktion gehoert in die Sicherung, nie in den Waechter.
python3 - "$ZIEL" <<'PYEOF'
import re, glob, sys
MUSTER = re.compile(r'\b(?:AKIA|ghp_|hf_|sk-|github_pat_|xox[bap]-|glpat-|AIza)[A-Za-z0-9_\-/+]{6,}')
for p in glob.glob(sys.argv[1] + '/**/*', recursive=True):
    try:
        with open(p, encoding='utf-8') as f: t = f.read()
    except (IsADirectoryError, UnicodeDecodeError, PermissionError): continue
    n = MUSTER.sub('[KEY-REDIGIERT]', t)
    if n != t:
        with open(p, 'w', encoding='utf-8') as f: f.write(n)
PYEOF
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
