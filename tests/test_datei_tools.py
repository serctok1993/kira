"""Harness-Haertung 10.07.: Datei-Tools loesen %ENV%-Pfade auf und lehren bei Fehlaufrufen.

Dokumentierte Fehlversuche kleiner Lokalmodelle: list_dir("%USERPROFILE%\\Desktop")
scheiterte woertlich; falsche Argumentnamen gaben nackte TypeErrors ohne Beispiel.
"""
from __future__ import annotations

import os

from core.agency.tools import builtin

# os.path.expandvars: %VAR% nur auf Windows, $VAR ueberall — Tests laufen auf beiden.
_VAR = "%KIRA_TEST_ORDNER%" if os.name == "nt" else "$KIRA_TEST_ORDNER"
_UNBEKANNT = "%NICHT_DA_XYZ_123%" if os.name == "nt" else "$NICHT_DA_XYZ_123"


def test_list_dir_expandiert_umgebungsvariable(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRA_TEST_ORDNER", str(tmp_path))
    (tmp_path / "hallo.txt").write_text("hi", encoding="utf-8")
    assert "hallo.txt" in builtin.list_dir(_VAR)


def test_read_file_expandiert_umgebungsvariable(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRA_TEST_ORDNER", str(tmp_path))
    (tmp_path / "notiz.txt").write_text("inhalt xyz", encoding="utf-8")
    assert "inhalt xyz" in builtin.read_file(f"{_VAR}/notiz.txt")


def test_write_file_expandiert_umgebungsvariable(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRA_TEST_ORDNER", str(tmp_path))
    out = builtin.write_file(f"{_VAR}/neu.md", "abc")
    assert "OK" in out
    assert (tmp_path / "neu.md").read_text(encoding="utf-8") == "abc"


def test_unbekannter_platzhalter_gibt_hinweis():
    out = builtin.list_dir(f"{_UNBEKANNT}/Desktop")
    assert "nicht gefunden" in out and "Platzhalter" in out


def test_lehrfehler_bei_falschen_argumenten():
    """Falsche/fehlende Argumente -> Meldung MIT korrektem Minimal-Beispiel, kein TypeError."""
    assert "Beispiel" in builtin.read_file(file="x.txt")   # falscher Arg-Name
    assert "Beispiel" in builtin.read_file()               # path fehlt
    assert "Beispiel" in builtin.write_file(path="x.md")   # content fehlt
    assert "Beispiel" in builtin.write_file(text="hallo")  # falscher Arg-Name
    assert "Beispiel" in builtin.append_file(path="x.md")  # content fehlt
    assert "Beispiel" in builtin.list_dir(dir="C:/")       # falscher Arg-Name
    assert "Beispiel" in builtin.make_dir()                # path fehlt


def test_list_dir_auf_datei_verweist_auf_read_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert "read_file" in builtin.list_dir(str(f))
