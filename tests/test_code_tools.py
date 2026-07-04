"""Coding-Grundausstattung: code_suche, datei_finden, edit_datei, write_file-Atomik, code:-Modus."""
from __future__ import annotations


# ---- code_suche ---------------------------------------------------------------------

def test_code_suche_findet_und_formatiert():
    from core.agency.tools.code_tools import code_suche
    out = code_suche("def resolve_model", "core/kernel", "*.py")
    assert "core/kernel/llm_router.py" in out
    assert ":" in out  # pfad:zeile: text


def test_code_suche_deckelt(monkeypatch):
    from core.agency.tools import code_tools
    monkeypatch.setattr(code_tools, "_MAX_TREFFER", 3)
    out = code_tools.code_suche("def ", "core", "*.py")
    assert "gedeckelt" in out


def test_code_suche_skippt_und_schuetzt():
    from core.agency.tools.code_tools import code_suche
    assert code_suche("x", "/etc") == "Pfad ausserhalb des Projekts oder nicht vorhanden."
    assert "Ungueltiges Regex" in code_suche("def (")
    # .venv/.git etc. tauchen nie in Treffern auf
    out = code_suche("(?i)python", ".", "*.py")
    assert ".venv/" not in out and ".git/" not in out


# ---- datei_finden -------------------------------------------------------------------

def test_datei_finden():
    from core.agency.tools.code_tools import datei_finden
    out = datei_finden("test_code_tools.py")
    assert "tests/test_code_tools.py" in out
    assert datei_finden("**/test_code_tools.py").count("test_code_tools.py") >= 1  # **/ normalisiert
    assert datei_finden("gibt_es_nicht_xyz.abc") == "Keine Datei gefunden."
    assert "Kein Muster" in datei_finden("  ")


# ---- edit_datei ---------------------------------------------------------------------

def _iso(monkeypatch, tmp_path):
    """selfdev auf tmp-ROOT + Events auf tmp-DB + Verify/Restart/Git neutralisieren."""
    from core.agency import selfdev
    from core.agency.tools import code_tools
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setattr(selfdev, "ROOT", tmp_path)
    monkeypatch.setattr(code_tools, "ROOT", tmp_path)
    monkeypatch.setattr(selfdev, "_verify", lambda: (True, "[exit 0] gruen"))
    monkeypatch.setattr(selfdev, "_request_restart", lambda which="all": None)
    monkeypatch.setattr(selfdev, "_git", lambda *a: None)
    return tmp_path


def test_edit_datei_happy(monkeypatch, tmp_path):
    from core.agency.tools.code_tools import edit_datei
    root = _iso(monkeypatch, tmp_path)
    f = root / "mod.py"
    f.write_text("def alt():\n    return 1\n", encoding="utf-8")

    out = edit_datei("mod.py", "return 1", "return 2")
    assert out.startswith("OK")
    assert "return 2" in f.read_text(encoding="utf-8")


def test_edit_datei_eindeutigkeit(monkeypatch, tmp_path):
    from core.agency.tools.code_tools import edit_datei
    root = _iso(monkeypatch, tmp_path)
    f = root / "mod.py"
    f.write_text("x = 1\nx = 1\n", encoding="utf-8")

    assert "nicht eindeutig" in edit_datei("mod.py", "x = 1", "x = 2")
    assert "nicht gefunden" in edit_datei("mod.py", "y = 9", "y = 8")
    assert f.read_text(encoding="utf-8") == "x = 1\nx = 1\n"  # unangetastet


def test_edit_datei_append_und_grenzen(monkeypatch, tmp_path):
    from core.agency.tools.code_tools import edit_datei
    root = _iso(monkeypatch, tmp_path)
    f = root / "notiz.md"
    f.write_text("# Kopf\n", encoding="utf-8")

    out = edit_datei("notiz.md", "", "Neuer Absatz.")
    assert out.startswith("OK")
    assert "Neuer Absatz." in f.read_text(encoding="utf-8")

    assert "ausserhalb" in edit_datei("/etc/passwd", "root", "x")
    assert "nicht gefunden" in edit_datei("fehlt.py", "a", "b")


def test_edit_datei_absoluter_pfad_normalisiert(monkeypatch, tmp_path):
    from core.agency.tools.code_tools import edit_datei
    root = _iso(monkeypatch, tmp_path)
    f = root / "tief" / "mod.py"
    f.parent.mkdir()
    f.write_text("a = 1\n", encoding="utf-8")

    out = edit_datei(str(f), "a = 1", "a = 2")  # absolut -> relativ zu ROOT
    assert out.startswith("OK")
    assert "a = 2" in f.read_text(encoding="utf-8")


# ---- write_file atomar ---------------------------------------------------------------

def test_write_file_atomar_ohne_tmp_leichen(tmp_path):
    from core.agency.tools.builtin import write_file
    ziel = tmp_path / "neu" / "datei.txt"
    out = write_file(str(ziel), "inhalt äöü")
    assert out.startswith("OK")
    assert ziel.read_text(encoding="utf-8") == "inhalt äöü"
    assert [x.name for x in ziel.parent.iterdir()] == ["datei.txt"]  # keine .tmp-Reste


# ---- code:-Modus ---------------------------------------------------------------------

def _tmp_dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()


def test_code_prefix_haengt_regeln_an(monkeypatch, tmp_path):
    from core.agency import act
    _tmp_dbs(monkeypatch, tmp_path)
    seen: dict = {}

    def fake_plan(task, session_id=None, on_event=None, escalate=False, code_review=False):
        seen["task"] = task
        return "fertig"

    monkeypatch.setattr(act, "plan_and_execute", fake_plan)

    act.act_chat("code: benenne Funktion um", session_id="t1")
    assert "CODING-REGELN" in seen["task"]
    assert "benenne Funktion um" in seen["task"]

    act.act_chat("plan: normale Planung", session_id="t1")
    assert "CODING-REGELN" not in seen["task"]  # plan: bleibt unveraendert


def test_werkzeuge_registriert():
    from core.agency.tools import builtin  # noqa: F401
    from core.agency.tools import registry
    names = [t.name for t in registry.all_tools()]
    for n in ("code_suche", "datei_finden", "edit_datei"):
        assert n in names
    schemas = {s["function"]["name"]: s for s in registry.tool_schemas()}
    req = schemas["code_suche"]["function"]["parameters"]["required"]
    assert "muster" in req and "pfad" not in req and "dateimuster" not in req
    assert "suche" in schemas["edit_datei"]["function"]["parameters"]["required"]  # '' nur explizit
