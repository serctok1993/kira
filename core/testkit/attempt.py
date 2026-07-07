"""In-Worktree-Ausfuehrung EINER Benchmark-Aufgabe. Laeuft als Subprozess mit gesetzter
Sandbox-Env (KIRA_ROOT/KIRA_DATA_DIR -> Worktree), sodass core.config die Datenpfade beim
Import in den Worktree einfriert. Liest die Aufgabe als JSON von stdin, gibt ein JSON-Ergebnis
auf stdout (letzte Zeile) aus. Kein Cloud-Spend (Firewall), Modell laeuft lokal.
"""
from __future__ import annotations

import json
import sys


def main() -> None:
    task = json.loads(sys.stdin.read() or "{}")
    from core.agency.act import plan_and_execute
    try:
        out = plan_and_execute(task.get("prompt", ""),
                               session_id="bench-" + str(task.get("id", "x")),
                               code_review=True)
        print(json.dumps({"text": (out or "")[:2000]}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)[:500]}))


if __name__ == "__main__":
    main()
