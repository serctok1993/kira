"""Was der 92er-Katalog der Werkstatt am Harness gezeigt hat (28.07.2026).

Der Lauf erreichte 67 von 92 (bereinigt ~76 %). Stark: Deutsch 10/10, Grenzen 9/10.
Schwach: Alltag 8/12 — und dort steckten zwei Fehler, die kein Training heilt, weil
sie gar nicht am Modell liegen.

**Aufgabe 001 — der Wochentag.** Auf „Trag mir Donnerstag 14 Uhr ein" antwortete das
Modell, es gebe „zwei Donnerstage im Juli (30. und 6. August)", und fragte zurück
statt einzutragen. Der Harness löst `heute/morgen/uebermorgen` seit PR #190 auf —
Wochentage nicht. Schlimmer: im Vertrag von `termin_add` stand nur
„TT.MM.JJJJ, z.B. 15.08.2026". Das Modell wusste also gar nicht, dass es relative
Angaben durchreichen darf, und rechnete deshalb selbst.

Beides gehört zusammen: die Auflösung UND der Vertrag, der sie anbietet.

**Aufgabe 082 — der falsche Name.** Das Modell rief `find_files`; das Werkzeug heißt
`datei_finden`. Der Lehrfehler griff („existiert nicht"), aber das Modell stellte
danach nicht um — die Liste aller 77 Werkzeuge ist zu lang, um daraus den einen zu
finden. Ein Vorschlag ist billiger als eine Liste.
"""
from __future__ import annotations

import datetime

import pytest

import core.agency.tools.builtin  # noqa: F401 — Registrierung ausloesen
import core.agency.tools.life_tools  # noqa: F401
import core.agency.tools.termin_tools  # noqa: F401
from core.agency import act, termine
from core.agency.tools import registry


def _di() -> datetime.date:
    """Dienstag, 28.07.2026 — der Tag des Katalog-Laufs."""
    return datetime.date(2026, 7, 28)


class TestWochentageLoestDerHarnessAuf:
    @pytest.mark.parametrize("eingabe,erwartet", [
        ("Donnerstag", "30.07.2026"),
        ("donnerstag", "30.07.2026"),
        ("Do", "30.07.2026"),
        ("am Montag", "03.08.2026"),
        ("Sonnabend", "01.08.2026"),
        ("Sonntag", "02.08.2026"),
    ])
    def test_der_naechste_passende_tag(self, eingabe, erwartet):
        assert termine._wochentag_aufloesen(eingabe.lower(), _di()) == erwartet

    def test_heute_ist_gemeint_wenn_der_tag_heute_ist(self):
        """Dienstag, gesagt an einem Dienstag: das ist heute, nicht in einer Woche."""
        assert termine._wochentag_aufloesen("dienstag", _di()) == "28.07.2026"

    def test_naechsten_schiebt_um_eine_woche(self):
        """Nur DA unterscheiden sich die beiden Formen — sonst sind sie gleich."""
        assert termine._wochentag_aufloesen("naechsten dienstag", _di()) == "04.08.2026"
        assert termine._wochentag_aufloesen("nächsten dienstag", _di()) == "04.08.2026"

    def test_naechsten_aendert_nichts_an_einem_anderen_tag(self):
        assert termine._wochentag_aufloesen("naechsten donnerstag", _di()) == "30.07.2026"

    @pytest.mark.parametrize("text", ["Blafasel", "15.08.2026", "", "irgendwann", "Montagabend"])
    def test_alles_andere_bleibt_unberuehrt(self, text):
        assert termine.datum_aufloesen(text) == text.strip()

    def test_die_alten_relativangaben_funktionieren_weiter(self):
        heute = datetime.date.today()
        assert termine.datum_aufloesen("heute") == heute.strftime("%d.%m.%Y")
        assert termine.datum_aufloesen("morgen") == \
            (heute + datetime.timedelta(days=1)).strftime("%d.%m.%Y")


