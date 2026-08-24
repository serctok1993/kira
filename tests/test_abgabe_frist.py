"""Abgabe-Frist: wer eine Uhr hat, liefert vor dem Schnitt.

Befund aus dem offiziellen Terminal-Bench-2.0-Lauf (24.08.2026): sechs Laeufe wurden
von der Wanduhr abgeschnitten und bekamen NULL Punkte — obwohl bei write-compressor
bereits zwei von drei Tests gruen waren und bei large-scale-text-editing zwei von fuenf.
Die Arbeit war da, nur nie in einen abgabefaehigen Zustand gebracht. Kira kannte die
Frist schlicht nicht: der Loop lief, bis Harbor ihn erschlug.

Der Waechter macht daraus zwei Dinge:
  * eine EINMALIGE Vorwarnung im letzten Viertel ("beginne nichts Neues, sichere jetzt"),
  * einen harten Schnitt vor der Frist, mit Reserve fuer die Schluss-Zusammenfassung —
    eine Antwort nach der Frist erreicht niemanden mehr.

Ohne `frist_ts` veraendert sich nichts: Chat und Missionen ohne Uhr laufen wie bisher.
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
    """Werkzeug nur fuer diesen Test — ohne @tool, sonst platzt der Werkzeug-Vertrag."""
    monkeypatch.setattr(act.registry, "tool_schemas", lambda nur=None: [])
    monkeypatch.setattr(act.registry, "get", lambda name: object())
    monkeypatch.setattr(act, "_run_tool_guarded", lambda name, tool, args, sid: "getan")


class _Uhr:
    """Steuerbare Wanduhr: jeder Aufruf von time.time() rueckt sie um `takt` vor."""

    def __init__(self, start: float = 1000.0, takt: float = 0.0):
        self.jetzt = start
        self.takt = takt

    def __call__(self) -> float:
        wert = self.jetzt
        self.jetzt += self.takt
        return wert


class _Werkzeugzuege:
    """Antwortet endlos mit Werkzeug-Aufrufen — der Lauf endet also nur an einer Grenze."""

    def __init__(self):
        self.zuege = 0
        self.gesehen: list[list[dict]] = []

    def __call__(self, messages, **kw):
        self.gesehen.append([dict(m) for m in messages])
        self.zuege += 1
        if any("ohne weitere Werkzeuge" in str(m.get("content") or "") for m in messages[-1:]):
            return {"text": "Teilergebnis: /app/out.json liegt vor.", "tool_calls": [],
                    "finish_reason": "stop"}
        return {"text": "", "finish_reason": "tool_calls",
                "tool_calls": [{"id": f"c{self.zuege}", "name": "probe", "args": {}}]}


def _lauf(monkeypatch, antworten, frist_ts=None, max_steps: int = 50,
          session_id: str = "t-frist") -> str:
    monkeypatch.setattr(act.llm_router, "complete", antworten)
    return act._native_loop(
        [{"role": "user", "content": "Loese die Aufgabe"}], "System",
        session_id=session_id, escalate=False, emit=lambda ev: None,
        max_steps=max_steps, erlaubt=frozenset({"probe"}), frist_ts=frist_ts)


class TestReserve:
    def test_lange_frist_bekommt_gedeckelte_reserve(self):
        assert act._frist_reserve(900.0) == 90.0

    def test_kurze_frist_bekommt_anteilige_reserve(self):
        assert act._frist_reserve(200.0) == pytest.approx(30.0)

    def test_winzige_frist_behaelt_mindestreserve(self):
        assert act._frist_reserve(10.0) == 5.0


class TestFristImLoop:
    def test_ohne_frist_bleibt_alles_wie_bisher(self, monkeypatch):
        """Chat und Missionen ohne Uhr duerfen den Waechter nicht einmal bemerken."""
        monkeypatch.setattr(act.time, "time", _Uhr(takt=1000.0))  # Zeit rast — egal
        antworten = _Werkzeugzuege()
        _lauf(monkeypatch, antworten, frist_ts=None, max_steps=3)
        assert antworten.zuege == 4, "ohne Frist muessen alle Schritte laufen (3 + Abschluss)"

    def test_vor_der_frist_wird_einmal_gewarnt(self, monkeypatch):
        from core.kernel import events
        # Budget 400s, pro Zug vergehen 60s -> Warnung ab <=100s uebrig, Schnitt bei <=60s
        monkeypatch.setattr(act.time, "time", _Uhr(start=1000.0, takt=60.0))
        antworten = _Werkzeugzuege()
        _lauf(monkeypatch, antworten, frist_ts=1400.0, session_id="t-frist-warn")
        warnungen = [m for zug in antworten.gesehen for m in zug
                     if "ZEITBUDGET" in str(m.get("content") or "")]
        assert warnungen, "die Vorwarnung kam nie"
        gebucht = [e for e in events.recent(80)
                   if e["type"] == "frist_warnung" and e.get("session_id") == "t-frist-warn"]
        assert len(gebucht) == 1, "die Vorwarnung darf genau einmal kommen"

    def test_nach_der_frist_wird_kein_werkzeug_mehr_gestartet(self, monkeypatch):
        from core.kernel import events
        monkeypatch.setattr(act.time, "time", _Uhr(start=1000.0, takt=60.0))
        antworten = _Werkzeugzuege()
        ergebnis = _lauf(monkeypatch, antworten, frist_ts=1400.0, max_steps=50,
                         session_id="t-frist-stop")
        assert antworten.zuege < 50, "der Lauf lief in die Frist statt vorher abzugeben"
        assert ergebnis == "Teilergebnis: /app/out.json liegt vor."
        assert any(e["type"] == "frist_abgelaufen" and e.get("session_id") == "t-frist-stop"
                   for e in events.recent(80))

    def test_abgelaufene_frist_stoppt_sofort(self, monkeypatch):
        """Frist schon vorbei: kein einziger Werkzeugzug mehr, nur noch die Abgabe."""
        monkeypatch.setattr(act.time, "time", _Uhr(start=5000.0, takt=0.0))
        antworten = _Werkzeugzuege()
        ergebnis = _lauf(monkeypatch, antworten, frist_ts=4000.0, session_id="t-frist-vorbei")
        assert antworten.zuege == 1, "trotz abgelaufener Frist wurde noch gearbeitet"
        assert ergebnis == "Teilergebnis: /app/out.json liegt vor."


class TestWarnungstext:
    def test_warnung_nennt_die_restzeit_und_verlangt_abgabe(self):
        t = act.frist_warnung(75.4)
        assert "75" in t
        assert "Neues" in t and "Teilergebnis" in t
