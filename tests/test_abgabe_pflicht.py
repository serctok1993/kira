"""Abgabe-Pflicht: ein Fragment ist kein Ergebnis.

Befund aus dem offiziellen Terminal-Bench-2.0-Lauf (24.08.2026, 89 Tasks, Nemotron
550B free). Die drei bestehenden Waechter des nativen Loops — Stups, Beweispflicht II
und III — sind alle auf `not used_tools` verriegelt. Das ist fuer ihren Zweck richtig
(wer arbeitet, soll nicht gestupst werden), reisst aber genau dort eine Luecke, wo die
meisten Punkte lagen:

  * Kira arbeitet 50+ Werkzeugschritte, denkt dann laut weiter statt abzugeben — der
    Halbsatz wird zur Endantwort. `used_tools` ist laengst True, kein Waechter greift.
    Betroffen u.a. feal-differential-cryptanalysis (kein attack.py), protein-assembly
    (kein gblock.txt), sqlite-db-truncate (kein recover.json), fix-ocaml-gc.
  * polyglot-c-py verbrannte 8192 Ausgabe-Token in EINEM Denk-Zug: der Anbieter kappte
    die Generierung am Deckel (finish_reason "length"), das Fragment wurde Endantwort,
    /app/polyglot existierte nie. Hier ist nichts geraten — der Abbruch ist gemessen.

Der Waechter kostet hoechstens EINEN Zug pro Lauf und laesst im Zweifel durch: nur der
gemessene Abschneide-Fall und ein Text, der auf einen Doppelpunkt endet, loesen ihn aus.
"""
from __future__ import annotations

import pytest

from core.agency import act


@pytest.fixture(autouse=True)
def _ereignis_tabelle():
    from core.kernel import events
    events.init_db()


@pytest.fixture(autouse=True)
def _probe_werkzeug(monkeypatch):
    """Ein Werkzeug NUR fuer diesen Test — bewusst ohne @tool-Registrierung.

    Ein global registriertes Testwerkzeug landet sonst in der echten Registry und
    laesst den Werkzeug-Vertrag (test_werkzeug_vertrag*) reihenfolgenabhaengig platzen.
    """
    monkeypatch.setattr(act.registry, "tool_schemas", lambda nur=None: [])
    monkeypatch.setattr(act.registry, "get", lambda name: object())
    monkeypatch.setattr(act, "_run_tool_guarded",
                        lambda name, tool, args, sid: f"getan: {args}")


class _Antworten:
    """Spielt Modell-Antworten ab; jede ist (text, tool_calls, finish_reason)."""

    def __init__(self, *zuege):
        self.zuege = list(zuege)
        self.gesehen: list[list[dict]] = []

    def __call__(self, messages, **kw):
        self.gesehen.append([dict(m) for m in messages])
        if not self.zuege:
            return {"text": "Fertig.", "tool_calls": [], "finish_reason": "stop"}
        text, calls, grund = self.zuege.pop(0)
        return {"text": text, "tool_calls": calls, "finish_reason": grund}


def _letzter_nutzer_text(gesehen) -> str:
    return next(m["content"] for m in reversed(gesehen[-1]) if m["role"] == "user")


def _lauf(monkeypatch, antworten, max_steps: int = 8, session_id: str = "t-abgabe") -> str:
    monkeypatch.setattr(act.llm_router, "complete", antworten)
    return act._native_loop(
        [{"role": "user", "content": "Loese die Aufgabe"}], "System",
        session_id=session_id, escalate=False, emit=lambda ev: None,
        max_steps=max_steps, erlaubt=frozenset({"abgabe_probe"}))


class TestAbgabeErkennung:
    def test_gekappte_generierung_gilt_als_unfertig(self):
        assert act._abgabe_unfertig("In Python, `#if 0", "length")

    def test_doppelpunkt_ende_gilt_als_unfertig(self):
        assert act._abgabe_unfertig("Let me parse this:", "stop")

    def test_fertiger_bericht_bleibt_unangetastet(self):
        assert not act._abgabe_unfertig(
            "Die Datei /app/out.json wurde erzeugt und der Test laeuft gruen.", "stop")

    def test_hoeflichkeitsfloskel_ist_kein_fragment(self):
        """'Let me know if ...' ist ein Abschluss, kein Weiterdenken."""
        assert not act._abgabe_unfertig(
            "Alles erledigt. Let me know if you need anything else.", "stop")


