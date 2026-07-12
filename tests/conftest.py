import os
import pathlib
import sys
import tempfile

# Testmodus prozessweit ANschalten, BEVOR irgendein core-Modul importiert wird: so greifen die
# Outbound-Guards (Mail/Telegram/Cloud-Budget) auch bei Import-/Collection-Zeit-Code, nicht erst
# waehrend der Testausfuehrung (wo PYTEST_CURRENT_TEST ohnehin test_mode() truthy macht).
os.environ.setdefault("KIRA_TEST_MODE", "1")

# W0-Fund (12.07.2026): Tests ohne eigenes DB_PATH-Monkeypatching schrieben in die LIVE
# data/state.db — Test-Events (service-/mcp-/playbook-Fehler), Test-Fakten ("Sergen trinkt
# Kaffee schwarz") und Tuning-Exporte landeten im echten Gedaechtnis; Kira las ihr eigenes
# Test-Rauschen als Bugs ins Backlog (B5/B6). Fix: JEDER pytest-Lauf bekommt automatisch
# eine Wegwerf-Datenwurzel, bevor core.config importiert wird. Bewusst KIRA_TEST_DATA_DIR
# statt KIRA_DATA_DIR: sandbox_active() bleibt False -> suppress_repo_writes() schuetzt
# das Repo weiter. Eine ECHTE Sandbox (Benchmark, KIRA_ROOT/KIRA_DATA_DIR) gewinnt.
if not (os.getenv("KIRA_ROOT") or os.getenv("KIRA_DATA_DIR")):
    os.environ.setdefault("KIRA_TEST_DATA_DIR",
                          tempfile.mkdtemp(prefix="kira-test-data-"))

# W3: Die Testsuite gilt als EINGERICHTETE Instanz — sonst wuerde das Onboarding-Gate
# (server.py) jeden TestClient-Aufruf nach /setup umleiten. Onboarding-Tests loeschen
# das Flag gezielt in ihrer eigenen Wegwerf-Datenwurzel.
_data = os.getenv("KIRA_TEST_DATA_DIR")
if _data:
    pathlib.Path(_data).mkdir(parents=True, exist_ok=True)
    pathlib.Path(_data, "onboarded.flag").write_text("test", encoding="utf-8")

# Projekt-Root importierbar machen (core.*), egal von wo pytest startet.
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
