"""Eine Bitte ist keine Garantie — der Harness sagt die Verspätung selbst an.

Befund vom 28.07.2026, gemessen an der Ereignis-DB (nur Ereignisse ab dem 12.07., davor
ist alles mit Testrauschen vermischt):

  * 55 verpasste Termine gegen 49 gelaufene — mehr Wecker fallen aus, als klingeln.
  * Die mittlere Verspätung eines verpassten Termins liegt bei 8,1 Stunden. Keiner
    unter einer Stunde, 38 von 55 über sechs Stunden, der schlimmste 39,5 Stunden.
  * Am härtesten trifft es "Sunrise Schlafzimmer" (14 verpasst gegen 3 gelaufen) und
    das "Morgen-Briefing 08:00" (9 gegen 8).

Seit dem 27.07. steht im Auftrag eines nachgeholten Termins die Bitte: "Sag am Anfang
kurz, dass es nachgereicht ist." Von 8 nachweislich verspäteten Läufen hat das
Modell es in **0** Fällen getan — das Briefing von heute früh (1,4 Stunden zu spät)
begann mit "# Morgen-Briefing — Dienstag, 28.07.2026", als wäre es acht Uhr.

Das ist dieselbe Lehre wie in der Nacht davor: der Harness muss das schwache Modell
tragen. Was gesagt werden MUSS, sagt der Harness — nicht das Modell auf Zuruf.

Der Hinweis im Auftrag bleibt trotzdem stehen: er sorgt dafür, dass der INHALT stimmt
(kein "Guten Morgen" um 16 Uhr). Die Zeile hier sorgt dafür, dass die Ansage kommt.
"""
from __future__ import annotations

import datetime as dt
import time

import pytest

from core.agency.missions import cron


@pytest.fixture(autouse=True)
def _ereignis_tabelle():
    """run_job schreibt Ereignisse — ohne Tabelle wirft jeder Lauf."""
    from core.kernel import events
    events.init_db()


def _jetzt() -> float:
    """Fester Bezugspunkt — sonst wandert der Test über Mitternacht."""
    return dt.datetime(2026, 7, 28, 9, 27).timestamp()


class TestWannGesagtWird:
    def test_der_normale_takt_ist_kein_wort_wert(self):
        """Der Runner tickt alle 30 Minuten — bis dahin ist "zu spät" nur der Takt.
        In der Live-DB waren 7 der 8 verspäteten Läufe genau das (0,3–0,5 h)."""
        for minuten in (0, 5, 20, 30, 44):
            assert cron._verspaetungs_zeile(minuten, _jetzt(), "Text") == "", minuten

    @pytest.mark.parametrize("minuten", [45, 87, 210, 480, 2370])
    def test_darueber_wird_es_gesagt(self, minuten):
        zeile = cron._verspaetungs_zeile(minuten, _jetzt(), "Ein Briefing.")
        assert zeile.startswith("(nachgereicht")

    def test_die_faellige_uhrzeit_steht_drin(self):
        """87 Minuten vor 09:27 ist 08:00 — die Uhrzeit, die im Job-Label steht."""
        zeile = cron._verspaetungs_zeile(87, _jetzt(), "Ein Briefing.")
        assert "08:00" in zeile

    def test_der_echte_fall_von_heute_frueh(self):
        """Morgen-Briefing 08:00, gelaufen 09:27 — 1,4 Stunden zu spät."""
        zeile = cron._verspaetungs_zeile(87, _jetzt(), "# Morgen-Briefing — Dienstag, 28.07.2026")
        assert "08:00" in zeile and "87 Minuten" in zeile


class TestDemModellNichtInsWortFallen:
    """Ein starkes Modell befolgt den Hinweis im Auftrag durchaus. Sagt der Text es
    schon selbst, schweigt der Harness — sonst stünde es doppelt da."""

    @pytest.mark.parametrize("text", [
        "Nachgereicht: hier dein Briefing von heute früh.",
        "Das kommt verspätet — der Rechner war aus.",
        "Kleiner Nachtrag, eigentlich für 08:00 gedacht:",
        "Ich reiche das nachträglich nach.",
    ])
    def test_wer_es_selbst_sagt_bekommt_keine_zweite_ansage(self, text):
        assert cron._verspaetungs_zeile(480, _jetzt(), text) == ""

    def test_ein_beilaeufiges_wort_spaeter_im_text_zaehlt_nicht(self):
        """Nur der Anfang zählt — sonst schluckt ein 'zu spät' auf Seite drei die Ansage."""
        text = "Hier dein Briefing.\n\n" + "Fliesstext. " * 60 + "Der Zug war zu spaet."
        assert cron._verspaetungs_zeile(480, _jetzt(), text) != ""


