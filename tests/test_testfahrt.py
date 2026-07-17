"""Testphasen-Werkzeuge (Werkstatt-Wunsch 17.07.):

(1) TESTFAHRT — ephemere Sessions (test-/bench-/desktop-) bekommen keine
    episodischen Alt-Erinnerungen in den Prompt (Fakten/Lektionen bleiben);
    nichts wird geloescht. Neue Modelle objektiv bewerten, ohne dass
    Alt-Chat-Kontext (inkl. gespeicherter Fabrikationen) hineinblutet.
(2) RADIERGUMMI — clear_session vergisst genau EINE session_id: jetzt mit
    zeilenweisem Backup (data/backups/) und FTS-Aufraeumung.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.mind.memory import store


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    from core import config
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    store.init_memory()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)        # Backups landen in tmp, nie live
    import core.mind.memory.embed as embed
    monkeypatch.setattr(embed, "embed", lambda text: None)   # FTS/Recency-Pfad testen
    return tmp_path


def test_testfahrt_erkennt_ephemere_sessions():
    assert store.ist_testfahrt("test-abc123")
    assert store.ist_testfahrt("bench-x") and store.ist_testfahrt("desktop-y")
    assert not store.ist_testfahrt("cockpit-2026") and not store.ist_testfahrt(None)


def test_nur_dauerhaft_laesst_episodisches_draussen():
    store.remember("Wir sprachen gestern ueber Lasagne", role="user",
                   kind="episodic", session_id="cockpit-alt")
    store.remember("Lasagne ist das Lieblingsessen", role="self", kind="fact")
    voll = store.recall("Lasagne", limit=6, exclude_session="test-neu")
    assert any("gestern" in m["text"] for m in voll)          # normal: Episodik dabei
    frisch = store.recall("Lasagne", limit=6, exclude_session="test-neu",
                          nur_dauerhaft=True)
    assert frisch and all("gestern" not in m["text"] for m in frisch)
    assert any("Lieblingsessen" in m["text"] for m in frisch)  # Fakten bleiben


def test_prompt_der_testfahrt_ist_frei_von_alt_chat(monkeypatch):
    from core.mind import agent
    store.remember("Alt-Chat: Herr Mueller, Ihr Termin wurde gebucht", role="partner",
                   kind="episodic", session_id="cockpit-alt")
    store.remember("Der Nutzer heisst NICHT Herr Mueller", role="self", kind="fact")
    c = agent.prompt_context("Termin", session_id="test-fahrt1")
    assert "Herr Mueller, Ihr Termin" not in c["erinnerungen"]
    assert "NICHT Herr Mueller" in c["erinnerungen"]
    c2 = agent.prompt_context("Termin", session_id="cockpit-neu")
    assert "Herr Mueller, Ihr Termin" in c2["erinnerungen"]   # normale Session: unveraendert


def test_radiergummi_sichert_und_raeumt_fts(_iso):
    tmp = _iso
    store.remember("weg damit A", kind="episodic", session_id="s-weg")
    store.remember("weg damit B", kind="episodic", session_id="s-weg")
    store.remember("bleibt", kind="episodic", session_id="s-bleibt")
    store.remember("Fakt bleibt immer", kind="fact", session_id="s-weg")
    n = store.clear_session("s-weg")
    assert n == 2
    assert store.count_by_kind("episodic") == 1               # nur die fremde Session
    assert store.count_by_kind("fact") == 1                   # Fakten unantastbar
    backups = list((Path(tmp) / "backups").glob("session-*.jsonl"))
    assert backups and "weg damit A" in backups[0].read_text(encoding="utf-8")
    with store._conn() as c:                                  # FTS-Leichen sind mit weg
        rest = c.execute("SELECT COUNT(*) FROM memory_fts WHERE text LIKE 'weg damit%'").fetchone()[0]
    assert rest == 0
