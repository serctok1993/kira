"""S6.1: Governance-Haertung — Verfassung schreibgeschuetzt, Freigaben idempotent.

Hintergrund (02.07.2026): constitution.md wurde ueber POST /api/file abgeschwaecht
(editable stand faelschlich auf True) und ein GOAL-Vorschlag wurde durch Doppelklick
10x angewendet (Vorschlag wurde nie konsumiert, decide() hatte keinen pending-Guard).
Diese Tests pinnen alle geschlossenen Loecher. Offline, Temp-DB, kein LLM.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.agency import approvals
from core.agency.tools import builtin
from core.config import MIND_DIR
from core.kernel import events
from core.mind import evolution


def _iso_events(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()


def _iso_evolution(monkeypatch, tmp_path):
    _iso_events(monkeypatch, tmp_path)
    monkeypatch.setattr(evolution, "PROPOSAL_DIR", tmp_path / "proposals")
    monkeypatch.setattr(evolution, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(evolution, "MIND_DIR", tmp_path / "mind")
    monkeypatch.setattr(evolution, "_read", lambda doc: "(alter Inhalt)")
    (tmp_path / "mind").mkdir()
    (tmp_path / "proposals").mkdir()


# --- Verfassung ist fuer Evolution tabu (inkl. Pfad-Tricks) --------------------

def test_evolution_rejects_constitution_and_emits_alert(monkeypatch, tmp_path):
    _iso_evolution(monkeypatch, tmp_path)
    for doc in ("constitution.md", "../constitution.md", "core/mind/constitution.md",
                str(tmp_path / "constitution.md")):
        with pytest.raises(ValueError):
            evolution.apply_update(doc)
        with pytest.raises(ValueError):
            evolution.propose_update(doc)  # blockt VOR jedem LLM-Call
    blocked = [e for e in events.recent(50) if e["type"] == "evolution_blocked"]
    assert len(blocked) == 8  # jeder Verstoss ist als Alarm sichtbar


def test_ensure_mutable_normalizes_paths(monkeypatch, tmp_path):
    _iso_evolution(monkeypatch, tmp_path)
    # Pfad-Varianten auf ein MUTABLE-Doc werden auf den Dateinamen normalisiert
    assert evolution._ensure_mutable("data/proposals/GOAL.md", "test") == "GOAL.md"
    assert evolution._ensure_mutable(" SOUL.md ", "test") == "SOUL.md"


# --- Vorschlaege werden beim Anwenden konsumiert (kein Mehrfach-Apply) ---------

def test_apply_update_consumes_proposal(monkeypatch, tmp_path):
    _iso_evolution(monkeypatch, tmp_path)
    prop = tmp_path / "proposals" / "GOAL.md"
    prop.write_text("neuer Inhalt", encoding="utf-8")

    res = evolution.apply_update("GOAL.md", reason="Test")
    assert res["consumed"] is True
    assert not prop.exists()  # DER Fix: Vorschlag ist weg
    assert (tmp_path / "mind" / "GOAL.md").read_text(encoding="utf-8") == "neuer Inhalt"
    assert (tmp_path / "history" / res["backup"]).read_text(encoding="utf-8") == "(alter Inhalt)"

    with pytest.raises(FileNotFoundError):  # zweiter Klick -> kein Re-Apply
        evolution.apply_update("GOAL.md", reason="Doppelklick")


# --- decide() ist idempotent (pending -> decided, genau einmal) ----------------

def _iso_approvals(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (approvals, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    approvals.init_approvals()


def test_decide_only_flips_pending(monkeypatch, tmp_path):
    _iso_approvals(monkeypatch, tmp_path)
    aid = approvals.create("Testaktion", kind="generic")

    first = approvals.decide(aid, approved=True)
    assert first["ok"] is True and first["status"] == "approved"

    second = approvals.decide(aid, approved=False)  # Doppelklick / Umentscheiden
    assert second["ok"] is False and second["error"] == "already decided"
    assert approvals.get(aid)["status"] == "approved"  # Erstentscheidung bleibt


def test_create_warns_on_autonomous_flood(monkeypatch, tmp_path):
    """Richter-Rat 04.07.2026: mehr als DAILY_AUTONOMOUS_BUDGET Kira-Eintraege/Tag
    -> approval_flood_warning-Event (warnt, blockiert nicht)."""
    _iso_approvals(monkeypatch, tmp_path)
    for i in range(approvals.DAILY_AUTONOMOUS_BUDGET + 1):
        approvals.create(f"Autonomer Eintrag {i}", kind="generic", source="kira")
    warns = [e for e in events.recent(50) if e["type"] == "approval_flood_warning"]
    assert len(warns) == 1  # genau beim Ueberschreiten, nicht davor
    assert warns[0]["payload"]["count_today"] == approvals.DAILY_AUTONOMOUS_BUDGET + 1
    # Eintraege vom Nutzer (dashboard) zaehlen nicht ins Kira-Budget
    approvals.create("Manuell", kind="generic", source="dashboard")
    assert approvals.created_today("kira") == approvals.DAILY_AUTONOMOUS_BUDGET + 1


def test_decide_no_evolution_side_effect_on_second_call(monkeypatch, tmp_path):
    _iso_approvals(monkeypatch, tmp_path)
    applied = []
    monkeypatch.setattr(evolution, "apply_update",
                        lambda doc, reason="": applied.append(doc) or {"doc": doc})
    aid = approvals.create("Selbst-Update", kind="evolution", ref="GOAL.md")
    approvals.decide(aid, approved=True)
    approvals.decide(aid, approved=True)
    assert applied == ["GOAL.md"]  # Seiteneffekt lief genau EINMAL


# --- API: Doppel-POST liefert 409, Verfassung nicht schreibbar -----------------

def test_api_decide_second_call_409(monkeypatch, tmp_path):
    _iso_approvals(monkeypatch, tmp_path)
    from core.api import server

    client = TestClient(server.app)
    aid = approvals.create("API-Test", kind="generic")
    r1 = client.post("/api/approvals/decide", json={"id": aid, "approved": True})
    assert r1.status_code == 200 and r1.json()["ok"] is True
    r2 = client.post("/api/approvals/decide", json={"id": aid, "approved": True})
    assert r2.status_code == 409 and r2.json()["error"] == "already decided"


def test_api_decide_proposal_consumed_then_409(monkeypatch, tmp_path):
    _iso_approvals(monkeypatch, tmp_path)
    from core.api import server

    monkeypatch.setattr(server, "ROOT", tmp_path)  # prop-Pfad in die Sandbox
    pdir = tmp_path / "data" / "proposals"
    pdir.mkdir(parents=True)
    pfile = pdir / "GOAL.md"
    pfile.write_text("Vorschlag", encoding="utf-8")

    applied = []

    def fake_apply(doc, reason=""):
        applied.append(doc)
        pfile.unlink()  # wie das echte apply_update: Vorschlag konsumieren
        return {"doc": doc, "consumed": True}

    monkeypatch.setattr(evolution, "apply_update", fake_apply)
    client = TestClient(server.app)

    r1 = client.post("/api/approvals/decide", json={"id": "prop:GOAL.md", "approved": True})
    assert r1.status_code == 200 and applied == ["GOAL.md"]
    r2 = client.post("/api/approvals/decide", json={"id": "prop:GOAL.md", "approved": True})
    assert r2.status_code == 409  # kein Vorschlag mehr da -> kein Re-Apply
    assert applied == ["GOAL.md"]


def test_api_file_constitution_editable_by_owner(tmp_path, monkeypatch):
    # Politik-Wechsel (auf des Nutzers Wunsch): der OWNER darf die Verfassung ueber das Cockpit
    # (/api/file) aendern — bewusst, mit Backup + Audit-Event. Kira SELBST kann das weiterhin
    # NICHT (kein arbiträres POST-Tool; write_file/self_edit/evolution bleiben geblockt, s.u.).
    from core.api import server

    con = tmp_path / "constitution.md"
    con.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setitem(server.FILES["constitution.md"], "path", con)
    monkeypatch.setattr(server, "MIND_DIR", tmp_path)        # Backup-Ziel (history/) -> tmp
    client = TestClient(server.app)
    assert client.get("/api/file", params={"name": "constitution.md"}).json()["editable"] is True
    w = client.post("/api/file", json={"name": "constitution.md", "content": "NEUE REGELN"})
    assert w.json()["ok"] is True
    assert con.read_text(encoding="utf-8") == "NEUE REGELN"
    baks = list((tmp_path / "history").glob("constitution.md.*.bak"))   # alte Fassung gesichert
    assert baks and baks[0].read_text(encoding="utf-8") == "ORIGINAL"


# --- Datei-Werkzeuge + self_edit blocken die Verfassung ------------------------

def test_write_file_tool_blocks_constitution(monkeypatch, tmp_path):
    _iso_events(monkeypatch, tmp_path)
    target = MIND_DIR / "constitution.md"
    before = target.read_text(encoding="utf-8")

    out = builtin.write_file(str(target), "HACK")
    assert out.startswith("BLOCKIERT") and "unantastbar" in out
    out2 = builtin.append_file(str(target), "HACK")
    assert out2.startswith("BLOCKIERT")
    assert target.read_text(encoding="utf-8") == before
    blocked = [e for e in events.recent(20) if e["type"] == "write_blocked"]
    assert {e["payload"]["tool"] for e in blocked} == {"write_file", "append_file"}


def test_write_file_other_paths_still_work(monkeypatch, tmp_path):
    _iso_events(monkeypatch, tmp_path)
    p = tmp_path / "notiz.txt"
    assert "OK" in builtin.write_file(str(p), "hallo")
    assert p.read_text(encoding="utf-8") == "hallo"


def test_self_edit_blocks_constitution(monkeypatch, tmp_path):
    _iso_events(monkeypatch, tmp_path)
    from core.agency import selfdev

    before = (MIND_DIR / "constitution.md").read_text(encoding="utf-8")
    res = selfdev.apply_edit("core/mind/constitution.md", "HACK", reason="Test")
    assert res["ok"] is False and "unantastbar" in res["error"]
    assert (MIND_DIR / "constitution.md").read_text(encoding="utf-8") == before
