"""Werkbank PR 1 — Loesch-Grundausstattung: Bench-/Skill-/Metrik-Loeschen.
Rein additiv, alles offline. (W1: Venture-/Radar-Loesch-Tests sind mit dem
Business-Strang ausgebaut worden.)"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import core.api.server as s
from core.agency.missions import metrics
from core.kernel import events


def _db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (metrics, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()


# ---------- Metriken ----------

def test_metrics_delete_entfernt_werte_und_meta(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    metrics.log("gewicht", 91.4)
    metrics.log("gewicht", 91.0)
    metrics.set_meta("gewicht", target=85, unit="kg")
    metrics.log("schlaf", 7)
    assert metrics.delete("Gewicht")                   # case-insensitiv (normalisiert)
    assert "gewicht" not in metrics.names()
    assert "schlaf" in metrics.names()                 # andere bleiben
    assert not metrics.delete("gewicht")               # schon weg
    assert not metrics.delete("")


# ---------- Benchmark-Leaderboard ----------

def test_api_bench_delete_filtert_jsonl(monkeypatch, tmp_path):
    import core.config as _c
    monkeypatch.setattr(_c, "DATA_DIR", tmp_path)
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    p = tmp_path / "bench"
    p.mkdir()
    rows = [{"ts": 1000.0, "suite": "humaneval", "model": "a", "pass_at_1": 90},
            {"ts": 2000.0, "suite": "swebench", "model": "b", "pass_at_1": 10}]
    (p / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    cl = TestClient(s.app)
    r = cl.post("/api/bench/delete", json={"ts": 2000.0}).json()
    assert r["ok"] and r["removed"] == 1
    rest = cl.get("/api/bench/results").json()["results"]
    assert len(rest) == 1 and rest[0]["model"] == "a"
    assert not cl.post("/api/bench/delete", json={"ts": 9999.0}).json()["ok"]
    assert not cl.post("/api/bench/delete", json={}).json()["ok"]


# ---------- Evolution: Lektionen mit ids ----------

def test_evolution_liefert_loeschbare_lektionen(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    from core.mind.memory import store as memory
    monkeypatch.setattr(memory, "all_skills", lambda: [{"id": "s1", "text": "Skill X"}])
    monkeypatch.setattr(memory, "all_lessons", lambda: [{"id": "l1", "text": "Lektion Y"}])
    d = TestClient(s.app).get("/api/evolution").json()
    assert d["skills"][0]["id"] == "s1"
    assert d["lessons"][0] == {"id": "l1", "text": "Lektion Y"}    # ids statt nackter Strings


# ---------- UI traegt die Knoepfe ----------

def test_cockpit_hat_loesch_knoepfe():
    html = TestClient(s.app).get("/").text
    for marker in ("/api/bench/delete", "data-zdel", "/api/metrics/delete", "data-mdel"):
        assert marker in html, f"fehlt im Cockpit: {marker}"