class TestDerVertragBietetEsAn:
    """Die Auflösung nützt nichts, wenn das Modell nicht weiß, dass es sie nutzen darf.
    Genau das war der Zustand: der Harness konnte heute/morgen, der Vertrag schwieg."""

    @pytest.mark.parametrize("werkzeug", ["termin_add", "erinnerung", "termin_update"])
    def test_das_datumsfeld_nennt_wochentage(self, werkzeug):
        t = registry.get(werkzeug)
        assert t, f"{werkzeug} ist nicht registriert"
        beschreibung = str(t.params.get("datum", ""))
        assert "Wochentag" in beschreibung or "Donnerstag" in beschreibung
        assert "heute/morgen" in beschreibung

    def test_das_datumsfeld_sagt_dass_nicht_gerechnet_werden_soll(self):
        assert "rechne NICHT selbst" in str(registry.get("termin_add").params["datum"])


class TestDerFehlertextLehrtDieEchtenTage:
    """Ein Modell, dem man „Format TT.MM.JJJJ" sagt, rechnet weiter selbst."""

    def test_die_hilfe_nennt_konkrete_daten(self):
        hilfe = termine.datums_hilfe()
        assert "Heute ist" in hilfe
        for tag in ("Montag", "Donnerstag", "Sonntag"):
            assert tag in hilfe
        assert hilfe.count(".2026") >= 7, "die konkreten Daten fehlen"

    def test_ein_kaputtes_datum_bekommt_die_hilfe(self):
        antwort = termine.add("irgendwann", "Zahnarzt")
        assert antwort["ok"] is False
        assert "Heute ist" in antwort["error"] and "Donnerstag" in antwort["error"]


class TestMeintestDu:
    """Aufgabe 082: find_files -> das Werkzeug heisst datei_finden."""

    def _alle(self) -> list[str]:
        return sorted(t.name for t in registry.all_tools())

    @pytest.mark.parametrize("falsch,erwartet", [
        ("find_files", "datei_finden"),
        ("list_files", "list_dir"),
        ("termin_delete", "termin_remove"),
        ("add_todo", "todo_add"),
        ("termin_updat", "termin_update"),
    ])
    def test_der_richtige_name_wird_vorgeschlagen(self, falsch, erwartet):
        assert erwartet in act._meintest_du(falsch, self._alle())

    @pytest.mark.parametrize("falsch", [
        pytest.param("send_telegram", id="es-gibt-kein-sende-werkzeug"),
        pytest.param("xyzzy", id="voelliger-unsinn"),
        pytest.param("", id="leer"),
    ])
    def test_lieber_kein_vorschlag_als_ein_falscher(self, falsch):
        """Ein falscher Vorschlag ist schlimmer als keiner: aus "send_telegram" wurde
        bei zu lockerer Schwelle "email_send" — das Modell haette eine Mail verschickt,
        statt einfach zu antworten."""
        assert act._meintest_du(falsch, self._alle()) == ""

    def test_ohne_werkzeugliste_kein_absturz(self):
        assert act._meintest_du("irgendwas", []) == ""
        assert act._meintest_du("irgendwas", None) == ""

    def test_jede_existiert_nicht_stelle_schlaegt_einen_namen_vor(self):
        """Er muss dort auftauchen, wo das Modell ihn liest — auf ALLEN drei Pfaden
        (ACT-Text, nativer Cloud-Loop, Chat). Genau solche Teil-Abdeckungen waren in
        der Nacht davor mehrfach das Problem."""
        import inspect
        import re as _re

        quelle = inspect.getsource(act)
        stellen = [m.start() for m in _re.finditer(r"existiert nicht\.", quelle)
                   if "obs" in quelle[max(0, m.start() - 120):m.start()]]
        assert len(stellen) >= 3, f"nur {len(stellen)} Fehlerstellen gefunden"
        for pos in stellen:
            umfeld = quelle[pos:pos + 260]
            assert "_meintest_du(" in umfeld, \
                f"ohne Namensvorschlag: …{quelle[pos:pos + 90]}…"
