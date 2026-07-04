"""Dispatcher + Liefernachweis: Planer vergibt Raenge, Schritte routen danach,
Datei-Behauptungen pro Schritt werden erzwungen (ein Zwangs-Retry, dann ehrlich).
"""
from __future__ import annotations


def _tmp_dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()
    return events


def _fake_complete(text: str):
    def fake(messages, system=None, task_type="chat", session_id=None, escalate=False, tools=None):
        return {"text": text, "cost_usd": 0.0, "model": "fake", "fell_back": False,
                "latency_s": 0.0, "escalated": False, "tool_calls": []}
    return fake


def _no_reflection(monkeypatch):
    from core.mind import reflection
    monkeypatch.setattr(reflection, "reflect_on", lambda *a, **k: {})


# ---- _make_plan: Rang-Etiketten -------------------------------------------------------

def test_make_plan_parst_raenge(monkeypatch):
    from core.agency import act
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "complete", _fake_complete(
        '[{"schritt": "Lies leads.csv", "rang": "reflex"},'
        ' {"schritt": "Schreibe Mails", "rang": "arbeiter"},'
        ' {"schritt": "Waehle Top 10", "rang": "denker"}]'))
    steps = act._make_plan("egal", None)
    assert [s["rang"] for s in steps] == ["reflex", "arbeiter", "denker"]


def test_make_plan_tolerant(monkeypatch):
    from core.agency import act
    from core.kernel import llm_router
    # Strings (schwacher Planer) -> denker; unbekannter Rang -> denker
    monkeypatch.setattr(llm_router, "complete", _fake_complete(
        '["Schritt eins", {"schritt": "Schritt zwei", "rang": "general"}]'))
    steps = act._make_plan("egal", None)
    assert steps[0] == {"schritt": "Schritt eins", "rang": "denker"}
    assert steps[1]["rang"] == "denker"
    # Muell -> ein Denker-Schritt mit der Aufgabe selbst
    monkeypatch.setattr(llm_router, "complete", _fake_complete("kein json hier"))
    steps = act._make_plan("mach was", None)
    assert steps == [{"schritt": "mach was", "rang": "denker"}]


# ---- Dispatcher: Schritte routen nach Rang --------------------------------------------

def test_dispatcher_routet_nach_rang(monkeypatch, tmp_path):
    from core.agency import act
    from core.kernel import llm_router
    _tmp_dbs(monkeypatch, tmp_path)
    _no_reflection(monkeypatch)
    monkeypatch.setattr(act, "_CLAIM_CHECK", False)
    monkeypatch.setattr(act, "_make_plan", lambda task, sid, escalate=True: [
        {"schritt": "lesen", "rang": "reflex"},
        {"schritt": "schreiben", "rang": "arbeiter"},
        {"schritt": "urteilen", "rang": "denker"},
    ])
    monkeypatch.setattr(llm_router, "complete", _fake_complete("Zusammenfassung."))
    calls: list = []

    def fake_act(task, session_id=None, max_steps=None, escalate=False, task_type="reason"):
        calls.append({"task_type": task_type, "escalate": escalate})
        return {"text": "ok", "steps": 1}

    monkeypatch.setattr(act, "act", fake_act)
    act.plan_and_execute("grosse Aufgabe", session_id="p1", escalate=True)

    assert [c["task_type"] for c in calls] == ["classify", "worker", "reason"]
    # Eskalation NUR fuer den Denker-Schritt — Arbeiter/Reflex bleiben billig
    assert [c["escalate"] for c in calls] == [False, False, True]


