"""Beweispflicht fuers Handwerk (SWE-bench-Befund 19.08.): ein Plan-Schritt mit
Edit-Auftrag ("Erstelle einen Patch", "Fuege X hinzu") endete in reiner Analyse-Prosa —
36 Lese-Werkzeuge, kein einziges Schreib-Werkzeug, Patch leer. Die bestehenden Waechter
griffen nicht: _missing_claims prueft nur NEUE Dateien, der Edit-rot-Reflex nur
missglueckte Edits. Jetzt gilt: Edit-Auftrag ohne Schreib-Werkzeug -> EIN Zwangs-Retry,
danach steht der Mangel ehrlich im Ergebnis. Plus: ein roher <tool_call> als
Schritt-Ergebnis (Runden-Budget mitten in der Arbeit zu Ende) wird ehrlich benannt
statt als Ergebnis durchgereicht."""
from __future__ import annotations

import pytest

from core.agency import act


@pytest.fixture(autouse=True)
def _ereignis_tabelle():
    from core.kernel import events
    events.init_db()


def _mini_plan(monkeypatch, schritt: str):
    """plan_and_execute auf EINEN Schritt verengen, act() wird pro Test gefaked."""
    monkeypatch.setattr(act, "_make_plan", lambda *a, **k: [{"rang": "arbeiter", "schritt": schritt}])
    monkeypatch.setattr(act, "_missing_claims", lambda out: [])
    monkeypatch.setattr(act.llm_router, "complete", lambda *a, **k: {"text": "Zusammenfassung."})


def test_edit_absicht_ohne_schreibwerkzeug_erzwingt_retry(monkeypatch):
    sid = "t-handwerk-1"
    _mini_plan(monkeypatch, "Erstelle einen minimalen Patch fuer qdp.py")
    laeufe = []
    def fake_act(task, **kw):
        laeufe.append(task)
        return {"text": "Das Problem ist klar: der Regex ist zu strikt."}  # nur Prosa
    monkeypatch.setattr(act, "act", fake_act)
    out = act.plan_and_execute("Behebe den QDP-Bug", session_id=sid)
    assert len(laeufe) == 2, "genau EIN Zwangs-Retry nach dem Analyse-only-Versuch"
    assert "NUR ANALYSIERT" in laeufe[1], "der Retry sagt klar, was fehlte"
    assert "NUR ANALYSE" in out, "der Mangel steht ehrlich im Ergebnis"


def test_wer_schreibt_wird_nicht_gestupst(monkeypatch):
    sid = "t-handwerk-2"
    _mini_plan(monkeypatch, "Erstelle einen minimalen Patch fuer qdp.py")
    laeufe = []
    def fake_act(task, **kw):
        laeufe.append(task)
        act._edit_tried_bump(sid, "edit_datei")  # der Lauf HAT geschrieben
        return {"text": "Edit gruen, Regex jetzt case-insensitive."}
    monkeypatch.setattr(act, "act", fake_act)
    out = act.plan_and_execute("Behebe den QDP-Bug", session_id=sid)
    assert len(laeufe) == 1, "kein Retry, wenn ein Schreib-Werkzeug lief"
    assert "NUR ANALYSE" not in out


def test_lese_schritt_wird_nie_gestupst(monkeypatch):
    sid = "t-handwerk-3"
    _mini_plan(monkeypatch, "Analysiere den Code, um die Ursache zu beheben")
    laeufe = []
    monkeypatch.setattr(act, "act", lambda task, **kw: (laeufe.append(task), {"text": "Analyse fertig."})[1])
    act.plan_and_execute("Verstehe den QDP-Bug", session_id=sid)
    assert len(laeufe) == 1, "Analyse-Schritte verlangen keinen Edit"


def test_roher_toolcall_wird_nicht_als_ergebnis_durchgereicht(monkeypatch):
    sid = "t-handwerk-4"
    _mini_plan(monkeypatch, "Lies die Datei separable.py")
    monkeypatch.setattr(act, "act", lambda task, **kw: {
        "text": "<tool_call>\n<function=read_file>\n<parameter=path>x.py</parameter>"})
    out = act.plan_and_execute("Analysiere separability", session_id=sid)
    assert "<tool_call>" not in out and "<function=" not in out
    assert "Runden-Budget erschoepft" in out


def test_zaehler_bleibt_pro_session_getrennt():
    act._edit_tried_bump("s-a", "edit_datei")
    act._edit_tried_bump("s-a", "write_file")
    act._edit_tried_bump("s-a", "read_file")   # zaehlt nicht
    assert act._edit_tried_get("s-a") == 2
    assert act._edit_tried_get("s-b") == 0


def test_substantiv_implementierung_ist_kein_edit_auftrag():
    """SWE-bench-v2-Fehlschuss: 'Exploriere ... und finde die separability_matrix
    Implementierung' loeste den Edit-Zwangs-Retry mitten in der ERKUNDUNG aus (das
    Substantiv matchte implementier\\w*, 'Exploriere' fehlte in der Ausschlussliste)
    und verbrannte das Runden-Budget. Verbformen bleiben Auftraege, Substantive nicht."""
    treffer = lambda t: bool(act._EDIT_INTENT.search(t) and not act._EDIT_INTENT_NOT.search(t))
    assert not treffer("Exploriere die Repository-Struktur und finde die separability_matrix Implementierung")
    assert not treffer("Finde die Implementierung des QDP-Readers")
    assert not treffer("Analysiere die Änderung")
    assert treffer("Implementiere die Funktion case-insensitive")
    assert treffer("Ändere die Regex auf case-insensitive")
