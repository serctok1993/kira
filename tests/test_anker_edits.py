"""P3 (Anker-Edits): edit_datei verzeiht Einrueckungs-Drift, Fehlschlaege LEHREN.

hashline-Muster aus dem grok-Selbststudium: ein roter Edit liefert FRISCHE Anker
(Zeilennummern + Zitat aus der echten Datei), damit das Modell direkt korrigiert
aufruft statt die Datei neu zu lesen (Kontext-Budget der kleinen Modelle!).
Deterministisch, ohne LLM, ohne Dateisystem — direkt auf selfdev._apply_edits.
"""
from __future__ import annotations

from core.agency.selfdev import _apply_edits

CODE = "def f():\n    if a:\n        tu_was()\n    return 1\n"


def test_exakter_match_bleibt_erste_wahl():
    new, err = _apply_edits(CODE, [("replace", "    return 1", "    return 2")])
    assert err is None and "    return 2" in new


def test_tolerantes_fenster_repariert_uniformen_drift():
    # das Modell liefert den Block 4 Spaces zu flach — Fenster matcht, REPLACE wandert mit
    new, err = _apply_edits(CODE, [("replace", "if a:\n    tu_was()",
                                    "if a and b:\n    tu_was()")])
    assert err is None
    assert "    if a and b:\n        tu_was()" in new
    assert "    return 1" in new                       # Rest der Datei unangetastet


def test_tolerant_greift_nur_bei_eindeutigem_fenster():
    zwei = "if a:\n    x()\ny = 0\nif a:\n    x()\n"
    new, err = _apply_edits(zwei, [("replace", "  if a:\n      x()", "if b:\n    x()")])
    assert new is None and "nicht eindeutig" in err
    assert "bis auf Einrueckung" in err and "Zeilen 1, 4" in err


def test_fehlschlag_zitiert_frische_anker():
    new, err = _apply_edits(CODE, [("replace", "    return 42", "    return 2")])
    assert new is None and "nicht gefunden" in err
    assert "WIRKLICH" in err and "return 1" in err     # Zitat aus der echten Datei
    assert "NICHT neu lesen" in err                    # die Anker-Regel steht im Fehler


def test_mehrdeutig_nennt_zeilen_und_beispiel_anker():
    zwei = "a = 1\nx = 0\na = 1\n"
    new, err = _apply_edits(zwei, [("replace", "a = 1", "a = 2")])
    assert new is None and "nicht eindeutig" in err
    assert "Zeilen 1, 3" in err
    assert "x = 0" in err                              # Beispiel-Anker mit Nachbarzeile


def test_manifest_traegt_die_anker_regel():
    from core.agency.tools import code_tools  # noqa: F401 -> registriert
    from core.agency.tools import registry

    schemas = {s["function"]["name"]: s for s in registry.tool_schemas()}
    desc = schemas["edit_datei"]["function"]["description"]
    assert "NICHT neu lesen" in desc and "Einrueckungs-Abweichungen" in desc
