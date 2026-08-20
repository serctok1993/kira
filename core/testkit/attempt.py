"""In-Worktree-Ausfuehrung EINER Benchmark-Aufgabe. Laeuft als Subprozess mit gesetzter
Sandbox-Env (KIRA_ROOT/KIRA_DATA_DIR -> Worktree), sodass core.config die Datenpfade beim
Import in den Worktree einfriert. Liest die Aufgabe als JSON von stdin, gibt ein JSON-Ergebnis
auf stdout (letzte Zeile) aus. Kein Cloud-Spend (Firewall), Modell laeuft lokal.
"""
from __future__ import annotations

import json
import sys


def _emit(ev: dict) -> None:
    """Ein Denk-/Werkzeug-Ereignis als @EV-Zeile an stdout streamen (der Runner leitet es live
    ans Cockpit weiter). Best-effort — Serialisierungs-Fehler duerfen den Lauf nie abreissen."""
    try:
        print("@EV " + json.dumps(ev, ensure_ascii=False), flush=True)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    task = json.loads(sys.stdin.read() or "{}")
    # Sandbox-DB frisch anlegen (leere state.db im Worktree -> Tabellen erst erzeugen), sonst
    # scheitert der erste events.emit an "no such table: events".
    from core.kernel import events
    from core.mind.memory import store
    events.init_db()
    store.init_memory()
    from core.agency.act import act, plan_and_execute
    try:
        if task.get("single_loop"):
            # Referenz-Harness-Muster (mini-swe-agent/OpenHands): EIN durchgehender Loop
            # mit hohem Runden-Budget, das Modell steuert selbst. Nemotron & Co. sind auf
            # genau dieses Muster trainiert; die Plan-Zerlegung verliert pro Teilschritt
            # Kontext (v5-Vergleichsgrundlage: 3/10 im Plan-Modus).
            out = act(task.get("prompt", ""),
                      session_id="bench-" + str(task.get("id", "x")),
                      max_steps=int(task.get("max_steps", 80)),
                      escalate=True, task_type="reason")["text"]
            print("@RESULT " + json.dumps({"text": (out or "")[:2000]}), flush=True)
            return
        # code_review=False fuer SWE-bench: dort ist die Endabnahme das OFFIZIELLE Eval —
        # Kiras eigene Testsuite-Abnahme waere im Fremd-Repo immer rot und wuerde den
        # fertigen Patch per Rollback wieder loeschen (der 0%-Bug vom ersten Lauf).
        out = plan_and_execute(task.get("prompt", ""),
                               session_id="bench-" + str(task.get("id", "x")),
                               code_review=bool(task.get("code_review", True)),
                               on_event=_emit)
        print("@RESULT " + json.dumps({"text": (out or "")[:2000]}), flush=True)
    except Exception as e:  # noqa: BLE001
        print("@RESULT " + json.dumps({"error": str(e)[:500]}), flush=True)


if __name__ == "__main__":
    main()
