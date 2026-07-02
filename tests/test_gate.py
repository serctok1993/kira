"""S3.2: Autonomie-Gate + Bridge-Klassifikator — offline, Temp-DB/-Config."""
from __future__ import annotations

from core.agency import approvals
from core.agency.mcp import registry_bridge as bridge
from core.governance import autonomy, gate
from core.kernel import events


def _setup(monkeypatch, tmp_path, chains_off=True, hard_gate=("money", "email_stranger")):
    db = str(tmp_path / "state.db")
    for mod in (approvals, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(autonomy, "_PATH", tmp_path / "autonomy.json")
    autonomy.set_config(chains_off=chains_off, hard_gate=list(hard_gate))
    events.init_db()
    approvals.init_approvals()  # pending() legt die Tabelle nicht selbst an


def test_hard_gate_blocks_without_executing(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    ran = []
    out = gate.guarded("money", "5 EUR Domain kaufen", "namecheap.com",
                       execute=lambda: ran.append(1) or "gekauft")
    assert "Wartet auf Sergens Freigabe" in out and "NICHT ausgefuehrt" in out
    assert ran == []  # DIE Kernzusicherung: nichts ist passiert
    pend = approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "money"  # KINDS-Erweiterung greift
    assert not any(e["type"] == "audit" for e in events.recent(20))


def test_free_kind_executes_and_audits(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    out = gate.guarded("external", "Repo anlegen", "kira-demo",
                       execute=lambda: "Repo erstellt", target="create_repository")
    assert out == "Repo erstellt"
    assert approvals.pending() == []
    audits = [e for e in events.recent(20) if e["type"] == "audit"]
    assert len(audits) == 1 and audits[0]["payload"]["target"] == "create_repository"


def test_chains_on_gates_everything(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, chains_off=False)
    ran = []
    out = gate.guarded("external", "Irgendwas", "", execute=lambda: ran.append(1))
    assert "Wartet auf Sergens Freigabe" in out and ran == []


def test_execute_error_returns_string_no_audit(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("API down")

    out = gate.guarded("external", "Aktion", "", execute=boom)
    assert "Fehler bei" in out and "API down" in out  # kein Raise -> executor retried nicht
    assert not any(e["type"] == "audit" for e in events.recent(20))


def test_gate_infrastructure_failure_fails_closed(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(autonomy, "needs_approval", lambda kind: 1 / 0)
    ran = []
    out = gate.guarded("external", "Aktion", "", execute=lambda: ran.append(1))
    assert "NICHT ausgefuehrt" in out and ran == []  # kaputtes Gate = sichere Richtung


# --- Bridge-Klassifikator + Schreibpfad ---------------------------------------

def test_classify_kind_matrix():
    assert bridge._classify_kind("create_payment_intent") == "money"
    assert bridge._classify_kind("create_refund") == "money"
    assert bridge._classify_kind("transfer_repository") == "money"  # falsch-positiv = sichere Richtung
    assert bridge._classify_kind("send_email") == "email_stranger"
    assert bridge._classify_kind("create_repository") == "external"
    assert bridge._classify_kind("apply_migration") == "external"
    # Lese-Tools kommen gar nicht erst zum Klassifikator
    assert not bridge._is_write_tool("list_repos")
    assert bridge._is_write_tool("fork_repository")  # neue Verben erkannt


def test_bridge_write_path_money_blocks(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(bridge, "_call_server_text",
                        lambda s, t, kw: calls.append((s, t)) or "ausgefuehrt")

    wrapper, _ = bridge._make_wrapper("stripe", "create_refund", "Refund", {})
    out = wrapper(charge="ch_1")
    assert "Wartet auf Sergens Freigabe" in out
    assert calls == []  # Server wurde NICHT beruehrt
    assert approvals.pending()[0]["kind"] == "money"


def test_bridge_write_path_external_runs_and_audits(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_call_server_text", lambda s, t, kw: "Repo erstellt")

    wrapper, _ = bridge._make_wrapper("github", "create_repository", "Neues Repo", {})
    out = wrapper(name="kira-demo")
    assert out == "Repo erstellt"
    assert approvals.pending() == []
    assert any(e["type"] == "audit" for e in events.recent(20))


def test_bridge_kinds_override(monkeypatch, tmp_path):
    """Sergens Linie: Payment-Link ANLEGEN = Zahlung annehmen = external (frei + Audit)."""
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_call_server_text", lambda s, t, kw: "Link erstellt")

    wrapper, _ = bridge._make_wrapper("stripe", "create_payment_link", "Payment-Link", {},
                                      kind_overrides={"create_payment_link": "external"})
    out = wrapper(price="price_1")
    assert out == "Link erstellt"  # Override schlaegt money-Heuristik
    assert approvals.pending() == []


def test_bridge_read_path_direct(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_call_server_text", lambda s, t, kw: "3 Repos gefunden")
    wrapper, _ = bridge._make_wrapper("github", "search_repositories", "Suche", {})
    assert wrapper(query="kira") == "3 Repos gefunden"
    assert not any(e["type"] == "audit" for e in events.recent(20))  # Lesen wird nicht auditiert
