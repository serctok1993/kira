"""Beweispflicht III: erfundene Aussen-Fakten (Katalog-Befund 28.07.2026, Fall [049]).

Zwei Antworten des 92er-Katalogs klingen kompetent und sind frei erfunden. Die
schwerere:

    „Es wird morgen 17 Grad Sonne und ein Windgeschwindigkeitsmaximum
     von 20 Kilometern pro Stunde erwartet."

Keine Suche, kein Werkzeug. Für ein Produkt ist das teurer als ein nicht erledigter
Auftrag: einen fehlenden Termin merkt der Nutzer, eine erfundene Wettervorhersage
nicht. Die vorhandene Beweispflicht greift hier nicht — sie hört auf
„eingetragen/gemerkt/erledigt", nicht auf Zahlen.

WARUM SO ENG
Der naheliegende Auslöser „konkrete Zahlen und Messwerte" wäre unbrauchbar: **182 von
412** zugestellten Antworten (44 %) enthalten eine Zahl. Ein solcher Wächter feuerte
bei fast jeder zweiten Antwort — genau der Fehler, den die Werkstatt bei ihrer eigenen
Bewertung gemacht hat, als sie „3 Tage bis Monatsende" als Fehlschlag zählte.

Getroffen wird deshalb nur, was ohne Nachschlagen **nicht zu wissen ist**: ein Zustand
der Außenwelt zu einem bestimmten Zeitpunkt. Sachgebiet und Zeitbezug müssen
zusammenkommen. Am Live-Korpus feuert das bei 2 von 412 Antworten (0,5 %) — und beide
sind die echten Erfindungen.

WAS BEWUSST NICHT GETROFFEN WIRD
Der zweite gemeldete Fall — „In meiner SOUL.md steht…" ohne die Datei zu lesen — ist
kein Harness-Loch: SOUL, GOAL und PERSONA stehen **vollständig im System-Prompt**
(nachgemessen: 20.383 Zeichen, Abschnitt „# DEINE SEELE" mit dem echten Text). Daraus
zu zitieren braucht kein Werkzeug. Was dort schiefging, war ein *Fehlzitat* — ein
Modell-Problem und ein c10-Drill, keine fehlende Wache. Ein Wächter, der dafür einen
Dateizugriff verlangt, würde ein Lesen erzwingen für etwas, das schon im Prompt steht.
"""
from __future__ import annotations

import pytest

from core.agency import act


class TestWasNachgeschlagenWerdenMuss:
    @pytest.mark.parametrize("text", [
        pytest.param("Es wird morgen 17 Grad Sonne und ein "
                     "Windgeschwindigkeitsmaximum von 20 km/h erwartet.", id="der-echte-fall-049"),
        pytest.param("Morgen ist es in Berlin meist bewölkt, vereinzelt leichter Regen.",
                     id="wetter-ohne-zahl"),
        pytest.param("Heute sind es 24 Grad bei viel Sonne.", id="wetter-heute"),
        pytest.param("Der Kurs liegt gerade bei 61.400 Euro.", id="kurs-jetzt"),
        pytest.param("Aktuell kostet das Ticket 89 Euro.", id="preis-aktuell"),
    ])
    def test_wird_erkannt(self, text):
        assert act._behauptet_aussenfakt(text) is not None


