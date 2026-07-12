#!/usr/bin/env bash
# Entfernt den Kira-Autostart (systemd-user-Unit) wieder.
set -euo pipefail
systemctl --user disable --now kira 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/kira.service"
systemctl --user daemon-reload
echo "OK: Kira-Autostart entfernt."
