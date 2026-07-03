"""S11: Playbooks — Prozeduren mit Reifegrad, Lernschleife und Vault-Index. Offline."""
from __future__ import annotations

from core.kernel import events
from core.mind import playbooks


_PB = """---
titel: Test-Ablauf
wann: Wenn etwas getestet werden soll.
reifegrad: {grade}
erfolge: 0
fehlschlaege: 0
serie: 0
letzte:
---

# Test-Ablauf

## Schritte

1. Etwas tun.

## Lektionen
"""


def _setup(monkeypatch, tmp_path, grade="entwurf", name="test-ablauf"):
    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir(exist_ok=True)
    (pb_dir / f"{name}.md").write_text(_PB.format(grade=grade), encoding="utf-8")
    (pb_dir / "_VORLAGE.md").write_text(_PB.format(grade="entwurf"), encoding="utf-8")
    monkeypatch.setattr(playbooks, "PB_DIR", pb_dir)
    monkeypatch.setattr(playbooks, "INDEX_PATH", tmp_path / "INDEX.md")
    monkeypatch.setattr(events, "DB_PATH", tmp_path / "state.db")
    events.init_db()  # approvals.create emittiert ungeschuetzt -> Tabelle muss existieren
    return pb_dir


def test_list_und_vorlage_wird_uebersprungen(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    pbs = playbooks.list_playbooks()
    assert len(pbs) == 1
    m = pbs[0]
    assert m["name"] == "test-ablauf" and m["reifegrad"] == "entwurf"
    assert m["erfolge"] == 0 and m["lektionen"] == 0


def test_resolve_fuzzy(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert playbooks.resolve("test-ablauf") == "test-ablauf"
    assert playbooks.resolve("Test-Ablauf") == "test-ablauf"
    assert playbooks.resolve("ablauf") == "test-ablauf"      # eindeutiger Teiltreffer
    assert playbooks.resolve("gibtsnicht") is None


def test_router_block(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    block = playbooks.router_block()
    assert "test-ablauf" in block and "[entwurf]" in block
    assert "playbook_read" in block and "playbook_result" in block
    monkeypatch.setattr(playbooks, "PB_DIR", tmp_path / "leer")
    assert playbooks.router_block() == ""                     # fail-soft: kein leerer Block im Prompt


def test_erfolg_zaehlt_und_serie_fuehrt_zu_vorschlag(monkeypatch, tmp_path):
    from core.agency import approvals

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "state.db")
    for i in range(playbooks.PROMOTE_AFTER - 1):
        res = playbooks.record_result("test-ablauf", True)
        assert res["ok"] and res["serie"] == i + 1 and res["proposal"] is None
    res = playbooks.record_result("test-ablauf", True)        # 5. Erfolg in Serie
    assert res["proposal"]                                    # Vorschlag liegt in der Inbox
    assert res["serie"] == 0                                  # Serie genullt -> kein Spam
    assert res["reifegrad"] == "entwurf"                      # NICHT selbst befoerdert
    pend = approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "playbook" and pend[0]["ref"] == "test-ablauf"


def test_fehlschlag_stuft_zurueck(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, grade="autonom")
    res = playbooks.record_result("test-ablauf", False)
    assert res["reifegrad"] == "begleitet" and res["demoted"] == "begleitet"
    res = playbooks.record_result("test-ablauf", False)
    assert res["reifegrad"] == "entwurf"
    res = playbooks.record_result("test-ablauf", False)       # unterste Stufe bleibt
    assert res["reifegrad"] == "entwurf" and res["demoted"] is None


def test_freigabe_befoerdert(monkeypatch, tmp_path):
    from core.agency import approvals

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "state.db")
    aid = approvals.create("Playbook befoerdern: test-ablauf", kind="playbook", ref="test-ablauf")
    out = approvals.decide(aid, approved=True)
    assert out["ok"] and out["applied"]["reifegrad"] == "begleitet"
    assert playbooks.list_playbooks()[0]["reifegrad"] == "begleitet"
    # Ablehnung eines zweiten Vorschlags aendert nichts
    aid2 = approvals.create("Playbook befoerdern: test-ablauf", kind="playbook", ref="test-ablauf")
    approvals.decide(aid2, approved=False)
    assert playbooks.list_playbooks()[0]["reifegrad"] == "begleitet"


def test_lektionen_anhaengen_mit_deckel(monkeypatch, tmp_path):
    pb_dir = _setup(monkeypatch, tmp_path)
    assert playbooks.add_lesson("test-ablauf", "Erste Lektion.")["ok"]
    text = (pb_dir / "test-ablauf.md").read_text(encoding="utf-8")
    assert "## Lektionen" in text and "Erste Lektion." in text
    for i in range(playbooks.MAX_LESSONS + 2):
        playbooks.add_lesson("test-ablauf", f"Lektion Nummer {i}.")
    text = (pb_dir / "test-ablauf.md").read_text(encoding="utf-8")
    _, _, rest = text.partition("## Lektionen")
    bullets = [l for l in rest.splitlines() if l.startswith("- ")]
    assert len(bullets) == playbooks.MAX_LESSONS              # Deckel haelt
    assert "Erste Lektion." not in text                       # aelteste ist rausgefallen
    assert f"Lektion Nummer {playbooks.MAX_LESSONS + 1}." in text
    assert "# Test-Ablauf" in text and "1. Etwas tun." in text  # Rumpf unangetastet


def test_ergebnis_mit_notiz_schreibt_lektion(monkeypatch, tmp_path):
    pb_dir = _setup(monkeypatch, tmp_path)
    playbooks.record_result("test-ablauf", False, notiz="Naechstes Mal Quelle pruefen.")
    text = (pb_dir / "test-ablauf.md").read_text(encoding="utf-8")
    assert "Naechstes Mal Quelle pruefen." in text
    assert "fehlschlaege: 1" in text                          # Zaehler in der Datei


def test_index_refresh_idempotent(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    res = playbooks.refresh_index()
    assert res["ok"] and res["playbooks"] == 1
    idx = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    assert "test-ablauf" in idx and idx.count("<!-- AUTO:START -->") == 1
    assert playbooks.refresh_index()["ok"]                    # zweiter Lauf: kein Marker-Duplikat
    idx2 = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    assert idx2.count("<!-- AUTO:START -->") == 1


def test_echte_vault_dateien():
    """Die ausgelieferten Starter-Playbooks und INDEX.md sind wohlgeformt."""
    pbs = playbooks.list_playbooks()
    names = {m["name"] for m in pbs}
    assert {"akquise-email", "wochen-review"} <= names
    assert all(m["reifegrad"] == "entwurf" for m in pbs)      # neue Playbooks starten unten
    idx = playbooks.INDEX_PATH.read_text(encoding="utf-8")
    assert idx.count("<!-- AUTO:START -->") == 1 and idx.count("<!-- AUTO:END -->") == 1


def test_router_steht_in_beiden_prompt_pfaden():
    from core.agency.act import _identity
    from core.mind import agent

    assert "DEINE PLAYBOOKS" in _identity()                   # Task-Pfad
    assert "DEINE PLAYBOOKS" in agent._playbooks_block()      # Chat-Pfad (Kopf-Funktion)


def test_werkzeuge_registriert_und_fail_soft(monkeypatch, tmp_path):
    from core.agency.tools import builtin  # noqa: F401
    from core.agency.tools import playbook_tools
    from core.agency.tools.registry import get

    _setup(monkeypatch, tmp_path)
    for name in ("playbook_list", "playbook_read", "playbook_result", "playbook_lesson"):
        assert get(name) is not None
    assert "test-ablauf" in playbook_tools.playbook_list()
    assert "## Schritte" in playbook_tools.playbook_read("test-ablauf")
    assert "nicht gefunden" in playbook_tools.playbook_read("gibtsnicht")
    out = playbook_tools.playbook_result("test-ablauf", "ja")
    assert "Erfolg" in out and "Serie 1" in out
    assert "festgehalten" in playbook_tools.playbook_lesson("test-ablauf", "Merken.")


def test_api_und_cockpit_marker():
    from core.api import server
    from core.api import ui

    d = server.api_playbooks()
    assert "playbooks" in d and d["grades"] == ["entwurf", "begleitet", "autonom"]
    html = ui.DASHBOARD_HTML
    for marker in ('data-s="playbooks"', 'id="v-playbooks"', 'id="pb-list"', "loadPlaybooks"):
        assert marker in html
