"""Trainingsvertrag-Wache (harness-seitig): die Wortlaute, auf die die LLM-Werkstatt
trainiert, duerfen sich nie STILL aendern.

Zweiter Gurt zum Werkstatt-Generator (der importiert/ankert dieselben Texte und
faellt bei Drift laut um — aber erst bei der naechsten Generierung; dieser Test
bricht schon im PR). Live-Beweis fuer den Bedarf: c1-c4 trainierten ein
Observation-Format, das die Produktion nie sprach (c5-Audit, 16.07.).

Aenderung hier gewollt? Dann Text UND Test anpassen + Werkstatt-Meldung
(Kategorie im Vertrag: Ergebnis-Rueckgabeformat / ACT-Protokoll / Nudge).
"""
from __future__ import annotations

from pathlib import Path

from core.agency import act

SRC = Path(act.__file__).read_text(encoding="utf-8")


def test_observation_wrapper_wortlaut():
    # Punkt 5 des Vertrags: das Ergebnis-Rueckgabeformat an das LLM — in BEIDEN
    # ACT-Schleifen (act + act_chat) identisch.
    assert SRC.count('f"ERGEBNIS von {name}:\\n{obs}\\n\\nMach weiter oder gib die finale Antwort."') == 2


def test_act_protokollzeile_und_beispiele():
    assert SRC.count('ACT <werkzeug_name> {{"argument": "wert"}}') == 2
    assert 'Beispiel: ACT web_fetch {{"url": "https://example.com"}}' in SRC
    assert 'Beispiel: ACT web_search {{"query": "Wetter Berlin heute"}}' in SRC


def test_nudge_und_zwangsabschluss_wortlaute():
    # der Anti-Ankuendigungs-Stups (beide Pfade) + die Schrittlimit-Abschluesse
    assert SRC.count("Der Auftrag liegt bereits vor —") >= 2
    assert "Nicht ankuendigen, nicht zurueckfragen." in SRC
    assert "Du hast genug recherchiert." in SRC
    assert "Fasse jetzt final fuer" in SRC


def test_hauptrollen_weiche_im_chat_pfad():
    # der lokale Chat baut das kuratierte haupt-Manifest, act() filtert nach Rolle —
    # und es gibt KEIN drittes, ungefiltertes manifest() im Prompt-Bau
    assert 'registry.manifest(nur=_hrollen.toolset("haupt"))' in SRC
    assert "registry.manifest(nur=erlaubt)" in SRC
    assert SRC.count("registry.manifest()") == 0