class TestDauerLiestSichWieDeutsch:
    @pytest.mark.parametrize("minuten,erwartet", [
        (45, "45 Minuten"),
        (87, "87 Minuten"),
        (95, "1,6 Stunden"),
        (480, "8,0 Stunden"),
        (2370, "2 Tage"),
    ])
    def test_dauer(self, minuten, erwartet):
        assert cron._dauer_text(minuten) == erwartet

    def test_kein_englisches_dezimaltrennzeichen(self):
        assert "." not in cron._dauer_text(95)


class TestDerGanzeWeg:
    """Die Ansage muss dort ankommen, wo der Nutzer sie liest — und im Cockpit-Feed."""

    def _job(self) -> dict:
        return {"id": "t1", "label": "Morgen-Briefing 08:00", "prompt": "Fasse den Tag zusammen.",
                "schedule": {"type": "daily", "at": "08:00"}, "runs": []}

    def test_die_nachricht_an_den_nutzer_traegt_die_ansage(self, monkeypatch):
        gesendet: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t) or True)
        monkeypatch.setattr("core.agency.act.act", lambda *a, **k: {"text": "Heute steht X an."})
        cron.run_job(self._job(), verspaetet_min=210)
        assert gesendet, "es ging gar nichts raus"
        assert "nachgereicht" in gesendet[0]
        assert "Heute steht X an." in gesendet[0]

    def test_ein_puenktlicher_lauf_bleibt_unveraendert(self, monkeypatch):
        gesendet: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t) or True)
        monkeypatch.setattr("core.agency.act.act", lambda *a, **k: {"text": "Heute steht X an."})
        cron.run_job(self._job(), verspaetet_min=0)
        assert gesendet and "nachgereicht" not in gesendet[0]

    def test_auch_der_cockpit_eintrag_sagt_es(self, monkeypatch):
        gemeldet: list[tuple] = []
        monkeypatch.setattr(cron, "_notify", lambda t: True)
        monkeypatch.setattr(cron.events, "emit",
                            lambda typ, p=None, **k: gemeldet.append((typ, p or {})))
        monkeypatch.setattr("core.agency.act.act", lambda *a, **k: {"text": "Heute steht X an."})
        cron.run_job(self._job(), verspaetet_min=210)
        laeufe = [p for typ, p in gemeldet if typ == "cron_run"]
        assert laeufe and "nachgereicht" in str(laeufe[0].get("summary"))
        assert laeufe[0].get("verspaetet_min") == 210

    def test_klemmt_telegram_traegt_auch_der_puffer_die_ansage(self, monkeypatch):
        """Der Melde-Puffer ist der Ersatzweg — dort darf die Ansage nicht verlorengehen."""
        gemerkt: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: False)
        monkeypatch.setattr("core.agency.missions.melde.merken",
                            lambda t: gemerkt.append(t) or True)
        monkeypatch.setattr("core.agency.act.act", lambda *a, **k: {"text": "Heute steht X an."})
        cron.run_job(self._job(), verspaetet_min=210)
        assert gemerkt and "nachgereicht" in gemerkt[0]

    def test_der_auftrag_bittet_das_modell_weiterhin(self, monkeypatch):
        """Die Bitte bleibt: sie sorgt dafür, dass der INHALT stimmt (kein 'Guten
        Morgen' um 16 Uhr). Die Harness-Zeile ist die Garantie, nicht der Ersatz."""
        gesehen: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: True)
        monkeypatch.setattr("core.agency.act.act",
                            lambda p, *a, **k: gesehen.append(p) or {"text": "X"})
        cron.run_job(self._job(), verspaetet_min=210)
        assert gesehen and "NACHGEHOLT" in gesehen[0]
