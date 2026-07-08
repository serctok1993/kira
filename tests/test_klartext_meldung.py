"""Klartext-Meldungen (Sergens Fund 08.07.): Telegram bekommt den 'KURZ FUER SERGEN'-
Block statt 1200 roher Zeichen, die mitten im Satz abreissen."""
from __future__ import annotations

from core.agency.missions import runner


def test_attempt_prompt_verlangt_kurzblock():
    p = runner._attempt_prompt({"id": "t1", "description": "Analysiere Fallstudie X"},
                               criteria=[{"text": "vollstaendig"}], attempt=1)
    assert "KURZ FUER SERGEN" in p and "einfacher Sprache" in p
    assert "Analysiere Fallstudie X" in p


def test_report_nimmt_kurzblock():
    text = ("Lange Analyse mit Tabellen und Details ..." + "x" * 2000
            + "\n\n**KURZ FUER SERGEN:**\nGatherUp verdient Geld, indem es Bewertungen "
              "automatisch nach jedem Kundenkontakt anfragt. Fuer uns heisst das: "
              "die Anbindung an Google My Business ist Pflicht. Naechster Schritt: Preischeck.")
    out = runner._report("Fallstudien-Synthese", text, " (Score 100)")
    assert out.startswith("🤖 Mission-Schritt erledigt (Score 100):")
    assert "GatherUp verdient Geld" in out and "Naechster Schritt" in out
    assert "Lange Analyse" not in out                      # Roh-Dump bleibt draussen
    assert "Volltext im Cockpit" in out


def test_report_fallback_kappt_am_satzende():
    text = ("Erster Satz mit Inhalt. " * 60)               # kein Kurzblock, sehr lang
    out = runner._report("Task", text)
    assert "[…]" in out and len(out) < 1100
    kern = out.split("\n\n")[1]                            # Body zwischen Kopf und Volltext-Zeile
    assert kern.endswith("[…]") and ". […]" in kern        # Satzgrenze, kein Wort-Abriss


def test_report_kurzblock_varianten():
    for marker in ("KURZ FUER SERGEN:", "Kurz für Sergen:", "KURZ FÜR SERGEN"):
        out = runner._report("T", f"Blabla vorher.\n{marker}\nDrei klare Saetze.")
        assert "Drei klare Saetze." in out and "Blabla" not in out
