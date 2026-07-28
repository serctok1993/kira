"""Lange Antworten kommen VOLLSTAENDIG an — Befund 28.07.2026.

Der Nutzer: "In Telegram kommen immer nur halbe Nachrichten durch."

Eine Ursache steckt in der Stueckelung: der Rohtext wurde hart bei 3800 Zeichen
geschnitten und erst DANACH nach HTML umgewandelt. Das Escaping macht ihn laenger
(& -> &amp;, < -> &lt;), und schon ab rund 2 % Sonderzeichen reisst ein Stueck
Telegrams 4096er-Grenze. Gemessen: ein 3800-Zeichen-Stueck mit Pfaden und Vergleichen
wird zu 5214 Zeichen — Telegram lehnt es ab, und der Notfall-Versand schickt es
unformatiert nach. Bei Codebloecken und Tabellen — Kiras Alltag — ist das der Normalfall.

Dazu schnitt der harte Schnitt mitten durch Woerter und Formatierungen.
"""
from __future__ import annotations

import pytest

from core.agency.connectors.telegram_bot import _stuecke, _tg_html

LIMIT = 4096


def _konvertiert(stueck: str) -> int:
    return len(_tg_html(stueck))


class TestLimitWirdEingehalten:
    @pytest.mark.parametrize("name,text", [
        ("viele Sonderzeichen", "Der Vergleich <alt> gegen <neu> & Pfade /a/b <-> /c/d. " * 200),
        ("Fliesstext", "Ein ganz normaler Satz ueber Kiras Arbeit an diesem Tag. " * 200),
        ("Absaetze", "## Abschnitt\n\nEin Absatz mit Inhalt.\n\n" * 150),
        ("eine Zeile ohne Luft", "x" * 12000),
        ("Codeblock", "`pfad/zu/datei.py` und <b>fett</b> & mehr\n" * 300),
    ])
    def test_kein_stueck_reisst_die_grenze(self, name, text):
        for s in _stuecke(text):
            assert _konvertiert(s) <= LIMIT, f"{name}: {_konvertiert(s)} Zeichen"

    def test_der_gemessene_live_fall(self):
        """3800 Rohzeichen mit Pfaden wurden zu 5214 HTML-Zeichen — abgelehnt."""
        text = "Der Vergleich <alt> gegen <neu> & die Pfade /a/b <-> /c/d. " * 90
        assert _konvertiert(text[:3800]) > LIMIT, "Testaufbau greift nicht mehr"
        for s in _stuecke(text):
            assert _konvertiert(s) <= LIMIT


class TestNichtsGehtVerloren:
    def test_der_inhalt_bleibt_vollstaendig(self):
        text = "Erster Absatz.\n\nZweiter Absatz mit <tag> und & Zeichen.\n\n" * 120
        zusammen = "".join(_stuecke(text))
        for wort in ("Erster", "Zweiter", "<tag>"):
            assert wort in zusammen

    def test_nichts_wird_doppelt_gesendet(self):
        text = "Eindeutiger Satz Nummer {}. ".format
        voll = "".join(text(i) for i in range(400))
        stuecke = _stuecke(voll)
        for i in range(400):
            assert sum(s.count(f"Nummer {i}.") for s in stuecke) == 1, i

    def test_leerer_text_ergibt_keine_leere_nachricht(self):
        assert _stuecke("") == []
        assert _stuecke("   \n  ") == []


class TestLesbareSchnitte:
    def test_wird_an_natuerlichen_grenzen_geschnitten(self):
        text = "Satz eins. Satz zwei. Satz drei. " * 300
        for s in _stuecke(text)[:-1]:
            assert s.rstrip()[-1] in ".!?", f"mitten im Satz: …{s[-30:]!r}"

    def test_absaetze_werden_bevorzugt(self):
        text = ("Ein Absatz mit etwas Text darin.\n\n" * 200)
        for s in _stuecke(text)[:-1]:
            assert s.rstrip().endswith("."), f"…{s[-30:]!r}"

    def test_kein_wort_wird_zerrissen(self):
        text = "unzerreissbareswortdasnichtgetrenntwerdendarf " * 300
        for s in _stuecke(text)[:-1]:
            assert s.rstrip().endswith("darf"), f"…{s[-30:]!r}"


class TestNormalfallBleibtGuenstig:
    """Der haeufigste Fall ist eine kurze Antwort — die darf kein Stueckeln sehen."""

    def test_kurze_nachricht_bleibt_ein_stueck(self):
        assert _stuecke("Hallo, hier ist dein Briefing.") == ["Hallo, hier ist dein Briefing."]

    def test_mittlere_nachricht_bleibt_ein_stueck(self):
        text = "a " * 1500          # 3000 Zeichen, keine Sonderzeichen
        assert len(_stuecke(text)) == 1

    def test_plain_modus_rechnet_ohne_html_aufschlag(self):
        """Ohne HTML gibt es kein Escaping — dann passt mehr in ein Stueck."""
        text = "<&>" * 1300         # 3900 Zeichen, als HTML weit ueber Limit
        assert len(_stuecke(text, html=False)) == 1
        assert len(_stuecke(text, html=True)) > 1
