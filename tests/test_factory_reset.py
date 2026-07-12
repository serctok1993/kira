"""Handover-Härtung C: Werkszustand / Blanko-Handover (Phase 5).

Kern-Sicherheit: nichts ohne exakte Bestätigung, jede Kategorie wird vorher gesichert,
Fakten sind NICHT im Standard, eine kaputte Kategorie reißt die anderen nicht ab.
Die Löschung selbst läuft gegen eine Wegwerf-DB (kein echtes Gedächtnis angefasst)."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.kernel import factory


def _fresh_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    monkeypatch.setattr("core.config.DB_PATH", db)
    import core.mind.memory.store as store
    import core.kernel.events as events
    monkeypatch.setattr(store, "DB_PATH", db, raising=False)
    monkeypatch.setattr(events, "DB_PATH", db, raising=False)
    store.init_memory()
    events.init_db()
    return store, events


# ---------- Schutz ----------

def test_reset_ohne_bestaetigung_tut_nichts():
    r = factory.reset(scope=["chats"], confirm="")
    assert r["ok"] is False and "Bestaetigung" in r["error"]


def test_reset_ohne_scope_tut_nichts():
    r = factory.reset(scope=[], confirm="WERKSZUSTAND")
    assert r["ok"] is False


def test_api_reset_verlangt_confirm():
    r = TestClient(s.app).post("/api/factory/reset", json={"scope": ["chats"]}).json()
    assert r["ok"] is False                                     # ohne confirm kein Reset


# ---------- Vorschau ----------

def test_preview_listet_kategorien_und_fakten_nicht_im_standard(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    p = factory.preview()
    keys = {c["key"] for c in p["categories"]}
    assert {"chats", "skills", "lektionen", "events", "wissen", "fakten"} <= keys
    fakten = next(c for c in p["categories"] if c["key"] == "fakten")
    assert fakten["standard"] is False                         # echte Fakten überleben Standard-Reset


# ---------- echter Reset gegen Wegwerf-DB ----------

def test_reset_sichert_und_loescht_nur_gewaehltes(monkeypatch, tmp_path):
    store, events = _fresh_db(monkeypatch, tmp_path)
    monkeypatch.setattr("core.config.DATA_DIR", tmp_path)       # Backups in den Wegwerf-Pfad
    store.remember("ein test-chat", role="user", kind="episodic", session_id="s1")
    store.remember("SKILL [x]: tu dies", role="self", kind="skill")
    store.remember("Mia mag dunkles UI", role="self", kind="fact")

    # nur Skills zuruecksetzen -> Fakt und Chat bleiben
    r = factory.reset(scope=["skills"], confirm="WERKSZUSTAND")
    assert r["ok"] and r["cleared"]["skills"] == 1
    assert store.count_by_kind("skill") == 0
    assert store.count_by_kind("fact") == 1                     # Fakt unangetastet
    assert store.count_by_kind("episodic") == 1                # Chat unangetastet
    # Backup wurde geschrieben
    backups = list((tmp_path / "backups").glob("memory-skill-*.jsonl"))
    assert backups and backups[0].read_text(encoding="utf-8").strip()


def test_kaputte_kategorie_stoppt_andere_nicht(monkeypatch, tmp_path):
    store, events = _fresh_db(monkeypatch, tmp_path)
    monkeypatch.setattr("core.config.DATA_DIR", tmp_path)
    store.remember("SKILL [y]: tu das", role="self", kind="skill")

    # events-Clear sabotieren -> muss gefangen werden, skills trotzdem gelöscht
    monkeypatch.setattr(events, "clear_all", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = factory.reset(scope=["skills", "events"], confirm="WERKSZUSTAND")
    assert r["ok"] is True
    assert r["cleared"]["skills"] == 1                          # lief durch
    assert r["cleared"]["events"] == -1                        # markiert als Fehler, kein Absturz


def test_delete_by_kind_leere_liste():
    from core.mind.memory import store
    assert store.delete_by_kind([])["deleted"] == 0            # nichts gewählt -> nichts weg
