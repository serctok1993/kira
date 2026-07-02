"""S5.5: Business-Radar — Scan/Dedupe/Pipeline/Konvertierung. Offline, LLM+Suche gefakt."""
from __future__ import annotations

from core.agency import radar, ventures
from core.agency.missions import objectives
from core.kernel import events, llm_router


def _setup(monkeypatch, tmp_path, llm_text: str, signals: str = "Signal " * 30):
    db = str(tmp_path / "state.db")
    for mod in (radar, ventures, objectives, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    radar.init_radar()
    monkeypatch.setattr(radar, "_gather", lambda themes: signals)

    def fake(messages, system=None, task_type="chat", session_id=None, escalate=False, tools=None):
        return {"text": llm_text, "cost_usd": 0.0, "model": "fake", "fell_back": False,
                "latency_s": 0.0, "escalated": False, "tool_calls": []}

    monkeypatch.setattr(llm_router, "complete", fake)


_GOOD = ('Hier: [{"title": "Nischen-Newsletter fuer Spediteure", '
         '"hypothesis": "Speditionen zahlen fuer kuratierte Ausschreibungen", '
         '"source_url": "https://x.de", "score": 72}, '
         '{"title": "KI-Rechnungs-Parser als Micro-SaaS", '
         '"hypothesis": "Steuerbueros zahlen pro Beleg", "score": 155}]')


def test_scan_stores_and_clamps(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _GOOD)
    res = radar.scan(notify=False)
    assert res["found"] == 2
    opps = radar.list_all()
    assert {o["title"] for o in opps} == {"Nischen-Newsletter fuer Spediteure",
                                          "KI-Rechnungs-Parser als Micro-SaaS"}
    assert max(o["score"] for o in opps) == 100  # 155 geclampt
    assert all(o["status"] == "new" for o in opps)
    assert sum(1 for e in events.recent(20) if e["type"] == "opportunity_found") == 2


def test_scan_dedupes_second_run(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _GOOD)
    assert radar.scan(notify=False)["found"] == 2
    assert radar.scan(notify=False)["found"] == 0  # Titel-Hash-Dedupe
    assert len(radar.list_all()) == 2


def test_scan_garbage_and_exception_fail_soft(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, "Ich liefere heute kein JSON.")
    assert radar.scan(notify=False)["found"] == 0

    def boom(*a, **k):
        raise RuntimeError("Modell weg")

    monkeypatch.setattr(llm_router, "complete", boom)
    res = radar.scan(notify=False)
    assert res["found"] == 0 and "Modell weg" in res["error"]
    assert any(e["type"] == "radar_error" for e in events.recent(10))


def test_scan_without_signals_skips_llm(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _GOOD, signals="  ")
    called = []
    monkeypatch.setattr(llm_router, "complete", lambda *a, **k: called.append(1))
    res = radar.scan(notify=False)
    assert res["found"] == 0 and called == []  # kein LLM-Call fuer nichts


def test_decide_whitelist_and_prefix(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _GOOD)
    radar.scan(notify=False)
    oid = radar.list_all()[0]["id"]
    assert radar.decide(oid[:8], "shortlist")
    assert radar.list_all("shortlist")
    assert not radar.decide(oid, "quatsch")   # Status-Whitelist
    assert not radar.decide("gibtsnicht", "rejected")


def test_convert_creates_venture_and_objective(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _GOOD)
    radar.scan(notify=False)
    o = radar.list_all()[0]
    res = radar.convert(o["id"][:8])
    assert res["ok"]
    v = ventures.get(res["venture_id"])
    assert v and v["status"] == "idea" and o["title"].startswith(v["name"][:20])
    objs = [x for x in objectives.list_active(domain="business")
            if x.get("venture_id") == res["venture_id"]]
    assert len(objs) == 1 and objs[0]["title"].startswith("Validiere:")
    assert radar._resolve(o["id"])["status"] == "converted"
