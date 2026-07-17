"""S4.1: Kontext-Diät — Persona-Budget, Lektionen-Curator, Embedding-Backfill. Offline."""
from __future__ import annotations

from core.config import MIND_DIR
from core.mind import curator
from core.mind.agent import PERSONA_BUDGET
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
# Gemessen wird der WERKSZUSTAND (core/mind/templates/PERSONA.md) — NICHT die
# live-editierbare core/mind/PERSONA.md: die schreiben Charakter-Editor + Agent
# fort, und die Suite haengt nie an Live-Daten (W0; Praxis-Fund 17.07.: Live-
# Persona 4999 Zeichen -> Suite kippte rot, obwohl der Werkszustand im Budget lag).
# Die LIVE-Groesse bewacht das Cockpit sanft (test_persona_wache_* unten).

def _werks_persona() -> str:
    raw = (MIND_DIR / "templates" / "PERSONA.md").read_text(encoding="utf-8")
    # Werksnamen hart statt identity.render(): CONFIG traegt Live-Overrides.
    return (raw.replace("{{USER_NAME_S}}", "Partners")
               .replace("{{USER_NAME}}", "Partner")
               .replace("{{AGENT_NAME}}", "Kira")).strip()


def test_persona_size_budget():
    # Diaet-Ziel (vorher 5378, dann 3800). Bewusst auf 4200 angehoben fuer zwei
    # hochwertige, taeglich wirkende Bloecke: "WO DU NACHSCHAUST" (effizienter
    # Karte->Adresse-Nachschau statt Vault-Scan) und "WIE DU MITDENKST" (1 Mitdenk-
    # Schritt). Bestehende Bloecke wurden dafuer gestrafft; geht bei JEDEM LLM-Call
    # mit, in Chat UND Mission (_identity).
    assert len(_werks_persona()) < PERSONA_BUDGET


def test_persona_keeps_all_rules():
    p = _werks_persona()
    for marker in ("Kira", "weiblich", "Basismodell", "remember_fact",
                   "web_search", "SPRACHMEMOS", "Not-Aus",
                   "Ketten ab", "FREMDE", "GELD", "Audit", "read_file", "Get-Content",
                   "db_query", "read_logs", "WINDOWS", "/work", "/plan",
                   "Sternchen", "KNAPP"):
        assert marker in p, f"Regel-Marker fehlt nach Trim: {marker}"


def test_persona_plus_body_cover_capabilities():
    """Faehigkeits-Selbstwissen (self_edit, run_command ...) ist nach S5.2 in den
    BODY-Kopf umgezogen — Persona + BODY zusammen muessen es tragen."""
    from core.mind import body

    combined = _werks_persona() + body.compact()
    for marker in ("self_edit", "run_command", "BODY.md"):
        assert marker in combined, f"Faehigkeits-Marker fehlt im Verbund: {marker}"


def test_persona_wache_meldet_budget_ueberzug(monkeypatch, tmp_path):
    """Sanfte Wache fuer die LIVE-Persona: ueber Budget -> Cockpit-Hinweis im
    Persona-Label + in der Speicher-Antwort, aber KEIN Suite-Fail. Persona-Quelle,
    Datei-Pfad und DBs sind auf tmp umgebogen — nichts Lebendes wird angefasst."""
    from fastapi.testclient import TestClient
    from core.api import server

    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "persona_text", lambda: "X" * (PERSONA_BUDGET + 799))
    c = TestClient(server.app)
    label = {f["name"]: f["label"] for f in c.get("/api/files").json()}["PERSONA.md"]
    assert "ueber dem" in label and str(PERSONA_BUDGET + 799) in label

    monkeypatch.setitem(server.FILES["PERSONA.md"], "path", tmp_path / "PERSONA.md")
    monkeypatch.setattr(server, "MIND_DIR", tmp_path)  # Backup-Ziel (history/) -> tmp
    r = c.post("/api/file", json={"name": "PERSONA.md", "content": "egal"}).json()
    assert r["ok"] is True and "Prompt-Kosten" in r["hinweis"]
    assert (tmp_path / "PERSONA.md").read_text(encoding="utf-8") == "egal"


def test_persona_wache_still_im_budget(monkeypatch, tmp_path):
    """Im Budget bleibt alles beim Alten: Label ohne Warnung, Antwort ohne Hinweis."""
    from fastapi.testclient import TestClient
    from core.api import server

    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "persona_text", lambda: "schlank")
    c = TestClient(server.app)
    label = {f["name"]: f["label"] for f in c.get("/api/files").json()}["PERSONA.md"]
    assert "⚠" not in label and "ueber dem" not in label

    monkeypatch.setitem(server.FILES["PERSONA.md"], "path", tmp_path / "PERSONA.md")
    monkeypatch.setattr(server, "MIND_DIR", tmp_path)
    r = c.post("/api/file", json={"name": "PERSONA.md", "content": "kurz"}).json()
    assert r == {"ok": True}  # kein hinweis-Feld


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
