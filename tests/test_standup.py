"""S5.1: Standup-Lagebericht + Cron-Platzhalter — offline, kein LLM."""
from __future__ import annotations

from core.agency.missions import cron, metrics, objectives, queue, standup
from core.kernel import events


def _use_tmp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (objectives, queue, metrics, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    # Post-Cap-Bloecke (Termin-Radar, Logbuch-Frage, Fokus) lesen sonst des Nutzers ECHTEN
    # Vault (ROOT/gedaechtnis) -> Testlaenge/-inhalt haengt an Live-Daten. Isolieren.
    monkeypatch.setattr(standup, "ROOT", tmp_path)
    events.init_db()
    objectives.init_objectives()
    queue.init_queue()


def test_build_context_sections_and_cap(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    # News-Block liest den Live-Monitor (Netz/Zustand) -> fuer den Cap-Check stummschalten
    monkeypatch.setattr(standup, "_news_block", lambda *a, **k: "")
    queue.add("Zahnarzt anrufen", mission="leben", due_date=__import__("datetime").date.today().isoformat())
    objectives.add("Abnehmen auf 85kg", kind="big", domain="leben")
    metrics.log("gewicht", 92.0)
    metrics.log("gewicht", 91.4)
    events.emit("mission_task_done", {"id": "x"})

    ctx = standup.build_context("morgen")
    assert "LAGEBERICHT" in ctx
    assert "Zahnarzt" in ctx and "HEUTE:" in ctx
    assert "Abnehmen" in ctx and "LEBEN" in ctx
    assert "gewicht: 91.4" in ctx and "-0.6" in ctx
    assert "1 Aufgaben erledigt" in ctx
    assert len(ctx) <= 2500  # Kap haelt (Kontext-Diaet)
    # KEIN LLM-Call: build_context ist reiner Daten-Read (kein llm_call-Event entstanden)
    assert not any(e["type"] == "llm_call" for e in events.recent(50))


def test_build_context_empty_db_is_calm(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    ctx = standup.build_context()
    assert "LAGEBERICHT" in ctx and "0 Aufgaben erledigt" in ctx


def test_build_context_kennt_kein_business_mehr(monkeypatch, tmp_path):
    # W1: der Business-/Ventures-Block ist AUSGEBAUT — auch mit business-Zielen in der DB
    # erzaehlt das Briefing nichts mehr davon (alte Daten bleiben stumm liegen).
    _use_tmp_db(monkeypatch, tmp_path)
    objectives.add("QS-SEO ausbauen", domain="business", target_date="2026-08-01")
    ctx = standup.build_context("morgen")
    assert "BUSINESS" not in ctx and "VENTURES" not in ctx


def test_cron_expands_standup_placeholder(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    queue.add("Zahnarzt anrufen", mission="leben",
              due_date=__import__("datetime").date.today().isoformat())
    received = {}

    def fake_act(prompt, session_id=None, escalate=False, task_type="bulk", **kw):
        received["prompt"] = prompt
        return {"text": "Briefing erstellt.", "steps": 1}

    import core.agency.act as act_mod
    monkeypatch.setattr(act_mod, "act", fake_act)
    monkeypatch.setattr(cron, "_next_run", lambda s, ref=None: 0.0)  # Schedule-Format entkoppeln

    job = {"id": "j1", "label": "Morgen-Briefing", "schedule": "08:00",
           "prompt": "{{standup}}\n\nErstelle daraus mein Briefing.", "enabled": True}
    res = cron.run_job(job, notify=False)
    assert res["ok"]
    assert "{{standup}}" not in received["prompt"]  # expandiert
    assert "LAGEBERICHT" in received["prompt"] and "Zahnarzt" in received["prompt"]
    assert "Erstelle daraus mein Briefing." in received["prompt"]


def test_cron_placeholder_fail_soft(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)

    def boom(scope="x"):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(standup, "build_context", boom)
    received = {}

    def fake_act(prompt, **kw):
        received["prompt"] = prompt
        return {"text": "ok", "steps": 1}

    import core.agency.act as act_mod
    monkeypatch.setattr(act_mod, "act", fake_act)
    monkeypatch.setattr(cron, "_next_run", lambda s, ref=None: 0.0)
    cron.run_job({"id": "j2", "label": "x", "schedule": "08:00",
                  "prompt": "{{standup}} egal", "enabled": True}, notify=False)
    assert "nicht verfuegbar" in received["prompt"]  # Platzhalter-Fallback statt Crash
