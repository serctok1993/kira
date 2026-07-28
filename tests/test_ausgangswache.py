"""Nichts Leeres und nichts Rohes verlaesst das Haus — Befund 28.07.2026.

Der Nutzer: "In Telegram kommen immer nur halbe Nachrichten durch."

Die Messung ueber 21 Tage Live-Daten zeigt: ein grosser Teil davon sind gar keine
halben Nachrichten, sondern VOELLIG LEERE.

    kira-c6-9b            103 Antworten, davon 11 leer  (10 %)
    kira-c6                98 Antworten, davon 10 leer  (10 %)
    glm-5.2               195 Antworten, davon  4 leer  ( 2 %)
    deepseek-v4-flash     172 Antworten, davon  1 leer  ( 0 %)

Dazu 13 Antworten, die rohe Werkzeugaufrufe waren — darunter remember_fact-Zeilen mit
privaten Finanzdaten, die so als Chat-Nachricht beim Nutzer landeten.

Beides ist rettbar: ein einziger Nachfass-Zug holt in aller Regel eine echte Antwort.
Fuer ein starkes Modell ist die Wache ein Nullpfad — sie feuert dort so gut wie nie.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.agency import act


@pytest.fixture(autouse=True)
def _db():
    from core.kernel import events

    events.init_db()


class TestRohenAufrufErkennen:
    @pytest.mark.parametrize("text", [
        'ACT remember_fact {"fact": "etwas Privates"}',
        "ACT list_models",
        'ACT web_search {"query": "x"}\n\nIch schaue mal nach.',
        "<tool_call>{...}",
    ])
    def test_werkzeugaufruf_ist_keine_antwort(self, text):
        assert act._ist_roher_werkzeugaufruf(text) is True

    @pytest.mark.parametrize("text", [
        "Es ist 14:30 Uhr.",
        "Ich habe das Briefing geschrieben — es liegt im Vault.",
        "Der Begriff ACT steht bei mir fuer Werkzeugaufrufe.",   # Prosa ueber ACT
        "",
    ])
    def test_echte_antworten_bleiben_unberuehrt(self, text):
        assert act._ist_roher_werkzeugaufruf(text) is False

    def test_eine_erklaerung_des_protokolls_ist_eine_gute_antwort(self):
        """Fragt der Partner, WIE Kira Werkzeuge aufruft, gehoert ein Beispiel in die
        Antwort. Wer nur nach "steht da irgendwo ACT" sucht, wirft genau diese Antwort
        weg und fragt sinnlos nach. Roh ist nur, was FAST NUR aus dem Aufruf besteht."""
        erklaerung = (
            'So rufe ich ein Werkzeug auf: ACT web_fetch {"url": "https://example.com"} '
            "— danach bekomme ich das Ergebnis zurueck und arbeite damit weiter. "
            "Pro Zug geht genau ein Aufruf."
        )
        assert act._ist_roher_werkzeugaufruf(erklaerung) is False


class TestWacheHoltNach:
    def _wache(self, antwort_des_modells):
        with patch.object(act, "_complete_resilient",
                          return_value={"text": antwort_des_modells}):
            return act._brauchbare_antwort("", [{"role": "user", "content": "Wie spaet?"}],
                                           system="s", session_id="t")

    def test_leere_antwort_wird_nachgefasst(self):
        assert self._wache("Es ist 14:30 Uhr.") == "Es ist 14:30 Uhr."

    def test_roher_aufruf_wird_nachgefasst(self):
        with patch.object(act, "_complete_resilient", return_value={"text": "Gemerkt."}):
            out = act._brauchbare_antwort('ACT remember_fact {"fact": "geheim"}',
                                          [{"role": "user", "content": "merk dir das"}],
                                          system="s", session_id="t")
        assert out == "Gemerkt."
        assert "remember_fact" not in out, "privater Werkzeugaufruf ging raus"

    def test_wenn_auch_der_nachfass_leer_bleibt_wird_es_gesagt(self):
        out = self._wache("")
        assert "keine brauchbare Antwort" in out
        assert out.strip(), "leere Nachricht an den Nutzer"

    def test_ein_zweiter_roher_aufruf_wird_nicht_durchgereicht(self):
        out = self._wache("ACT jetzt")
        assert not act._ist_roher_werkzeugaufruf(out)

    def test_nachfassen_wird_protokolliert(self, monkeypatch):
        gemeldet: list[str] = []
        monkeypatch.setattr(act.events, "emit",
                            lambda typ, p=None, **k: gemeldet.append(typ))
        self._wache("Fertige Antwort.")
        assert "antwort_nachgefasst" in gemeldet

    def test_ein_fehler_beim_nachfassen_kostet_keine_antwort(self, monkeypatch):
        monkeypatch.setattr(act, "_complete_resilient",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Netz weg")))
        out = act._brauchbare_antwort("", [], system="s", session_id="t")
        assert "keine brauchbare Antwort" in out


class TestStarkeModelleMerkenNichts:
    def test_gute_antwort_loest_keinen_zusatzaufruf_aus(self, monkeypatch):
        aufrufe: list[int] = []
        monkeypatch.setattr(act, "_complete_resilient",
                            lambda *a, **k: aufrufe.append(1) or {"text": "x"})
        out = act._brauchbare_antwort("Hier ist dein Briefing, vollstaendig.", [],
                                      system="s", session_id="t")
        assert out == "Hier ist dein Briefing, vollstaendig."
        assert aufrufe == [], "die Wache hat unnoetig ein Modell gerufen"


class TestBeidePfadeSindGeschuetzt:
    def test_chat_und_missionspfad_rufen_dieselbe_wache(self):
        import inspect

        quelle = inspect.getsource(act)
        # act_chat ueber _finalize, act() direkt vor dem act_done-Ausgang
        assert quelle.count("_brauchbare_antwort(") >= 3, "ein Ausgang ist ungeschuetzt"
