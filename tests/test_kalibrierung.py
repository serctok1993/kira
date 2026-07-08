"""Selbstkalibrierung (B-025): Nudge-/Fehler-/Fallback-Raten pro Modell — deterministisch."""
from __future__ import annotations

import time

from core.agency import approvals, calibration
from core.kernel import events


def _setup(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (events, approvals):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    approvals.init_approvals()


def _feed(n_calls_a=12, nudges_a=4):
    """Modell A: viele Anrufe + Stupser; Modell B: sauber; plus Task-Signale."""
    for _ in range(n_calls_a):
        events.emit("llm_call", {"model": "deepseek/flash", "task_type": "chat",
                                 "fell_back": False, "escalated": False,
                                 "cost_usd": 0.01, "latency_s": 2.0})
    for _ in range(nudges_a):
        events.emit("nudge", {"model": "deepseek/flash", "task_type": "chat"})
    events.emit("llm_call_error", {"model": "deepseek/flash", "error": "timeout"})
    events.emit("llm_call", {"model": "glm/5.2", "task_type": "reason",
                             "fell_back": True, "escalated": True,
                             "cost_usd": 0.05, "latency_s": 8.0})
    events.emit("model_fallback", {"task_type": "reason", "wanted": "glm/5.2",
                                   "used": "ollama/qwen", "reason": "missing_key"})
    events.emit("task_retry", {"id": "t1", "attempt": 2})
    events.emit("task_scored", {"id": "t1", "verdict": "pass", "strategy": "standard"})
    events.emit("task_scored", {"id": "t2", "verdict": "fail", "strategy": "standard"})
    events.emit("task_failed_final", {"id": "t2"})


def test_rows_since_filtert_und_sortiert(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    events.emit("nudge", {"model": "a"})
    events.emit("llm_call", {"model": "a"})
    events.emit("unrelated", {"x": 1})
    rows = events.rows_since(("nudge", "llm_call"), since_ts=time.time() - 60)
    assert [r["type"] for r in rows] == ["nudge", "llm_call"]  # aelteste zuerst, gefiltert
    assert events.rows_since(("nudge",), since_ts=time.time() + 60) == []
    assert events.rows_since((), since_ts=0) == []


def test_report_aggregiert_pro_modell(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _feed()
    rep = calibration.report(days=7)
    assert rep["total_calls"] == 13
    a = next(m for m in rep["models"] if m["model"] == "deepseek/flash")
    assert a["calls"] == 12 and a["nudges"] == 4 and a["errors"] == 1
    assert a["nudge_rate"] == round(4 / 12, 3)
    assert a["avg_latency_s"] == 2.0 and a["cost_usd"] == 0.12
    b = next(m for m in rep["models"] if m["model"] == "glm/5.2")
    assert b["fallback_rate"] == 1.0 and b["escalated"] == 1
    assert rep["strategies"]["standard"] == {"attempts": 2, "passed": 1, "pass_rate": 0.5}
    assert rep["task_retries"] == 1 and rep["tasks_failed"] == 1
    assert rep["fallbacks"] == {"reason wollte glm/5.2": 1}


def test_render_leer_und_mit_empfehlung(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert "nichts zu kalibrieren" in calibration.render(days=7)
    _feed(n_calls_a=12, nudges_a=4)  # nudge_rate 0.33 > 0.2 bei calls >= MIN_CALLS
    txt = calibration.render(days=7)
    assert "SELBSTKALIBRIERUNG" in txt and "deepseek/flash" in txt
    assert "EMPFEHLUNGEN" in txt and "kuendigt oft nur an" in txt


def test_propose_braucht_genug_daten(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _feed(n_calls_a=5, nudges_a=0)  # 6 Anrufe gesamt < 25
    assert calibration.propose(days=7, min_calls=25) is None
    assert approvals.pending() == []

    _feed(n_calls_a=30, nudges_a=8)
    aid = calibration.propose(days=7, min_calls=25)
    assert aid
    pend = approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "generic"
    assert "Selbstkalibrierungs-Report" in pend[0]["title"]
    assert "EMPFEHLUNGEN" in pend[0]["detail"]
    assert any(e["type"] == "calibration_report" for e in events.recent(10))


def test_api_kalibrierung(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import core.api.server as s
    _setup(monkeypatch, tmp_path)
    _feed()
    d = TestClient(s.app).get("/api/kalibrierung?days=7").json()
    assert d["total_calls"] == 13 and "SELBSTKALIBRIERUNG" in d["text"]
    assert any(m["model"] == "deepseek/flash" for m in d["models"])
    d1 = TestClient(s.app).get("/api/kalibrierung?days=999").json()
    assert d1["days"] == 90  # geklemmt


def test_cockpit_zeigt_kalibrierung():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="ck-kalib"' in html and "/api/kalibrierung" in html
