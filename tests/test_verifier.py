"""Stufe 2b: Pruefer — offline, LLM per monkeypatch gefakt, kein Netz."""
from __future__ import annotations

import json

from core.agency import verifier
from core.agency.missions import queue
from core.kernel import events, llm_router


def _use_tmp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (queue, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()  # verifier.emit() setzt die events-Tabelle voraus (wie im Runner-Start)
    return db


def _fake_complete(text: str):
    """Fabrik: llm_router.complete-Fake mit voller Dict-Form + Aufruf-Zaehler."""
    calls = []

    def fake(messages, system=None, task_type="chat", session_id=None, escalate=False, tools=None):
        calls.append({"task_type": task_type, "user": messages[-1]["content"]})
        return {"text": text, "cost_usd": 0.001, "model": "fake", "fell_back": False,
                "latency_s": 0.0, "escalated": False, "tool_calls": []}

    fake.calls = calls
    return fake


# --- Kriterien ---------------------------------------------------------------

def test_generate_criteria_parses_json(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    fake = _fake_complete('Hier: ["Nennt 3 Quellen mit URL", "Enthaelt Preisspanne in EUR"]')
    monkeypatch.setattr(llm_router, "complete", fake)
    crit = verifier.generate_criteria("Recherchiere Hosting-Preise", "research")
    assert [c["text"] for c in crit] == ["Nennt 3 Quellen mit URL", "Enthaelt Preisspanne in EUR"]


def test_generate_criteria_fallback_on_garbage_and_exception(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_router, "complete", _fake_complete("kein json hier"))
    crit = verifier.generate_criteria("egal", "produce")
    assert crit == verifier._DEFAULT_CRITERIA["produce"]

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm_router, "complete", boom)
    crit = verifier.generate_criteria("egal", "publish")
    assert crit == verifier._DEFAULT_CRITERIA["publish"]
    # unbekannte Art -> research-Fallback
    assert verifier.generate_criteria("egal", "unbekannt") == verifier._DEFAULT_CRITERIA["research"]


def test_ensure_criteria_caches_in_task(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    queue.init_queue()
    tid = queue.add("Recherchiere X", kind="research")
    fake = _fake_complete('["Kriterium A ist erfuellt", "Kriterium B ist erfuellt"]')
    monkeypatch.setattr(llm_router, "complete", fake)

    crit1 = verifier.ensure_criteria(queue.get_task(tid))
    assert len(fake.calls) == 1
    assert json.loads(queue.get_task(tid)["acceptance"]) == crit1

    # zweiter Aufruf: aus dem Cache, KEIN weiterer LLM-Call (stabile Torpfosten)
    crit2 = verifier.ensure_criteria(queue.get_task(tid))
    assert crit2 == crit1
    assert len(fake.calls) == 1


# --- Harte Checks ------------------------------------------------------------

def test_empty_result_fails_hard_without_judge(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    fake = _fake_complete("{}")
    monkeypatch.setattr(llm_router, "complete", fake)
    out = verifier.verify({"id": "t", "kind": "research"}, [{"text": "egal"}], "   ")
    assert out["verdict"] == "retry" and out["score"] == 10
    assert fake.calls == []  # Judge wurde gespart


def test_degrade_marker_fails_hard_without_judge(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    fake = _fake_complete("{}")
    monkeypatch.setattr(llm_router, "complete", fake)
    text = verifier._DEGRADE_MARKER + " auf einen Fehler gestossen ... " + "x" * 100
    out = verifier.verify({"id": "t", "kind": "research"}, [{"text": "egal"}], text)
    assert out["verdict"] == "retry"
    assert fake.calls == []
    assert "Degrade" in out["feedback"]


def test_produce_artifact_checks(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    good = tmp_path / "gut.py"
    good.write_text("x = 1\n", encoding="utf-8")
    bad = tmp_path / "kaputt.py"
    bad.write_text("def f(:\n", encoding="utf-8")

    checks = verifier.deterministic_checks(
        {"kind": "produce", "artifact_path": str(good)}, "Datei erstellt: " + str(good))
    assert all(c["ok"] for c in checks)

    checks = verifier.deterministic_checks(
        {"kind": "produce", "artifact_path": str(bad)}, "Datei erstellt: " + str(bad))
    compile_check = [c for c in checks if "kompiliert" in c["text"]][0]
    assert compile_check["ok"] is False

    checks = verifier.deterministic_checks(
        {"kind": "produce", "artifact_path": str(tmp_path / "fehlt.py")}, "Datei angeblich da " * 5)
    missing = [c for c in checks if "existiert" in c["text"]][0]
    assert missing["ok"] is False


def test_publish_url_check_monkeypatched(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(verifier, "_url_reachable", lambda url: (True, "HTTP 200"))
    checks = verifier.deterministic_checks(
        {"kind": "publish"}, "Veroeffentlicht unter https://example.com/post-1 wie geplant." + "x" * 20)
    url_check = [c for c in checks if "URL" in c["text"]][0]
    assert url_check["ok"] is True

    checks = verifier.deterministic_checks({"kind": "publish"}, "Habe es irgendwo veroeffentlicht, ehrlich." * 3)
    url_check = [c for c in checks if "URL" in c["text"]][0]
    assert url_check["ok"] is False  # keine URL genannt


# --- Judge -------------------------------------------------------------------

def test_judge_pass_and_retry(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    crit = [{"text": "Nennt 3 Quellen"}, {"text": "Klare Empfehlung"}]
    result = "Quellen: a.com, b.com, c.com. Empfehlung: Anbieter B, weil guenstiger." + "x" * 50

    good = _fake_complete('{"criteria":[{"ok":true,"why":"3 Quellen"},{"ok":true,"why":"klar"}],'
                          '"score":85,"verdict":"pass","feedback":""}')
    monkeypatch.setattr(llm_router, "complete", good)
    out = verifier.verify({"id": "t", "kind": "research"}, crit, result)
    assert out["verdict"] == "pass" and out["score"] == 85
    assert len([c for c in out["checks"] if c["source"] == "llm"]) == 2

    weak = _fake_complete('{"criteria":[{"ok":false,"why":"nur 1 Quelle"},{"ok":true,"why":"ok"}],'
                          '"score":45,"verdict":"retry","feedback":"Suche 2 weitere Quellen"}')
    monkeypatch.setattr(llm_router, "complete", weak)
    out = verifier.verify({"id": "t", "kind": "research"}, crit, result)
    assert out["verdict"] == "retry" and out["score"] == 45
    assert out["feedback"] == "Suche 2 weitere Quellen"


def test_judge_garbage_fails_open(monkeypatch, tmp_path):
    db = _use_tmp_db(monkeypatch, tmp_path)
    events.init_db()
    monkeypatch.setattr(llm_router, "complete", _fake_complete("Ich bin heute kein JSON."))
    out = verifier.verify({"id": "t", "kind": "research"}, [{"text": "egal"}], "Ein substanzielles Ergebnis. " * 5)
    assert out["verdict"] == "pass" and out["score"] is None  # fail-open
    assert any(e["type"] == "verify_error" for e in events.recent(10))
