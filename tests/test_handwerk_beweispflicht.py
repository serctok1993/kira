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


def test_synthese_toolcall_wird_aus_schritten_gebaut(monkeypatch):
    """v4-Befund (12907): auch die ABSCHLUSS-Synthese kann einen rohen Werkzeug-Aufruf
    liefern — der Schritt-Guard sieht das nicht (es ist sein eigener Ausgang). Dann wird
    das Endergebnis ehrlich aus den Schritten gebaut statt Markup durchzureichen."""
    sid = "t-handwerk-5"
    _mini_plan(monkeypatch, "Lies die Datei separable.py")
    monkeypatch.setattr(act, "act", lambda task, **kw: {"text": "Analyse fertig."})
    monkeypatch.setattr(act.llm_router, "complete", lambda *a, **k: {
        "text": "<tool_call>\n<function=run_command>\n<parameter=command>grep -n x</parameter>"})
    out = act.plan_and_execute("Analysiere separability", session_id=sid)
    assert "<tool_call>" not in out and "<function=" not in out
    assert "Analyse fertig." in out, "das Ergebnis kommt aus den echten Schritten"


def test_auch_das_retry_ergebnis_leckt_keinen_toolcall(monkeypatch):
    """v4-Ordering-Befund: der Leak-Check lief VOR dem Edit-Zwangs-Retry — endete der
    Retry selbst mit einem rohen <tool_call> (Runden-Budget wieder zu Ende), ging das
    Markup ungefiltert ins Schritt-Ergebnis. Jetzt laeuft die Benennung auch danach."""
    sid = "t-handwerk-6"
    _mini_plan(monkeypatch, "Erstelle einen minimalen Patch fuer qdp.py")
    antworten = iter(["Nur Prosa, kein Edit.",
                      "<tool_call>\n<function=read_file>\n<parameter=path>x.py</parameter>"])
    monkeypatch.setattr(act, "act", lambda task, **kw: {"text": next(antworten)})
    out = act.plan_and_execute("Behebe den QDP-Bug", session_id=sid)
    assert "<tool_call>" not in out and "<function=" not in out
    assert "NUR ANALYSE" in out


def test_budget_env_override_greift_und_live_bleibt(monkeypatch):
    """SWE-bench-Runden-Budget: KIRA_BUDGET_MAX_STEPS_PLAN_STEP hebt das Budget NUR
    wenn gesetzt (Sandbox); ohne Env gilt der Config-/Stufen-Wert wie bisher."""
    monkeypatch.setenv("KIRA_BUDGET_MAX_STEPS_PLAN_STEP", "24")
    assert act._budget("max_steps_plan_step", 12, "reason", True) == 24
    monkeypatch.delenv("KIRA_BUDGET_MAX_STEPS_PLAN_STEP")
    assert act._budget("max_steps_plan_step", 12) >= 1  # Basis-/Stufenwert, kein Crash
    monkeypatch.setenv("KIRA_BUDGET_MAX_STEPS_PLAN_STEP", "quatsch")
    assert act._budget("max_steps_plan_step", 12) >= 1  # kaputter Wert faellt zurueck


def test_neue_datei_ist_kein_fix(monkeypatch):
    """9B-Befund (SWE-bench-Baseline, 4/10 Patches nur in NEUEN Dateien): ein
    Fix-Auftrag ist mit write_file (neue Repro-/Testdatei) NICHT erfuellt — nur
    edit_datei/self_edit aendern Bestehendes. Genau EIN Zwangs-Retry, danach steht
    'KEIN FIX AM BESTAND' ehrlich im Ergebnis."""
    sid = "t-handwerk-7"
    _mini_plan(monkeypatch, "Behebe den Bug in qdp.py")
    laeufe = []
    def fake_act(task, **kw):
        laeufe.append(task)
        act._edit_tried_bump(sid, "write_file")  # legt NUR eine neue Datei an
        return {"text": "Repro-Datei test.qdp angelegt, Bug nachgestellt."}
    monkeypatch.setattr(act, "act", fake_act)
    out = act.plan_and_execute("Behebe den QDP-Bug", session_id=sid)
    assert len(laeufe) == 2, "genau EIN Modify-Zwangs-Retry"
    assert "NUR NEUE DATEIEN" in laeufe[1]
    assert "KEIN FIX AM BESTAND" in out


def test_echter_edit_erfuellt_den_fix_auftrag(monkeypatch):
    sid = "t-handwerk-8"
    _mini_plan(monkeypatch, "Behebe den Bug in qdp.py")
    laeufe = []
    def fake_act(task, **kw):
        laeufe.append(task)
        act._edit_tried_bump(sid, "edit_datei")  # aendert Bestehendes
        return {"text": "Regex in qdp.py auf IGNORECASE gestellt."}
    monkeypatch.setattr(act, "act", fake_act)
    out = act.plan_and_execute("Behebe den QDP-Bug", session_id=sid)
    assert len(laeufe) == 1, "kein Retry bei echtem Edit"
    assert "KEIN FIX AM BESTAND" not in out


def test_fuege_hinzu_darf_neue_datei(monkeypatch):
    """'Fuege X hinzu'-Auftraege duerfen legitim mit write_file erfuellt werden —
    der Modify-Guard greift NUR bei Fix-Verben."""
    sid = "t-handwerk-9"
    _mini_plan(monkeypatch, "Füge eine Hilfsdatei helpers.py hinzu")
    laeufe = []
    def fake_act(task, **kw):
        laeufe.append(task)
        act._edit_tried_bump(sid, "write_file")
        return {"text": "helpers.py angelegt."}
    monkeypatch.setattr(act, "act", fake_act)
    act.plan_and_execute("Baue helpers", session_id=sid)
    assert len(laeufe) == 1, "write_file erfuellt einen Hinzufuege-Auftrag"
