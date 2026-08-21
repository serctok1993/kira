"""Gleiche Zeitstempel duerfen die Reihenfolge nicht verwuerfeln — Befund 28.07.2026.

Aufgefallen an einem sporadisch roten Test: zwei Ereignisse, in derselben Millisekunde
geschrieben, kamen in umgekehrter Reihenfolge zurueck. Windows hat rund 15 ms
Zeitaufloesung — bei schnellen Modellen fallen mehrere Ereignisse regelmaessig in
denselben Zeitstempel, und `ORDER BY ts` allein laesst die Reihenfolge dann offen.

Betroffen war nicht nur die Kalibrierung, sondern auch das GEDAECHTNIS: landen Frage
und Antwort in derselben Millisekunde, konnte das Modell die Antwort VOR der Frage im
Kontext sehen. Kleine Modelle verkraften inkohaerenten Verlauf deutlich schlechter als
grosse — sie uebernehmen die Verwirrung.

`rowid` ist die Einfuegereihenfolge und macht jede Abfrage eindeutig.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from core.kernel import events


@pytest.fixture(autouse=True)
def _db():
    events.init_db()


class TestKeineAbfrageOhneTiebreaker:
    def test_alle_zeit_sortierungen_sind_eindeutig(self):
        """Waechter: neue ORDER BY ts ohne rowid fallen sofort auf."""
        offen = []
        for pfad in pathlib.Path("core").rglob("*.py"):
            for i, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
                if "ORDER BY ts" in zeile and "rowid" not in zeile:
                    offen.append(f"{pfad}:{i}")
        assert not offen, "ohne Tiebreaker: " + ", ".join(offen)


class TestEreignisseBleibenInReihenfolge:
    def test_gleiche_millisekunde_bleibt_geordnet(self, monkeypatch):
        """Der Fall, der den Bug zeigte: alle Ereignisse mit identischem Zeitstempel."""
        import time as _t

        fest = _t.time()
        monkeypatch.setattr(events.time, "time", lambda: fest)
        for typ in ("erstes", "zweites", "drittes"):
            events.emit(typ, {})
        rows = events.rows_since(("erstes", "zweites", "drittes"), since_ts=fest - 1)
        assert [r["type"] for r in rows] == ["erstes", "zweites", "drittes"]

    def test_recent_liefert_neueste_zuerst_auch_bei_gleichstand(self, monkeypatch):
        import time as _t

        fest = _t.time()
        monkeypatch.setattr(events.time, "time", lambda: fest)
        for typ in ("a1", "a2", "a3"):
            events.emit(typ, {})
        # Nur die EIGENEN Ereignisse pruefen: Hintergrund-Threads (z.B. ein MCP-
        # Watchdog aus einem Nachbartest) duerfen hier zwischenfunken, ohne die
        # Ordnungs-Aussage zu kippen (CI-Flake auf fb1720e).
        letzte = [e["type"] for e in events.recent(10) if e["type"] in ("a1", "a2", "a3")]
        assert letzte == ["a3", "a2", "a1"], letzte


class TestGedaechtnisBleibtInReihenfolge:
    def test_frage_kommt_vor_antwort(self, monkeypatch):
        """Sonst sieht das Modell seine eigene Antwort vor der Frage des Nutzers."""
        from core.mind.memory import store

        store.init_memory()
        import time as _t
        fest = _t.time()
        monkeypatch.setattr(store.time, "time", lambda: fest)
        store.remember("Wie spaet ist es?", role="user", session_id="s-reihenfolge")
        store.remember("Es ist 14 Uhr.", role="partner", session_id="s-reihenfolge")
        verlauf = store.recent_dialogue("s-reihenfolge", limit=10)
        texte = [h.get("text") for h in verlauf]
        assert texte.index("Wie spaet ist es?") < texte.index("Es ist 14 Uhr."), texte
