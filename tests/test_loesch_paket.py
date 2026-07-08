"""Werkbank PR 1 — Loesch-Grundausstattung: Projekte archivieren, Bench-/Radar-/
Datei-/Skill-/Metrik-Loeschen. Rein additiv, alles offline."""
from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

import core.api.server as s
from core.agency import radar, ventures
from core.agency.missions import metrics
from core.kernel import events


def _db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (ventures, radar, metrics, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()


# ---------- Projekte: archivieren + Datei loeschen ----------

def test_venture_archive_verschwindet_aus_listen(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    vid = ventures.add("Testprojekt", hypothesis="h")
    assert any(v["id"] == vid for v in ventures.summary())
    assert ventures.archive(vid)
    assert not any(v["id"] == vid for v in ventures.list_all())
    assert not any(v["id"] == vid for v in ventures.summary())      # Cockpit-Pfad
    assert ventures.get(vid)["status"] == "dead"                    # Spur bleibt
    assert not ventures.archive("gibtsnicht")


def test_venture_datei_loeschen_mit_guard(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    import core.config as _c
    monkeypatch.setattr(_c, "DATA_DIR", tmp_path / "data")
    vid = ventures.add("P")
    (ventures.files_dir(vid) / "angebot.pdf").write_bytes(b"x")
    assert ventures.delete_file(vid, "angebot.pdf")
    assert ventures.list_files(vid) == []
    for bad in ("../../.env", "..\\x", ".versteckt", ""):
        assert not ventures.delete_file(vid, bad)


def test_api_ventures_archive_und_file_delete(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    import core.config as _c
    monkeypatch.setattr(_c, "DATA_DIR", tmp_path / "data")
    vid = ventures.add("P2")
    (ventures.files_dir(vid) / "a.txt").write_bytes(b"1")
    cl = TestClient(s.app)
    r = cl.post("/api/ventures/file-delete", json={"id": vid, "name": "a.txt"}).json()
    assert r["ok"] and r["files"] == []
    assert cl.post("/api/ventures/archive", json={"id": vid}).json()["ok"]


# ---------- Radar: loeschen + aufraeumen ----------

def _idee(title: str, status: str = "new", ts: float | None = None) -> str:
    import uuid
    oid = uuid.uuid4().hex
    with radar._conn() as c:
        c.execute("INSERT INTO opportunities (id, ts, title, status, hash, updated_ts) "
                  "VALUES (?,?,?,?,?,?)", (oid, ts or time.time(), title, status, oid[:8], time.time()))
    return oid


def test_radar_delete_und_purge(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    radar.init_radar()
    oid = _idee("Idee A")
    alt = _idee("Idee B alt", status="rejected", ts=time.time() - 40 * 86400)
    frisch = _idee("Idee C frisch", status="rejected")

    assert radar.delete(oid[:8])                       # Kurz-Id erlaubt
    assert not any(o["id"] == oid for o in radar.list_all())
    assert not radar.delete("ffffffff")

    assert radar.purge_rejected(days=30) == 1          # nur die alte fliegt
    ids = [o["id"] for o in radar.list_all()]
    assert frisch in ids and alt not in ids


def test_api_opportunities_delete_purge(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    radar.init_radar()
    oid = _idee("Web-Idee")
    cl = TestClient(s.app)
    assert cl.post("/api/opportunities/delete", json={"id": oid}).json()["ok"]
    _idee("alt", status="rejected", ts=time.time() - 99 * 86400)
    assert cl.post("/api/opportunities/purge", json={}).json()["purged"] == 1


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
    for marker in ("ak-archive", "data-fdel", "/api/ventures/archive", "/api/bench/delete",
                   "data-odel", "rd-purge", "data-zdel", "/api/metrics/delete", "data-mdel"):
        assert marker in html, f"fehlt im Cockpit: {marker}"
