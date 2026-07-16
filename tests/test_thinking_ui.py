"""Thinking-Runde: der Denkprozess im Chat ist live beobachtbar.

Sergens Wunsch (16.07.): beim Arbeiten sehen, WAS gerade laeuft und WO die
Fehler passieren. Marker-Tests nach dem Feedback-Runden-Muster.
"""
from __future__ import annotations

from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.script import SCRIPT


def test_kopfzeile_traegt_status_und_zaehler():
    # Kopf: Live-Status (tnow) + Sekundenzaehler (tsecs, selbstheilender Interval)
    for m in ('<span class="tnow">', '<span class="tsecs">', "dieser._tick=setInterval"):
        assert m in SCRIPT, f"Kopf-Marker fehlt: {m}"
    assert 'classList.contains("live")' in SCRIPT          # Ticker raeumt sich selbst auf
    # Summary zaehlt Fehler und zeigt sie rot
    assert '".ostat.err"' in SCRIPT and 'class="terr"' in SCRIPT
    assert '" Fehler</span>"' in SCRIPT


def test_aktionen_tragen_zustandspunkte():
    # jede Tool-Zeile startet mit ● (laeuft) und wird bei der Beobachtung ✓/✕
    assert '<span class="tst run">●</span>' in SCRIPT
    assert "lastToolRow" in SCRIPT
    assert 'st.classList.add(bad?"err":"ok")' in SCRIPT
    assert 'st.textContent=bad?"✕":"✓"' in SCRIPT


def test_neue_werkzeuge_haben_klarnamen():
    # TOOLMAP kennt die Fahrplan-Neuzugaenge — sonst zeigt der Trace rohe Namen
    for m in ("todo_plan", "todo_stand", "code_symbol", "code_umriss",
              "erinnerung", "termin_add", "delegate", "schwarm"):
        assert f" {m}:[" in SCRIPT or f",{m}:[" in SCRIPT or f"\n {m}:[" in SCRIPT, \
            f"TOOLMAP-Eintrag fehlt: {m}"


def test_stile_fuer_status_und_fehler():
    for m in (".trow .tst{", ".trow .tst.run{", ".trow .tst.err{",
              ".think .h .tnow{", ".think .h .tsecs{", ".think .h .terr{"):
        assert m in CSS, f"Stil fehlt: {m}"
    assert "auPuls" in CSS                                  # der Lauf-Punkt pulsiert dezent
