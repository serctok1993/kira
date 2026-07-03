"""FastAPI-Cockpit: Chat (mit Live-Thinking), Seele/Dateien, Modelle, Protokoll.

Ein Prozess, eine Seite (Terminal-Look). Start:
    uv run uvicorn core.api.server:app --reload   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import time

import anyio
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from core.agency.tools import builtin as _builtin  # noqa: F401  (registriert eingebaute Tools)
from core.agency.tools import registry
from core.agency.tools import synthesize as _synth
from core.config import CONFIG, MIND_DIR, ROOT
from core.governance import audit, secrets, treasury
from core.kernel import events, models
from core.kernel.llm_router import today_spend_usd
from core.kernel.phrases import THINKING_PHRASES
from core.kernel.scheduler import heartbeat_on, kill_switch_active, kill_switch_path, set_heartbeat
from core.mind.agent import Agent
from core.mind.memory import store as memory

app = FastAPI(title="Kira Cockpit")
events.init_db()
memory.init_memory()
try:  # Workspace-Tabellen (Ziele + Task-Felder + Freigabe-Inbox) sicherstellen
    from core.agency.missions import objectives as _objectives, queue as _queue0
    from core.agency import approvals as _approvals0
    _objectives.init_objectives()
    _queue0.init_queue()
    _approvals0.init_approvals()
except Exception:  # noqa: BLE001
    pass
_synth.load_synthesized()  # selbstgebaute Werkzeuge fuer die Uebersicht verfuegbar machen
try:  # MCP-Bruecke im Hintergrund anschliessen (Ausfall darf den Boot nie bricken)
    from core.agency.mcp import registry_bridge as _mcp_bridge
    _mcp_bridge.init_background()
except Exception:  # noqa: BLE001
    pass

# Im Dashboard sichtbare/bearbeitbare Dateien.
# Die Verfassung ist ueberall nur lesend (Cockpit, Kira-Tools, Evolution) — Aenderungen
# macht Sergen bewusst via Git/Editor. Grund: am 02.07. wurde sie ueber genau diesen
# Endpoint abgeschwaecht, ohne dass es jemandem auffiel.
FILES: dict[str, dict] = {
    "constitution.md": {"path": MIND_DIR / "constitution.md", "editable": False, "label": "Verfassung (nur lesend — Aenderung nur via Git durch Sergen)"},
    "SOUL.md": {"path": MIND_DIR / "SOUL.md", "editable": True, "label": "Seele (SOUL)"},
    "GOAL.md": {"path": MIND_DIR / "GOAL.md", "editable": True, "label": "Ziel (GOAL)"},
    "USER.md": {"path": MIND_DIR / "USER.md", "editable": True, "label": "Nutzer-Profil (Sergen)"},
    "config.yaml": {"path": ROOT / "config.yaml", "editable": True, "label": "Konfiguration (Vorsicht: YAML)"},
}


# ---------- REST ----------
@app.get("/health")
def health() -> dict:
    return {"status": "alive", "harness": CONFIG["identity"]["harness_name"]}


@app.get("/api/status")
def api_status() -> dict:
    m = models.status()
    return {
        "harness": CONFIG["identity"]["harness_name"],
        "partner": CONFIG["identity"].get("partner_name") or "Partner",
        "model": m["default"],
        "api_keys": m["api_keys"],
        "providers": m["providers"],
        "ollama_local": m["ollama_local"],
        "escalation_model": m["escalation_model"],
        "num_ctx": m.get("num_ctx"),
        "max_tokens": m.get("max_tokens"),
        "temperature": CONFIG["models"].get("temperature"),
        "keep_alive": CONFIG["models"].get("keep_alive"),
        "voice": CONFIG.get("channels", {}).get("telegram", {}).get("voice"),
        "whisper": CONFIG.get("channels", {}).get("telegram", {}).get("whisper_model"),
        "spend_usd_today": round(today_spend_usd(), 4),
        "budget": treasury.status(),
        "kill_switch": kill_switch_active(),
        "events": events.counts_by_type(),
        "lessons": memory.recall_lessons(8),
    }


@app.get("/api/overview")
def api_overview() -> dict:
    last_mission = None
    for e in events.recent(300):
        if e["type"] == "mission_task_done":
            last_mission = {"ts": e["ts"], "summary": str(e["payload"].get("summary", ""))}
            break
    return {
        "partner": CONFIG["identity"].get("partner_name") or "Partner",
        "model": models.status()["default"],
        "kill_switch": kill_switch_active(),
        "budget": treasury.status(),
        "mission": {"name": CONFIG.get("mission", {}).get("name"), "heartbeat": heartbeat_on()},
        "tools": [t.name for t in registry.all_tools()],
        "lessons": memory.recall_lessons(5),
        "last_mission": last_mission,
        "events_total": sum(events.counts_by_type().values()),
    }


@app.get("/api/governance")
def api_governance() -> dict:
    return {
        "treasury": treasury.status(),
        "audit": audit.recent(30),
    }


# S8.3: echte Autonomie-Schalter statt Vertrauensbarometer (trust.py ist deprecated —
# das Gating lief ohnehin schon ueber autonomy.needs_approval, die Stufe war Deko).
@app.get("/api/autonomy")
def api_autonomy() -> dict:
    from core.governance import autonomy

    d = autonomy._load()
    council = (CONFIG.get("governance", {}) or {}).get("council_gate", ["money"])
    return {"chains_off": bool(d.get("chains_off", True)),
            "hard_gate": list(d.get("hard_gate", [])),
            "council_gate": list(council) if isinstance(council, (list, tuple)) else ["money"],
            "kinds": ["money", "email_stranger", "publish", "external", "email"]}


@app.post("/api/autonomy")
async def api_autonomy_set(body: dict) -> dict:
    from core.governance import autonomy

    hard = body.get("hard_gate")
    if hard is not None and not isinstance(hard, list):
        return {"ok": False, "error": "hard_gate muss eine Liste sein"}
    d = autonomy.set_config(chains_off=body.get("chains_off"), hard_gate=hard)
    events.emit("autonomy_changed", {"chains_off": d.get("chains_off"),
                                     "hard_gate": d.get("hard_gate")})
    return {"ok": True, **d}


@app.get("/api/files")
def api_files() -> list[dict]:
    return [{"name": n, "label": f["label"], "editable": f["editable"]} for n, f in FILES.items()]


@app.get("/api/file")
def api_file(name: str) -> dict:
    f = FILES.get(name)
    if not f:
        return {"error": "unbekannte Datei"}
    p = f["path"]
    content = p.read_text(encoding="utf-8") if p.exists() else ""
    return {"name": name, "label": f["label"], "editable": f["editable"], "content": content}


@app.post("/api/file")
async def api_file_save(body: dict) -> dict:
    name = body.get("name", "")
    f = FILES.get(name)
    if not f or not f["editable"]:
        return {"ok": False, "error": "Datei ist nicht bearbeitbar."}
    p = f["path"]
    # Backup vor dem Ueberschreiben (Undo-Spur)
    hist = MIND_DIR / "history"
    hist.mkdir(parents=True, exist_ok=True)
    if p.exists():
        ts = time.strftime("%Y%m%d-%H%M%S")
        (hist / f"{name}.{ts}.bak").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(body.get("content", ""), encoding="utf-8")
    events.emit("file_edited", {"file": name, "via": "dashboard"})
    return {"ok": True}


@app.get("/api/events")
def api_events(limit: int = 60, before: float | None = None) -> list[dict]:
    evs = events.recent(limit, before=before)
    for e in evs:
        e["sev"] = events.severity(e["type"])
    return evs


@app.get("/api/memory")
def api_memory(limit: int = 80) -> list[dict]:
    return memory.recent(limit)


@app.get("/api/memory/history")
def api_memory_history(limit: int = 60) -> list[dict]:
    """Chronik der Gedaechtnis-Aenderungen (add/update/delete) — vorher/nachher
    nachvollziehbar, aus dem append-only Event-Log."""
    out: list[dict] = []
    for e in events.recent(500):
        if e["type"] in ("memory_add", "memory_update", "memory_delete"):
            p = e.get("payload") or {}
            out.append({"ts": e["ts"], "action": e["type"], "role": p.get("role"),
                        "kind": p.get("kind"), "old": p.get("old"), "new": p.get("new"),
                        "text": p.get("text"), "mem_id": p.get("mem_id")})
            if len(out) >= limit:
                break
    return out


@app.post("/api/memory/delete")
async def api_memory_delete(body: dict) -> dict:
    memory.delete(body.get("id", ""))
    events.emit("memory_deleted", {"id": body.get("id", ""), "via": "dashboard"})
    return {"ok": True}


@app.get("/api/secrets")
def api_secrets() -> dict:
    from core.kernel.llm_router import _PROVIDER_KEYS

    return {
        "set": secrets.names_status(),
        "pending": secrets.pending(),
        "suggested": list(_PROVIDER_KEYS.values()) + ["TELEGRAM_BOT_TOKEN", "BRAVE_API_KEY"],
    }


@app.post("/api/secrets/set")
async def api_secrets_set(body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "Name fehlt"}
    secrets.set_secret(name, body.get("value", ""))
    return {"ok": True}


@app.post("/api/model/use")
async def api_model_use(body: dict) -> dict:
    return {"ok": True, "active": models.set_model(body.get("id", ""))}


@app.post("/api/model/openrouter")
async def api_model_openrouter(body: dict) -> dict:
    return {"ok": True, "active": models.add_openrouter(body.get("model", ""))}


@app.get("/api/model/catalog")
def api_model_catalog() -> dict:
    return {"catalog": models.catalog(), "roles": models.roles()}


@app.post("/api/model/role")
async def api_model_role(body: dict) -> dict:
    role = (body.get("role") or "").strip()
    model = (body.get("model") or "").strip()
    if not role or not model:
        return {"ok": False, "error": "role + model noetig"}
    m = models.set_role(role, model)
    events.emit("model_role_set", {"role": role, "model": m, "via": "dashboard"})
    return {"ok": True, "role": role, "model": m}


@app.get("/api/model/loaded")
def api_model_loaded() -> dict:
    return models.loaded()


@app.post("/api/model/params")
async def api_model_params(body: dict) -> dict:
    p = models.set_params(num_ctx=body.get("num_ctx"), max_tokens=body.get("max_tokens"))
    # Warmup: Ollama laedt mit neuem Kontext neu -> GPU-Fit sofort sichtbar
    try:
        from core.kernel import llm_router

        await anyio.to_thread.run_sync(
            lambda: llm_router.complete([{"role": "user", "content": "ok"}], task_type="chat")
        )
    except Exception:
        pass
    return {"ok": True, **p, "loaded": models.loaded()}


@app.get("/api/mission")
def api_mission() -> dict:
    from core.agency.missions import queue as mqueue

    mqueue.init_queue()
    m = CONFIG.get("mission", {})
    recent = []
    for e in events.recent(250):
        if e["type"] == "mission_task_done":
            recent.append({"ts": e["ts"], "summary": str(e["payload"].get("summary", ""))})
            if len(recent) >= 8:
                break
    return {
        "enabled": heartbeat_on(),
        "notify": bool(m.get("notify_telegram")),
        "interval": CONFIG.get("heartbeat", {}).get("interval_seconds", 1800),
        "mission": m.get("name"),
        "goal": m.get("goal", ""),
        "pending": mqueue.pending(m.get("name", "default")),
        "recent": recent,
    }


@app.post("/api/mission/toggle")
async def api_mission_toggle(body: dict) -> dict:
    set_heartbeat(bool(body.get("on")))
    events.emit("heartbeat_toggle", {"on": heartbeat_on(), "via": "dashboard"})
    return {"ok": True, "enabled": heartbeat_on()}


@app.post("/api/mission/runonce")
async def api_mission_runonce(body: dict) -> dict:
    from core.agency.missions import runner

    out = await anyio.to_thread.run_sync(runner.run_once)
    return {"ok": True, "result": out}


@app.get("/api/monitor")
def api_monitor() -> dict:
    from core.agency.connectors import news_monitor

    recent = []
    for e in events.recent(250):
        if e["type"] == "monitor_new":
            recent.append({
                "ts": e["ts"], "label": e["payload"].get("label"),
                "count": e["payload"].get("count"), "summary": e["payload"].get("summary", ""),
            })
            if len(recent) >= 8:
                break
    return {"watches": news_monitor.list_watches(), "recent": recent}


@app.post("/api/monitor/add")
async def api_monitor_add(body: dict) -> dict:
    from core.agency.connectors import news_monitor

    return {"ok": True, "watch": news_monitor.add_watch(body.get("kind", "search"), body.get("value", ""), body.get("label", ""))}


@app.post("/api/monitor/remove")
async def api_monitor_remove(body: dict) -> dict:
    from core.agency.connectors import news_monitor

    return {"ok": news_monitor.remove_watch(body.get("id", ""))}


@app.post("/api/monitor/check")
async def api_monitor_check(body: dict) -> dict:
    from core.agency.connectors import news_monitor

    out = await anyio.to_thread.run_sync(lambda: news_monitor.run_all(force=True, notify=True))
    return {"ok": True, **out}


@app.get("/api/cron")
def api_cron() -> dict:
    from core.agency.missions import cron

    return {"jobs": cron.list_jobs()}


@app.post("/api/cron/add")
async def api_cron_add(body: dict) -> dict:
    from core.agency.missions import cron

    return {"ok": True, "job": cron.add_job(
        body.get("label", ""), body.get("prompt", ""), body.get("schedule", "60m"),
        scope=body.get("scope", "system"), enabled=bool(body.get("enabled", True)))}


@app.post("/api/cron/remove")
async def api_cron_remove(body: dict) -> dict:
    from core.agency.missions import cron

    return {"ok": cron.remove_job(body.get("id", ""))}


@app.post("/api/cron/toggle")
async def api_cron_toggle(body: dict) -> dict:
    from core.agency.missions import cron

    return {"ok": True, "enabled": cron.toggle_job(body.get("id", ""))}


@app.post("/api/cron/runnow")
async def api_cron_runnow(body: dict) -> dict:
    from core.agency.missions import cron

    out = await anyio.to_thread.run_sync(lambda: cron.run_now(body.get("id", "")))
    return {"ok": True, "result": out}


@app.post("/api/cron/update")
async def api_cron_update(body: dict) -> dict:
    from core.agency.missions import cron

    ok = cron.update_job(body.get("id", ""), body.get("label"), body.get("prompt"), body.get("schedule"))
    return {"ok": ok}


@app.get("/api/services")
def api_services() -> dict:
    import json as _json
    import socket as _sock

    try:
        d = _json.loads((ROOT / "data" / "services.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {"ts": 0, "services": {}}
    fresh = (time.time() - float(d.get("ts", 0))) < 20  # Supervisor-Herzschlag frisch?

    def _up(port: int) -> bool:
        with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as so:
            so.settimeout(0.6)
            return so.connect_ex(("127.0.0.1", port)) == 0

    return {"supervisor": fresh, "services": d.get("services", {}), "ollama": _up(11434), "heartbeat": heartbeat_on()}


@app.post("/api/restart")
async def api_restart(body: dict) -> dict:
    which = (body.get("which") or "all").strip().lower() or "all"
    flag = ROOT / "data" / "restart.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(which, encoding="utf-8")
    events.emit("restart_requested", {"which": which, "via": "dashboard"})
    return {"ok": True, "which": which}


# ---------- Steuerung: Direktive, Config, Mission-Ziel, Queue, Gedaechtnis ----------
_CONFIG_WHITELIST = {
    "models.temperature", "models.max_tokens", "models.num_ctx", "models.keep_alive", "models.request_timeout",
    "governance.budget.daily_eur", "governance.budget.monthly_eur", "governance.trust_level",
    "mission.goal", "mission.notify_telegram", "heartbeat.interval_seconds",
    "channels.telegram.voice", "channels.telegram.whisper_model",
}
_MODEL_LIVE = {"models.temperature": "temperature", "models.max_tokens": "max_tokens",
               "models.num_ctx": "num_ctx", "models.keep_alive": "keep_alive"}  # live, kein Neustart


@app.post("/api/config/set")
async def api_config_set(body: dict) -> dict:
    from core.config import set_override

    path = (body.get("path") or "").strip()
    if path not in _CONFIG_WHITELIST:
        return {"ok": False, "error": "Schluessel nicht erlaubt"}
    value = body.get("value")
    live = path in _MODEL_LIVE
    if live:
        models.set_params(**{_MODEL_LIVE[path]: value})
    else:
        set_override(path, value)
    events.emit("config_set", {"path": path, "live": live, "via": "dashboard"})
    return {"ok": True, "path": path, "value": value, "live": live}


def _focus_path():
    return ROOT / "data" / "focus.json"


@app.get("/api/direktive")
def api_direktive() -> dict:
    import json as _j

    try:
        d = _j.loads(_focus_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    return {"focus": d.get("focus", ""), "ts": d.get("ts", 0)}


@app.post("/api/direktive")
async def api_direktive_set(body: dict) -> dict:
    import json as _j

    from core.agency.missions import queue as mqueue

    focus = (body.get("focus") or "").strip()
    _focus_path().write_text(_j.dumps({"focus": focus, "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
    try:  # offene Queue leeren -> naechster Tick plant um den neuen Fokus herum
        mqueue.init_queue()
        mqueue.clear(CONFIG.get("mission", {}).get("name", "default"))
    except Exception:  # noqa: BLE001
        pass
    events.emit("focus_set", {"focus": focus[:200], "via": "dashboard"})
    return {"ok": True, "focus": focus}


@app.post("/api/direktive/now")
async def api_direktive_now(body: dict) -> dict:
    from core.agency.act import act

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "leer"}
    events.emit("direktive_now", {"prompt": prompt[:200], "via": "dashboard"})
    from core.kernel import runstate
    runstate.enter_turn()  # aktiver Cockpit-Zug -> Neustart wartet bis danach
    try:
        out = await anyio.to_thread.run_sync(lambda: act(prompt, session_id="direktive", escalate=bool(body.get("escalate"))))
    finally:
        runstate.exit_turn()
    text = (out.get("text") or "").strip()
    try:
        import os as _os

        import httpx as _hx

        tok = _os.getenv("TELEGRAM_BOT_TOKEN")
        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        if tok and chat:
            _hx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                     json={"chat_id": chat, "text": ("🎯 Direktive erledigt:\n" + text)[:4000]}, timeout=15)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "result": text}


@app.post("/api/mission/config")
async def api_mission_config(body: dict) -> dict:
    from core.config import set_override

    if body.get("goal") is not None:
        set_override("mission.goal", str(body.get("goal")))
    if body.get("interval") is not None:
        try:
            set_override("heartbeat.interval_seconds", int(body.get("interval")))
        except Exception:  # noqa: BLE001
            pass
    if body.get("notify") is not None:
        set_override("mission.notify_telegram", bool(body.get("notify")))
    events.emit("mission_config", {"via": "dashboard"})
    (ROOT / "data" / "restart.flag").write_text("runner", encoding="utf-8")  # Ziel greift nach Runner-Bounce
    return {"ok": True}


@app.post("/api/mission/queue/add")
async def api_queue_add(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    desc = (body.get("description") or "").strip()
    if not desc:
        return {"ok": False, "error": "leer"}
    mqueue.init_queue()
    tid = mqueue.add(desc, mission=CONFIG.get("mission", {}).get("name", "default"),
                     priority=int(body.get("priority", 3)),
                     objective_id=body.get("objective_id") or None,
                     due_date=(body.get("due_date") or None),
                     kind=body.get("kind", "research"))
    return {"ok": True, "id": tid}


@app.post("/api/mission/queue/remove")
async def api_queue_remove(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    return {"ok": mqueue.remove(body.get("id", ""))}


@app.post("/api/mission/queue/clear")
async def api_queue_clear(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    mqueue.init_queue()
    return {"ok": True, "cleared": mqueue.clear(CONFIG.get("mission", {}).get("name", "default"))}


# ---------- Workspace: Ziele/Projekte + To-Do-Board (Phase 1) ----------
def _mission_name() -> str:
    return CONFIG.get("mission", {}).get("name", "default")


@app.get("/api/mission/board")
def api_mission_board() -> dict:
    from core.agency.missions import objectives, queue as mqueue

    objectives.init_objectives()
    mqueue.init_queue()
    return {"objectives": objectives.list_all(), "board": mqueue.board(_mission_name())}


@app.post("/api/mission/task/update")
async def api_task_update(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    tid = body.get("id", "")
    fields = {k: body[k] for k in ("priority", "status", "objective_id", "due_date",
                                   "deferred_until", "kind", "description") if k in body}
    if "priority" in fields:
        try:
            fields["priority"] = int(fields["priority"])
        except Exception:  # noqa: BLE001
            fields.pop("priority")
    return {"ok": mqueue.update_task(tid, **fields)}


@app.get("/api/objectives")
def api_objectives() -> list[dict]:
    from core.agency.missions import objectives

    objectives.init_objectives()
    return objectives.list_all()


@app.post("/api/objectives")
async def api_objectives_add(body: dict) -> dict:
    from core.agency.missions import objectives

    title = (body.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "leer"}
    objectives.init_objectives()
    oid = objectives.add(title, kind=body.get("kind", "weekly"),
                         parent_id=body.get("parent_id") or None,
                         target_date=body.get("target_date") or None,
                         notes=body.get("notes") or None,
                         domain=body.get("domain") or "business")
    events.emit("objective_add", {"id": oid, "title": title, "kind": body.get("kind", "weekly"), "via": "dashboard"})
    return {"ok": True, "id": oid}


@app.post("/api/objectives/update")
async def api_objectives_update(body: dict) -> dict:
    from core.agency.missions import objectives

    oid = body.get("id", "")
    fields = {k: body[k] for k in ("title", "kind", "status", "progress", "target_date",
                                   "notes", "parent_id", "domain", "venture_id") if k in body}
    if "progress" in fields and fields["progress"] is not None:
        try:
            fields["progress"] = max(0, min(100, int(fields["progress"])))
        except Exception:  # noqa: BLE001
            fields.pop("progress")
    return {"ok": objectives.update(oid, **fields)}


@app.post("/api/objectives/delete")
async def api_objectives_delete(body: dict) -> dict:
    from core.agency.missions import objectives

    return {"ok": objectives.delete(body.get("id", ""))}


@app.post("/api/objectives/plan")
async def api_objectives_plan(body: dict) -> dict:
    """Ein Ziel per Planner in konkrete To-Dos zerlegen (LLM) und der Queue hinzufuegen."""
    from core.agency.missions import objectives, planner, queue as mqueue

    oid = body.get("id", "")
    objectives.init_objectives()
    mqueue.init_queue()
    obj = next((o for o in objectives.list_all() if o["id"] == oid), None)
    if not obj:
        return {"ok": False, "error": "Ziel nicht gefunden"}
    goal = obj["title"] + (("\n" + obj["notes"]) if obj.get("notes") else "")
    existing = [t["description"] for t in mqueue.all_tasks(_mission_name()) if t.get("objective_id") == oid]
    context = "Bereits geplant:\n" + "\n".join(existing) if existing else "(noch nichts geplant)"
    tasks = await anyio.to_thread.run_sync(lambda: planner.generate_tasks(goal, context, n=int(body.get("n", 3))))
    for t in tasks:
        mqueue.add(t, mission=_mission_name(), priority=int(body.get("priority", 3)), objective_id=oid)
    events.emit("objective_planned", {"id": oid, "tasks": tasks})
    return {"ok": True, "tasks": tasks}


# ---------- Lebens-Ebene: Todos, Ziele, Metriken (S5) ----------
@app.get("/api/life/board")
def api_life_board() -> dict:
    from core.agency.missions import objectives, queue as mqueue

    objectives.init_objectives()
    mqueue.init_queue()
    return {"objectives": objectives.list_active(domain="leben"),
            "board": mqueue.board("leben")}


@app.post("/api/life/add")
async def api_life_add(body: dict) -> dict:
    """S9.4: Todo/Auftrag direkt im Me-Bereich anlegen (mission='leben' = dein Leben-Board)."""
    from core.agency.missions import queue as mqueue

    desc = str(body.get("description", "")).strip()
    if not desc:
        return {"ok": False, "error": "leer"}
    mqueue.init_queue()
    tid = mqueue.add(desc, mission="leben", priority=int(body.get("priority", 3)),
                     due_date=body.get("due_date") or None)
    events.emit("life_todo_added", {"id": tid, "via": "cockpit"})
    return {"ok": True, "id": tid}


@app.get("/api/metrics")
def api_metrics(name: str = "", days: int = 90) -> dict:
    from core.agency.missions import metrics

    if name.strip():
        return {"name": name.strip().lower(), "series": metrics.series(name, days=days)}
    return {"latest": metrics.latest(), "names": metrics.names()}


@app.post("/api/metrics/log")
async def api_metrics_log(body: dict) -> dict:
    from core.agency.missions import metrics

    name = (body.get("name") or "").strip()
    try:
        value = float(str(body.get("value")).replace(",", "."))
    except (TypeError, ValueError):
        return {"ok": False, "error": "value braucht eine Zahl"}
    if not name:
        return {"ok": False, "error": "name fehlt"}
    metrics.log(name, value, note=body.get("note") or None)
    return {"ok": True}


# ---------- Ventures: Standbeine mit eigenem Konto-Buch (S3) ----------
@app.get("/api/ventures")
def api_ventures() -> dict:
    from core.agency import ventures

    return {"ventures": ventures.summary()}


@app.post("/api/ventures")
async def api_ventures_add(body: dict) -> dict:
    from core.agency import ventures

    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "leer"}
    ms = body.get("milestone_eur")
    try:
        ms = float(ms) if ms not in (None, "") else None
    except (TypeError, ValueError):
        ms = None
    vid = ventures.add(name, hypothesis=body.get("hypothesis") or "",
                       milestone_eur=ms, notes=body.get("notes") or None)
    return {"ok": True, "id": vid}


@app.post("/api/ventures/update")
async def api_ventures_update(body: dict) -> dict:
    from core.agency import ventures

    vid = body.get("id", "")
    fields = {k: body[k] for k in ("name", "status", "hypothesis", "milestone_eur", "notes") if k in body}
    return {"ok": ventures.update(vid, **fields)}


@app.get("/api/ventures/ledger")
def api_ventures_ledger(id: str) -> dict:
    from core.agency import ventures

    return {"ledger": ventures.ledger(id), "balance": ventures.balance(id)}


@app.post("/api/ventures/book")
async def api_ventures_book(body: dict) -> dict:
    """Buchung via Dashboard — gleiche Regel wie das ledger_book-Werkzeug:
    Ausgaben ueber record_spend (Budget + Ledger), Einnahmen direkt."""
    from core.agency import ventures
    from core.governance import treasury

    vid = body.get("id", "")
    direction = body.get("direction", "")
    try:
        amount = float(body.get("amount_eur", 0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "amount_eur braucht eine Zahl"}
    if amount <= 0 or direction not in ("in", "out") or not ventures.get(vid):
        return {"ok": False, "error": "id/direction/amount pruefen"}
    note = body.get("note") or ""
    if direction == "out":
        ok, why = treasury.can_spend(amount)
        if not ok:
            return {"ok": False, "error": why}
        treasury.record_spend(amount, note or "Ausgabe via Dashboard", category="venture", venture_id=vid)
    else:
        ventures.book(vid, "in", amount, category="venture", note=note)
    return {"ok": True, "balance": ventures.balance(vid)}


# ---------- Business-Radar (S5.5) ----------
@app.get("/api/opportunities")
def api_opportunities(status: str = "") -> dict:
    from core.agency import radar

    return {"opportunities": radar.list_all(status)}


@app.post("/api/opportunities/decide")
async def api_opportunities_decide(body: dict) -> dict:
    from core.agency import radar

    return {"ok": radar.decide(body.get("id", ""), body.get("status", ""),
                               note=body.get("note", ""))}


@app.post("/api/opportunities/convert")
async def api_opportunities_convert(body: dict) -> dict:
    from core.agency import radar

    return await anyio.to_thread.run_sync(lambda: radar.convert(body.get("id", "")))


@app.post("/api/radar/scan")
async def api_radar_scan() -> dict:
    from core.agency import radar

    return await anyio.to_thread.run_sync(lambda: radar.scan(notify=False))


# ---------- Wissens-Archiv (S5.4) ----------
@app.get("/api/knowledge")
def api_knowledge() -> dict:
    from core.mind import knowledge

    return {"docs": knowledge.list_docs()}


@app.get("/api/knowledge/search")
def api_knowledge_search(q: str, k: int = 5) -> dict:
    from core.mind import knowledge

    return {"hits": knowledge.search(q, k=max(1, min(10, k)))}


@app.post("/api/knowledge/add")
async def api_knowledge_add(body: dict) -> dict:
    from core.mind import knowledge

    return await anyio.to_thread.run_sync(
        lambda: knowledge.ingest_text((body.get("title") or "Notiz").strip(),
                                      body.get("text") or "", source="paste",
                                      tags=body.get("tags") or ""))


@app.post("/api/knowledge/upload")
async def api_knowledge_upload(file: UploadFile = File(...), tags: str = Form("")) -> dict:
    from core.mind import knowledge

    data = await file.read()
    fname = file.filename or "upload.txt"
    return await anyio.to_thread.run_sync(
        lambda: knowledge.ingest_file(data, fname, source="upload", tags=tags))


@app.post("/api/knowledge/delete")
async def api_knowledge_delete(body: dict) -> dict:
    from core.mind import knowledge

    return {"ok": knowledge.delete(body.get("id", ""))}


# ---------- Agenten-Sicht + Projekt-Spuren (S5.3b, rein lesend) ----------
_ORGANS = {
    "Planner": ("mission_planned", "objective_planned", "plan_made"),
    "Actor": ("mission_task_start", "act_start", "tool_call"),
    "Pruefer": ("task_scored", "task_criteria"),
    "Council": ("council_verdict", "council_argument", "council_opening"),
    "Curator": ("skills_curated", "lessons_curated"),
    "Reflexion": ("reflection",),
    "Radar/Monitor": ("monitor_new", "opportunity_found"),
    "Trigger": ("trigger_fired",),
    "Selbst-Check": ("doctor_report",),
}


@app.get("/api/agents")
def api_agents() -> dict:
    """Rollen-Sicht: welches Organ zuletzt gearbeitet hat + Dienste + MCP (S5)."""
    last: dict[str, dict] = {}
    for e in events.recent(500):
        for organ, types in _ORGANS.items():
            if organ not in last and e["type"] in types:
                last[organ] = {"ts": e["ts"], "event": e["type"],
                               "detail": str(e.get("payload") or {})[:140]}
    mcp: dict = {}
    try:
        from core.agency.mcp import registry_bridge

        mcp = registry_bridge.server_status()
    except Exception:  # noqa: BLE001
        pass
    skills_total = 0
    try:
        skills_total = len(memory.all_skills())
    except Exception:  # noqa: BLE001
        pass
    doctor_report = None
    for e in events.recent(500):
        if e["type"] == "doctor_report":
            doctor_report = {"ts": e["ts"], **(e.get("payload") or {})}
            break
    return {
        "organs": [{"name": o, **(last.get(o) or {})} for o in _ORGANS],
        "mcp": mcp,
        "tools_total": len(registry.all_tools()),
        "skills_total": skills_total,
        "doctor": doctor_report,
    }


@app.get("/api/venture/trace")
def api_venture_trace(id: str) -> dict:
    """Projekt-Drilldown: Ziel-Baum + Tasks (mit Scores) + Arbeitsstand je Ziel."""
    from core.agency import ventures
    from core.agency.missions import objectives, queue as mqueue, workingset

    v = ventures.get(id)
    if not v:
        return {"error": "unbekanntes Venture"}
    objs = [o for o in objectives.list_all() if o.get("venture_id") == id]
    all_t = mqueue.all_tasks(None, limit=500)
    out_objs = []
    for o in objs:
        tasks = [t for t in all_t if t.get("objective_id") == o["id"]]
        out_objs.append({**o, "tasks": tasks[:20],
                         "workingset": workingset.render(o["id"], max_chars=1000)})
    return {"venture": v, "balance": ventures.balance(id),
            "ledger": ventures.ledger(id, limit=15), "objectives": out_objs,
            # S8.2: Projekt-Akte — Briefing, Kosten bislang, Dateien
            "briefing": ventures.briefing(id, max_chars=4000),
            "costs": ventures.costs(id),
            "files": ventures.list_files(id)}


@app.post("/api/ventures/briefing")
async def api_venture_briefing(body: dict) -> dict:
    """S8.2: Briefing (Sergens Daueranweisungen) komplett setzen ODER Notiz anhaengen."""
    from core.agency import ventures

    vid = str(body.get("id", "")).strip()
    if not ventures.get(vid):
        return {"ok": False, "error": "unbekanntes Venture"}
    if body.get("note"):
        ventures.append_briefing(vid, str(body["note"]))
    else:
        ventures.set_briefing(vid, str(body.get("text", "")))
    return {"ok": True, "briefing": ventures.briefing(vid, max_chars=4000)}


@app.post("/api/ventures/upload")
async def api_venture_upload(id: str = Form(...), file: UploadFile = File(...)) -> dict:
    """S8.2: Datei in die Projekt-Akte legen (Bilder/Anhaenge fuer spaetere Mails etc.)."""
    from core.agency import ventures

    if not ventures.get(id):
        return {"ok": False, "error": "unbekanntes Venture"}
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        return {"ok": False, "error": "Datei zu gross (max 15 MB)"}
    import re as _re

    safe = _re.sub(r"[^A-Za-z0-9._ -]", "_", file.filename or "datei")[:120] or "datei"
    dest = ventures.files_dir(id) / safe
    dest.write_bytes(raw)
    events.emit("venture_file_added", {"venture_id": id, "name": safe, "bytes": len(raw)})
    return {"ok": True, "files": ventures.list_files(id)}


# ---------- Freigabe-Inbox + Tages-Digest (Phase 2) ----------
def _pending_proposals() -> list[dict]:
    """Offene Selbstaenderungs-Vorschlaege (alle MUTABLE-Docs) als Inbox-Eintraege (kind=evolution)."""
    from core.mind import evolution

    out = []
    pdir = ROOT / "data" / "proposals"
    try:
        for doc in sorted(evolution.MUTABLE):
            p = pdir / doc
            if p.exists():
                out.append({"id": "prop:" + doc, "ts": p.stat().st_mtime, "kind": "evolution",
                            "title": f"Selbst-Aenderung: {doc}", "detail": p.read_text(encoding="utf-8")[:4000],
                            "ref": doc, "source": "kira", "status": "pending"})
    except Exception:  # noqa: BLE001
        pass
    return out


@app.get("/api/approvals")
def api_approvals() -> dict:
    from core.agency import approvals

    approvals.init_approvals()
    pend = approvals.pending() + _pending_proposals()
    pend.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return {"pending": pend, "recent": approvals.recent(20)}


@app.post("/api/approvals/decide")
async def api_approvals_decide(body: dict) -> dict:
    from core.agency import approvals

    aid = body.get("id", "")
    approved = bool(body.get("approved"))
    note = body.get("note")
    if aid.startswith("prop:"):  # Selbstaenderungs-Vorschlag (MUTABLE-Doc)
        doc = aid[5:]
        pfile = ROOT / "data" / "proposals" / doc
        if not pfile.exists():  # bereits entschieden (Doppelklick) oder nie da
            return JSONResponse({"ok": False, "error": "kein offener Vorschlag (bereits entschieden?)"},
                                status_code=409)
        if approved:
            try:
                from core.mind import evolution
                # apply_update konsumiert den Vorschlag -> zweiter Klick landet oben im 409
                res = await anyio.to_thread.run_sync(lambda: evolution.apply_update(doc, "Freigabe via Inbox"))
                return {"ok": True, "status": "approved", "applied": res}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)}
        else:
            try:
                pfile.unlink()
            except OSError:
                pass
            events.emit("approval_decided", {"id": aid, "status": "rejected", "kind": "evolution"})
            return {"ok": True, "status": "rejected"}
    res = approvals.decide(aid, approved, note)
    if not res.get("ok") and res.get("error") == "already decided":
        return JSONResponse(res, status_code=409)
    return res


@app.get("/api/digest")
def api_digest() -> dict:
    """Tages-Digest: was Kira heute getan/produziert hat + offene Freigaben."""
    import datetime as _dt
    from core.agency import approvals

    start = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    done, planned, artifacts = [], 0, []
    errs = 0
    for e in events.recent(600):
        if e["ts"] < start:
            continue
        t, p = e["type"], (e.get("payload") or {})
        if t == "mission_task_done":
            done.append(str(p.get("summary", ""))[:160])
        elif t == "objective_planned":
            planned += len(p.get("tasks", []) or [])
        elif t in ("file_edited",):
            artifacts.append(str(p.get("file", "")))
        elif t in ("turn_timeout", "llm_call_timeout", "service_crash", "act_degraded"):
            errs += 1
    approvals.init_approvals()
    news = 0
    try:
        from core.agency.connectors import news_monitor
        news = len(news_monitor.recent_reports() or []) if hasattr(news_monitor, "recent_reports") else 0
    except Exception:  # noqa: BLE001
        news = 0
    return {
        "date": _dt.date.today().isoformat(),
        "tasks_done": done[:10], "tasks_done_count": len(done),
        "planned": planned, "artifacts": artifacts[:10],
        "pending_approvals": len(approvals.pending()) + len(_pending_proposals()),
        "errors": errs, "news": news,
        "spend_usd": round(today_spend_usd(), 4), "budget": treasury.status(),
    }


@app.get("/api/costs")
def api_costs() -> dict:
    """Kosten-Aufschluesselung aus den llm_call-Events: heute + 7 Tage, pro Modell + Top-Sessions."""
    import datetime as _dt
    from collections import defaultdict

    start_today = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    start_7d = time.time() - 7 * 86400
    m_today: dict = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    m_7d: dict = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    sess: dict = defaultdict(float)
    tot_today = tot_7d = 0.0
    for e in events.recent(4000):
        if e["type"] != "llm_call":
            continue
        p = e.get("payload") or {}
        cost = float(p.get("cost_usd") or 0.0)
        model = p.get("model", "?")
        if e["ts"] >= start_7d:
            m_7d[model]["calls"] += 1; m_7d[model]["cost"] += cost; tot_7d += cost
        if e["ts"] >= start_today:
            m_today[model]["calls"] += 1; m_today[model]["cost"] += cost; tot_today += cost
            sess[e.get("session_id") or "?"] += cost

    def _fmt(d):
        return sorted([{"model": m, "calls": v["calls"], "cost": round(v["cost"], 4)} for m, v in d.items()],
                      key=lambda x: -x["cost"])
    top = sorted([{"session": s, "cost": round(c, 4)} for s, c in sess.items() if c > 0], key=lambda x: -x["cost"])[:6]
    return {"today": {"total": round(tot_today, 4), "by_model": _fmt(m_today), "top_sessions": top},
            "week": {"total": round(tot_7d, 4), "by_model": _fmt(m_7d)},
            "budget": treasury.status()}


@app.get("/api/insights")
def api_insights(days: int = 14) -> dict:
    """Lern-Statistik (S6.6c): Outcome-Muster aus insights.py, rein lesend fuers Cockpit."""
    from core.agency import insights, outcomes

    days = max(1, min(int(days or 14), 90))
    return {
        "days": days,
        "stats": outcomes.stats(days),
        "patterns": insights.fail_patterns(days),
        "strategies": insights.strategy_stats(days),
        "brief": insights.render_brief(days),
    }


@app.get("/api/desktop")
def api_desktop() -> dict:
    """S8.5: Desktop-Pflege-Config + Vorschau des naechsten Scans (read-only)."""
    from core.agency import desktop_watch

    cfg = desktop_watch.load_cfg()
    preview = desktop_watch.scan(cfg) if cfg.get("enabled") else {"scanned": 0, "suggestions": []}
    return {"config": cfg, "preview": preview}


@app.post("/api/desktop/config")
async def api_desktop_config(body: dict) -> dict:
    from core.agency import desktop_watch

    cfg = desktop_watch.load_cfg()
    if "enabled" in body:
        cfg["enabled"] = bool(body["enabled"])
    if isinstance(body.get("folders"), list):
        cfg["folders"] = [str(f) for f in body["folders"] if str(f).strip()]
    desktop_watch.save_cfg(cfg)
    return {"ok": True, "config": cfg}


@app.post("/api/desktop/scan")
async def api_desktop_scan(body: dict) -> dict:
    """Sofort einen Sortiervorschlag erzeugen (landet in der Freigabe-Inbox)."""
    from core.agency import desktop_watch

    return await anyio.to_thread.run_sync(desktop_watch.propose)


@app.get("/api/evolution")
def api_evolution(limit: int = 40) -> dict:
    """S8.1: 'Was ich zuletzt an mir verbessert habe' — Timeline aus dem Event-Log
    (self_edit/selfdev/self_tick/learn_skill/self_update/insights) + Skills + Lektionen."""
    _KINDS = {
        "self_tick": "🔧 Selbst-Optimierung", "selfdev_applied": "✅ Code geaendert",
        "selfdev_rejected": "↩ Aenderung verworfen (Test rot)", "selfdev_verify_failed": "↩ Verify fehlgeschlagen",
        "self_update_proposed": "🧬 Selbst-Update vorgeschlagen", "self_update_applied": "🧬 Selbst-Update angewendet",
        "insights_weekly": "💡 Wochen-Lektionen gezogen", "insights_lessons": "💡 Lektionen gezogen",
        "write_blocked": "🛡 Schreibschutz griff", "evolution_blocked": "🛡 Evolution blockiert",
    }
    timeline = []
    for e in events.recent(600):
        lbl = _KINDS.get(e["type"])
        if not lbl:
            continue
        p = e.get("payload") or {}
        detail = p.get("summary") or p.get("file") or p.get("doc") or p.get("name") or ""
        timeline.append({"ts": e["ts"], "type": e["type"], "label": lbl, "detail": str(detail)[:200]})
        if len(timeline) >= limit:
            break
    skills = memory.all_skills()[:20] if hasattr(memory, "all_skills") else []
    return {"timeline": timeline, "skills": skills, "lessons": memory.recall_lessons(8)}


_NEWS_CACHE: dict = {"ts": 0.0, "data": None}
_NEWS_FEEDS = [
    ("HN", "https://hnrss.org/frontpage"),
    ("HN·AI", "https://hnrss.org/newest?q=AI+OR+LLM+OR+agent"),
]


@app.get("/api/news")
def api_news() -> dict:
    """KI/Tech-News aus Default-RSS-Feeds (serverseitig, 15-min-Cache) — laeuft
    unabhaengig vom manuellen Monitor, damit der Ticker sofort lebt."""
    import time as _t
    import xml.etree.ElementTree as ET

    import httpx as _hx

    if _NEWS_CACHE["data"] and (_t.time() - _NEWS_CACHE["ts"]) < 900:
        return _NEWS_CACHE["data"]
    items: list[dict] = []
    for label, url in _NEWS_FEEDS:
        try:
            r = _hx.get(url, timeout=8, headers={"User-Agent": "KiraCockpit/1.0"})
            root = ET.fromstring(r.text)
            cnt = 0
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                if title:
                    items.append({"source": label, "title": title[:160], "link": link})
                    cnt += 1
                if cnt >= 7:
                    break
        except Exception:  # noqa: BLE001
            continue
    out = {"items": items[:16], "ts": _t.time()}
    _NEWS_CACHE.update(ts=_t.time(), data=out)
    return out


@app.post("/api/memory/update")
async def api_memory_update(body: dict) -> dict:
    ok = memory.update_text(body.get("id", ""), body.get("text", ""))
    events.emit("memory_updated", {"id": body.get("id", ""), "via": "dashboard"})
    return {"ok": ok}


@app.post("/api/memory/add")
async def api_memory_add(body: dict) -> dict:
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "leer"}
    mid = memory.remember(text, role=body.get("role", "user"), kind=body.get("kind", "semantic"))
    events.emit("memory_added", {"id": mid, "via": "dashboard"})
    return {"ok": True, "id": mid}


@app.post("/api/kill")
async def api_kill(body: dict) -> dict:
    if body.get("on"):
        kill_switch_path().write_text("stop", encoding="utf-8")
        events.emit("kill_switch_set", {"via": "dashboard"})
    else:
        p = kill_switch_path()
        if p.exists():
            p.unlink()
        events.emit("kill_switch_clear", {"via": "dashboard"})
    return {"ok": True, "kill_switch": kill_switch_active()}


@app.get("/api/bg")
def api_bg():
    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"background.{ext}"
        if p.exists():
            return FileResponse(str(p))
    return Response(status_code=404)


@app.post("/api/bg/upload")
async def api_bg_upload(body: dict) -> dict:
    import base64
    import re

    m = re.match(r"data:image/(\w+);base64,(.+)$", body.get("dataurl", ""), re.DOTALL)
    if not m:
        return {"ok": False, "error": "kein gueltiges Bild"}
    ext = m.group(1).lower().replace("jpeg", "jpg")
    raw = base64.b64decode(m.group(2))
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        old = data_dir / f"background.{e}"
        if old.exists():
            old.unlink()
    (data_dir / f"background.{ext}").write_bytes(raw)
    events.emit("background_set", {"ext": ext, "bytes": len(raw)})
    return {"ok": True, "ext": ext, "bytes": len(raw)}


@app.post("/api/bg/clear")
async def api_bg_clear(body: dict) -> dict:
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"background.{e}"
        if p.exists():
            p.unlink()
    return {"ok": True}


# ---------- Kira-Avatar (S6.6d) — Sergens Higgsfield-Bild fuer Hero + Chat ----------
@app.get("/api/avatar")
def api_avatar():
    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"avatar.{ext}"
        if p.exists():
            return FileResponse(str(p))
    return Response(status_code=404)


@app.post("/api/avatar/upload")
async def api_avatar_upload(body: dict) -> dict:
    import base64
    import re

    m = re.match(r"data:image/(\w+);base64,(.+)$", body.get("dataurl", ""), re.DOTALL)
    if not m:
        return {"ok": False, "error": "kein gueltiges Bild"}
    ext = m.group(1).lower().replace("jpeg", "jpg")
    raw = base64.b64decode(m.group(2))
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        old = data_dir / f"avatar.{e}"
        if old.exists():
            old.unlink()
    (data_dir / f"avatar.{ext}").write_bytes(raw)
    events.emit("avatar_set", {"ext": ext, "bytes": len(raw)})
    return {"ok": True, "ext": ext, "bytes": len(raw)}


@app.post("/api/avatar/clear")
async def api_avatar_clear(body: dict) -> dict:
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"avatar.{e}"
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.post("/api/transcribe")
async def api_transcribe(body: dict) -> dict:
    import base64
    import re

    m = re.match(r"data:audio/[\w.+-]+;base64,(.+)$", body.get("audio", ""), re.DOTALL)
    if not m:
        return {"ok": False, "error": "kein Audio"}
    raw = base64.b64decode(m.group(1))
    vdir = ROOT / "data" / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    fp = vdir / f"cockpit-{int(time.time())}.webm"
    fp.write_bytes(raw)

    def _t():
        from core.agency.connectors.transcribe import transcribe

        return transcribe(str(fp))

    try:
        txt = await anyio.to_thread.run_sync(_t)
    except ImportError:
        return {"ok": False, "error": "faster-whisper fehlt (uv sync)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": txt or ""}


@app.post("/api/vision")
async def api_vision(body: dict) -> dict:
    img = body.get("image", "")
    if not img.startswith("data:image"):
        return {"ok": False, "error": "kein Bild"}
    prompt = (body.get("prompt") or "").strip()

    def _call():
        from core.agency import vision

        return vision.describe(img, prompt)

    try:
        txt = await anyio.to_thread.run_sync(_call)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": txt}


# S7c: Session-Metadaten (Archiv-Flag) als Sidecar — Sessions selbst leben im Memory.
_CHAT_META = ROOT / "data" / "chat_meta.json"


def _chat_meta() -> dict:
    try:
        return json.loads(_CHAT_META.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_chat_meta(meta: dict) -> None:
    atomic_write(_CHAT_META, json.dumps(meta, indent=1, ensure_ascii=False))


@app.get("/api/chat/sessions")
def api_chat_sessions(archived: int = 0) -> dict:
    """Sessions-Liste; archivierte sind standardmaessig ausgeblendet (archived=1 zeigt alle)."""
    meta = _chat_meta()
    out = []
    for s in memory.sessions(limit=60):
        arch = bool((meta.get(s["session_id"]) or {}).get("archived"))
        if arch and not archived:
            continue
        out.append({**s, "archived": arch})
    return {"sessions": out}


@app.post("/api/chat/archive")
async def api_chat_archive(body: dict) -> dict:
    sid = str(body.get("sid", "")).strip()
    if not sid:
        return {"ok": False, "error": "sid fehlt"}
    meta = _chat_meta()
    meta.setdefault(sid, {})["archived"] = bool(body.get("archived", True))
    _save_chat_meta(meta)
    return {"ok": True, "archived": meta[sid]["archived"]}


@app.get("/api/chat/history")
def api_chat_history(sid: str = "") -> dict:
    return {"messages": memory.recent_dialogue(sid, limit=200) if sid else []}


@app.post("/api/chat/delete")
async def api_chat_delete(body: dict) -> dict:
    return {"ok": True, "deleted": memory.clear_session(body.get("sid", ""))}


# ---------- Chat (Live-Thinking) ----------
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    import uuid

    from core.agency.act import act_chat_stream

    from core.kernel import runstate

    await ws.accept()
    sid = ws.query_params.get("sid") or ("cockpit-" + uuid.uuid4().hex[:8])
    await ws.send_json({"role": "system", "text": f"Verbunden. Session {sid[-8:]}."})
    try:
        while True:
            user_text = await ws.receive_text()
            runstate.enter_turn()  # aktiver Cockpit-Zug -> Neustart (self_edit/restart_self) wartet bis danach
            try:
                gen = act_chat_stream(user_text, sid)

                def next_piece():
                    try:
                        return next(gen)
                    except StopIteration:
                        return None

                while True:
                    piece = await anyio.to_thread.run_sync(next_piece)
                    if piece is None:
                        break
                    await ws.send_json({"role": "partner", **piece})
                await ws.send_json({"role": "partner", "done": True})
            finally:
                runstate.exit_turn()  # idle -> ein aufgeschobener Neustart wird jetzt ausgeloest (nach der Antwort)
    except WebSocketDisconnect:
        pass


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # Sprüche-Katalog (eine Quelle) in die Seite injizieren -> kein Extra-Request, kein Drift.
    # [1:-1] = ohne aeussere Klammern (die stehen schon im JS: const PHRASES=[...]) -> bei
    # ausbleibender Injektion bleibt [] als sichere, gueltige Fallback-Form.
    inner = json.dumps(THINKING_PHRASES, ensure_ascii=False)[1:-1]
    return DASHBOARD_HTML.replace("/*__PHRASES__*/", inner)


# Das komplette Cockpit-Frontend lebt seit S5.3a in core/api/ui/ (css.py, views.py,
# script.py) — drei handliche Module statt einer 90-KB-Wand hier. Der Export bleibt
# identisch: DASHBOARD_HTML ist weiterhin ueber core.api.server importierbar.
from core.api.ui import DASHBOARD_HTML  # noqa: E402
from core.kernel.fs import atomic_write
