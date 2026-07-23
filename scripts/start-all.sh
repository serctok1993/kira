#!/usr/bin/env bash
# Startet das ganze Kira-Oekosystem unter Linux: Ollama + Supervisor (Cockpit/Bot/Runner).
# Manuell aufrufen oder als systemd-user-Unit (siehe scripts/kira.service + SETUP-linux.md).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Worktree-Riegel (Vorfall 18./19.07.): in einem git-Worktree ist .git eine DATEI —
# von dort bootet sonst eine Alt-Kira (leeres data/ -> setup_required). Nur Hauptrepo.
case "$ROOT" in */.claude/worktrees/*) WT=1;; *) WT=0;; esac
if [ -f "$ROOT/.git" ] || [ "$WT" = 1 ]; then
  echo "ABBRUCH: $ROOT ist ein git-Worktree - Start nur aus dem Hauptrepo." >&2
  exit 1
fi
cd "$ROOT"

# 0) Ollama (Modell-Backend) sicherstellen — fehlt es (Offline-Box ohne Ollama?), klare Meldung
if ! curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if command -v ollama >/dev/null 2>&1; then
    nohup ollama serve >/dev/null 2>&1 &
    sleep 5
  else
    echo "Hinweis: Ollama laeuft nicht und wurde nicht gefunden — lokale Modelle fehlen." >&2
  fi
fi

# 1) Kira ueber den Supervisor (haelt Cockpit/Bot/Runner am Leben; Singleton ueber Port 8009)
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$ROOT/data/logs"
exec "$PY" -m core.kernel.supervisor
