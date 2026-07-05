"""Code-Modus 'Claude-Code-Look': Diff hinter jedem Edit + strukturierter Cockpit-Trace.

Backend: edit_datei/self_edit liefern Diffstat (+x −y) und einen ```diff-Block; der Live-Trace
zeigt Edits ganz (Diff), andere Werkzeuge knapp. Frontend: strukturierte Werkzeug-Zeilen +
farbige Diff-Darstellung.
"""
from __future__ import annotations


# ---- Diff-Helfer ---------------------------------------------------------------------

def test_diff_summary_zaehlt():
    from core.agency import selfdev
    old = "a\nb\nc\n"
    new = "a\nB\nc\nd\n"
    add, rem = selfdev.diff_summary(old, new)
    assert add == 2 and rem == 1   # +B +d, -b


def test_compact_diff_fenced_und_gedeckelt():
    from core.agency import selfdev
    old = "".join(f"z{i}\n" for i in range(200))
    new = old.replace("z0\n", "zNEU\n")
    d = selfdev.compact_diff(old, new, "gross.py", max_lines=10)
    assert d.startswith("```diff\n") and d.rstrip().endswith("```")
    assert "-z0" in d and "+zNEU" in d
    assert "weitere Diff-Zeilen" not in d or "…" in d   # Deckel greift sauber
    # nichts geaendert -> leer
    assert selfdev.compact_diff("x\n", "x\n", "x.py") == ""


# ---- edit_datei zeigt den Diff -------------------------------------------------------

def _iso(monkeypatch, tmp_path):
    from core.agency import selfdev
    from core.agency.tools import code_tools
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setattr(selfdev, "ROOT", tmp_path)
    monkeypatch.setattr(code_tools, "ROOT", tmp_path)
    monkeypatch.setattr(selfdev, "_verify", lambda: (True, "gruen"))
    monkeypatch.setattr(selfdev, "_request_restart", lambda which="all": None)
    monkeypatch.setattr(selfdev, "_git", lambda *a: None)
    return tmp_path


def test_edit_datei_liefert_diffstat_und_diff(monkeypatch, tmp_path):
    from core.agency.tools.code_tools import edit_datei
    root = _iso(monkeypatch, tmp_path)
    (root / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    out = edit_datei("mod.py", "return 1", "return 2")
    assert out.startswith("OK")
    assert "(+1 −1)" in out                 # Diffstat
    assert "```diff" in out and "+    return 2" in out and "-    return 1" in out


def test_self_edit_reicht_diff_durch(monkeypatch, tmp_path):
    from core.agency import selfdev
    from core.kernel import llm_router
    root = _iso(monkeypatch, tmp_path)
    (root / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(llm_router, "complete",
                        lambda *a, **k: {"text": "<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE"})
    r = selfdev.self_edit("mod.py", "gib 2 zurueck")
    assert r["ok"] and r["stat"] == (1, 1)
    assert "```diff" in r["diff"]


# ---- Live-Trace-Deckel: Edits ganz, Rest knapp ---------------------------------------

def test_trace_obs_zeigt_edit_diff_ganz():
    from core.agency import act
    long = "OK — x.py (+1 −1).\n```diff\n" + "\n".join(f"+z{i}" for i in range(60)) + "\n```"
    assert len(act._trace_obs("edit_datei", long)) == len(long)     # Edit: ganz
    assert len(act._trace_obs("self_edit", long)) == len(long)
    assert len(act._trace_obs("read_file", "x" * 5000)) == 260      # Rest: knapp


# ---- Frontend-Marker -----------------------------------------------------------------

def test_trace_ui_marker():
    from core.api.ui.script import SCRIPT
    from core.api.ui.css import HEAD_AND_CSS as CSS
    assert "TOOLMAP" in SCRIPT and "renderDiff" in SCRIPT and "traceTool" in SCRIPT
    assert "```diff" in SCRIPT                       # Diff-Erkennung im Obs
    assert ".tdiff .add" in CSS and ".tdiff .del" in CSS and ".trow" in CSS
