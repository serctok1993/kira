"""P4 (Symbol-Navigation): code_symbol + code_umriss — ast-Index mit mtime-Cache.

Der groesste Kontext-Hebel fuer kleine Modelle: EINE praezise Antwort statt
Datei-Raten. Offline, tmp-ROOT, 0 Abhaengigkeiten (reines ast der stdlib).
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture()
def projekt(monkeypatch, tmp_path):
    from core.agency.tools import code_tools
    monkeypatch.setattr(code_tools, "ROOT", tmp_path)
    monkeypatch.setattr(code_tools, "_SYM_CACHE", {})
    (tmp_path / "kern.py").write_text(
        '"""Kern-Modul."""\n'
        "LIMIT = 5\n\n\n"
        "class Motor:\n"
        '    """Treibt alles an."""\n\n'
        "    def start(self, kraft=1):\n"
        "        return kraft\n\n\n"
        "def helfer(x):\n"
        "    return x + LIMIT\n", encoding="utf-8")
    (tmp_path / "nutzer.py").write_text(
        "from kern import Motor, helfer\n\n"
        "m = Motor()\n"
        "m.start(2)\n"
        "print(helfer(1))\n", encoding="utf-8")
    (tmp_path / "kaputt.py").write_text("def offen(:\n", encoding="utf-8")
    return tmp_path


def test_symbol_findet_definition_und_verwendungen(projekt):
    from core.agency.tools.code_tools import code_symbol
    out = code_symbol("helfer")
    assert "DEFINITION:" in out and "kern.py:12  def helfer(x)" in out
    assert "VERWENDUNGEN" in out and "nutzer.py" in out
    out = code_symbol("start")                      # Methode: Definition + Attribut-Aufruf
    assert "def start(self, kraft=1)" in out and "nutzer.py: 4" in out
    assert "LIMIT = " in code_symbol("LIMIT")       # Modul-Konstante als Definition


def test_symbol_lehrt_bei_tippfehler(projekt):
    from core.agency.tools.code_tools import code_symbol
    out = code_symbol("helferr")
    assert "nicht gefunden" in out and "helfer" in out and "exakten Namen" in out
    assert "Kein Symbolname" in code_symbol("  ")


def test_symbol_cache_invalidiert_bei_aenderung(projekt):
    from core.agency.tools.code_tools import code_symbol
    assert "nicht gefunden" in code_symbol("neuling")
    f = projekt / "kern.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n\ndef neuling():\n    pass\n",
                 encoding="utf-8")
    st = f.stat()
    os.utime(f, (st.st_atime + 10, st.st_mtime + 10))   # mtime-Sprung erzwingen
    assert "def neuling()" in code_symbol("neuling")


def test_umriss_zeigt_landkarte(projekt):
    from core.agency.tools.code_tools import code_umriss
    out = code_umriss("kern.py")
    assert out.startswith("kern.py — ")
    assert "class Motor" in out and '"Treibt alles an."' in out
    assert "def start(self, kraft=1)" in out and "def helfer(x)" in out
    assert "LIMIT = " in out


def test_umriss_lehrende_grenzen(projekt):
    from core.agency.tools.code_tools import code_umriss
    assert "nicht gefunden" in code_umriss("fehlt.py")
    assert "ausserhalb" in code_umriss("/etc/passwd")
    out = code_umriss("kaputt.py")
    assert "Syntaxfehler" in out and "kaputt.py" in out and "Zeile 1" in out
    (projekt / "notiz.md").write_text("# x\n", encoding="utf-8")
    assert "keine Python-Datei" in code_umriss("notiz.md")


def test_werkzeuge_im_manifest_und_regeln():
    from core.agency import act
    from core.agency.tools import code_tools  # noqa: F401 -> registriert
    from core.agency.tools import registry
    namen = [t.name for t in registry.all_tools(include_disabled=True)]
    assert "code_symbol" in namen and "code_umriss" in namen
    # CODING-REGELN lehren die Navigations-Reihenfolge, der RBE-Guard kennt beide
    assert "code_symbol" in act._CODING_REGELN and "code_umriss" in act._CODING_REGELN


def test_rbe_guard_schreibt_navigation_gut(monkeypatch, tmp_path):
    from core.agency import act
    monkeypatch.setattr(act, "_SEEN_FILES", {})
    act._rbe_record("s1", "code_symbol", {"name": "foo"}, "core/x.py:3  def foo()\n")
    assert "core/x.py" in act._rbe_seen("s1")
    act._rbe_record("s1", "code_umriss", {"pfad": "core/y.py"}, "core/y.py — 9 Zeilen")
    assert "core/y.py" in act._rbe_seen("s1")
