#!/usr/bin/env bash
# Registriert Kira als systemd-user-Unit (Autostart beim Login, KEIN Root noetig).
# Einmal ausfuehren. Entfernen: scripts/uninstall-autostart.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Worktree-Riegel (Vorfall 18./19.07.): Autostart darf NIE in einen git-Worktree zeigen
# (.git ist dort eine DATEI) — sonst bootet beim Login eine Alt-Kira. Nur Hauptrepo.
case "$ROOT" in */.claude/worktrees/*) WT=1;; *) WT=0;; esac
if [ -f "$ROOT/.git" ] || [ "$WT" = 1 ]; then
  echo "ABBRUCH: $ROOT ist ein git-Worktree - Autostart nur aus dem Hauptrepo." >&2
  exit 1
fi
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

# Vorlage kopieren und den echten Kira-Pfad eintragen (statt %h/kira)
sed "s|%h/kira|$ROOT|g" "$ROOT/scripts/kira.service" > "$UNIT_DIR/kira.service"

systemctl --user daemon-reload
systemctl --user enable --now kira
echo "OK: Kira laeuft als systemd-user-Unit und startet beim Login."
echo "Status:  systemctl --user status kira"
echo "Logs:    journalctl --user -u kira -f"
echo "Tipp Offline-Box (Start ohne Login): sudo loginctl enable-linger $USER"
