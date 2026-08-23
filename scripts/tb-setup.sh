#!/usr/bin/env bash
# Terminal-Bench-2.0-Umgebung fuer den Kira-Adapter (core/testkit/tb_kira_agent.py).
# Braucht: uv, Docker-Daemon, OPENROUTER_API_KEY in .env.
#
# Betriebswissen (23.08.2026, erarbeitet gegen Docker-Hub-Rate-Limits + 20GB-Platte):
#  * Docker Hub drosselt anonyme Pulls hart (429) -> daemon.json unten routet ueber
#    mirror.gcr.io. Die 89 Prebuilt-Images (alexgshaw/*) liegen NICHT im Mirror,
#    aber alle 89 Tasks bauen aus nur 7 populaeren Basis-Images (python/ubuntu/
#    debian), die der Mirror liefert -> Voll-Lauf mit --force-build statt Prebuilt.
#  * Platte: ~1,5GB je Task-Image -> waehrend des Laufs Images fertiger Trials
#    loeschen (docker rmi / docker image prune), sonst laufen 89 Tasks die
#    Session-Platte voll.
#  * Abgebrochene/fehlgeschlagene Trials wiederholen:
#      .tb-venv/bin/harbor jobs resume -p tb-jobs/<job> -f RuntimeError
#    (faengt Pull-429er UND KiraDegraded aus dem Adapter, z.B. OpenRouter-
#    Tagesquota-Tod; Quota-Reset 00:00 UTC).
set -euo pipefail
cd "$(dirname "$0")/.."

# Docker: kein systemd im Container -> Daemon von Hand; Mirror gegen Hub-429.
if ! docker info >/dev/null 2>&1; then
  mkdir -p /etc/docker
  printf '{\n  "registry-mirrors": ["https://mirror.gcr.io"]\n}\n' > /etc/docker/daemon.json
  nohup dockerd > /tmp/dockerd.log 2>&1 &
  for _ in $(seq 30); do docker info >/dev/null 2>&1 && break; sleep 2; done
fi

uv venv --python 3.13 .tb-venv
uv pip install --python .tb-venv/bin/python terminal-bench harbor
uv pip install --python .tb-venv/bin/python -r pyproject.toml
# Kira fuer den Harbor-Prozessbaum importierbar machen (Subprozesse verlieren PYTHONPATH)
echo "$(pwd)" > .tb-venv/lib/python3.13/site-packages/kira_root.pth

echo "Fertig. Offizieller Lauf (Wellen-Betrieb, siehe Kopfkommentar):"
echo '  set -a && . ./.env && set +a'
echo '  .tb-venv/bin/harbor run -d terminal-bench@2.0 \'
echo '      --agent-import-path core.testkit.tb_kira_agent:KiraAgent \'
echo '      --model openrouter/nvidia/nemotron-3-ultra-550b-a55b:free \'
echo '      --jobs-dir tb-jobs --job-name kira-tb2-official -n 3 --force-build'
