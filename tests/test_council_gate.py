"""S4.2: Council-als-Gate — Rats-Urteil landet im Geld-Inbox-Eintrag. Offline."""
from __future__ import annotations

from core.agency import approvals
from core.config import CONFIG
from core.governance import autonomy, gate
from core.kernel import events, llm_router


def _setup(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (approvals, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(autonomy, "_PATH", tmp_path / "autonomy.json")
    autonomy.set_config(chains_off=True, hard_gate=["money", "email_stranger"])
    events.init_db()
    approvals.init_approvals()


def _fake_complete(text: str):
    calls = []

    def fake(messages, system=None, task_type="chat", session_id=None, escalate=False, tools=None):
        calls.append(task_type)
        return {"text": text, "cost_usd": 0.0, "model": "fake", "fell_back": False,
                "latency_s": 0.0, "escalated": False, "tool_calls": []}

    fake.calls = calls
    return fake


def test_money_gate_includes_council_verdict(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    # Assistent-Pivot 13.08.: Live-Config hat council_gate=[] (Rat aus). Der Test prueft
    # den MECHANISMUS und pinnt das Gate deshalb selbst — W0: nie an Live-Daten haengen.
    monkeypatch.setitem(CONFIG["governance"], "council_gate", ["money"])
    fake = _fake_complete("ENTSCHEIDUNG: Ja, aber erst nach Preisvergleich.\nBEGRUENDUNG: ...")
    monkeypatch.setattr(llm_router, "complete", fake)

    ran = []
    out = gate.guarded("money", "10 EUR Domain kaufen", "namecheap.com, .de-Domain",
                       execute=lambda: ran.append(1))
    assert "Wartet auf Partners Freigabe" in out and ran == []
    pend = approvals.pending()
    assert len(pend) == 1
    assert "RATS-URTEIL" in pend[0]["detail"]
    assert "Preisvergleich" in pend[0]["detail"]  # Judge-Urteil liegt bei
    assert len(fake.calls) == 4  # 3 Personas + 1 Judge
    assert any(e["type"] == "council_verdict" for e in events.recent(20))


def test_council_crash_still_files_request(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    # Assistent-Pivot 13.08.: Mechanismus-Test pinnt das Council-Gate selbst (s.o.).
    monkeypatch.setitem(CONFIG["governance"], "council_gate", ["money"])

    def boom(*a, **k):
        raise RuntimeError("Modell weg")

    monkeypatch.setattr(llm_router, "complete", boom)
    out = gate.guarded("money", "5 EUR ausgeben", "Detail", execute=lambda: "nie")
    assert "Wartet auf Partners Freigabe" in out  # Debatten-Ausfall blockiert die Anfrage NICHT
    pend = approvals.pending()
    assert len(pend) == 1 and "Rats-Debatte fehlgeschlagen" in pend[0]["detail"]


def test_non_gated_kind_skips_council(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    fake = _fake_complete("egal")
    monkeypatch.setattr(llm_router, "complete", fake)
    out = gate.guarded("external", "Repo anlegen", "detail", execute=lambda: "ok")
    assert out == "ok"
    assert fake.calls == []  # frei laufende Aktionen kosten keine Debatte


def test_gated_kind_outside_council_list_skips_debate(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setitem(CONFIG, "governance",
                        {**CONFIG.get("governance", {}), "council_gate": []})
    fake = _fake_complete("egal")
    monkeypatch.setattr(llm_router, "complete", fake)
    out = gate.guarded("money", "Geld-Aktion", "detail", execute=lambda: "nie")
    assert "Wartet auf Partners Freigabe" in out
    assert fake.calls == []  # Debatte abgeschaltet -> reiner Inbox-Eintrag
    assert "RATS-URTEIL" not in approvals.pending()[0]["detail"]