class TestAbgabeWaechterImLoop:
    def test_fragment_nach_getaner_arbeit_wird_gestupst(self, monkeypatch):
        """Die eigentliche Luecke: used_tools ist True, trotzdem muss der Stups feuern."""
        antworten = _Antworten(
            ("", [{"id": "1", "name": "abgabe_probe", "args": {"was": "schritt"}}], "tool_calls"),
            ("Let me trace through the Feistel structure:", [], "stop"),
            ("Fertig: /app/attack.py erzeugt und geprueft.", [], "stop"),
        )
        assert _lauf(monkeypatch, antworten) == "Fertig: /app/attack.py erzeugt und geprueft."
        assert "unfertig" in _letzter_nutzer_text(antworten.gesehen)

    def test_gekapptes_erstes_wort_wird_gestupst(self, monkeypatch):
        """polyglot-c-py: Token-Deckel im ersten Zug, kein Werkzeug, kein Artefakt."""
        antworten = _Antworten(
            ("Let me think about how to create a polyglot. Key challenges: 1. Python uses `#",
             [], "length"),
            ("", [{"id": "1", "name": "abgabe_probe", "args": {"was": "datei"}}], "tool_calls"),
            ("Die Datei /app/polyglot/main.py.c liegt vor, beide Laeufe stimmen.", [], "stop"),
        )
        assert _lauf(monkeypatch, antworten).startswith("Die Datei /app/polyglot")
        # Der Stups kam VOR dem Werkzeugzug — genau das rettet den Lauf.
        assert "unfertig" in antworten.gesehen[1][-1]["content"]

    def test_fertige_antwort_kostet_keinen_extrazug(self, monkeypatch):
        antworten = _Antworten(
            ("", [{"id": "1", "name": "abgabe_probe", "args": {"was": "schritt"}}], "tool_calls"),
            ("Die Datei liegt unter /app/out.json, der Test ist gruen.", [], "stop"),
        )
        assert _lauf(monkeypatch, antworten).startswith("Die Datei liegt")
        assert len(antworten.gesehen) == 2, "eine fertige Antwort wurde unnoetig gestupst"

    def test_hoechstens_ein_stups_pro_lauf(self, monkeypatch):
        """Auch wenn jeder Zug ein Fragment ist: der Abgabe-Waechter kostet EINEN Zug."""
        from core.kernel import events
        antworten = _Antworten(
            ("Erst denke ich nach:", [], "stop"),
            ("Und jetzt noch mehr Gedanken:", [], "stop"),
            ("Immer noch am Denken:", [], "stop"),
        )
        _lauf(monkeypatch, antworten, session_id="t-abgabe-einmal")
        gestupst = [e for e in events.recent(80)
                    if e["type"] == "abgabe_stups" and e.get("session_id") == "t-abgabe-einmal"]
        assert len(gestupst) == 1, "der Waechter feuerte mehr als einmal"

    def test_im_letzten_zug_wird_nicht_mehr_gestupst(self, monkeypatch):
        """Ohne Zug Luft waere der Stups nur verlorene Zeit — dann lieber das Fragment."""
        fragment = ("Der ELF-Header liegt bei Offset 0x40 und die Segmenttabelle "
                    "beginnt direkt dahinter, wobei das erste PT_LOAD-Segment ab")
        antworten = _Antworten((fragment, [], "length"))
        assert _lauf(monkeypatch, antworten, max_steps=1) == fragment
        assert len(antworten.gesehen) == 1

    def test_stups_wird_als_ereignis_gebucht(self, monkeypatch):
        from core.kernel import events
        antworten = _Antworten(
            ("Ich analysiere weiter:", [], "stop"),
            ("Fertig.", [], "stop"),
        )
        _lauf(monkeypatch, antworten)
        typen = [e["type"] for e in events.recent(50)]
        assert "abgabe_stups" in typen
