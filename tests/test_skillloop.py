"""Skill-Automatik (Hermes-Lernkreis): destillieren -> Skeptiker -> speichern.
Komplett offline: LLM gestubbt, Temp-DB, Temp-Wartungszustand.
"""
from __future__ import annotations

import json


def _setup(monkeypatch, tmp_path, antworten):
    """Sandbox: Guards oeffnen, LLM stubben, Memory + Zaehler auf tmp umbiegen."""
    from core import config
    from core.kernel import llm_router, events
    from core.mind.memory import store
    from core.agency.missions import maintenance

    monkeypatch.setattr(config, "test_mode", lambda: False)
    monkeypatch.setattr(config, "outbound_blocked", lambda: False)
    db = str(tmp_path / "state.db")
    monkeypatch.setattr(store, "DB_PATH", db, raising=False)
    monkeypatch.setattr(events, "DB_PATH", db, raising=False)
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    store.init_memory()
    events.init_db()  # memory.remember emittiert memory_add -> braucht die events-Tabelle
    it = iter(antworten)
    calls = []
    def fake(msgs, **k):
        calls.append({"prompt": msgs[0]["content"], **k})
        return {"text": next(it), "model": "stub", "cost_usd": 0, "fell_back": False,
                "latency_s": 0, "escalated": False, "tool_calls": []}
    monkeypatch.setattr(llm_router, "complete", fake)
    return store, calls


def test_lernt_skill_wenn_skeptiker_ja_sagt(monkeypatch, tmp_path):
    from core.mind import skillloop
    store, calls = _setup(monkeypatch, tmp_path, [
        "NAME: Impressum-Recherche\nSCHRITTE: 1. Site suchen 2. /impressum laden 3. Mail extrahieren",
        "JA — wiederverwendbar und plausibel."])
    r = skillloop.maybe_learn("Finde Kontakt von Firma X", "Mail gefunden: x@y.de",
                              attempt=2, duration_s=30, criteria=[], score=90)
    assert r and r["name"] == "Impressum-Recherche"
    assert len(calls) == 2
    assert calls[0]["task_type"] == "bulk" and calls[1]["task_type"] == "reason"  # billig destillieren, Denker richtet
    sk = store.recall_skills()
    assert any("Impressum-Recherche" in s for s in sk)


def test_skeptiker_nein_blockt_speicherung(monkeypatch, tmp_path):
    from core.mind import skillloop
    store, _ = _setup(monkeypatch, tmp_path, [
        "NAME: Trivialitaet\nSCHRITTE: Google benutzen",
        "NEIN: das weiss jedes Modell ohnehin."])
    r = skillloop.maybe_learn("x", "y", attempt=3, duration_s=200, criteria=[], score=95)
    assert r is None
    assert store.recall_skills() == []


def test_none_destillat_speichert_nichts(monkeypatch, tmp_path):
    from core.mind import skillloop
    store, calls = _setup(monkeypatch, tmp_path, ["NONE"])
    assert skillloop.maybe_learn("x", "y", attempt=2, duration_s=10, criteria=[], score=90) is None
    assert len(calls) == 1  # Skeptiker wird gar nicht erst gerufen
    assert store.recall_skills() == []


def test_leichte_tasks_und_schlechte_scores_lernen_nicht(monkeypatch, tmp_path):
    from core.mind import skillloop
    _, calls = _setup(monkeypatch, tmp_path, [])
    # leicht: 1 Versuch, kurz, wenig Kriterien
    assert skillloop.maybe_learn("x", "y", attempt=1, duration_s=5, criteria=[], score=95) is None
    # schwer, aber Score zu niedrig
    assert skillloop.maybe_learn("x", "y", attempt=3, duration_s=500, criteria=[], score=60) is None
    # Score fehlt (Judge ausgefallen)
    assert skillloop.maybe_learn("x", "y", attempt=3, duration_s=500, criteria=[], score=None) is None
    assert calls == []  # kein einziger LLM-Aufruf


def test_testmodus_und_firewall_lernen_nie(monkeypatch, tmp_path):
    from core.mind import skillloop
    from core import config
    _, calls = _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(config, "test_mode", lambda: True)
    assert skillloop.maybe_learn("x", "y", attempt=3, duration_s=500, criteria=[], score=95) is None
    monkeypatch.setattr(config, "test_mode", lambda: False)
    monkeypatch.setattr(config, "outbound_blocked", lambda: True)
    assert skillloop.maybe_learn("x", "y", attempt=3, duration_s=500, criteria=[], score=95) is None
    assert calls == []


def test_tagesdrossel_greift(monkeypatch, tmp_path):
    from core.mind import skillloop
    antworten = []
    for _ in range(skillloop.MAX_NEW_PER_DAY + 1):
        antworten += ["NAME: S\nSCHRITTE: tun", "JA"]
    store, _ = _setup(monkeypatch, tmp_path, antworten)
    for _ in range(skillloop.MAX_NEW_PER_DAY):
        assert skillloop.maybe_learn("x", "y", attempt=2, duration_s=200, criteria=[], score=90)
    # der (N+1)-te Versuch am selben Tag wird gedrosselt
    assert skillloop.maybe_learn("x", "y", attempt=2, duration_s=200, criteria=[], score=90) is None


def test_raist_nie_bei_llm_fehler(monkeypatch, tmp_path):
    from core.mind import skillloop
    from core.kernel import llm_router
    _setup(monkeypatch, tmp_path, [])
    def boom(msgs, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(llm_router, "complete", boom)
    assert skillloop.maybe_learn("x", "y", attempt=2, duration_s=200, criteria=[], score=90) is None


def test_runner_ruft_lernkreis_im_pass_zweig():
    import inspect
    from core.agency.missions import runner
    src = inspect.getsource(runner._execute_scored)
    assert "skillloop.maybe_learn" in src  # Verdrahtung am pass-Zweig


def test_liveops_kennt_skill_events():
    from core.kernel import events
    d = events.describe("skill_learned", {"name": "Impressum-Recherche"})
    assert "gelernt" in d["text"] and "Impressum" in d["detail"]
    r = events.describe("skill_rejected", {"name": "X", "grund": "trivial"})
    assert "Skeptiker" in r["text"] and "trivial" in r["detail"]
