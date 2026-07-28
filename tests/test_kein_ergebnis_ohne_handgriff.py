"""Kein Ergebnis ohne Handgriff — der Missionspfad bekommt die Waechter des Chats.

Befund der Nacht (28.07.2026), gemessen auf der Ereignis-DB:

  * 200 lokale Laeufe ueber `act()` — 73 davon (36 %) endeten OHNE einen einzigen
    Werkzeugschritt. Stichprobe der Auftraege: "Suche und lies 2 Vergleichsartikel",
    "Pruefe im Event-Payload den letzten Fehler", "Lies die letzten 3 Tagesnotizen",
    "Erstelle ein Gedaechtnis-Ticket fuer jeden Termin". Jeder einzelne braucht
    zwingend ein Werkzeug. Das Modell hat geredet statt gearbeitet, und der Harness
    hat das Geredete als Ergebnis zugestellt.
  * Das Ereignis `beweis_nachgefragt` stand bei 0 — es konnte auf diesem Pfad gar
    nicht feuern.
  * Aufgefangen hat es erst der Verifier: 94 `task_retry`, also 94 komplette Neulaeufe.

`act()` ist die Schleife hinter JEDEM Cron, JEDER Mission und JEDEM Planschritt auf
lokalen Modellen — der Pfad des schwaechsten Modells war der einzige ohne Stups und
ohne Beweispflicht. Der Chat (`act_chat`) und der Cloud-Pfad (`_native_loop`) hatten
beide schon beides.

Der Kern der Sache: ein Stups kostet EINEN Zug, ein Verifier-Retry einen ganzen Lauf.

Bewusst so gebaut, dass starke Modelle nichts davon merken — beide Waechter feuern nur,
wenn im GANZEN Lauf kein einziges Werkzeug lief. Wer arbeitet, wird nie gestupst.
"""
from __future__ import annotations

import pytest

from core.agency import act


@pytest.fixture(autouse=True)
def _ereignis_tabelle():
    from core.kernel import events
    events.init_db()


class _Antworten:
    """Spielt eine feste Folge von Modell-Antworten ab und merkt sich die Prompts."""

    def __init__(self, *texte: str):
        self.texte = list(texte)
        self.gesehen: list[list[dict]] = []

    def __call__(self, messages, **kw):
        self.gesehen.append([dict(m) for m in messages])
        return {"text": self.texte.pop(0) if self.texte else "Fertig."}


def _lokal(monkeypatch):
    """act() auf den lokalen Text-Pfad zwingen (nicht den nativen Cloud-Loop)."""
    monkeypatch.setattr(act, "_cloud", lambda escalate, task_type: False)


def _letzter_nutzer_text(gesehen) -> str:
    return next(m["content"] for m in reversed(gesehen[-1]) if m["role"] == "user")