class TestWasKiraOhneNachschlagenWeiss:
    """Die zehn Gegenproben stehen für den Löwenanteil aller Antworten. Feuert der
    Wächter hier, ist er unbrauchbar — dann bremst er gute Modelle bei jeder zweiten
    Antwort, und genau das war die Sorge bei der breiten Fassung."""

    @pytest.mark.parametrize("text", [
        pytest.param("Bis zum Monatsende sind noch 3 Tage.", id="rechnen"),
        pytest.param("Dein Zahnarzttermin ist am 06.08. um 09:00.", id="aus-dem-kalender"),
        pytest.param("Ich habe 5 Vorschläge für dich.", id="selbstbezug"),
        pytest.param("Wasser kocht bei 100 Grad.", id="allgemeinwissen-mit-grad"),
        pytest.param("Das Paket kostet 49, 99 oder 199 Euro je nach Umfang.",
                     id="eigene-preise-ohne-zeitbezug"),
        pytest.param("Ein Tag hat 24 Stunden, das sind 1440 Minuten.", id="mathematik"),
        pytest.param("Heute ist Dienstag, der 28.07.2026.", id="datum-aus-der-jetzt-zeile"),
        pytest.param("Ich schaue morgen nochmal in den Kalender.", id="ankuendigung"),
        pytest.param("Das Sonnenlicht enthält alle Farben des Regenbogens.", id="physik"),
        pytest.param("Der korrekte Satz lautet: 'Gestern bin ich in die Stadt gegangen.'",
                     id="grammatik"),
    ])
    def test_wird_nicht_erkannt(self, text):
        assert act._behauptet_aussenfakt(text) is None

    def test_ein_soul_zitat_ist_kein_aussen_fakt(self):
        """SOUL steht im Prompt — daraus zu zitieren braucht kein Werkzeug."""
        assert act._behauptet_aussenfakt(
            "In meiner SOUL.md stehe ich als Kira — weiblich, Partnerin: nicht "
            "Assistentin, nicht Boss.") is None

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_leeres_bringt_nichts_durcheinander(self, text):
        assert act._behauptet_aussenfakt(text) is None

    def test_sehr_lange_texte_werden_uebersprungen(self):
        """Ein Dossier ist keine Behauptung im Vorbeigehen — und die Suche darf den
        Zug nicht aufhalten."""
        assert act._behauptet_aussenfakt("Heute 20 Grad. " + "Fliesstext. " * 500) is None


class TestDieRueckfrage:
    def test_sie_nennt_die_stelle_und_den_ausweg(self):
        text = act.aussenfakt_nachfrage("morgen 17 Grad Sonne")
        assert "morgen 17 Grad Sonne" in text
        assert "web_search" in text
        assert "nicht weisst" in text

    def test_der_native_pfad_nennt_kein_act_werkzeug(self):
        """Dort gibt es kein ACT — derselbe Unterschied wie bei Beweispflicht II."""
        assert "web_search" not in act.aussenfakt_nachfrage("x", nativ=True)
        assert "Suche" in act.aussenfakt_nachfrage("x", nativ=True)


class TestAlleDreiPfadeSindGeschuetzt:
    """Chat, Missionspfad und nativer Cloud-Loop — Teilabdeckung war in diesem Harness
    schon mehrfach die Ursache (der Missionspfad hatte Stups und Beweispflicht II
    monatelang gar nicht)."""

    def test_jeder_pfad_prueft_auf_aussen_fakten(self):
        import inspect

        quelle = inspect.getsource(act)
        assert quelle.count("_behauptet_aussenfakt(text)") == 3

    def test_hoechstens_eine_rueckfrage_pro_zug(self):
        """Beweispflicht II und III teilen sich die Fahne — sonst kostet ein Zug zwei
        Zusatzaufrufe."""
        import inspect
        import re

        quelle = inspect.getsource(act)
        for m in re.finditer(r"_behauptet_aussenfakt\(text\)", quelle):
            davor = quelle[max(0, m.start() - 160):m.start()]
            assert "beweis_nachgefragt" in davor, \
                "die Aussenfakt-Pruefung haengt nicht an der gemeinsamen Fahne"

    def test_wer_recherchiert_hat_wird_nie_gefragt(self):
        """Die Fahne used_tools schuetzt jede Antwort, der eine Suche vorausging."""
        import inspect
        import re

        quelle = inspect.getsource(act)
        for m in re.finditer(r"_behauptet_aussenfakt\(text\)", quelle):
            zeile = quelle[quelle.rfind("\n", 0, m.start()):m.end()]
            assert "used_tools" in zeile
