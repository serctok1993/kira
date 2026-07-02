"""S4.1: Kontext-Diät — Persona-Budget, Lektionen-Curator, Embedding-Backfill. Offline."""
from __future__ import annotations

from core.mind import curator
from core.mind.agent import PERSONA_DIRECTIVE
from core.mind.memory import store as memory
import core.mind.memory.embed as embed_mod
from core.kernel import events, llm_router


def _use_tmp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (memory, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    memory.init_memory()


def _fake_complete(text: str):
    def fake(messages, system=None, task_type="chat", session_id=None, escalate=False, tools=None):
        return {"text": text, "cost_usd": 0.0, "model": "fake", "fell_back": False,
                "latency_s": 0.0, "escalated": False, "tool_calls": []}
    return fake


# --- Persona: Budget + alle Verhaltensregeln erhalten -------------------------

def test_persona_size_budget():
    # Diaet-Ziel: unter 3800 Zeichen (vorher 5378) — geht bei JEDEM LLM-Call mit,
    # in Chat UND Mission (_identity).
    assert len(PERSONA_DIRECTIVE) < 3800


def test_persona_keeps_all_rules():
    p = PERSONA_DIRECTIVE
    for marker in ("Kira", "weiblich", "Basismodell", "remember_fact", "self_edit",
                   "run_command", "web_search", "SPRACHMEMOS", "Not-Aus",
                   "Ketten ab", "FREMDE", "GELD", "Audit", "read_file", "Get-Content",
                   "db_query", "read_logs", "WINDOWS", "/work", "/plan",
                   "Sternchen", "KNAPP"):
        assert marker in p, f"Regel-Marker fehlt nach Trim: {marker}"


# --- Lektionen-Curator ----------------------------------------------------------

def _seed_lessons(n):
    for i in range(n):
        memory.remember(f"Lektion Nummer {i}: pruefe X bevor Y", role="self", kind="lesson")


def test_curate_lessons_consolidates(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(embed_mod, "embed", lambda t: None)  # kein Ollama im Test
    _seed_lessons(8)
    memory.remember("SKILL [x]: bleibt unberuehrt", role="self", kind="skill")

    monkeypatch.setattr(llm_router, "complete", _fake_complete(
        "LEKTION: Erst pruefen, dann handeln\nLEKTION: Quellen immer verlinken\nQuatschzeile"))
    res = curator.curate_lessons()
    assert res == {"before": 8, "after": 2}
    texts = [l["text"] for l in memory.all_lessons()]
    assert texts and all("LEKTION" not in t for t in texts)  # Praefix abgestreift
    assert len(texts) == 2
    assert len(memory.all_skills()) == 1  # Skills nicht angefasst
    assert any(e["type"] == "lessons_curated" for e in events.recent(10))


def test_curate_lessons_never_deletes_blind(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(embed_mod, "embed", lambda t: None)
    _seed_lessons(7)
    monkeypatch.setattr(llm_router, "complete", _fake_complete("Ich verweigere heute Listen."))
    res = curator.curate_lessons()
    assert "keine bereinigte Liste" in res["note"]
    assert len(memory.all_lessons()) == 7  # NICHTS geloescht


def test_curate_lessons_skips_when_few(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(embed_mod, "embed", lambda t: None)
    _seed_lessons(3)
    called = []
    monkeypatch.setattr(llm_router, "complete", lambda *a, **k: called.append(1))
    res = curator.curate_lessons()
    assert "zu wenige" in res["note"] and called == []  # kein LLM-Call verschwendet


# --- Embedding-Backfill ----------------------------------------------------------

def test_backfill_embeddings(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(embed_mod, "embed", lambda t: None)  # Eintraege OHNE Embedding anlegen
    for i in range(4):
        memory.remember(f"Alt-Eintrag {i}", kind="fact")

    monkeypatch.setattr(embed_mod, "embed", lambda t: [1.0, 0.0, 0.5])  # Embedder "wieder da"
    assert memory.backfill_embeddings() == 4
    assert memory.backfill_embeddings() == 0  # idempotent: nichts mehr offen


def test_backfill_stops_when_embedder_down(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(embed_mod, "embed", lambda t: None)
    memory.remember("ohne Vektor", kind="fact")
    assert memory.backfill_embeddings() == 0  # kein Endlos-Versuch, naechster Wartungslauf
