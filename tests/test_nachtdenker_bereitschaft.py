"""Ein lauschender Port ist noch keine Bereitschaft (Katalog-Befund 28.07.2026).

Drei Aufgaben des 92er-Katalogs liefen je bis zur harten Wall-Clock-Grenze — 1.390 s,
1.815 s, 1.808 s — ohne eine einzige Antwort. Der llama.cpp-Server auf 8081 lauschte
dabei brav und lieferte auf `/models` ein sauberes 200; er war nur taub. Nach einem
`taskkill` war die Karte sofort frei.

Der Automat prüfte genau dieses `/models` und übergab dem tauben Server daraufhin die
Rollen `reason`, `worker` und `bulk`. Danach lief JEDE Anfrage in die Zeitgrenze,
statt in einer Sekunde zu scheitern. Ein tauber Server ist schlimmer als ein
abgeschalteter.

Zweiter Befund derselben Sache: die Rollenübernahme war nirgends sichtbar. Aus Sicht
des Nutzers wechselte Kira nach einem Neustart ohne Grund das Modell — und jede
Modellwahl aus dem Steuerpult war beim nächsten Fensterwechsel weg.
"""
from __future__ import annotations

import httpx
import pytest

from core.kernel import events, nachtdenker


class _Antwort:
    def __init__(self, code: int, inhalt: str | None = "OK", kaputt: bool = False):
        self.status_code = code
        self._inhalt = inhalt
        self._kaputt = kaputt

    def json(self) -> dict:
        if self._kaputt:
            raise ValueError("kein JSON")
        return {"choices": [{"message": {"content": self._inhalt}}]}


@pytest.fixture
def _endpunkt(monkeypatch):
    monkeypatch.setattr(nachtdenker, "_cfg",
                        lambda: {"endpunkt": "http://127.0.0.1:8081/v1",
                                 "modell": "openai/nachtdenker", "ende": "07:30"})


class TestBereitschaftsTest:
    def test_ein_antwortender_server_gilt_als_bereit(self, monkeypatch, _endpunkt):
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _Antwort(200, "OK"))
        assert nachtdenker._bereit() == (True, "")

    def test_der_taube_server_faellt_durch(self, monkeypatch, _endpunkt):
        """Der Live-Fall: Port lauscht, es kommt nur nie etwas zurueck."""
        def haengt(*a, **k):
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx, "post", haengt)
        bereit, grund = nachtdenker._bereit()
        assert bereit is False
        assert "taub" in grund and "30" in grund

    @pytest.mark.parametrize("antwort,soll_grund", [
        (_Antwort(500), "HTTP 500"),
        (_Antwort(200, ""), "leere Antwort"),
        (_Antwort(200, None), "leere Antwort"),
        (_Antwort(200, kaputt=True), "verwertbaren Inhalt"),
    ])
    def test_alles_andere_gilt_als_nicht_bereit(self, monkeypatch, _endpunkt,
                                                antwort, soll_grund):
        monkeypatch.setattr(httpx, "post", lambda *a, **k: antwort)
        bereit, grund = nachtdenker._bereit()
        assert bereit is False and soll_grund in grund

    def test_ohne_endpunkt_kein_absturz(self, monkeypatch):
        monkeypatch.setattr(nachtdenker, "_cfg", lambda: {})
        assert nachtdenker._bereit()[0] is False

    def test_der_test_ist_klein_und_hat_eine_harte_grenze(self, monkeypatch, _endpunkt):
        """Er laeuft im Runner-Takt — er darf nichts kosten und nie haengen."""
        gesehen: dict = {}

        def merken(url, **k):
            gesehen.update(k)
            gesehen["url"] = url
            return _Antwort(200, "OK")

        monkeypatch.setattr(httpx, "post", merken)
        nachtdenker._bereit()
        assert gesehen["timeout"] <= 60
        assert gesehen["json"]["max_tokens"] <= 20
        assert gesehen["url"].endswith("/chat/completions")


class TestRollenWerdenNichtBlindUebergeben:
    """Vor der Uebernahme muss der Server ANTWORTEN, nicht nur lauschen."""

    def test_ein_tauber_server_bekommt_die_rollen_nicht(self, monkeypatch, _endpunkt):
        events.init_db()
        uebernommen: list = []
        monkeypatch.setattr(nachtdenker, "_health", lambda: True)
        monkeypatch.setattr(nachtdenker, "_bereit", lambda: (False, "keine Antwort in 30s"))
        monkeypatch.setattr(nachtdenker, "_aktivieren", lambda st: uebernommen.append(st))
        monkeypatch.setattr(nachtdenker, "fenster_aktiv", lambda now=None: True)
        monkeypatch.setattr(nachtdenker, "_state", lambda: {"phase": "aus"})
        monkeypatch.setattr(nachtdenker, "_cfg",
                            lambda: {"enabled": True, "endpunkt": "http://127.0.0.1:8081/v1",
                                     "modell": "x", "ende": "07:30"})
        gemerkt: list = []
        monkeypatch.setattr(nachtdenker, "_merken", lambda st: gemerkt.append(st))
        nachtdenker.tick()
        assert uebernommen == [], "die Rollen gingen an einen tauben Server"
        assert gemerkt and gemerkt[-1].get("phase") == "fehler"

    def test_ein_antwortender_server_bekommt_sie(self, monkeypatch, _endpunkt):
        events.init_db()
        uebernommen: list = []
        monkeypatch.setattr(nachtdenker, "_health", lambda: True)
        monkeypatch.setattr(nachtdenker, "_bereit", lambda: (True, ""))
        monkeypatch.setattr(nachtdenker, "_aktivieren", lambda st: uebernommen.append(st))
        monkeypatch.setattr(nachtdenker, "fenster_aktiv", lambda now=None: True)
        monkeypatch.setattr(nachtdenker, "_state", lambda: {"phase": "aus"})
        monkeypatch.setattr(nachtdenker, "_cfg",
                            lambda: {"enabled": True, "endpunkt": "http://127.0.0.1:8081/v1",
                                     "modell": "x", "ende": "07:30"})
        monkeypatch.setattr(nachtdenker, "_merken", lambda st: None)
        nachtdenker.tick()
        assert len(uebernommen) == 1


class TestDerNutzerSiehtDenWechsel:
    """Bis heute stand im Cockpit-Feed nichts darueber — Kira wechselte scheinbar
    grundlos das Modell, und die eigene Modellwahl war weg."""

    def test_fensterbeginn_nennt_rollen_und_modell(self):
        d = events.describe("nachtdenker_start",
                            {"rollen": ["reason", "worker", "bulk"], "alias": "nacht35b"})
        assert "reason" in d["detail"] and "worker" in d["detail"]
        assert "nacht35b" in d["detail"]
        assert d["text"] and "Nachtfenster" in d["text"]

    def test_fensterende_sagt_dass_die_rollen_zurueck_sind(self):
        d = events.describe("nachtdenker_stop",
                            {"grund": "fensterende", "rollen_zurueck": ["reason", "worker"]})
        assert "zurueck" in d["detail"] and "reason" in d["detail"]

    def test_die_stoerung_nennt_den_grund(self):
        d = events.describe("nachtdenker_fehler",
                            {"error": "Endpunkt lauscht, ist aber nicht bereit: leere Antwort"})
        assert "nicht bereit" in d["detail"]

    def test_kaputte_payload_bringt_die_ansicht_nicht_um(self):
        for typ in ("nachtdenker_start", "nachtdenker_stop", "nachtdenker_fehler",
                    "nachtdenker_neustart"):
            d = events.describe(typ, None)
            assert isinstance(d.get("text"), str) and d["text"]
