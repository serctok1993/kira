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


def test_stream_suite_streamt_ereignisse():
    """Der Live-Generator liefert Start/Denk-Strom/Ergebnis/Endstand — ohne echtes Modell
    (attempt_fn injiziert)."""
    from core.testkit import bench
    fake_attempt = lambda wt, env, t: iter(  # noqa: E731
        [{"kind": "think", "text": "ich denke nach"}, {"kind": "tool", "name": "edit_datei"}])
    suite = {"tasks": [
        {"id": "a", "prompt": "mach was", "verify_cmd": "python -c \"import sys;sys.exit(0)\""},
        {"id": "b", "prompt": "und das", "verify_cmd": "python -c \"import sys;sys.exit(1)\""},
    ]}
    evs = list(bench.stream_suite(suite, attempt_fn=fake_attempt))
    kinds = [e["kind"] for e in evs]
    assert kinds[0] == "suite_start" and kinds[-1] == "summary"
    assert "task_start" in kinds and "act" in kinds and "task_done" in kinds
    # der Denk-Strom kommt durch
    assert any(e["kind"] == "act" and e["ev"].get("text") == "ich denke nach" for e in evs)
    summ = evs[-1]
    assert summ["total"] == 2 and summ["passed"] == 1  # a besteht, b faellt


def test_sandbox_allow_llm_setzt_env():
    from core.testkit import sandbox
    e_off = sandbox.sandbox_env("/tmp/x", allow_llm=False)
    e_on = sandbox.sandbox_env("/tmp/x", allow_llm=True)
    assert "KIRA_ALLOW_LLM" not in e_off
    assert e_on["KIRA_ALLOW_LLM"] == "1" and e_on["KIRA_NO_OUTBOUND"] == "1"


def test_cockpit_hat_benchmark_tab():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="v-bench"' in html and 'id="bench-start"' in html
    assert "loadBench" in html and "/ws/bench" in html
