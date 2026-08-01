"""Resonanz: was zu einem Thema wirklich ankommt — und was das Werkzeug NICHT tut.

Gegenstück zu web_search. Die Suche beantwortet „was gibt es dazu", Resonanz „worüber
wird geredet und was davon trägt" — gemessen an Upvotes und Kommentaren.

WAS AM 29.07.2026 GEMESSEN WURDE, bevor eine Zeile davon gebaut war:

  * **Hacker News** läuft ohne alles — kein Schlüssel, kein Konto. Probe „local llm":
    10 Treffer mit Punkten und Kommentaren.
  * **Reddit** ist zu. Die öffentliche `search.json` antwortet mit 403, Server
    `snooserv` — Reddits eigene Sperre, kein Rate-Limit. Alle Varianten (www, old,
    `/r/<sub>/top.json`) liefern dieselbe Sperrseite. Nur noch mit eigenen
    App-Zugangsdaten erreichbar.
  * **Bluesky** — 403 von einem CDN-Knoten, nicht von der API.
  * **Lemmy** — erreichbar, aber die Suche ignoriert die Anfrage: bei `sort=Relevance`
    null Treffer, bei `TopMonth` einer von vier thematisch passend. Verworfen. Rauschen
    ist in einem Werkzeug, dessen ganzer Wert Signal ist, schlimmer als eine Lücke.

Die Tests hier gehen NIE ins Netz — CI läuft offline, und ein Test, der von einer
fremden API abhängt, misst deren Verfügbarkeit statt unseren Code.
"""
from __future__ import annotations

import time

import pytest

import core.agency.tools.builtin  # noqa: F401 — Registrierung ausloesen
from core.agency import resonanz
from core.agency.tools import registry


class _Antwort:
    def __init__(self, code: int, daten: dict | None = None):
        self.status_code = code
        self._daten = daten or {}

    def json(self) -> dict:
        return self._daten


def _hn_treffer(n: int = 3) -> dict:
    jetzt = int(time.time())
    return {"hits": [
        {"title": f"Beitrag {i}", "points": 10 * i, "num_comments": i,
         "created_at_i": jetzt - 3600, "objectID": str(i), "url": f"https://example.com/{i}"}
        for i in range(1, n + 1)]}


@pytest.fixture(autouse=True)
def _kein_netz_und_keine_events(monkeypatch):
    """Nichts geht raus — weder ins Netz noch in die Ereignis-DB."""
    monkeypatch.setattr(resonanz.events, "emit", lambda *a, **k: None)
    monkeypatch.setattr(resonanz, "_reddit_token", lambda: "")


class TestDieFirewallGehtVor:
    def test_ohne_netz_wird_nichts_erfunden(self, monkeypatch):
        """Im Benchmark/Sandbox-Lauf gibt es keine Zahlen — dann muss das Werkzeug es
        SAGEN, nicht schweigen. Ein Modell, das eine leere Antwort bekommt, füllt sie
        sonst aus dem eigenen Kopf."""
        monkeypatch.setattr(resonanz._cfg, "outbound_blocked", lambda: True)
        gerufen: list = []
        monkeypatch.setattr(resonanz.httpx, "get", lambda *a, **k: gerufen.append(1))
        text = resonanz.bericht("egal")
        assert "abgeschaltet" in text and "erfinde keine" in text
        assert gerufen == [], "trotz Firewall wurde das Netz angefasst"


class TestWertung:
    def test_kommentare_wiegen_doppelt(self):
        """Ein Klick auf den Pfeil nach oben ist billig, ein geschriebener Kommentar
        nicht — Diskussion ist das stärkere Signal."""
        assert resonanz._wertung({"punkte": 10, "kommentare": 0}) == 10
        assert resonanz._wertung({"punkte": 0, "kommentare": 10}) == 20

    def test_fehlende_zahlen_bringen_nichts_durcheinander(self):
        assert resonanz._wertung({}) == 0
        assert resonanz._wertung({"punkte": None, "kommentare": None}) == 0

    def test_sortiert_wird_nach_resonanz_nicht_nach_punkten(self, monkeypatch):
        viel_diskutiert = {"punkte": 10, "kommentare": 50, "ts": time.time(),
                           "titel": "diskutiert", "wo": "x", "url": "u", "quelle": "hn"}
        viel_geklickt = {"punkte": 80, "kommentare": 1, "ts": time.time(),
                         "titel": "geklickt", "wo": "x", "url": "u", "quelle": "hn"}
        monkeypatch.setattr(resonanz, "_hackernews",
                            lambda *a: ([viel_geklickt, viel_diskutiert], ""))
        treffer, _ = resonanz.suchen("x")
        assert treffer[0]["titel"] == "diskutiert"   # 110 schlaegt 82


