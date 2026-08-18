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
        {"id": "pass", "verify_cmd": sys.executable + " -c \"import sys; sys.exit(0)\""},
        {"id": "fail", "verify_cmd": sys.executable + " -c \"import sys; sys.exit(1)\""},
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
        {"id": "a", "prompt": "mach was", "verify_cmd": sys.executable + " -c \"import sys;sys.exit(0)\""},
        {"id": "b", "prompt": "und das", "verify_cmd": sys.executable + " -c \"import sys;sys.exit(1)\""},
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


def test_sandbox_model_direktwahl_setzt_force_model():
    """model= reicht KIRA_FORCE_MODEL in den Sandbox-Env durch (gleiche Semantik wie
    swebench._agent_env) — vorher erbte der Coding-Bench stur die Live-Rollen aus
    config.yaml und war als Modell-Pruefstand unbrauchbar. Ohne model verschwindet ein
    geerbter Wert (kein Durchsickern aus der Eltern-Umgebung in einen Lauf ohne Wahl)."""
    import os
    from unittest import mock
    from core.testkit import sandbox
    e = sandbox.sandbox_env("/tmp/x", allow_llm=True, model="openrouter/neu/modell-x")
    assert e["KIRA_FORCE_MODEL"] == "openrouter/neu/modell-x"
    with mock.patch.dict(os.environ, {"KIRA_FORCE_MODEL": "geerbt/alt"}):
        e_ohne = sandbox.sandbox_env("/tmp/x", allow_llm=True)
    assert "KIRA_FORCE_MODEL" not in e_ohne


def test_run_suite_reicht_model_in_den_worktree():
    """run_suite(model=...) landet als KIRA_FORCE_MODEL im Env des Versuchs-Subprozesses."""
    from core.testkit import bench
    gesehen = {}
    def stub(wt, env, task):
        gesehen[task["id"]] = (env.get("KIRA_FORCE_MODEL"), env.get("KIRA_ALLOW_LLM"))
        return {"stub": True}
    suite = {"tasks": [{"id": "t1", "verify_cmd": sys.executable + " -c \"import sys;sys.exit(0)\""}]}
    bench.run_suite(suite, exec_fn=stub, allow_llm=True, model="openrouter/zukunft/super-5")
    assert gesehen["t1"] == ("openrouter/zukunft/super-5", "1")


def test_setup_cmd_laeuft_vor_dem_versuch():
    """setup_cmd legt Material in den Worktree, BEVOR der Versuch startet (z.B. die kaputte
    Datei, die die Aufgabe reparieren soll) — und verify sieht denselben Zustand."""
    from core.testkit import bench
    gesehen = {}
    def stub(wt, env, task):
        gesehen["vorher_da"] = (Path(wt) / "material.txt").exists()
        return {"stub": True}
    suite = {"tasks": [{
        "id": "s1",
        "setup_cmd": "printf 'da' > material.txt",
        "verify_cmd": sys.executable + " -c \"import sys;sys.exit(0 if open('material.txt').read()=='da' else 1)\"",
    }]}
    summary = bench.run_suite(suite, exec_fn=stub)
    assert gesehen["vorher_da"] is True
    assert summary["passed"] == 1


def test_setup_material_ueberlebt_run_rollback():
    """Die Endabnahme rollt einen roten Lauf per git reset --hard zurueck. Material aus
    setup_cmd muss das ueberleben (committet), sonst liest sich 'Datei weg' als
    Modellversagen statt als 'Aufgabe nicht geloest'."""
    import subprocess as sp
    from core.testkit import bench
    def stub(wt, env, task):
        # Kiras Lauf: committet einen (kaputten) Edit, Endabnahme rollt ALLES auf den
        # Stand vor dem Versuch zurueck — exakt das reset --hard aus act._endabnahme.
        (Path(wt) / "material.txt").write_text("kaputter edit", encoding="utf-8")
        sp.run(["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-am", "edit"], capture_output=True)
        sp.run(["git", "-C", str(wt), "reset", "--hard", "HEAD~1"], capture_output=True)
        return {"stub": True}
    suite = {"tasks": [{
        "id": "s2",
        "setup_cmd": "printf 'original' > material.txt",
        "verify_cmd": sys.executable + " -c \"import sys;sys.exit(0 if open('material.txt').read()=='original' else 1)\"",
    }]}
    summary = bench.run_suite(suite, exec_fn=stub)
    assert summary["passed"] == 1, summary["results"][0]
