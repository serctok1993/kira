"""Coding-Benchmark-Runner: faehrt eine Suite von Coding-Aufgaben, jede in einem eigenen
git-Worktree (Sandbox), und bewertet sie ueber ein Akzeptanz-Kommando (verify_cmd).

Eine Aufgabe: {"id", "prompt", "verify_cmd"}.  Der Lauf pro Aufgabe:
  1. Wegwerf-Worktree oeffnen (Live-Repo bleibt unberuehrt, Firewall an).
  2. Kira den Auftrag ausfuehren lassen (act.plan_and_execute im Worktree) — Standard-Exec;
     fuer Tests ueber exec_fn injizierbar.
  3. verify_cmd im Worktree ausfuehren -> returncode 0 = bestanden (das Akzeptanz-Orakel).

CLI:  python -m core.testkit.bench --suite tests/bench/suite.json
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

from core.testkit.sandbox import make_worktree


def _default_exec(worktree: Path, env: dict, task: dict) -> dict:
    """Standard-Ausfuehrung: startet act.plan_and_execute im Worktree als Subprozess (Sandbox-Env
    schon gesetzt -> Datenpfade zeigen in den Worktree, Cloud-Spend blockiert)."""
    p = subprocess.run([sys.executable, "-m", "core.testkit.attempt"],
                       cwd=str(worktree), env=env, input=json.dumps(task),
                       capture_output=True, text=True, timeout=int(task.get("timeout", 1800)))
    line = (p.stdout.strip().splitlines() or [""])[-1]
    try:
        return json.loads(line)
    except Exception:  # noqa: BLE001
        return {"raw": (p.stdout + p.stderr)[-500:]}


def _setup(worktree: Path, env: dict, task: dict) -> None:
    """Optionales setup_cmd VOR dem Versuch im Worktree ausfuehren (z.B. eine kaputte
    Datei hinlegen, die die Aufgabe reparieren soll). Scheitert das Setup, soll die
    Aufgabe sichtbar scheitern — nicht der Runner abreissen."""
    cmd = task.get("setup_cmd")
    if not cmd:
        return
    subprocess.run(cmd, shell=True, cwd=str(worktree), env=env,
                   capture_output=True, text=True, timeout=int(task.get("setup_timeout", 120)))
    # Material COMMITTEN (Wegwerf-Branch): die Endabnahme rollt einen roten Lauf per
    # git reset --hard auf den Stand VOR dem Versuch zurueck — uncommittetes Material,
    # das Kira waehrend des Laufs committet hat, wuerde dabei restlos verschwinden und
    # verify saehe "Datei fehlt" statt "Aufgabe nicht geloest" (Suite-v3-Befund).
    for args in (("add", "-A"), ("commit", "-m", "bench-setup", "--no-verify", "--quiet")):
        subprocess.run(["git", "-C", str(worktree), *args],
                       capture_output=True, text=True, timeout=60)


def _verify(worktree: Path, env: dict, task: dict) -> tuple[int, str]:
    cmd = task.get("verify_cmd")
    if not cmd:
        return 0, "(kein verify_cmd — nur Ausfuehrung, keine Bewertung)"
    p = subprocess.run(cmd, shell=True, cwd=str(worktree), env=env,
                       capture_output=True, text=True, timeout=int(task.get("verify_timeout", 900)))
    return p.returncode, (p.stdout + p.stderr)


def run_task(task: dict, repo_root=None, exec_fn=None,
             allow_llm: bool = False, model: str | None = None) -> dict:
    """Eine Aufgabe in einem eigenen Worktree ausfuehren + bewerten. Nie werfend.

    allow_llm/model: Direktwahl wie in stream_suite/swebench — model setzt KIRA_FORCE_MODEL
    im Sandbox-Env (schlaegt alle Rollen), allow_llm=True erlaubt Cloud-Modelle trotz
    Firewall. Default beides aus -> CLI-Verhalten unveraendert (lokal, 0 EUR)."""
    exec_fn = exec_fn or _default_exec
    tid = str(task.get("id", "task"))
    rid = f"{tid}-{uuid.uuid4().hex[:6]}"  # eindeutiger Branch, keine Kollision bei Wiederholung
    with make_worktree(repo_root=repo_root, run_id=rid, allow_llm=allow_llm, model=model) as (wt, env):
        try:
            _setup(wt, env, task)
            attempt = exec_fn(wt, env, task) or {}
        except Exception as e:  # noqa: BLE001 — ein kaputter Versuch darf die Suite nicht abreissen
            attempt = {"error": str(e)[:300]}
        rc, out = _verify(wt, env, task)
    return {"id": tid, "passed": rc == 0, "verify_rc": rc,
            "verify_out": out[-1500:], "attempt": attempt}


def run_suite(suite, repo_root=None, exec_fn=None,
              allow_llm: bool = False, model: str | None = None) -> dict:
    """Ganze Suite fahren. `suite` = Pfad zu suite.json ODER Liste/Dict mit 'tasks'."""
    if isinstance(suite, (str, Path)):
        suite = json.loads(Path(suite).read_text(encoding="utf-8"))
    tasks = suite.get("tasks", []) if isinstance(suite, dict) else list(suite)
    results = [run_task(t, repo_root=repo_root, exec_fn=exec_fn,
                        allow_llm=allow_llm, model=model) for t in tasks]
    passed = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed, "results": results}


def _load_tasks(suite) -> list[dict]:
    if isinstance(suite, (str, Path)):
        suite = json.loads(Path(suite).read_text(encoding="utf-8"))
    return suite.get("tasks", []) if isinstance(suite, dict) else list(suite)


def _stream_attempt(worktree: Path, env: dict, task: dict):
    """Startet attempt.py und yieldet dessen Denk-/Werkzeug-Ereignisse (@EV) live."""
    proc = subprocess.Popen([sys.executable, "-m", "core.testkit.attempt"],
                            cwd=str(worktree), env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        proc.stdin.write(json.dumps(task))
        proc.stdin.close()
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("@EV "):
                try:
                    yield json.loads(line[4:])
                except Exception:  # noqa: BLE001
                    pass
            # @RESULT wird nicht gestreamt — die Bewertung macht verify_cmd
    finally:
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)


def stream_suite(suite, repo_root=None, allow_llm: bool = True, attempt_fn=None,
                 model: str | None = None):
    """Generator fuer die LIVE-Ansicht im Cockpit: yieldet Ereignis-Dicts —
      {kind:'suite_start', total}
      {kind:'task_start', id, prompt}
      {kind:'act', id, ev}              (Denk-/Werkzeug-Strom von Kira)
      {kind:'task_done', id, passed, rc, out}
      {kind:'summary', passed, total}
    allow_llm=True (Default hier): mit dem ECHTEN Modell testen (Modell-Vergleich), Mail/Telegram
    bleiben geblockt."""
    attempt_fn = attempt_fn or _stream_attempt
    tasks = _load_tasks(suite)
    yield {"kind": "suite_start", "total": len(tasks)}
    passed = 0
    for t in tasks:
        tid = str(t.get("id", "task"))
        yield {"kind": "task_start", "id": tid, "prompt": (t.get("prompt") or "")[:300]}
        rid = f"{tid}-{uuid.uuid4().hex[:6]}"
        try:
            with make_worktree(repo_root=repo_root, run_id=rid, allow_llm=allow_llm,
                               model=model) as (wt, env):
                _setup(wt, env, t)
                for ev in attempt_fn(wt, env, t):
                    yield {"kind": "act", "id": tid, "ev": ev}
                rc, out = _verify(wt, env, t)
        except Exception as e:  # noqa: BLE001
            rc, out = 1, f"[Runner-Fehler] {e}"
        ok = rc == 0
        passed += 1 if ok else 0
        yield {"kind": "task_done", "id": tid, "passed": ok, "rc": rc, "out": out[-800:]}
    yield {"kind": "summary", "passed": passed, "total": len(tasks)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Kira Coding-Benchmark")
    ap.add_argument("--suite", default="tests/bench/suite.json")
    ap.add_argument("--model", default=None,
                    help="Direktwahl: DIESES Modell fuer alle Rollen (KIRA_FORCE_MODEL)")
    ap.add_argument("--allow-llm", action="store_true",
                    help="Cloud-Modelle trotz Sandbox-Firewall erlauben (Budget greift weiter)")
    args = ap.parse_args()
    summary = run_suite(args.suite, allow_llm=args.allow_llm or bool(args.model), model=args.model)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in summary["results"]:
        print(f"  {'✓' if r['passed'] else '✗'} {r['id']} (rc={r['verify_rc']})")
    print(f"\nBenchmark: {summary['passed']}/{summary['total']} bestanden.")


if __name__ == "__main__":
    main()