class TestQuellenkette:
    def test_reddit_wird_ohne_zugangsdaten_sauber_uebersprungen(self):
        """Kein Absturz, kein 403 im Gesicht des Modells — ein klarer Hinweis."""
        treffer, hinweis = resonanz._reddit("egal", 30, 25)
        assert treffer == []
        assert "Zugangsdaten" in hinweis and "REDDIT_CLIENT_ID" in hinweis

    def test_eine_tote_quelle_stoppt_die_andere_nicht(self, monkeypatch):
        """Dasselbe Ketten-Muster wie web_search."""
        def kaputt(*a):
            raise ConnectionError("Netz weg")

        monkeypatch.setattr(resonanz, "_reddit", kaputt)
        monkeypatch.setattr(resonanz.httpx, "get", lambda *a, **k: _Antwort(200, _hn_treffer(3)))
        treffer, hinweise = resonanz.suchen("x")
        assert len(treffer) == 3
        assert any("reddit" in h for h in hinweise)

    def test_hackernews_wird_richtig_gelesen(self, monkeypatch):
        monkeypatch.setattr(resonanz.httpx, "get", lambda *a, **k: _Antwort(200, _hn_treffer(2)))
        treffer, hinweis = resonanz._hackernews("x", 30, 25)
        assert hinweis == "" and len(treffer) == 2
        assert treffer[0]["punkte"] == 10 and treffer[0]["kommentare"] == 1
        assert treffer[0]["wo"] == "Hacker News"

    def test_ein_fehlercode_wird_gemeldet_statt_geschluckt(self, monkeypatch):
        monkeypatch.setattr(resonanz.httpx, "get", lambda *a, **k: _Antwort(503))
        treffer, hinweis = resonanz._hackernews("x", 30, 25)
        assert treffer == [] and "503" in hinweis

    def test_beitraege_ohne_titel_fliegen_raus(self, monkeypatch):
        monkeypatch.setattr(resonanz.httpx, "get",
                            lambda *a, **k: _Antwort(200, {"hits": [{"points": 99}]}))
        treffer, _ = resonanz._hackernews("x", 30, 25)
        assert treffer == []


class TestDerBericht:
    def _mit_treffern(self, monkeypatch, n=3):
        monkeypatch.setattr(resonanz, "_reddit", lambda *a: ([], ""))
        monkeypatch.setattr(resonanz.httpx, "get", lambda *a, **k: _Antwort(200, _hn_treffer(n)))

    def test_die_rohzahlen_stehen_in_jeder_zeile(self, monkeypatch):
        """Die Gewichtung muss nachvollziehbar sein, nicht geglaubt werden."""
        self._mit_treffern(monkeypatch)
        text = resonanz.bericht("x", limit=3)
        assert text.count("Punkte,") == 3 and text.count("Kommentare") >= 3

    def test_die_wertung_wird_offengelegt(self, monkeypatch):
        self._mit_treffern(monkeypatch)
        assert "2x Kommentaren" in resonanz.bericht("x")

    def test_kein_treffer_ist_eine_aussage_keine_luecke(self, monkeypatch):
        """Sonst füllt das Modell die Leere aus dem eigenen Kopf — genau der Fall,
        gegen den Beweispflicht III gebaut wurde."""
        monkeypatch.setattr(resonanz, "_reddit", lambda *a: ([], ""))
        monkeypatch.setattr(resonanz.httpx, "get", lambda *a, **k: _Antwort(200, {"hits": []}))
        text = resonanz.bericht("voellig unbekanntes thema")
        assert "wenig geschrieben" in text and "erfinden" in text

    def test_ohne_thema_wird_gelehrt(self):
        assert resonanz.bericht("").startswith("Fehler:")

    def test_die_nicht_erreichbaren_quellen_werden_genannt(self, monkeypatch):
        monkeypatch.setattr(resonanz.httpx, "get", lambda *a, **k: _Antwort(200, _hn_treffer(1)))
        assert "Nicht erreichbar" in resonanz.bericht("x")


class TestDasWerkzeug:
    def test_es_ist_registriert(self):
        t = registry.get("resonanz")
        assert t and set(t.params) == {"thema", "tage", "limit"}

    def test_falsche_argumente_werden_gelehrt(self):
        antwort = registry.get("resonanz").func(suchbegriff="x")
        assert antwort.startswith("Falscher Aufruf") and "thema" in antwort

    def test_ohne_thema_wird_gelehrt(self):
        assert "thema" in registry.get("resonanz").func()

    @pytest.mark.parametrize("tage,limit,soll_tage,soll_limit", [
        (0, 0, 1, 1),
        (9999, 999, 365, 25),
        ("30", "10", 30, 10),
    ])
    def test_die_grenzen_werden_eingefangen(self, monkeypatch, tage, limit,
                                            soll_tage, soll_limit):
        """Ein kleines Modell schickt gern 0 oder 1000 — das darf nicht in eine
        sinnlose Anfrage laufen."""
        gesehen: dict = {}
        monkeypatch.setattr(resonanz, "bericht",
                            lambda th, tage, limit: gesehen.update(tage=tage, limit=limit) or "ok")
        registry.get("resonanz").func(thema="x", tage=tage, limit=limit)
        assert gesehen == {"tage": soll_tage, "limit": soll_limit}

    def test_unsinnige_zahlen_werden_gelehrt(self):
        antwort = registry.get("resonanz").func(thema="x", tage="bald")
        assert "Zahlen sein" in antwort
