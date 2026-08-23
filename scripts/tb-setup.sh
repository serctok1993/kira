#!/usr/bin/env bash
# Terminal-Bench-2.0-Umgebung fuer den Kira-Adapter (core/testkit/tb_kira_agent.py).
# Braucht: uv, Docker-Daemon, OPENROUTER_API_KEY in .env.
#
# Betriebswissen (23.08.2026, erarbeitet gegen Docker-Hub-Rate-Limits + 20GB-Platte):
#  * Docker Hub drosselt anonyme Pulls hart (429) -> daemon.json unten routet ueber
#    mirror.gcr.io. Der Mirror ist ein Pull-Through-Cache fuer GANZ docker.io —
#    auch die 89 Prebuilt-Images (alexgshaw/*) kommen darueber ohne Limit.
#    Prebuilt ist der Koenigsweg (kanonische Leaderboard-Umgebung, kein --force-build:
#    lokale Builds scheitern am TLS-Proxy, weil RUN-Downloads der Proxy-CA nicht trauen).
#  * TLS-Proxy der Sandbox: ALLER HTTPS-Verkehr wird re-terminiert. Laufzeit-
#    Downloads im Task-Container fixt der Adapter selbst (KiraAgent.setup()
#    installiert /root/.ccr/agent-proxy-ca.crt in den Container; No-op ausserhalb).
#  * Platte: ~1-6GB je Task-Image -> waehrend des Laufs Images fertiger Trials
#    loeschen (docker rmi / docker image prune), sonst laufen 89 Tasks die
#    Session-Platte voll.
#  * Abgebrochene/fehlgeschlagene Trials wiederholen:
#      .tb-venv/bin/harbor jobs resume -p tb-jobs/<job> -f RuntimeError
#    (faengt Pull-Fehler UND KiraDegraded aus dem Adapter, z.B. OpenRouter-
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
echo '      --agent core.testkit.tb_kira_agent:KiraAgent \'
echo '      --model openrouter/nvidia/nemotron-3-ultra-550b-a55b:free \'
echo '      --jobs-dir tb-jobs --job-name kira-tb2-official -n 2 -y \'
echo '      --ve UV_NATIVE_TLS=1 \'
echo '      --ve SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \'
echo '      --ve REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \'
echo '      --ve CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \'
echo '      --ve NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \'
echo '      --ve GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt \'
echo '      --ve PIP_CERT=/etc/ssl/certs/ca-certificates.crt'
echo '  # Verifier-TLS: TB2-Verifier holen pytest via uv — ohne diese Env-Schiene'
echo '  # (plus uv.toml/certifi-Fix im Adapter-setup()) faellt jede Loesung auf 0.'
