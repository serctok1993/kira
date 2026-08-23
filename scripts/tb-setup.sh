#!/usr/bin/env bash
# Terminal-Bench-2.0-Umgebung fuer den Kira-Adapter (core/testkit/tb_kira_agent.py).
# Braucht: uv, Docker-Daemon, OPENROUTER_API_KEY in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
uv venv --python 3.13 .tb-venv
uv pip install --python .tb-venv/bin/python terminal-bench harbor
uv pip install --python .tb-venv/bin/python -r pyproject.toml
.tb-venv/bin/harbor download "terminal-bench@2.0"
echo "Fertig. Lauf-Beispiel:"
echo '  set -a && . ./.env && set +a'
echo '  .tb-venv/bin/harbor run -d "terminal-bench@2.0" \'
echo '      -a core.testkit.tb_kira_agent:KiraAgent \'
echo '      -m openrouter/nvidia/nemotron-3-ultra-550b-a55b:free -o tb-jobs'
# Kira fuer den Harbor-Prozessbaum importierbar machen (Subprozesse verlieren PYTHONPATH)
echo "$(cd "$(dirname "$0")/.." && pwd)" > .tb-venv/lib/python3.13/site-packages/kira_root.pth
