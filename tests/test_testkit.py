"""Testkit: die Worktree-Sandbox isoliert einen Lauf vollstaendig vom Live-Repo, und der
Benchmark-Runner faehrt eine Suite + bewertet sie ueber verify_cmd.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_worktree_isoliert_und_raeumt_auf():
    from core.testkit import sandbox
    root = sandbox._repo_root()
    before = {ln for ln in subprocess.run(
        ["git", "-C", str(root), "branch", "--list", "bench/*"],
        capture_output=True, text=True).stdout.splitlines()}

    with sandbox.make_worktree(run_id="unittest") as (wt, env):
        assert Path(wt).exists()
        # Ein Subprozess IM Worktree sieht die Datenpfade in der Sandbox (env vor core-Import)
        r = subprocess.run([sys.executable, "-c", "import core.config as c; print(c.DB_PATH)"],
                           cwd=str(wt), env=env, capture_output=True, text=True)
        assert str(wt) in r.stdout, r.stdout + r.stderr
        # Firewall-Env ist scharf
        assert env["KIRA_NO_OUTBOUND"] == "1" and env["KIRA_TEST_MODE"] == "1"

    # nach dem Block: Worktree weg, kein neuer bench/-Branch uebrig
    assert not Path(wt).exists()
    after = {ln for ln in subprocess.run(
        ["git", "-C", str(root), "branch", "--list", "bench/*"],
        capture_output=True, text=True).stdout.splitlines()}
    assert after == before


def test_run_suite_bewertet_ueber_verify():
    from core.testkit import bench
    stub = lambda wt, env, task: {"stub": True}  # kein echtes act -> kein Modell noetig  # noqa: E731
    suite = {"tasks": [
        {"id": "pass", "verify_cmd": "python -c \"import sys; sys.exit(0)\""},
        {"id": "fail", "verify_cmd": "python -c \"import sys; sys.exit(1)\""},
    ]}
    summary = bench.run_suite(suite, exec_fn=stub)
    assert summary["total"] == 2 and summary["passed"] == 1
    by = {r["id"]: r["passed"] for r in summary["results"]}
    assert by == {"pass": True, "fail": False}


def test_suite_json_wohlgeformt():
    from core.config import ROOT
    import json
    data = json.loads((ROOT / "tests" / "bench" / "suite.json").read_text(encoding="utf-8"))
    assert data["tasks"] and all("id" in t and "verify_cmd" in t for t in data["tasks"])
