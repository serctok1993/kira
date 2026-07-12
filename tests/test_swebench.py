"""SWE-bench-Lite-Adapter: Checkout ueber Bare-Spiegel, Patch-Sammlung, Prognose,
predictions.jsonl und Live-Stream — komplett offline (lokales Fake-GitHub, Agent gestubbt).
"""
from __future__ import annotations

import json
import subprocess


def _mk_repo(tmp_path):
    """Ein lokales 'GitHub'-Repo mit einem Commit — dient als Fetch-Quelle."""
    src = tmp_path / "github" / "demo"
    src.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    (src / "modul.py").write_text("def kaputt():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=src, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
                   cwd=src, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src,
                         capture_output=True, text=True, check=True).stdout.strip()
    return src, sha


def _sandbox(monkeypatch, tmp_path, src):
    from core import config
    from core.testkit import swebench as swb
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(swb, "_repo_url", lambda repo: str(src))
    return swb


def test_checkout_ueber_spiegel_und_cache(monkeypatch, tmp_path):
    src, sha = _mk_repo(tmp_path)
    swb = _sandbox(monkeypatch, tmp_path, src)
    dest = tmp_path / "wd1"
    swb.checkout("demo/demo", sha, dest)
    assert (dest / "modul.py").exists()
    # zweiter Checkout nutzt den Spiegel (kein erneuter Remote-Fetch noetig)
    dest2 = tmp_path / "wd2"
    swb.checkout("demo/demo", sha, dest2)
    assert (dest2 / "modul.py").exists()
    assert (tmp_path / "data" / "bench" / "repos" / "demo__demo.git").exists()


def test_collect_patch_und_prognose(monkeypatch, tmp_path):
    src, sha = _mk_repo(tmp_path)
    swb = _sandbox(monkeypatch, tmp_path, src)
    wd = tmp_path / "wd"
    swb.checkout("demo/demo", sha, wd)
    (wd / "modul.py").write_text("def kaputt():\n    return 2\n", encoding="utf-8")
    (wd / "neu.py").write_text("x = 1\n", encoding="utf-8")  # neue Datei zaehlt mit
    patch = swb.collect_patch(wd)
    assert "modul.py" in patch and "neu.py" in patch
    gold = "diff --git a/modul.py b/modul.py\n--- a/modul.py\n+++ b/modul.py\n"
    ok, info = swb.prognose(patch, gold)
    assert ok and "modul.py" in info
    ok2, info2 = swb.prognose(patch, "diff --git a/andere.py b/andere.py\n")
    assert not ok2 and "keine Gold-Datei" in info2
    ok3, info3 = swb.prognose("", gold)
    assert not ok3 and "kein Patch" in info3


def test_load_tasks_aus_cache(monkeypatch, tmp_path):
    from core import config
    from core.testkit import swebench as swb
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    cache = tmp_path / "bench"
    cache.mkdir(parents=True)
    rows = [{"instance_id": f"demo-{i}", "repo": "d/d", "base_commit": "abc",
             "problem_statement": "Bug", "patch": ""} for i in range(5)]
    (cache / "swebench_lite.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert len(swb.load_tasks()) == 5
    assert len(swb.load_tasks(limit=2)) == 2
    assert swb.load_tasks(limit=2)[0]["instance_id"] == "demo-0"


def test_stream_swebench_ende_zu_ende_offline(monkeypatch, tmp_path):
    src, sha = _mk_repo(tmp_path)
    swb = _sandbox(monkeypatch, tmp_path, src)
    gold = "diff --git a/modul.py b/modul.py\n"
    monkeypatch.setattr(swb, "load_tasks", lambda limit=None: [{
        "instance_id": "demo-1", "repo": "demo/demo", "base_commit": sha,
        "problem_statement": "kaputt() liefert 1 statt 2", "patch": gold}])
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda role="default", escalate=False: ("test-modell", False))

    def fake_agent(wd, task, allow_llm=True, model=None):
        (wd / "modul.py").write_text("def kaputt():\n    return 2\n", encoding="utf-8")
        yield {"type": "tool_call", "payload": {"tool": "edit_datei"}}
    evs = list(swb.stream_swebench(limit=1, agent_fn=fake_agent))
    kinds = [e["kind"] for e in evs]
    assert kinds[0] == "suite_start" and "act" in kinds and kinds[-1] == "summary"
    summ = evs[-1]
    assert summ["suite"] == "swebench" and summ["passed"] == 1 and summ["model"] == "test-modell"
    assert "PROGNOSE" in summ["note"]
    # predictions.jsonl im offiziellen Format geschrieben
    preds = (tmp_path / "data" / "bench" / "swebench-predictions.jsonl").read_text(encoding="utf-8")
    row = json.loads(preds.strip().splitlines()[-1])
    assert row["instance_id"] == "demo-1" and row["model_name_or_path"] == "kira+test-modell"
    assert "modul.py" in row["model_patch"]


def test_stream_swebench_agent_crash_reisst_nicht_ab(monkeypatch, tmp_path):
    src, sha = _mk_repo(tmp_path)
    swb = _sandbox(monkeypatch, tmp_path, src)
    monkeypatch.setattr(swb, "load_tasks", lambda limit=None: [{
        "instance_id": "demo-2", "repo": "demo/demo", "base_commit": sha,
        "problem_statement": "x", "patch": ""}])
    def boom(wd, task, allow_llm=True, model=None):
        raise RuntimeError("agent tot")
        yield  # pragma: no cover
    evs = list(swb.stream_swebench(limit=1, agent_fn=boom))
    summ = evs[-1]
    assert summ["kind"] == "summary" and summ["passed"] == 0