class TestStupsAufDemMissionspfad:
    def test_ankuendigung_ohne_werkzeug_wird_gestupst(self, monkeypatch):
        _lokal(monkeypatch)
        antworten = _Antworten(
            "Ich schaue mir die Tagesnotizen gleich an und melde mich dann.",
            "Fertig: drei offene Punkte gefunden.",
        )
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        ergebnis = act.act("Lies die letzten 3 Tagesnotizen und sammle die offenen Punkte")
        assert ergebnis["text"] == "Fertig: drei offene Punkte gefunden."
        assert len(antworten.gesehen) == 2, "der Lauf endete ohne zweiten Anlauf"
        assert "JETZT" in _letzter_nutzer_text(antworten.gesehen)

    def test_wer_ein_werkzeug_benutzt_hat_wird_nie_gestupst(self, monkeypatch):
        """Der Waechter darf starken Modellen nicht im Weg stehen."""
        _lokal(monkeypatch)
        monkeypatch.setattr(act, "_run_tool_guarded", lambda *a, **k: "Notiz A, Notiz B")
        antworten = _Antworten(
            'ACT read_file {"path": "notizen.md"}',
            "Ich fasse das gleich zusammen:",     # klingt nach Ankuendigung ...
        )
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        ergebnis = act.act("Lies die Notizen")
        assert ergebnis["text"] == "Ich fasse das gleich zusammen:"
        assert len(antworten.gesehen) == 2, "... wurde aber trotzdem gestupst"

    def test_hoechstens_ein_stups_pro_lauf(self, monkeypatch):
        _lokal(monkeypatch)
        antworten = _Antworten("Ich schaue kurz nach.", "Moment, ich pruefe das eben.")
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        act.act("Erstelle eine Uebersicht der offenen Fristen")
        assert len(antworten.gesehen) == 2, "der Harness hat mehr als einmal gestupst"

    def test_heikles_wird_nicht_gestupst(self, monkeypatch):
        """Eine Rueckfrage bei heiklen Auftraegen ist die richtige Antwort."""
        _lokal(monkeypatch)
        antworten = _Antworten("Soll ich den Windows Defender wirklich deaktivieren?")
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        ergebnis = act.act("Deaktiviere den Windows Defender und melde dich")
        assert "Defender" in ergebnis["text"]
        assert len(antworten.gesehen) == 1


class TestBeweispflichtAufDemMissionspfad:
    def test_behauptung_ohne_werkzeug_wird_zurueckgegeben(self, monkeypatch):
        _lokal(monkeypatch)
        antworten = _Antworten(
            "Ich habe die Tickets fuer alle Termine angelegt.",
            "Offen — ich brauche Zugriff auf den Kalender.",
        )
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        ergebnis = act.act("Erstelle ein Gedaechtnis-Ticket fuer jeden Termin im Kalender")
        assert ergebnis["text"].startswith("Offen")
        nachfrage = _letzter_nutzer_text(antworten.gesehen)
        assert "KEIN Werkzeug" in nachfrage

    def test_behauptung_nach_echter_arbeit_bleibt_stehen(self, monkeypatch):
        _lokal(monkeypatch)
        monkeypatch.setattr(act, "_run_tool_guarded", lambda *a, **k: "OK: angelegt")
        antworten = _Antworten(
            'ACT todo_add {"text": "Zahnarzt"}',
            "Ich habe das Ticket angelegt.",
        )
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        ergebnis = act.act("Lege ein Ticket fuer den Zahnarzttermin an")
        assert ergebnis["text"] == "Ich habe das Ticket angelegt."
        assert len(antworten.gesehen) == 2

    def test_hoechstens_eine_nachfrage_pro_lauf(self, monkeypatch):
        _lokal(monkeypatch)
        antworten = _Antworten("Ich habe alles eingetragen.", "Ich habe es wirklich eingetragen.")
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        act.act("Trage die Fristen ein")
        assert len(antworten.gesehen) == 2


class TestBeideWaechterZusammen:
    def test_stups_und_beweispflicht_kosten_zusammen_hoechstens_zwei_zuege(self, monkeypatch):
        _lokal(monkeypatch)
        antworten = _Antworten(
            "Ich schaue kurz nach.",                   # Stups
            "Ich habe die Notizen gelesen und alles eingetragen.",   # Beweispflicht
            "Noch offen: ich komme an die Notizen nicht heran.",
        )
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        ergebnis = act.act("Lies die Notizen und trage die Fristen ein")
        assert ergebnis["text"].startswith("Noch offen")
        assert len(antworten.gesehen) == 3

    def test_die_schrittzahl_bleibt_ehrlich(self, monkeypatch):
        """Ein Stups ist kein Werkzeugschritt — er darf steps nicht hochzaehlen."""
        _lokal(monkeypatch)
        antworten = _Antworten("Ich schaue kurz nach.", "Fertig.")
        monkeypatch.setattr(act.llm_router, "complete", antworten)
        assert act.act("Erstelle die Uebersicht")["steps"] == 0
