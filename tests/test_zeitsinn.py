"""Zeitsinn (Praxis-Fund 08.07.): Kira kennt jetzt die echte Uhrzeit, und verpasste
Tages-Crons werden nach PC-Neustart NICHT stundenspaeter nachgeholt."""
from __future__ import annotations

import datetime as dt
import json
import time

from core.agency.missions import cron
from core.kernel import events
from core.mind import agent


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    monkeypatch.setattr(cron, "_notify", lambda text: None)


def _job(sched: dict, next_run: float, label: str = "test") -> dict:
    return {"id": "j1", "label": label, "prompt": "Es ist 05:55 Uhr. Fuehre den Sunrise aus.",
            "schedule": sched, "schedule_text": "05:55", "enabled": True, "escalate": False,
            "scope": "system", "last_run": 0, "next_run": next_run, "runs": []}


# ---------- JETZT-Zeile: Kira kennt die echte Zeit ----------

def test_jetzt_zeile_hat_datum_und_wochentag():
    z = agent.jetzt_zeile()
    n = dt.datetime.now()
    assert z.startswith("JETZT: ")
    assert n.strftime("%d.%m.%Y") in z and n.strftime("%H:%M") in z
    assert agent._WOCHENTAGE[n.weekday()] in z


def test_identity_und_systemprompt_beginnen_mit_jetzt(monkeypatch, tmp_path):
    from core.agency import act
    assert act._identity().startswith("JETZT: ")
    # Chat-Prompt: Memory faellt ohne DB weich aus -> auf tmp-DB zeigen
    from core.mind.memory import store as memory
    monkeypatch.setattr(memory, "DB_PATH", str(tmp_path / "mem.db"))
    memory.init_memory()
    assert agent.build_system_prompt("hallo").startswith("JETZT: ")


def test_cron_prompt_bekommt_echte_zeit(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen = {}

    def fake_act(prompt, session_id=None, escalate=False, task_type="reason"):
        seen["prompt"] = prompt
        return {"text": "ok"}

    import core.agency.act as act_mod
    monkeypatch.setattr(act_mod, "act", fake_act)
    job = _job({"type": "daily", "time": "05:55"}, next_run=time.time() - 60)
    cron.run_job(job, notify=False)
    assert seen["prompt"].startswith("JETZT: ")                    # echte Zeit steht VOR
    assert "Es ist 05:55 Uhr" in seen["prompt"]                    # ...der alten Behauptung


# ---------- Verfallsfenster: verpasste Tages-Crons nicht nachholen ----------

def test_daily_stark_ueberfaellig_wird_uebersprungen(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    now = time.time()
    cron._save([_job({"type": "daily", "time": "05:55"}, next_run=now - 11 * 3600, label="Sunrise")])
    executed = []
    monkeypatch.setattr(cron, "run_job", lambda j, notify=True: executed.append(j["label"]) or {"ok": True, "summary": ""})

    ran = cron.run_due(now=now)
    assert ran == [] and executed == []                            # NICHT nachgeholt
    j = json.loads(cron.JOBS.read_text(encoding="utf-8"))[0]
    assert j["next_run"] > now                                     # neuer regulaerer Termin
    assert "verpasst" in j["runs"][-1]["summary"]                  # Spur im Verlauf
    assert any(e["type"] == "cron_missed" for e in events.recent(5))


def test_daily_leicht_verspaetet_laeuft_noch(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    now = time.time()
    cron._save([_job({"type": "daily", "time": "05:55"}, next_run=now - 30 * 60)])  # 30 min spaet
    executed = []
    monkeypatch.setattr(cron, "run_job", lambda j, notify=True: executed.append(j["label"]) or {"ok": True, "summary": ""})
    ran = cron.run_due(now=now)
    assert len(ran) == 1 and executed == ["test"]                  # innerhalb der Gnadenfrist


def test_intervall_holt_genau_einmal_nach(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    now = time.time()
    cron._save([_job({"type": "interval", "minutes": 30}, next_run=now - 11 * 3600)])

    def fake_run(j, notify=True):
        j["next_run"] = cron._next_run(j["schedule"])              # wie das Original: neu ab jetzt
        return {"ok": True, "summary": ""}

    monkeypatch.setattr(cron, "run_job", fake_run)
    assert len(cron.run_due(now=now)) == 1                         # ein Nachhol-Lauf, kein Schwall
    j = json.loads(cron.JOBS.read_text(encoding="utf-8"))[0]
    assert j["next_run"] > now                                     # danach frisch getaktet


def test_cron_missed_wird_beschrieben():
    d = events.describe("cron_missed", {"label": "Sunrise", "overdue_h": 11.5})
    assert "verpasst" in d["text"] and "Sunrise" in d["detail"]