def test_cockpit_hat_swebench_auswahl():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'value="swebench"' in html and "SWE-bench Lite" in html


def test_ws_bench_kennt_swebench():
    import inspect
    import core.api.server as s
    src = inspect.getsource(s.ws_bench)
    assert "swebench" in src and "stream_swebench" in src


# --- Fixes nach des Nutzers 0/40-Lauf (Lauf 1 war systematisch kaputt) -----------
def test_agent_env_laesst_kira_root_in_ruhe(monkeypatch):
    """0%-Ursache 1: KIRA_ROOT zeigte aufs Fremd-Repo -> Subprozess starb beim Import
    (config.yaml/core/mind fehlen dort). Jetzt: ROOT bleibt Kiras Repo, nur Daten umgelenkt."""
    import shutil
    from core.testkit import swebench as swb
    monkeypatch.setenv("KIRA_ROOT", "/sollte/verschwinden")
    env = swb._agent_env(allow_llm=False)
    try:
        assert "KIRA_ROOT" not in env
        assert env["KIRA_TEST_MODE"] == "1" and env["KIRA_NO_OUTBOUND"] == "1"
        assert "KIRA_ALLOW_LLM" not in env and env["KIRA_DATA_DIR"]
        assert env["KIRA_RANK_FLOOR"] == "reason"   # kein Schritt faellt auf reflex/lokal
    finally:
        shutil.rmtree(env["KIRA_DATA_DIR"], ignore_errors=True)


def test_rank_floor_hebt_reflex_schritte(monkeypatch):
    """Mit KIRA_RANK_FLOOR=reason laeuft im Plan-Dispatcher kein Schritt mehr auf
    classify/worker — der Boden greift VOR dem Code-Guard (Quelle: act.py-Dispatcher)."""
    import inspect
    from core.agency import act
    src = inspect.getsource(act.plan_and_execute)
    assert "KIRA_RANK_FLOOR" in src


def test_run_agent_hat_lebenszeichen_und_timeout():
    """'Haengt er oder denkt er?': stiller Subprozess liefert alle ~25s ein
    Lebenszeichen-Event, und nach 'timeout' wird hart gekillt."""
    import inspect
    from core.testkit import swebench as swb
    src = inspect.getsource(swb._run_agent)
    assert "arbeitet noch" in src and "proc.kill()" in src and "Timeout" in src


def test_agent_payload_ohne_kira_endabnahme_und_mit_repo_pfad():
    """0%-Ursache 2: Kiras Testsuite-Endabnahme war im Fremd-Repo immer rot und rollte
    den fertigen Patch zurueck. SWE-bench laeuft ohne code_review; der Prompt nennt
    den relativen Repo-Pfad und verbietet Aenderungen ausserhalb."""
    import inspect
    from core.testkit import swebench as swb
    src = inspect.getsource(swb._run_agent)
    assert '"code_review": False' in src
    assert "AUSSCHLIESSLICH" in swb._PROMPT and "{repo}" in swb._PROMPT
    from core.testkit import attempt
    assert 'task.get("code_review", True)' in inspect.getsource(attempt.main)


def test_leaderboard_beschriftet_swebench_richtig():
    """Anzeige-Bug: swebench-Laeufe hiessen im Leaderboard 'Smoke'."""
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'SWE-bench*' in html and "suiteName" in html
    assert "ev.out" in html  # Fehl-Grund je Aufgabe sichtbar im Live-Verlauf


# --- Modell-Direktwahl (des Nutzers Wunsch: beliebige IDs testen, auch kuenftige) --
def test_force_model_schlaegt_alle_rollen(monkeypatch):
    from core.kernel import llm_router
    monkeypatch.setenv("KIRA_FORCE_MODEL", "openrouter/zukunft/super-5")
    assert llm_router.resolve_model("reason") == ("openrouter/zukunft/super-5", False)
    assert llm_router.resolve_model("classify", escalate=True) == ("openrouter/zukunft/super-5", False)
    monkeypatch.delenv("KIRA_FORCE_MODEL")
    m, _ = llm_router.resolve_model("reason")
    assert m != "openrouter/zukunft/super-5"  # ohne Env: normale Rollen-Aufloesung


def test_swebench_env_traegt_direktwahl(monkeypatch):
    import shutil
    from core.testkit import swebench as swb
    env = swb._agent_env(allow_llm=False, model="openrouter/neu/modell-x")
    try:
        assert env["KIRA_FORCE_MODEL"] == "openrouter/neu/modell-x"
    finally:
        shutil.rmtree(env["KIRA_DATA_DIR"], ignore_errors=True)


def test_cockpit_hat_modell_direktwahl():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="bench-model-pick"' in html and 'id="bench-model-list"' in html
    assert "Gemessen wird" in html  # ehrliche Anzeige statt Chat-Modell


def test_api_model_resolve(monkeypatch):
    from fastapi.testclient import TestClient
    import core.api.server as s
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda role="default", escalate=False: ("openrouter/z-ai/glm-5.2", False))
    d = TestClient(s.app).get("/api/model/resolve?role=reason").json()
    assert d["model"] == "openrouter/z-ai/glm-5.2" and d["fallback"] is False
