"""Plünder-Paket + Kurator-Härtung (13.08.2026): Landlock-Sandbox, Anti-Loop-Nudge,
Spill, Secret-Maskierung, Gedächtnis-Alterung."""
from __future__ import annotations


# --- Anti-Loop-Nudge -------------------------------------------------------
def test_nudge_erst_ab_drei_gleichen_calls():
    from core.agency.act import _call_key, _loop_nudge

    verlauf: list[str] = []
    k = _call_key("db_query", {"sql": "SELECT 1"})
    assert _loop_nudge(k, verlauf) is None      # 1
    assert _loop_nudge(k, verlauf) is None      # 2
    assert "3x" in (_loop_nudge(k, verlauf) or "")  # 3 -> Hinweis


def test_nudge_eskaliert_und_zaehler_bricht_bei_anderem_call():
    from core.agency.act import _call_key, _loop_nudge

    verlauf: list[str] = []
    k = _call_key("web_fetch", {"url": "http://x"})
    for _ in range(4):
        _loop_nudge(k, verlauf)
    assert "WARNUNG" in (_loop_nudge(k, verlauf) or "")   # 5
    _loop_nudge(_call_key("read_file", {"p": "a"}), verlauf)  # anderer Call bricht die Serie
    assert _loop_nudge(k, verlauf) is None


def test_nudge_unterscheidet_argumente():
    from core.agency.act import _call_key

    assert _call_key("t", {"a": 1, "b": 2}) == _call_key("t", {"b": 2, "a": 1})  # Reihenfolge egal
    assert _call_key("t", {"a": 1}) != _call_key("t", {"a": 2})


# --- Spill -----------------------------------------------------------------
def test_spill_laesst_kleine_outputs_unberuehrt():
    from core.agency.act import _spill

    klein = "kurze Ausgabe"
    assert _spill("run_command", klein, "test-sid") == klein


def test_spill_lagert_grosse_outputs_aus_und_haelt_kopf_und_fuss(tmp_path, monkeypatch):
    from core.agency import act
    from core.kernel import events
    from core.agency.act import _spill

    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    gross = "KOPFMARKE" + ("x" * 20000) + "FUSSMARKE"
    r = _spill("run_command", gross, "test-sid")
    assert len(r) < len(gross)
    assert "KOPFMARKE" in r and "FUSSMARKE" in r
    assert "ausgelagert nach" in r and "read_file" in r


# --- Secret-Maskierung -----------------------------------------------------
def test_maskiere_erkennt_gaengige_token_formate():
    from core.governance.secrets import maskiere

    for roh in ("ghp_" + "a" * 30, "github_pat_" + "b" * 30, "sk-" + "c" * 30,
                "xoxb-" + "1" * 20, "AKIA" + "A" * 16, "glpat-" + "d" * 20):
        assert maskiere(f"vorher {roh} nachher") == "vorher <SECRET-MASKIERT> nachher"


def test_maskiere_laesst_normalen_text_in_ruhe():
    from core.governance.secrets import maskiere

    t = "Der Termin ist morgen um 9, Projekt luvex-app, Kosten 12,90 EUR."
    assert maskiere(t) == t


def test_events_speichern_kein_klartext_secret(tmp_path, monkeypatch):
    from core.kernel import events

    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    events.emit("test_secret", {"text": "token ghp_" + "z" * 30,
                                "tief": {"args": {"wert": "sk-" + "y" * 30}}})
    roh = str(events.recent(5))
    assert "ghp_" not in roh and "sk-yyy" not in roh
    assert "SECRET-MASKIERT" in roh


# --- Kurator-Härtung -------------------------------------------------------
def test_erhaltungsquote_schlaegt_bei_kahlschlag_an(monkeypatch):
    from core.mind import curator_haertung as ch

    alt = [{"id": str(i), "text": f"LEKTION {i}"} for i in range(10)]
    neu = [{"id": "a", "text": "LEKTION eine"}]
    zustand = {"phase": 0}

    def fake_all_lessons():
        zustand["phase"] += 1
        return alt if zustand["phase"] == 1 else neu

    gemeldet = {}
    monkeypatch.setattr(ch.memory, "init_memory", lambda: None)
    monkeypatch.setattr(ch.memory, "all_lessons", fake_all_lessons)
    monkeypatch.setattr(ch.events, "emit", lambda t, p=None, **k: gemeldet.update({t: p}))

    r = ch.sichere_kuration("lesson", lambda: {"before": 10, "after": 1})
    assert "warnung" in r and r["backup"]
    assert "curator_verdacht" in gemeldet


def test_normale_kuration_ohne_warnung(monkeypatch):
    from core.mind import curator_haertung as ch

    alt = [{"id": str(i), "text": f"LEKTION {i}"} for i in range(8)]
    neu = [{"id": str(i), "text": f"LEKTION {i}"} for i in range(6)]
    zustand = {"phase": 0}

    def fake_all_lessons():
        zustand["phase"] += 1
        return alt if zustand["phase"] == 1 else neu

    monkeypatch.setattr(ch.memory, "init_memory", lambda: None)
    monkeypatch.setattr(ch.memory, "all_lessons", fake_all_lessons)
    monkeypatch.setattr(ch.events, "emit", lambda *a, **k: None)

    r = ch.sichere_kuration("lesson", lambda: {"before": 8, "after": 6})
    assert "warnung" not in r


# --- Sandbox ---------------------------------------------------------------
def test_sandbox_laesst_sudo_ungewrappt():
    from core.agency.shelltool import _sandbox_argv

    assert _sandbox_argv("sudo apt-get update") is None


def test_sandbox_wrappt_normale_befehle_wenn_verfuegbar():
    from core.agency.shelltool import _LL_BIN, _sandbox_argv

    argv = _sandbox_argv("echo hallo")
    if not _LL_BIN.exists():          # Fail-open ist erlaubtes Verhalten
        assert argv is None
    else:
        assert argv and argv[0] == str(_LL_BIN)
        assert "--ro" in argv and "--rw" in argv and argv[-2:] == ["/bin/sh", "-c"]
