import os
import pathlib
import sys

# Testmodus prozessweit ANschalten, BEVOR irgendein core-Modul importiert wird: so greifen die
# Outbound-Guards (Mail/Telegram/Cloud-Budget) auch bei Import-/Collection-Zeit-Code, nicht erst
# waehrend der Testausfuehrung (wo PYTEST_CURRENT_TEST ohnehin test_mode() truthy macht).
os.environ.setdefault("KIRA_TEST_MODE", "1")

# Projekt-Root importierbar machen (core.*), egal von wo pytest startet.
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
