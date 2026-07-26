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


# --- Umbenennen / Loeschen (Live-Fund 22.07.: beides fehlte komplett) ----------------
# Kern der Pruefung: delete_file VERNICHTET NIE — es raeumt in den Papierkorb, und der
# in der Antwort genannte Rueckweg muss wirklich funktionieren.
import pathlib
import re

from core.config import DATA_DIR, MIND_DIR, ROOT


def test_move_file_benennt_um(tmp_path):
    alt = tmp_path / "alt.md"
    alt.write_text("inhalt", encoding="utf-8")
    out = builtin.move_file(str(alt), str(tmp_path / "neu.md"))
    assert "OK" in out
    assert not alt.exists()
    assert (tmp_path / "neu.md").read_text(encoding="utf-8") == "inhalt"


def test_move_file_verschiebt_in_vorhandenen_ordner(tmp_path):
    q = tmp_path / "datei.txt"
    q.write_text("x", encoding="utf-8")
    ordner = tmp_path / "ziel"
    ordner.mkdir()
    assert "OK" in builtin.move_file(str(q), str(ordner))
    assert (ordner / "datei.txt").exists()


def test_move_file_ueberschreibt_belegtes_ziel_nie(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("A", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("B", encoding="utf-8")
    out = builtin.move_file(str(a), str(b))
    assert "gibt es schon" in out
    assert b.read_text(encoding="utf-8") == "B" and a.exists()


def test_delete_file_raeumt_in_papierkorb_und_rueckweg_traegt(tmp_path):
    f = tmp_path / "weg.md"
    f.write_text("bitte weg", encoding="utf-8")
    out = builtin.delete_file(str(f))
    assert "Papierkorb" in out and not f.exists()
    treffer = re.search(r'quelle="([^"]+)"', out)
    assert treffer, f"Rueckweg fehlt in der Antwort: {out}"
    kopie = pathlib.Path(treffer.group(1))
    assert kopie.exists() and kopie.read_text(encoding="utf-8") == "bitte weg"
    assert "OK" in builtin.move_file(str(kopie), str(f))
    assert f.read_text(encoding="utf-8") == "bitte weg"


def test_delete_file_ordner_nennt_inhalt(tmp_path):
    d = tmp_path / "kram"
    d.mkdir()
    (d / "a.txt").write_text("1", encoding="utf-8")
    out = builtin.delete_file(str(d))
    assert "Ordner" in out and "Eintraegen" in out and not d.exists()


def test_delete_file_blockiert_kern():
    out = builtin.delete_file(str(ROOT / "core" / "agency" / "verifier.py"))
    assert "BLOCKIERT" in out and "Kern" in out


def test_move_file_blockiert_kern(tmp_path):
    out = builtin.move_file(str(ROOT / "core" / "agency" / "verifier.py"),
                            str(tmp_path / "verifier-alt.py"))
    assert "BLOCKIERT" in out and "Kern" in out
    assert (ROOT / "core" / "agency" / "verifier.py").exists()


def test_delete_file_blockiert_verfassung():
    out = builtin.delete_file(str(MIND_DIR / "constitution.md"))
    assert "BLOCKIERT" in out and "Verfassung" in out


def test_delete_file_blockiert_den_papierkorb_selbst():
    sicherung = pathlib.Path(DATA_DIR) / "backups" / "papierkorb"
    sicherung.mkdir(parents=True, exist_ok=True)
    out = builtin.delete_file(str(sicherung))
    assert "BLOCKIERT" in out and "Sicherungs-Ordner" in out
    assert sicherung.exists()


def test_neue_datei_werkzeuge_lehren_statt_zu_crashen():
    assert "Falscher Aufruf" in builtin.move_file()
    assert "quelle" in builtin.move_file()
    assert "Falscher Aufruf" in builtin.delete_file(pfad="C:/tmp/x.md")


def test_neue_datei_werkzeuge_sind_registriert():
    from core.agency.tools import registry

    namen = {t.name for t in registry.all_tools()}
    assert {"move_file", "delete_file"} <= namen


def test_move_file_darf_den_papierkorb_selbst_nicht_wegtragen(tmp_path):
    korb = pathlib.Path(DATA_DIR) / "backups" / "papierkorb"
    korb.mkdir(parents=True, exist_ok=True)
    out = builtin.move_file(str(korb), str(tmp_path / "geklaut"))
    assert "BLOCKIERT" in out and korb.exists()


def test_move_file_verweigert_ablage_im_sicherungsordner(tmp_path):
    f = tmp_path / "heimlich.md"
    f.write_text("x", encoding="utf-8")
    ziel = pathlib.Path(DATA_DIR) / "backups" / "papierkorb" / "heimlich.md"
    out = builtin.move_file(str(f), str(ziel))
    assert "BLOCKIERT" in out and f.exists()
