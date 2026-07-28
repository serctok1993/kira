"""Keine Nachricht verschwindet in der Warteschlange — Befund 28.07.2026.

Der Bot verarbeitet pro Chat EINEN Zug gleichzeitig; alles andere wartet. Die
Warteschlange fasste `deque(maxlen=3)` — die vierte Nachricht verdraengte die aelteste
STILLSCHWEIGEND. Kein Ereignis, keine Meldung. Und Kira hatte dem Nutzer für genau
diese Nachricht gerade "nehm ich gleich mit" versprochen.

Das trifft kleine Modelle systematisch haerter: sie brauchen laenger pro Zug, stauen
also mehr an und verlieren dadurch mehr Nachrichten als ein schnelles Cloud-Modell.
Gemessen an der Live-DB: 17 von 547 Nachrichten blieben unbeantwortet, darunter drei
lange work:-Auftraege und zweimal "Wie spaet ist es gerade?".
"""
from __future__ import annotations

from collections import deque

import pytest

from core.agency.connectors import telegram_bot as tb


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    from core.kernel import events

    events.init_db()
    monkeypatch.setattr(tb, "_chat_busy", {})
    monkeypatch.setattr(tb, "_chat_queue", {})


def _nachricht(text: str, chat_id: int = 7) -> dict:
    return {"message": {"chat": {"id": chat_id}, "text": text, "message_id": hash(text) % 9999}}


@pytest.fixture
def gesendet(monkeypatch):
    raus: list[str] = []
    monkeypatch.setattr(tb, "_send", lambda c, ch, t, *a, **k: raus.append(t) or True)
    monkeypatch.setattr(tb.threading, "Thread",
                        lambda **k: type("T", (), {"start": lambda s: None})())
    return raus


class TestUeberlaufWirdGesagt:
    def test_verdraengte_nachricht_wird_gemeldet(self, gesendet):
        tb._dispatch(None, _nachricht("erste — die faellt raus"))     # startet den Zug
        for i in range(tb._QUEUE_MAX):
            tb._dispatch(None, _nachricht(f"wartet {i}"))
        tb._dispatch(None, _nachricht("die eine zu viel"))
        warnungen = [t for t in gesendet if "nicht" in t and "bearbeitet" in t]
        assert warnungen, "Ueberlauf blieb still"
        assert "wartet 0" in warnungen[0], "die falsche Nachricht gemeldet"
        assert "nochmal" in warnungen[0]

    def test_ueberlauf_wird_protokolliert(self, gesendet, monkeypatch):
        gemeldet: list[str] = []
        monkeypatch.setattr(tb.events, "emit", lambda typ, p=None, **k: gemeldet.append(typ))
        tb._dispatch(None, _nachricht("start"))
        for i in range(tb._QUEUE_MAX + 1):
            tb._dispatch(None, _nachricht(f"m{i}"))
        assert "chat_queue_ueberlauf" in gemeldet

    def test_ohne_ueberlauf_kommt_die_normale_quittung(self, gesendet):
        tb._dispatch(None, _nachricht("start"))
        tb._dispatch(None, _nachricht("zweite"))
        assert any("nehm das gleich mit" in t for t in gesendet)
        assert not any("nicht" in t and "bearbeitet" in t for t in gesendet)

    def test_quittung_nennt_die_zahl_der_wartenden(self, gesendet):
        tb._dispatch(None, _nachricht("start"))
        tb._dispatch(None, _nachricht("a"))
        tb._dispatch(None, _nachricht("b"))
        assert any("2 warten" in t for t in gesendet)


class TestWarteschlangeIstAlltagstauglich:
    def test_deckel_ist_gross_genug_fuer_ein_gespraech(self):
        """Drei Plaetze waren nach zwei Rueckfragen voll."""
        assert tb._QUEUE_MAX >= 10

    def test_der_deckel_bleibt_bestehen(self):
        """Unbegrenzt waere ein Speicherleck — der Deckel ist Absicht."""
        tb._chat_busy[7] = True
        for i in range(50):
            tb._dispatch(None, _nachricht(f"m{i}"))
        assert len(tb._chat_queue[7]) == tb._QUEUE_MAX

    def test_reihenfolge_bleibt_erhalten(self, gesendet):
        tb._dispatch(None, _nachricht("start"))
        for i in range(3):
            tb._dispatch(None, _nachricht(f"m{i}"))
        texte = [(u.get("message") or {}).get("text") for u in tb._chat_queue[7]]
        assert texte == ["m0", "m1", "m2"]


class TestKeineRegression:
    def test_erste_nachricht_startet_sofort_einen_zug(self, monkeypatch):
        gestartet: list[str] = []
        monkeypatch.setattr(tb, "_send", lambda *a, **k: True)
        monkeypatch.setattr(tb.threading, "Thread",
                            lambda **k: type("T", (), {"start": lambda s: gestartet.append("x")})())
        tb._dispatch(None, _nachricht("die erste"))
        assert gestartet == ["x"]
        assert tb._chat_busy[7] is True

    def test_button_klicks_umgehen_die_warteschlange(self, monkeypatch):
        behandelt: list[str] = []
        monkeypatch.setattr(tb, "_handle_callback", lambda c, cq: behandelt.append("cb"))
        tb._chat_busy[7] = True
        tb._dispatch(None, {"callback_query": {"id": "1", "data": "ctl:refresh"}})
        assert behandelt == ["cb"], "Button-Klick landete in der Warteschlange"
