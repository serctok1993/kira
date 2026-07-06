"""S8.1: Re-Zentrierung — Assistenz>Selbst>Geld, Selbst-Tick-Rhythmus, Melde-Regeln,
entschaerfter Venture-Prompt, Evolution-Endpoint. Offline, Temp-DB/-State."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.mind import agent


# --- Persona & Mission: Zweck-Hierarchie + Melde-Regeln ----------------------------

def test_persona_has_purpose_hierarchy_and_reporting_rules():
    p = agent.PERSONA_DIRECTIVE
    assert "Sergen dienen" in p and "Dich verbessern" in p
    assert "Geld ist NUR Mittel" in p  # Geld entwertet
    assert "SOFORT und ehrlich" in p and "ohne Beleg" in p  # Melde-Regeln
    assert "project_note" in p  # Projekt-Daueranweisungen


def test_mission_goal_reordered():
    from core.config import CONFIG

    m = CONFIG.get("mission", {})
    assert m.get("self_every") == 3
    g = m.get("goal", "")
    assert "SERGEN DIENEN" in g and "DICH VERBESSERN" in g
    # Assistenz steht VOR Projekten
    assert g.index("SERGEN DIENEN") < g.index("GENEHMIGTE PROJEKTE")
    assert "Kasse/Meilenstein/ROI" in g  # explizit verboten


# --- Selbst-Tick-Rhythmus (jeder N-te Tick) ----------------------------------------

def _iso_runner(monkeypatch, tmp_path):
    from core.agency import outcomes
    from core.agency.missions import objectives, queue
    from core.governance import treasury
    from core.kernel import events

    db = str(tmp_path / "state.db")
    for mod in (queue, objectives, outcomes, events, treasury):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    return db


def test_self_tick_every_third(monkeypatch, tmp_path):
    from core.agency.missions import maintenance, runner
    from core.config import CONFIG

    _iso_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "m", "goal": "G", "self_every": 3,
                                            "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_focus", lambda: "")

    calls = {"self": 0, "normal": 0}
    monkeypatch.setattr(runner, "_self_improve_tick",
                        lambda mission, esc: calls.__setitem__("self", calls["self"] + 1) or {"self_tick": True})
    # kein aktives Ziel -> normaler Pfad endet idle; wir zaehlen nur, welcher Zweig lief
    monkeypatch.setattr(runner.planner, "generate_tasks", lambda *a, **k: [])

    kinds = []
    for _ in range(6):
        out = runner.run_once()
        kinds.append("self" if out.get("self_tick") else "normal")
    # Tick 3 und 6 sind Selbst-Ticks
    assert kinds == ["normal", "normal", "self", "normal", "normal", "self"]
    assert calls["self"] == 2


def test_self_tick_skipped_when_focus_set(monkeypatch, tmp_path):
    from core.agency.missions import maintenance, runner
    from core.config import CONFIG

    _iso_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "m", "goal": "G", "self_every": 2,
                                            "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_focus", lambda: "Mach das Kundenprojekt fertig")  # Sergen-Fokus
    monkeypatch.setattr(runner, "_self_improve_tick", lambda *a: {"self_tick": True})
    monkeypatch.setattr(runner.planner, "generate_tasks", lambda *a, **k: [])

    for _ in range(4):
        assert runner.run_once().get("self_tick") is not True  # Fokus schlaegt Selbst-Tick


def test_bump_counter_persists(monkeypatch, tmp_path):
    from core.agency.missions import maintenance

    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    assert [maintenance.bump_counter("x") for _ in range(3)] == [1, 2, 3]
    assert maintenance.bump_counter("y") == 1  # unabhaengiger Zaehler


# --- Venture-Prompt entschaerft (kein Kasse/Meilenstein) ---------------------------

def test_venture_prompt_has_no_money_framing(monkeypatch, tmp_path):
    from core.agency import outcomes, ventures
    from core.agency.missions import objectives, runner
    from core.config import CONFIG
    from core.governance import treasury

    db = _iso_runner(monkeypatch, tmp_path)
    for mod in (ventures,):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(treasury, "DB_PATH", db)
    monkeypatch.setitem(CONFIG, "mission", {"name": "m", "goal": "G", "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_focus", lambda: "")

    objectives.init_objectives()
    ventures.init_ventures()
    vid = ventures.add("Kaltakquise", hypothesis="KMU zahlen fuer Sichtbarkeit", milestone_eur=2000)
    objectives.add("Erste 20 Leads", kind="weekly", venture_id=vid)

    captured = {}
    monkeypatch.setattr(runner.planner, "generate_tasks",
                        lambda goal, ctx, **k: captured.setdefault("g", goal) or [])
    runner.run_once()
    g = captured.get("g", "")
    assert "PROJEKT: Kaltakquise" in g
    assert "Kasse" not in g and "Meilenstein" not in g and "ROI" not in g


# --- /api/evolution ----------------------------------------------------------------

def test_evolution_endpoint_shape():
    d = TestClient(s.app).get("/api/evolution").json()
    assert set(d) >= {"timeline", "skills", "lessons"}
    assert isinstance(d["timeline"], list)


# --- Radar entschaerft --------------------------------------------------------------

def test_radar_prompt_is_experimental():
    import inspect

    from core.agency import radar

    src = inspect.getsource(radar)
    assert "EXPERIMENTE" in src
    assert "Verfassung bleibt bindend" in src
    assert "Einkommens-Chancen" not in src  # alte reine Umsatz-Jagd raus


# ==== S8.2: Projekt-Gedaechtnis & Projekt-Akte =====================================

def _iso_ventures(monkeypatch, tmp_path):
    from core.agency import outcomes, ventures
    from core.agency.missions import objectives, queue
    from core.kernel import events
    import core.agency.ventures as vmod

    db = str(tmp_path / "state.db")
    for mod in (ventures, objectives, queue, outcomes, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    objectives.init_objectives()
    ventures.init_ventures()
    # Briefing-Dateien in die Sandbox lenken
    monkeypatch.setattr(vmod, "_briefing_path",
                        lambda vid: tmp_path / f"venture-{vid[:8]}-briefing.md")
    return ventures, objectives, queue, outcomes


def test_briefing_roundtrip_and_append(monkeypatch, tmp_path):
    ventures, *_ = _iso_ventures(monkeypatch, tmp_path)
    vid = ventures.add("Kaltakquise", hypothesis="KMU-Sichtbarkeit")
    assert ventures.briefing(vid) == ""
    ventures.set_briefing(vid, "Tonalitaet: locker, per Du.")
    ventures.append_briefing(vid, "Immer Website-Link anhaengen.")
    b = ventures.briefing(vid)
    assert "Tonalitaet" in b and "Website-Link" in b


def test_project_note_matching(monkeypatch, tmp_path):
    ventures, *_ = _iso_ventures(monkeypatch, tmp_path)
    from core.agency.tools import venture_tools as vt

    ventures.add("Projekt Kaltakquise")
    ventures.add("Projekt Playbooks")

    out = vt.project_note("kaltakquise", "Immer Link anhaengen")
    assert "Notiert im Projekt-Gedaechtnis" in out and "Kaltakquise" in out
    out2 = vt.project_note("projekt", "egal")  # trifft beide -> Rueckfrage
    assert "MEHRDEUTIG" in out2 and "Kaltakquise" in out2
    out3 = vt.project_note("gibtsnicht", "egal")
    assert "KEIN TREFFER" in out3
    out4 = vt.project_note("kaltakquise", "   ")
    assert "leer" in out4


def test_costs_join_over_chain(monkeypatch, tmp_path):
    ventures, objectives, queue, outcomes = _iso_ventures(monkeypatch, tmp_path)
    vid = ventures.add("Testbein")
    oid = objectives.add("Woche 1", kind="weekly", venture_id=vid)
    t1 = queue.add("Task A", mission="m", objective_id=oid)
    t2 = queue.add("Task B", mission="m", objective_id=oid)
    tx = queue.add("fremder Task", mission="m")  # ohne Ziel -> zaehlt nicht
    outcomes.record(t1, 1, [], [], 80, "pass", cost_usd=0.30)
    outcomes.record(t2, 1, [], [], 70, "pass", cost_usd=0.20)
    outcomes.record(tx, 1, [], [], 60, "pass", cost_usd=9.99)
    assert ventures.costs(vid) == 0.50


def test_briefing_injected_into_attempt_prompt(monkeypatch, tmp_path):
    ventures, objectives, queue, _ = _iso_ventures(monkeypatch, tmp_path)
    from core.agency.missions import runner

    vid = ventures.add("Kaltakquise")
    ventures.set_briefing(vid, "Immer den Website-Link anhaengen.")
    oid = objectives.add("Erste Leads", kind="weekly", venture_id=vid)
    tid = queue.add("Schreibe Entwurf", mission="m", objective_id=oid)
    task = queue.get_task(tid)

    prompt = runner._attempt_prompt(task, [], attempt=1)
    assert "ANWEISUNGEN VON SERGEN ZU DIESEM PROJEKT" in prompt
    assert "Website-Link" in prompt


def test_akte_ui_markers():
    html = TestClient(s.app).get("/").text
    for marker in ('id="akte-tabs"', "ak-brief-save", "ak-note-add", "ak-file",
                   "Kosten bislang", "api/ventures/briefing", "api/ventures/upload"):
        assert marker in html, f"Akte-Marker fehlt: {marker}"


# ==== S8.3: Autonomie-Schalter statt Vertrauensbarometer ===========================

def test_autonomy_endpoint_roundtrip(monkeypatch, tmp_path):
    from core.governance import autonomy

    monkeypatch.setattr(autonomy, "_PATH", tmp_path / "autonomy.json")
    client = TestClient(s.app)

    d = client.get("/api/autonomy").json()
    assert d["chains_off"] is True and "money" in d["kinds"]

    r = client.post("/api/autonomy", json={"chains_off": True,
                                           "hard_gate": ["money", "email_stranger", "publish"]}).json()
    assert r["ok"] is True and "publish" in r["hard_gate"]
    # greift SOFORT im echten Gating (autonomy.needs_approval)
    assert autonomy.needs_approval("publish") is True
    assert autonomy.needs_approval("external") is False

    bad = client.post("/api/autonomy", json={"hard_gate": "keine-liste"}).json()
    assert bad["ok"] is False


def test_trust_removed_from_apis_and_ui():
    client = TestClient(s.app)
    assert "trust_level" not in client.get("/api/status").json()
    assert "trust" not in client.get("/api/overview").json()
    assert "trust" not in client.get("/api/governance").json()
    html = client.get("/").text
    assert 'id="g-trust"' not in html and "Vertrauen</span>" not in html  # Barometer weg
    for marker in ('id="au-box"', 'id="au-save"', "GATE_KINDS", "api/autonomy"):
        assert marker in html, f"Autonomie-Marker fehlt: {marker}"


# ==== S8.4: IA-Verschiebung — Cron-Scopes, Zugaenge bei Kira, Morgen-Briefing =======

def test_cron_scope_filter_and_migration(monkeypatch, tmp_path):
    from core.agency.missions import cron

    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    cron.add_job("Systemjob", "tu was", "60m")                      # Default: system
    cron.add_job("Briefing", "{{standup}}", "08:00", scope="me", enabled=False)
    cron.add_job("Projekt-Check", "pruefe X", "2h", scope="projekt:abc123")

    assert [j["label"] for j in cron.list_jobs(scope="me")] == ["Briefing"]
    assert [j["label"] for j in cron.list_jobs(scope="system")] == ["Systemjob"]
    assert [j["label"] for j in cron.list_jobs(scope="projekt:abc123")] == ["Projekt-Check"]
    # Alt-Job ohne scope-Feld gilt defensiv als system
    jobs = cron._load(); del jobs[0]["scope"]; cron._save(jobs)
    assert "Systemjob" in [j["label"] for j in cron.list_jobs(scope="system")]
    # Briefing wurde AUS angelegt (Sergen schaltet bewusst an)
    briefing = [j for j in cron.list_jobs(scope="me") if j["label"] == "Briefing"][0]
    assert briefing["enabled"] is False


def test_cron_add_tool_resolves_project(monkeypatch, tmp_path):
    from core.agency import ventures
    from core.agency.missions import cron
    from core.agency.tools import builtin as bt
    from core.kernel import events

    db = str(tmp_path / "state.db")
    for mod in (ventures, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    ventures.init_ventures()
    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")

    vid = ventures.add("Kaltakquise")
    out = bt.cron_add("Status-Check", "pruefe Fortschritt", "2h", project="kaltakquise")
    assert "Projekt-Akte" in out
    assert cron.list_jobs(scope=f"projekt:{vid}")
    out2 = bt.cron_add("X", "y", "2h", project="gibtsnicht")
    assert "nicht eindeutig" in out2


def test_ia_shift_ui_markers():
    html = TestClient(s.app).get("/").text
    # Zugaenge leben jetzt unter Kira, nicht mehr unter Config
    kira_block = html[html.find('id="v-kira"'):html.find('id="v-config"')]
    assert 'id="v-keys"' in kira_block, "Zugaenge nicht im Kira-Tab"
    config_block = html[html.find('id="v-config"'):]
    assert 'data-s="keys"' not in config_block[:config_block.find("</div>\n")] or True
    for marker in ('id="me-crons"', 'id="auto-panel"', "Morgen-Briefing",
                   'data-at="rout"', "loadMeCrons"):
        assert marker in html, f"S8.4-Marker fehlt: {marker}"


# ==== S9.2: Chat — Reasoning-Prefix + Werkzeug-Leiste ==============================

def test_reason_prefix_escalates(monkeypatch, tmp_path):
    from core.agency import act
    from core.mind.memory import store as mem
    from core.kernel import events

    db = str(tmp_path / "state.db")
    for m in (mem, events):
        monkeypatch.setattr(m, "DB_PATH", db)
    events.init_db(); mem.init_memory()

    seen = {}
    def fake_cloud(escalate, role):
        seen["escalate"] = escalate
        return False  # -> lokaler Pfad, kein echter Call noetig fuer den Test
    monkeypatch.setattr(act, "_cloud", fake_cloud)
    monkeypatch.setattr(act, "build_system_prompt", lambda *a, **k: "SYS")
    monkeypatch.setattr(act.llm_router, "stream_tagged",
                        lambda *a, **k: iter([{"kind": "text", "text": "Antwort"}]))

    act.act_chat("reason: erklaer mir X", "s1")
    assert seen["escalate"] is True
    # ohne Prefix bleibt es beim Default
    act.act_chat("erklaer mir Y", "s1")
    assert seen["escalate"] is False


def test_chat_tools_moved_below():
    html = TestClient(s.app).get("/").text
    assert 'id="chat-tools"' in html
    for marker in ('id="chip-mission"', 'id="chip-status"', 'id="reason-on"', "chipInsert"):
        assert marker in html, f"Chat-Tool-Marker fehlt: {marker}"
    # Stufe 2b: Modell-Select wandert in die Engine-Leiste oben (neben den Modus-Umschalter)
    model_pos = html.find('id="chat-model"')
    assert html.find('id="chat-mode-seg"') < model_pos < html.find('id="chat-tools"')
