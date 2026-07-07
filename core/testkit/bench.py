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


def _verify(worktree: Path, env: dict, task: dict) -> tuple[int, str]:
    cmd = task.get("verify_cmd")
    if not cmd:
        return 0, "(kein verify_cmd — nur Ausfuehrung, keine Bewertung)"
    p = subprocess.run(cmd, shell=True, cwd=str(worktree), env=env,
                       capture_output=True, text=True, timeout=int(task.get("verify_timeout", 900)))
    return p.returncode, (p.stdout + p.stderr)


def run_task(task: dict, repo_root=None, exec_fn=None) -> dict:
    """Eine Aufgabe in einem eigenen Worktree ausfuehren + bewerten. Nie werfend."""
    exec_fn = exec_fn or _default_exec
    tid = str(task.get("id", "task"))
    rid = f"{tid}-{uuid.uuid4().hex[:6]}"  # eindeutiger Branch, keine Kollision bei Wiederholung
    with make_worktree(repo_root=repo_root, run_id=rid) as (wt, env):
        try:
            attempt = exec_fn(wt, env, task) or {}
        except Exception as e:  # noqa: BLE001 — ein kaputter Versuch darf die Suite nicht abreissen
            attempt = {"error": str(e)[:300]}
        rc, out = _verify(wt, env, task)
    return {"id": tid, "passed": rc == 0, "verify_rc": rc,
            "verify_out": out[-1500:], "attempt": attempt}


def run_suite(suite, repo_root=None, exec_fn=None) -> dict:
    """Ganze Suite fahren. `suite` = Pfad zu suite.json ODER Liste/Dict mit 'tasks'."""
    if isinstance(suite, (str, Path)):
        suite = json.loads(Path(suite).read_text(encoding="utf-8"))
    tasks = suite.get("tasks", []) if isinstance(suite, dict) else list(suite)
    results = [run_task(t, repo_root=repo_root, exec_fn=exec_fn) for t in tasks]
    passed = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed, "results": results}


def main() -> None:
    ap = argparse.ArgumentParser(description="Kira Coding-Benchmark")
    ap.add_argument("--suite", default="tests/bench/suite.json")
    args = ap.parse_args()
    summary = run_suite(args.suite)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in summary["results"]:
        print(f"  {'✓' if r['passed'] else '✗'} {r['id']} (rc={r['verify_rc']})")
    print(f"\nBenchmark: {summary['passed']}/{summary['total']} bestanden.")


if __name__ == "__main__":
    main()
