import pathlib
import sys

# Projekt-Root importierbar machen (core.*), egal von wo pytest startet.
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
