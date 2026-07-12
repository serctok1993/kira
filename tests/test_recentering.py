"""S8.1/W1: Re-Zentrierung — Assistenz>Selbst, Selbst-Tick-Rhythmus, Melde-Regeln,
Autonomie-Schalter, Chat-Werkbank. Offline, Temp-DB/-State. (Die Venture-/Projekt-
Tests sind mit dem Business-Strang in W1 ausgebaut worden.)"""
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
    assert "project_note" not in p  # W1: Projekt-Werkzeug ist ausgebaut


def test_persona_hat_mitdenken_und_nachschau_blocks():
    """Prompt-Touch: Proaktivitaet (1 Mitdenk-Schritt, ausser Voice) + effizienter
    Nachschau-Weg (Karte -> Adresse -> nur diese Datei, nie den Vault scannen)."""
    p = agent.PERSONA_DIRECTIVE
    # Mitdenken: genau EIN vorausschauender Schritt, Voice ist die Ausnahme
    assert "WIE DU MITDENKST" in p
    assert "GENAU EIN" in p
    assert "sprich:" in p  # Voice-Modus bleibt knapp
    assert "ok, mach ich" in p  # das explizit NICHT als ganze Antwort
    # Nachschau: adressiert statt scannen
    assert "WO DU NACHSCHAUST" in p
    assert "INDEX.md" in p and "stammbaum" in p and "playbooks" in p
    assert "nie alles durchwuehlen" in p or "nicht den ganzen Ordner" in p


def test_mission_goal_reordered():
    # S12: Dienst-Mission ohne Geldziel — Alltag tragen + Selbstpflege, Messbarkeit
    # ueber Betriebs-Metriken statt Euro. Melde-Regeln bleiben woertlich bindend.
    from core.config import CONFIG

    m = CONFIG.get("mission", {})
    assert m.get("self_every") == 3
    g = m.get("goal", "")
    assert "SERGENS ALLTAG TRAGEN" in g and "DICH SELBST PFLEGEN" in g
    # Assistenz steht VOR der Selbstpflege; kein Business-/Etappen-Ziel mehr in der Mission
    assert g.index("SERGENS ALLTAG TRAGEN") < g.index("DICH SELBST PFLEGEN")
    assert "GENEHMIGTE PROJEKTE" not in g and "10k" not in g
    assert "Kasse/Meilenstein/ROI" in g  # Geld-Denken bleibt explizit ausgeschlossen
    assert "NIE Erfolg behaupten ohne Beleg" in g  # Melde-Regeln woertlich erhalten
    assert "Betriebs-Metriken" in g


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
    # nichts einplanen -> normaler Pfad endet idle; wir zaehlen nur, welcher Zweig lief
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


# --- W1: der Heartbeat plant OHNE Business-Grind -------------------------------------

def test_run_once_plant_direkt_auf_die_mission(monkeypatch, tmp_path):
    from core.agency.missions import maintenance, runner
    from core.config import CONFIG

    _iso_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    monkeypatch.setitem(CONFIG, "mission", {"name": "m", "goal": "DIENST-MISSION",
                                            "notify_telegram": False})
    monkeypatch.setattr(runner, "kill_switch_active", lambda: False)
    monkeypatch.setattr(runner, "_focus", lambda: "")

    captured = {}
    monkeypatch.setattr(runner.planner, "generate_tasks",
                        lambda goal, ctx, **k: captured.update({"g": goal}) or [])
    out = runner.run_once()
    assert out.get("idle") is True
    assert captured["g"] == "DIENST-MISSION"        # kein Ziel-/Projekt-Kopf mehr davor


# --- /api/evolution ----------------------------------------------------------------

def test_evolution_endpoint_shape():
    d = TestClient(s.app).get("/api/evolution").json()
    assert set(d) >= {"timeline", "skills", "lessons"}
    assert isinstance(d["timeline"], list)


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


# ==== S8.4: IA-Verschiebung — Cron-Scopes, Morgen-Briefing ==========================

def test_cron_scope_filter_and_migration(monkeypatch, tmp_path):
    from core.agency.missions import cron

    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    cron.add_job("Systemjob", "tu was", "60m")                      # Default: system
    cron.add_job("Briefing", "{{standup}}", "08:00", scope="me", enabled=False)

    assert [j["label"] for j in cron.list_jobs(scope="me")] == ["Briefing"]
    assert [j["label"] for j in cron.list_jobs(scope="system")] == ["Systemjob"]
    # Alt-Job ohne scope-Feld gilt defensiv als system
    jobs = cron._load(); del jobs[0]["scope"]; cron._save(jobs)
    assert "Systemjob" in [j["label"] for j in cron.list_jobs(scope="system")]
    # Briefing wurde AUS angelegt (Sergen schaltet bewusst an)
    briefing = [j for j in cron.list_jobs(scope="me") if j["label"] == "Briefing"][0]
    assert briefing["enabled"] is False


def test_ia_shift_ui_markers():
    html = TestClient(s.app).get("/").text
    for marker in ('id="me-crons"', 'id="auto-panel"', "Morgen-Briefing", "loadMeCrons"):
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
    for marker in ('id="cmd-help"', 'id="reason-level"', "chipInsert", 'id="cmd-pop"'):
        assert marker in html, f"Chat-Tool-Marker fehlt: {marker}"
    # S11: Modell-Knopf wandert in die Werkzeugleiste (ganz rechts, ueber Senden)
    assert 'id="model-btn"' in html
    assert html.find('id="chat-tools"') < html.find('id="model-btn"') < html.find('id="cform"')
