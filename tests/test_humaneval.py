"""HumanEval-Adapter: Extraktion, Programmbau, Subprozess-Pruefung und Live-Stream —
komplett offline getestet (Datensatz + Modell gestubbt).
"""
from __future__ import annotations

PROBLEM = {
    "task_id": "HumanEval/0",
    "prompt": "def add(a, b):\n    \"\"\"Addiere zwei Zahlen.\"\"\"\n",
    "entry_point": "add",
    "test": "def check(f):\n    assert f(1, 2) == 3\n    assert f(-1, 1) == 0\n",
}


def test_extract_code_zaun_und_roh():
    from core.testkit import humaneval as he
    assert he.extract_code("bla\n```python\nx = 1\n```\nfertig") == "x = 1"
    assert he.extract_code("```\ny = 2\n```") == "y = 2"
    assert he.extract_code("z = 3") == "z = 3"  # ohne Zaun: rohe Antwort


def test_build_program_voll_und_fortsetzung():
    from core.testkit import humaneval as he
    voll = he.build_program(PROBLEM, "```python\ndef add(a, b):\n    return a + b\n```")
    assert voll.count("def add") == 1 and "check(add)" in voll
    forts = he.build_program(PROBLEM, "```python\n    return a + b\n```")
    assert forts.startswith("def add")  # Prompt vorangestellt


def test_run_program_pass_und_fail():
    from core.testkit import humaneval as he
    ok = he.build_program(PROBLEM, "```python\ndef add(a, b):\n    return a + b\n```")
    schlecht = he.build_program(PROBLEM, "```python\ndef add(a, b):\n    return a - b\n```")
    assert he.run_program(ok) is True
    assert he.run_program(schlecht) is False


def test_stream_humaneval_score(monkeypatch):
    from core.testkit import humaneval as he
    from core.kernel import llm_router
    p2 = dict(PROBLEM, task_id="HumanEval/1")
    monkeypatch.setattr(he, "load_problems", lambda limit=None: [PROBLEM, p2][: limit or 2])
    antworten = iter([
        "```python\ndef add(a, b):\n    return a + b\n```",   # richtig
        "```python\ndef add(a, b):\n    return 42\n```",       # falsch
    ])
    monkeypatch.setattr(llm_router, "complete", lambda msgs, **k: {
        "text": next(antworten), "model": "test-modell", "cost_usd": 0, "fell_back": False,
        "latency_s": 0, "escalated": False, "tool_calls": []})
    evs = list(he.stream_humaneval(limit=2, role="reason"))
    kinds = [e["kind"] for e in evs]
    assert kinds[0] == "suite_start" and kinds[-1] == "summary"
    summ = evs[-1]
    assert summ["passed"] == 1 and summ["total"] == 2 and summ["pass_at_1"] == 50.0


def test_stream_humaneval_llm_fehler_faellt_durch(monkeypatch):
    from core.testkit import humaneval as he
    from core.kernel import llm_router
    monkeypatch.setattr(he, "load_problems", lambda limit=None: [PROBLEM])
    def boom(msgs, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(llm_router, "complete", boom)
    evs = list(he.stream_humaneval(limit=1))
    summ = evs[-1]
    assert summ["passed"] == 0  # Fehler = nicht bestanden, Lauf reisst nicht ab


def test_summary_traegt_modell(monkeypatch):
    from core.testkit import humaneval as he
    from core.kernel import llm_router
    monkeypatch.setattr(he, "load_problems", lambda limit=None: [PROBLEM])
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda role="default", escalate=False: ("openrouter/z-ai/glm-5.2", False))
    monkeypatch.setattr(llm_router, "complete", lambda msgs, **k: {
        "text": "```python\ndef add(a, b):\n    return a + b\n```", "model": "x", "cost_usd": 0,
        "fell_back": False, "latency_s": 0, "escalated": False, "tool_calls": []})
    evs = list(he.stream_humaneval(limit=1, role="reason"))
    assert evs[0]["model"] == "openrouter/z-ai/glm-5.2"       # suite_start
    assert evs[-1]["model"] == "openrouter/z-ai/glm-5.2"      # summary -> Leaderboard


def test_leaderboard_persistenz_und_endpoint(monkeypatch, tmp_path):
    import core.config as cfg
    import core.api.server as s
    from starlette.testclient import TestClient
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    s._bench_record({"suite": "humaneval", "role": "reason"},
                    {"kind": "summary", "suite": "humaneval", "role": "reason",
                     "model": "glm-5.2", "total": 164, "passed": 140, "pass_at_1": 85.4})
    s._bench_record({}, {"kind": "summary", "total": 1, "passed": 1})  # Smoke ohne Modell
    d = TestClient(s.app).get("/api/bench/results").json()
    rs = d["results"]
    assert len(rs) == 2 and rs[0]["total"] == 1               # neueste zuerst
    assert rs[1]["model"] == "glm-5.2" and rs[1]["pass_at_1"] == 85.4


def test_cockpit_hat_leaderboard():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="bench-results"' in html and 'id="bench-copy"' in html
    assert "Leaderboard" in html and "copyBenchResults" in html


def test_cockpit_hat_humaneval_auswahl():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="bench-suite"' in html and 'value="humaneval"' in html
    assert 'id="bench-role"' in html and 'id="bench-limit"' in html
    assert "pass@1" in html


def test_stream_humaneval_direktwahl_modell(monkeypatch):
    """model=... schlaegt die Rolle: complete bekommt das Modell explizit, das
    Leaderboard traegt die Direktwahl."""
    from core.testkit import humaneval as he
    from core.kernel import llm_router
    monkeypatch.setattr(he, "load_problems", lambda limit=None: [PROBLEM])
    seen = {}
    def fake(msgs, **k):
        seen.update(k)
        return {"text": "```python\ndef add(a, b):\n    return a + b\n```", "model": "x",
                "cost_usd": 0, "fell_back": False, "latency_s": 0, "escalated": False,
                "tool_calls": []}
    monkeypatch.setattr(llm_router, "complete", fake)
    evs = list(he.stream_humaneval(limit=1, role="reason", model="openrouter/neu/super-6"))
    assert seen.get("model") == "openrouter/neu/super-6"
    assert evs[0]["model"] == "openrouter/neu/super-6"
    assert evs[-1]["model"] == "openrouter/neu/super-6"


def test_stream_humaneval_initialisiert_db_auf_frischer_wurzel(monkeypatch, tmp_path):
    """Auf einer frischen Datenwurzel (keine events-Tabelle) darf der Lauf nicht VOR dem
    Modell-Call an der Budget-Pruefung sterben — der Score laese sich sonst als 0% des
    Modells, obwohl kein einziger Call stattfand."""
    from core.kernel import events
    from core.testkit import humaneval
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))  # frisch, keine Tabellen
    monkeypatch.setattr(humaneval, "load_problems",
                        lambda limit=None: [{"task_id": "T/0", "prompt": "def f():\n", "test": "", "entry_point": "f"}])
    monkeypatch.setattr(humaneval, "solve", lambda pr, role="reason", model=None: (True, "m"))
    evs = list(humaneval.stream_humaneval(limit=1, model="egal/direkt"))
    assert evs[-1]["passed"] == 1
    # und die Tabelle existiert jetzt wirklich (init_db lief)
    assert events.recent(1) == []