def test_dispatcher_ohne_eskalation(monkeypatch, tmp_path):
    from core.agency import act
    from core.kernel import llm_router
    _tmp_dbs(monkeypatch, tmp_path)
    _no_reflection(monkeypatch)
    monkeypatch.setattr(act, "_CLAIM_CHECK", False)
    monkeypatch.setattr(act, "_make_plan", lambda task, sid, escalate=True: [
        {"schritt": "urteilen", "rang": "denker"}])
    monkeypatch.setattr(llm_router, "complete", _fake_complete("fertig"))
    calls: list = []
    monkeypatch.setattr(act, "act", lambda task, session_id=None, max_steps=None,
                        escalate=False, task_type="reason":
                        calls.append(escalate) or {"text": "ok", "steps": 1})
    act.plan_and_execute("auto-plan aufgabe", session_id="p2", escalate=False)
    assert calls == [False]  # Auto-Plan eskaliert auch Denker-Schritte nicht


# ---- Liefernachweis pro Schritt --------------------------------------------------------

def test_liefernachweis_retry_und_erfolg(monkeypatch, tmp_path):
    from core.agency import act
    from core.kernel import llm_router
    events = _tmp_dbs(monkeypatch, tmp_path)
    _no_reflection(monkeypatch)
    monkeypatch.setattr(act, "_CLAIM_CHECK", True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(act, "_make_plan", lambda task, sid, escalate=True: [
        {"schritt": "Schreibe die Mail nach ~/Desktop/luvex/mail1.md", "rang": "arbeiter"}])
    monkeypatch.setattr(llm_router, "complete", _fake_complete("Zusammenfassung."))

    versuche: list = []

    def fake_act(task, session_id=None, max_steps=None, escalate=False, task_type="reason"):
        versuche.append(task)
        if len(versuche) == 1:  # erster Versuch: LUEGT — Datei existiert nicht
            return {"text": "Ich habe die Mail erstellt: `~/Desktop/luvex/mail1.md`", "steps": 1}
        # Retry: liefert WIRKLICH
        f = tmp_path / "Desktop" / "luvex" / "mail1.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("mail", encoding="utf-8")
        return {"text": "Jetzt wirklich erstellt: `~/Desktop/luvex/mail1.md`", "steps": 2}

    monkeypatch.setattr(act, "act", fake_act)
    final = act.plan_and_execute("Mail schreiben", session_id="p3", escalate=False)

    assert len(versuche) == 2  # genau EIN Zwangs-Retry
    assert "existieren NICHT" in versuche[1]  # der Retry-Prompt ist hart und konkret
    assert "NICHT BELEGT" not in final
    types = [e["type"] for e in events.recent(30)]
    assert "plan_step_retry" in types
    assert "plan_step_unproven" not in types


def test_liefernachweis_ehrlicher_fehlschlag(monkeypatch, tmp_path):
    from core.agency import act
    from core.kernel import llm_router
    events = _tmp_dbs(monkeypatch, tmp_path)
    _no_reflection(monkeypatch)
    monkeypatch.setattr(act, "_CLAIM_CHECK", True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(act, "_make_plan", lambda task, sid, escalate=True: [
        {"schritt": "Schreibe nach ~/Desktop/x/fake.md", "rang": "arbeiter"}])
    # Synthese gibt leeren Text -> Fallback baut die Zusammenfassung aus den Schritten
    monkeypatch.setattr(llm_router, "complete", _fake_complete(""))
    monkeypatch.setattr(act, "act", lambda *a, **k: {
        "text": "Erledigt, gespeichert unter `~/Desktop/x/fake.md`", "steps": 1})

    final = act.plan_and_execute("liefern", session_id="p4", escalate=False)

    assert "NICHT BELEGT" in final  # der Fehlschlag steht EHRLICH im Ergebnis
    assert "plan_step_unproven" in [e["type"] for e in events.recent(30)]


# ---- Playbook (Obsidian-Richtungsleitung) ---------------------------------------------

def test_leads_playbook_vorhanden():
    from pathlib import Path
    from core.config import ROOT
    pb = (ROOT / "playbooks" / "leads-recherche.md").read_text(encoding="utf-8")
    assert pb.startswith("---")
    assert "reifegrad: entwurf" in pb
    assert "Beweispflicht" in pb  # Akzeptanz verlangt existierende Datei
