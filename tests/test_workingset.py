"""Stufe 2e: Working-Set-Scratchpad — reines Datei-Modul, offline."""
from __future__ import annotations

from core.agency.missions import workingset


def _use_tmp_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(workingset, "_DIR", tmp_path / "workspace")


def test_append_render_roundtrip(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    assert workingset.render("obj1") == ""  # noch keine Datei -> leer, kein Crash
    workingset.append("obj1", "[85/pass] Hosting recherchiert -> Anbieter B empfohlen")
    workingset.append("obj1", "[40/retry] Preisvergleich -> Quellen fehlten")
    out = workingset.render("obj1")
    assert "Anbieter B empfohlen" in out and "Quellen fehlten" in out
    assert out.index("Anbieter B") < out.index("Quellen fehlten")  # chronologisch


def test_objectives_are_separate_files(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    workingset.append("obj1", "Zeile fuer Ziel 1")
    workingset.append("obj2", "Zeile fuer Ziel 2")
    assert "Ziel 2" not in workingset.render("obj1")
    assert "Ziel 1" not in workingset.render("obj2")


def test_filename_is_sanitized(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    p = workingset.path_for("../böse/../id!")
    assert p.parent == workingset._DIR  # kein Pfad-Ausbruch
    assert p.name == "objective-bseid.md"


def test_trim_keeps_newest(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(workingset, "_MAX_BYTES", 600)
    for i in range(40):
        workingset.append("obj1", f"Eintrag Nummer {i:03d} " + "fuellstoff " * 3)
    raw = workingset.path_for("obj1").read_text(encoding="utf-8")
    assert len(raw.encode("utf-8")) <= 600
    assert "Eintrag Nummer 039" in raw   # das Neueste bleibt
    assert "Eintrag Nummer 000" not in raw  # das Aelteste faellt weg
    assert raw.startswith("[")  # Trim schneidet an Zeilengrenzen


def test_render_tail_respects_max_chars(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    for i in range(30):
        workingset.append("obj1", f"Eintrag {i:02d} " + "x" * 50)
    out = workingset.render("obj1", max_chars=200)
    assert len(out) <= 200
    assert "Eintrag 29" in out
    assert not out.startswith("x")  # beginnt an einer Zeilengrenze
