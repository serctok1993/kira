"""FastAPI-Cockpit: Chat (mit Live-Thinking), Seele/Dateien, Modelle, Protokoll.

Ein Prozess, eine Seite (Terminal-Look). Start:
    uv run uvicorn core.api.server:app --reload   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import time

import anyio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response

from core.agency.tools import builtin as _builtin  # noqa: F401  (registriert eingebaute Tools)
from core.agency.tools import registry
from core.agency.tools import synthesize as _synth
from core.config import CONFIG, MIND_DIR, ROOT
from core.governance import audit, secrets, treasury, trust
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

# Im Dashboard sichtbare/bearbeitbare Dateien. Alles editierbar — DU bist der Eigentuemer.
# (Die Verfassung ist nur fuer KIRA gesperrt — via evolution.py; du darfst sie hier aendern.)
FILES: dict[str, dict] = {
    "constitution.md": {"path": MIND_DIR / "constitution.md", "editable": True, "label": "Verfassung (fuer Kira gesperrt, von dir editierbar)"},
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
        "trust_level": trust.level(),
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
        "trust": {"level": trust.level(), "label": trust.LEVELS.get(trust.level(), "?")},
        "mission": {"name": CONFIG.get("mission", {}).get("name"), "heartbeat": heartbeat_on()},
        "tools": [t.name for t in registry.all_tools()],
        "lessons": memory.recall_lessons(5),
        "last_mission": last_mission,
        "events_total": sum(events.counts_by_type().values()),
    }


@app.get("/api/governance")
def api_governance() -> dict:
    lv = trust.level()
    return {
        "treasury": treasury.status(),
        "trust": {"level": lv, "label": trust.LEVELS.get(lv, "?"), **trust.stats()},
        "audit": audit.recent(30),
    }


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

    return {"ok": True, "job": cron.add_job(body.get("label", ""), body.get("prompt", ""), body.get("schedule", "60m"))}


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
                         notes=body.get("notes") or None)
    events.emit("objective_add", {"id": oid, "title": title, "kind": body.get("kind", "weekly"), "via": "dashboard"})
    return {"ok": True, "id": oid}


@app.post("/api/objectives/update")
async def api_objectives_update(body: dict) -> dict:
    from core.agency.missions import objectives

    oid = body.get("id", "")
    fields = {k: body[k] for k in ("title", "kind", "status", "progress", "target_date", "notes", "parent_id") if k in body}
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


# ---------- Freigabe-Inbox + Tages-Digest (Phase 2) ----------
def _pending_proposals() -> list[dict]:
    """Offene SOUL/GOAL-Selbstaenderungs-Vorschlaege als Inbox-Eintraege (kind=evolution)."""
    out = []
    pdir = ROOT / "data" / "proposals"
    try:
        for doc in ("SOUL.md", "GOAL.md"):
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
    if aid.startswith("prop:"):  # SOUL/GOAL-Vorschlag
        doc = aid[5:]
        pfile = ROOT / "data" / "proposals" / doc
        if approved:
            try:
                from core.mind import evolution
                res = await anyio.to_thread.run_sync(lambda: evolution.apply_update(doc, "Freigabe via Inbox"))
                return {"ok": True, "status": "approved", "applied": res}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)}
        else:
            try:
                if pfile.exists():
                    pfile.unlink()
            except Exception:  # noqa: BLE001
                pass
            events.emit("approval_decided", {"id": aid, "status": "rejected", "kind": "evolution"})
            return {"ok": True, "status": "rejected"}
    return approvals.decide(aid, approved, note)


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


@app.get("/api/chat/sessions")
def api_chat_sessions() -> dict:
    return {"sessions": memory.sessions()}


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


DASHBOARD_HTML = """<!doctype html>
<html lang="de"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Kira Cockpit</title>
<style>
:root{--bg:#04040a;--panel:#0d0d16;--panel2:#08080f;--line:#241b3a;--ink:#eceef4;
 --muted:#8a86a0;--accent:#b026ff;--accent2:#7c3aed;--hud:#22d3ee;--glow:#b026ff;
 --amber:#d8b4fe;--danger:#ff3d68;--ok:#34ff9e;--warn:#f5a623;}
html[data-theme="gruen"]{--accent:#39ff14;--accent2:#16a34a;--hud:#adff2f;--glow:#39ff14;--amber:#bbf7d0;}
html[data-theme="blau"]{--accent:#22d3ee;--accent2:#0891b2;--hud:#38bdf8;--glow:#22d3ee;--amber:#a5f3fc;}
.thm{width:30px;height:30px;border-radius:8px;cursor:pointer;padding:0;border:2px solid var(--line);background:var(--panel);
 display:inline-flex;align-items:center;justify-content:center;background-size:cover;background-position:center}
.thm:hover{border-color:var(--accent)}
.thm.on{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent),0 0 14px var(--glow)}
.thm .td{width:15px;height:15px;border-radius:50%;display:inline-block}
.thm.kira{background:linear-gradient(135deg,#3a2150,#0a0410)}
.live{width:7px;height:7px;border-radius:50%;background:var(--ok);display:inline-block;animation:ping 2.4s ease-out infinite}
@keyframes ping{0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}70%,100%{box-shadow:0 0 0 7px rgba(52,211,153,0)}}
.pulse{color:var(--muted);font-weight:500;letter-spacing:.2px}
#feed-list{font-size:12.5px;max-height:280px;overflow:auto;margin-top:6px}
.fd{display:flex;gap:12px;padding:5px 2px;border-bottom:1px solid var(--line)}
.fd .fdt{color:var(--muted);min-width:72px;font-variant-numeric:tabular-nums}
.fd .fdx{flex:1;color:var(--ink)}
.fd.error .fdx{color:var(--danger)} .fd.chat .fdx{color:var(--accent)} .fd.info .fdx{color:var(--muted)}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;font:14px/1.5 ui-monospace,"Cascadia Code",Consolas,monospace;
 background:radial-gradient(1100px 620px at 78% -12%, rgba(90,60,150,.16), #07070a 62%) fixed;color:var(--ink)}
#side{width:210px;flex-shrink:0;border-right:1px solid var(--line);background:rgba(13,9,20,.72);
 backdrop-filter:blur(8px);display:flex;flex-direction:column}
#side h1{font-size:19px;letter-spacing:4px;padding:16px 16px 2px;color:#fff;margin:0;
 text-shadow:0 0 10px rgba(139,92,246,.30)}
#side .sub{font-size:11px;color:var(--muted);padding:0 16px 14px;letter-spacing:1px}
#side a{display:block;padding:10px 16px;color:var(--ink);text-decoration:none;cursor:pointer;
 border-left:3px solid transparent}
#side a:hover{background:rgba(168,85,247,.10)}
#side a.on{background:rgba(168,85,247,.14);border-left-color:var(--accent);color:#fff}
#side .spacer{flex:1}
#side .kill{margin:12px;padding:9px;text-align:center;border:1px solid var(--line);border-radius:8px;
 cursor:pointer;color:var(--muted)}
#side .kill.active{border-color:var(--danger);color:var(--danger)}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#bar{padding:9px 18px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center;
 font-size:12px;color:var(--muted);background:var(--panel2)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent);display:inline-block}
#v-home h2{font-size:18px;letter-spacing:1px}
#bar b{color:var(--ink)}
.view{flex:1;overflow:auto;display:none;padding:18px}
.view.on{display:flex;flex-direction:column}
/* chat */
#log{flex:1;overflow:auto;display:flex;flex-direction:column;gap:12px;max-width:880px;margin:0 auto;width:100%}
.msg{padding:11px 14px;border-radius:12px;border:1px solid var(--line);white-space:pre-wrap;max-width:84%}
.me{align-self:flex-end;background:rgba(124,58,237,.22);border-color:rgba(168,85,247,.35)}
.bot{align-self:flex-start;background:rgba(21,15,32,.72)}
.sys{align-self:center;color:var(--muted);font-size:12px;border:none}
.think{align-self:flex-start;max-width:84%;color:var(--muted);font-size:12px;font-style:italic;
 border-left:2px solid var(--accent2);padding:4px 10px;margin:-4px 0 0;white-space:pre-wrap;display:none}
.think.show{display:block}
.think .h{color:var(--accent2);font-style:normal;cursor:pointer}
#cform{display:flex;gap:10px;max-width:880px;margin:10px auto 0;width:100%}
#cin{flex:1;padding:12px;border-radius:10px;border:1px solid var(--line);background:var(--panel);color:var(--ink);
 outline:none;font-family:inherit}
#cin:focus{border-color:var(--accent2)}
button{padding:0 16px;border:none;border-radius:8px;cursor:pointer;font-weight:600;font-family:inherit;
 background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
button.ghost{background:var(--panel);color:var(--ink);border:1px solid var(--line)}
/* files */
.cols{display:flex;gap:16px;flex:1;min-height:0}
.flist{width:230px;flex-shrink:0;display:flex;flex-direction:column;gap:6px}
.flist .f{padding:9px 11px;border:1px solid var(--line);border-radius:8px;cursor:pointer;background:var(--panel)}
.flist .f:hover{border-color:var(--accent2)}
.flist .f.on{border-color:var(--accent);color:var(--accent)}
.flist .f small{display:block;color:var(--muted);font-size:10px}
.fedit{flex:1;display:flex;flex-direction:column;gap:8px;min-width:0}
#farea{flex:1;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;
 padding:12px;font-family:inherit;font-size:13px;resize:none;outline:none}
#farea:read-only{color:var(--muted)}
.frow{display:flex;gap:10px;align-items:center}
/* models + protokoll */
.card{background:rgba(16,16,20,.72);backdrop-filter:blur(6px);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px;max-width:880px}
.card h3{margin:0 0 8px;font-size:13px;color:var(--amber)}
.pill{display:inline-block;padding:3px 9px;border:1px solid var(--line);border-radius:20px;margin:3px 5px 3px 0;
 font-size:12px;cursor:pointer}
.pill:hover{border-color:var(--accent)}
.pill.ok{color:var(--accent);border-color:var(--accent2)}
.pill.no{color:var(--muted)}
.row{display:flex;gap:8px;margin-top:8px}
.row input{flex:1;padding:9px;border:1px solid var(--line);border-radius:8px;background:var(--panel2);color:var(--ink);
 outline:none;font-family:inherit}
#evlog,#memlist{font-size:12px;max-width:980px}
.e{padding:6px 10px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:flex-start}
.e .t{color:var(--accent);min-width:150px}
.e .m{color:var(--muted);white-space:pre-wrap;flex:1;cursor:pointer}
.e .m.clamp{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.e.error{background:rgba(240,89,106,.09);border-left:3px solid var(--danger)}
.e.error .t{color:var(--danger)}
.e.action .t{color:var(--accent)}
.e.chat .t{color:#67e8c9}
.e.info .t{color:var(--muted)}
.pill.on{color:#fff;border-color:var(--accent);background:rgba(168,85,247,.14)}
.card:hover{border-color:rgba(139,92,246,.26)}
#side{background:linear-gradient(180deg,rgba(14,14,18,.92),rgba(8,8,11,.86))}
.ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--danger)}
.look{display:flex;gap:10px;align-items:center;justify-content:center;padding:8px 12px;
 margin:0 12px 6px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:12px}
.look label,.look a{cursor:pointer;color:var(--muted);text-decoration:none}
.look label:hover,.look a:hover{color:var(--accent)}
.direktive{max-width:1120px;margin:0 0 16px;border:1px solid var(--line);border-radius:12px;
 padding:14px;background:rgba(16,16,20,.72)}
.direktive h3{margin:0 0 8px;color:var(--amber)}
.home-cols{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;max-width:1400px}
.home-main{flex:3 1 520px;min-width:0;display:flex;flex-direction:column;gap:14px}
.home-side{flex:1 1 300px;min-width:280px;display:flex;flex-direction:column;gap:10px}
.home-main .direktive,.home-main .home-feed{max-width:none;margin:0;width:100%}
.home-side .card{max-width:none;margin:0;padding:11px 13px}
.home-side .card h3{font-size:12px;margin:0 0 6px}
.home-feed #feed-list{max-height:440px}
textarea.k{width:100%;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;
 padding:10px;font-family:inherit;font-size:13px;resize:vertical;outline:none;min-height:52px}
textarea.k:focus{border-color:var(--accent2)}
.muted{color:var(--muted)}
/* ===== Kira-Signature: UI-Font, Aura/Glow, Motion (additiv, ueberschreibt via Quellreihenfolge) ===== */
:root{--mono:ui-monospace,"Cascadia Code",Consolas,monospace}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,"Helvetica Neue",Arial,sans-serif}
.think,#farea,#evlog,#memlist,#feed-list,.e{font-family:var(--mono)}
/* NEON-BG: kein Grid mehr -> theme-farbiger Glow + dezente STATISCHE Scanline (kein Flackern) */
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
 background:
  radial-gradient(1200px 800px at 82% -14%, color-mix(in srgb, var(--glow) 16%, transparent), transparent 60%),
  radial-gradient(900px 700px at 10% 110%, color-mix(in srgb, var(--hud) 9%, transparent), transparent 60%),
  repeating-linear-gradient(0deg, rgba(255,255,255,.012) 0 1px, transparent 1px 3px)}
#side h1{font-size:24px;letter-spacing:6px;text-shadow:0 0 18px var(--glow),0 0 42px var(--glow);animation:flickerin 1.3s ease both}
@keyframes flickerin{0%{opacity:0}10%{opacity:.6}13%{opacity:.2}22%{opacity:.95}27%{opacity:.4}33%,100%{opacity:1}}
#side a{transition:background .18s ease,border-color .18s ease,color .18s ease}
#side a.on{box-shadow:inset 3px 0 0 var(--accent),inset 0 0 22px color-mix(in srgb,var(--glow) 14%,transparent)}
button{transition:transform .12s ease,box-shadow .2s ease,filter .2s ease;box-shadow:0 0 14px color-mix(in srgb,var(--glow) 28%,transparent)}
button:hover{filter:brightness(1.12);transform:translateY(-1px);box-shadow:0 0 20px var(--glow)}
button:active{transform:translateY(0)}
button.ghost{box-shadow:none}
button.ghost:hover{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 0 12px color-mix(in srgb,var(--glow) 30%,transparent)}
.card{transition:border-color .2s ease,transform .2s ease,box-shadow .2s ease}
.card:hover{transform:translateY(-1px);box-shadow:0 10px 30px rgba(0,0,0,.35)}
.pill{transition:border-color .15s ease,color .15s ease,background .15s ease}
.view.on{animation:viewin .32s ease both}
@keyframes viewin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.msg{animation:msgin .28s cubic-bezier(.2,.7,.2,1) both;border-radius:14px;box-shadow:0 2px 10px rgba(0,0,0,.22);line-height:1.5}
.me{background:linear-gradient(135deg,rgba(124,58,237,.26),rgba(109,40,217,.18));border-color:rgba(168,85,247,.38)}
.bot{background:rgba(20,16,30,.82);border-color:rgba(139,92,246,.14)}
@keyframes msgin{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.think{background:rgba(139,92,246,.05);border-left:2px solid var(--accent);border-radius:10px;padding:8px 12px;box-shadow:inset 0 0 0 1px rgba(139,92,246,.06)}
.thinking{align-self:flex-start;display:flex;align-items:center;gap:9px;margin:2px 0;padding:7px 14px;
 font-size:13.5px;font-weight:500;border-radius:12px;
 background:linear-gradient(90deg,transparent,rgba(139,92,246,.08),transparent)}
.thinking .sh{color:var(--accent);filter:drop-shadow(0 0 7px var(--accent));animation:spin 3.4s linear infinite}
.thinking .tx{background:linear-gradient(90deg,var(--muted) 0%,#fff 22%,var(--accent) 44%,var(--muted) 66%);
 background-size:220% 100%;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;
 animation:shimmer 2.7s linear infinite}
@keyframes shimmer{to{background-position:-220% 0}}
@keyframes spin{to{transform:rotate(360deg)}}
/* ===== HUD-Kommandozentrale ===== */
/* --hud kommt jetzt pro Theme aus dem :root/data-theme oben (faerbt beim Wechsel mit) */
.hud-strip{display:flex;flex-wrap:wrap;align-items:stretch;margin-bottom:14px;border:1px solid var(--line);
 border-radius:10px;overflow:hidden;background:rgba(10,12,16,.7);font-family:var(--mono)}
.hud-cell{padding:8px 14px;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:3px;min-width:118px}
.hud-cell:last-child{border-right:none}
.hud-cell .k{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted)}
.hud-cell .val{font-size:13px;color:var(--ink)}
.hud-cell.spacer{flex:1;min-width:0}
.mini-bar{height:5px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:5px;min-width:96px}
.mini-bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--hud),var(--accent))}
.mini-bar.warn>i{background:linear-gradient(90deg,var(--warn),var(--danger))}
.cmd-grid{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;max-width:1500px}
.cmd-main{flex:2 1 520px;min-width:0;display:flex;flex-direction:column;gap:14px}
.cmd-side{flex:1 1 320px;min-width:300px;display:flex;flex-direction:column;gap:14px}
.panel{position:relative;border:1px solid var(--line);border-radius:10px;background:rgba(12,14,18,.66);backdrop-filter:blur(4px)}
.panel::before,.panel::after{content:"";position:absolute;width:9px;height:9px;border:1px solid var(--hud);opacity:.5}
.panel::before{top:-1px;left:-1px;border-right:none;border-bottom:none}
.panel::after{bottom:-1px;right:-1px;border-left:none;border-top:none}
.panel-h{display:flex;align-items:center;gap:8px;padding:9px 13px;border-bottom:1px solid var(--line);
 font-family:var(--mono);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--hud)}
.panel-h .sp{flex:1}
.panel-b{padding:10px 13px}
#ops-feed{max-height:52vh;overflow:auto;font-family:var(--mono);font-size:12px}
.op{display:flex;gap:10px;padding:5px 13px;border-bottom:1px solid rgba(255,255,255,.04);align-items:flex-start}
.op .opt{color:var(--muted);min-width:62px;font-variant-numeric:tabular-nums}
.op .opx{flex:1;color:var(--ink);word-break:break-word}
.op.error{background:rgba(240,89,106,.08)} .op.error .opx{color:var(--danger)}
.op.action .opx{color:var(--hud)} .op.chat .opx{color:var(--accent)} .op.info .opx{color:var(--muted)}
.op .od{width:6px;height:6px;border-radius:50%;margin-top:6px;background:var(--muted);flex-shrink:0}
.op.action .od{background:var(--hud)} .op.error .od{background:var(--danger)} .op.chat .od{background:var(--accent)}
.ticker{overflow:hidden;white-space:nowrap;border-bottom:1px solid var(--line);background:rgba(0,0,0,.25)}
.ticker>span{display:inline-block;padding:7px 0;font-family:var(--mono);font-size:12px;color:var(--hud);animation:tick 42s linear infinite}
@keyframes tick{from{transform:translateX(100%)}to{transform:translateX(-100%)}}
.ticker:hover>span{animation-play-state:paused}
.news-item{padding:8px 13px;border-bottom:1px solid rgba(255,255,255,.05);font-size:12px}
.news-item b{color:var(--ink)} .news-item small{color:var(--muted)}
.badge{display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;letter-spacing:.5px;border:1px solid var(--line);font-family:var(--mono)}
.badge.kira{color:var(--accent);border-color:var(--accent2)}
.badge.you{color:var(--hud);border-color:rgba(94,234,212,.4)}
.badge.kind{color:var(--muted)}
.memrow{border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin-bottom:8px;background:rgba(16,16,20,.5)}
.memrow .mh{display:flex;gap:7px;align-items:center;margin-bottom:5px;font-size:11px;color:var(--muted);flex-wrap:wrap}
.hist .old{color:var(--danger);text-decoration:line-through;opacity:.75}
.hist .new{color:var(--ok)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;font-family:var(--mono);font-size:11px}
.seg a{padding:5px 10px;color:var(--muted);cursor:pointer;border-right:1px solid var(--line)}
.seg a:last-child{border-right:none}
.seg a.on{background:rgba(94,234,212,.12);color:var(--hud)}
.thinking .tx{color:var(--hud)}
/* ===== NEON v2: Scrollbars + Panel-Glow + Theme-follow + Mission-Grid ===== */
*{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--accent) 45%,#2a2440) transparent}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--accent) 34%,transparent);border-radius:8px;border:2px solid transparent;background-clip:padding-box}
::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--glow) 70%,transparent);box-shadow:0 0 8px var(--glow)}
::-webkit-scrollbar-corner{background:transparent}
/* vorher hartkodierte Tuerkis-Werte -> folgen jetzt dem Theme */
.badge.you{border-color:color-mix(in srgb,var(--hud) 50%,transparent)}
.seg a.on{background:color-mix(in srgb,var(--hud) 16%,transparent)}
/* Panels: staerkerer Neon-Rahmen + leuchtende Ecken + Header-Glow */
.panel{border-color:color-mix(in srgb,var(--hud) 22%,var(--line));box-shadow:0 0 0 1px color-mix(in srgb,var(--hud) 8%,transparent),0 10px 34px rgba(0,0,0,.55)}
.panel::before,.panel::after{width:12px;height:12px;border-color:var(--hud);opacity:.9;filter:drop-shadow(0 0 4px var(--hud))}
.panel-h{color:var(--hud);text-shadow:0 0 10px color-mix(in srgb,var(--hud) 60%,transparent);border-bottom-color:color-mix(in srgb,var(--hud) 20%,var(--line))}
.card{border-color:color-mix(in srgb,var(--accent) 16%,var(--line))}
.card h3{color:var(--accent);text-shadow:0 0 10px color-mix(in srgb,var(--glow) 45%,transparent)}
h2{text-shadow:0 0 14px color-mix(in srgb,var(--glow) 45%,transparent)}
.ticker>span{color:var(--hud);text-shadow:0 0 8px color-mix(in srgb,var(--hud) 55%,transparent)}
.live{box-shadow:0 0 9px var(--ok)}
.pill.ok,.pill.on{box-shadow:0 0 10px color-mix(in srgb,var(--glow) 30%,transparent)}
/* Mission: ausgewogenes 2-Spalten-Grid (kein Stranden), gleiche Hoehen */
.mgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:stretch;max-width:1560px;margin-bottom:14px}
.mgrid>.panel{min-height:210px;display:flex;flex-direction:column}
.mgrid>.panel>.panel-b,.mgrid>.panel>[class*="-list"],.mgrid>.panel>#todo-board,.mgrid>.panel>#obj-list{flex:1}
@media(max-width:1000px){.mgrid{grid-template-columns:1fr}}
.emptybox{display:flex;align-items:center;justify-content:center;min-height:150px;color:var(--muted);
 border:1px dashed color-mix(in srgb,var(--hud) 30%,var(--line));border-radius:10px;font-family:var(--mono);text-align:center;padding:16px}
@media (prefers-reduced-motion: reduce){
 *{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important}
 body::after{animation:none}
}
</style></head><body>
<div id="side">
  <h1>KIRA</h1><div class="sub" id="who">cockpit</div>
  <a data-v="home" class="on" title="Steuern, Live-Puls, Kernzustand">› Uebersicht</a>
  <a data-v="mission" title="Ziele, Projekte, To-Dos — dein Fahrplan">◈ Mission</a>
  <a data-v="chat" title="Mit mir reden">› Chat</a>
  <a data-v="files" title="Wer ich bin: Verfassung, Seele, Ziel, dein Profil">› Seele &amp; Dateien</a>
  <a data-v="gov" title="Meine Leitplanken: Budget, Vertrauen, Audit">› Gewissen</a>
  <a data-v="monitor" title="Was ich draussen beobachte">› Monitor</a>
  <a data-v="cron" title="Feste Termine (wiederkehrende Aufgaben)">› Cron</a>
  <a data-v="keys" title="Schluessel &amp; Passwoerter">› Zugaenge</a>
  <a data-v="mem" title="Was ich mir merke">› Gedaechtnis</a>
  <a data-v="models" title="Mein Gehirn &amp; System: Modell, Parameter, Verhalten">⚙ Einstellungen</a>
  <a data-v="log" title="Alles was ich tue (Live-Log)">› Protokoll</a>
  <div class="spacer"></div>
  <div class="look">
    <button class="thm on" data-theme="" title="Schwarz / Lila (Standard)"><span class="td" style="background:#8b5cf6"></span></button>
    <button class="thm" data-theme="gruen" title="Schwarz / Gruen"><span class="td" style="background:#22c55e"></span></button>
    <button class="thm" data-theme="blau" title="Schwarz / Blau"><span class="td" style="background:#3b82f6"></span></button>
    <button class="thm kira" id="thm-kira" data-theme="kira" title="Kira-Modus (Bild-Hintergrund)"></button>
    <label id="bgup" title="Kira-Bild waehlen / aendern" style="cursor:pointer;color:var(--muted);margin-left:2px;font-size:15px">📷<input id="bgquick" type="file" accept="image/*" style="display:none"/></label>
  </div>
  <div class="kill" id="kill">Not-Aus: aus</div>
</div>
<div id="main">
  <div id="bar">
    <span class="live"></span>
    <span id="pulse" class="pulse">…</span>
    <span style="flex:1"></span>
    <span class="muted"><b id="b-model">…</b></span>
    <span class="muted">heute <b id="b-spend">…</b></span>
    <span id="b-kill"></span>
  </div>

  <div class="view on" id="v-home">
    <div class="hud-strip" id="hud-strip"></div>
    <div class="direktive">
      <h3>🎯 Befehl an Kira</h3>
      <textarea id="dir-text" class="k" placeholder="Sag mir, worauf ich mich konzentrieren soll — oder gib mir einen Sofort-Auftrag…"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
        <button id="dir-now">⚡ Sofort ausfuehren</button>
        <button class="ghost" id="dir-focus">🧭 Als Fokus setzen</button>
        <button class="ghost" id="dir-clear" title="Fokus loeschen">Fokus loeschen</button>
        <span class="muted" id="dir-hint" style="align-self:center"></span>
      </div>
      <div id="dir-result" style="margin-top:8px;white-space:pre-wrap;display:none;border-top:1px solid var(--line);padding-top:8px"></div>
    </div>
    <div class="cmd-grid">
      <div class="cmd-main">
        <div class="panel">
          <div class="panel-h">◈ Live-Ops <span class="live"></span><span class="sp"></span>
            <span class="seg" id="ops-filter"><a data-of="all" class="on">alle</a><a data-of="action">aktionen</a><a data-of="chat">chat</a><a data-of="error">fehler</a></span>
          </div>
          <div id="ops-feed"><span class="muted" style="padding:10px 13px;display:block">…</span></div>
        </div>
      </div>
      <div class="cmd-side">
        <div class="panel">
          <div class="panel-h">◈ Intel · KI-News <span class="sp"></span><a id="news-seed" class="muted" style="cursor:pointer;font-size:10px">+ Quellen</a></div>
          <div class="ticker" id="news-ticker"><span>… Intel wird geladen …</span></div>
          <div id="news-list" class="panel-b"><span class="muted">…</span></div>
        </div>
        <div class="home-side" id="home"></div>
      </div>
    </div>
  </div>

  <div class="view" id="v-mission">
    <div class="mgrid">
      <div class="panel">
        <div class="panel-h">◈ ZIELE / PROJEKTE <span class="sp"></span><a id="obj-new-btn" class="muted" style="cursor:pointer;font-size:11px">+ ZIEL</a></div>
        <div class="panel-b" id="obj-form" style="display:none">
          <div class="row" style="flex-wrap:wrap">
            <input id="obj-title" placeholder="Ziel/Projekt-Titel" style="flex:1;min-width:180px"/>
            <select id="obj-kind"><option value="big">Big Project</option><option value="monthly">Monatsziel</option><option value="weekly" selected>Wochenziel</option></select>
            <input id="obj-date" type="date" title="Zieldatum"/>
            <button id="obj-add">Anlegen</button>
          </div>
        </div>
        <div id="obj-list" class="panel-b"><span class="muted">…</span></div>
      </div>
      <div class="panel">
        <div class="panel-h">◈ TO-DO / BACKLOG <span class="sp"></span><a id="todo-new-btn" class="muted" style="cursor:pointer;font-size:11px">+ TO-DO</a></div>
        <div class="panel-b" id="todo-form" style="display:none">
          <div class="row" style="flex-wrap:wrap">
            <input id="todo-desc" placeholder="Was zu tun ist" style="flex:1;min-width:170px"/>
            <select id="todo-prio"><option value="1">P1</option><option value="2">P2</option><option value="3" selected>P3</option><option value="4">P4</option></select>
            <input id="todo-due" type="date" title="faellig"/>
            <button id="todo-add">+</button>
          </div>
          <div class="muted" style="margin-top:5px;font-size:11px">Ziel zuordnen (optional): <select id="todo-obj"><option value="">— keins —</option></select></div>
        </div>
        <div id="todo-board" class="panel-b"><span class="muted">…</span></div>
      </div>
    </div>
    <div class="mgrid">
      <div class="panel">
        <div class="panel-h">◈ FREIGABE-INBOX <span class="live"></span><span class="sp"></span><span class="muted" id="inbox-count" style="font-size:11px"></span></div>
        <div id="inbox-list" class="panel-b"><span class="muted">…</span></div>
      </div>
      <div class="panel">
        <div class="panel-h">◈ TAGES-DIGEST</div>
        <div id="digest" class="panel-b"><span class="muted">…</span></div>
      </div>
    </div>
  </div>

  <div class="view" id="v-chat">
    <div id="chatbar" style="display:flex;gap:8px;align-items:center;padding:4px 0 8px;flex-wrap:wrap">
      <select id="sess-list" style="max-width:300px" title="Unterhaltung waehlen"></select>
      <button type="button" class="ghost" id="sess-new" title="Neue Unterhaltung" style="padding:6px 10px">＋ Neu</button>
      <button type="button" class="ghost" id="sess-del" title="Diese Unterhaltung loeschen" style="padding:6px 10px">🗑</button>
      <span style="flex:1"></span>
      <small class="muted">Hirn:</small>
      <select id="chat-model" style="max-width:200px"></select>
      <label class="muted" title="Plan-Modus: erst Plan, dann Schritt fuer Schritt" style="cursor:pointer;display:inline-flex;align-items:center;gap:4px"><input type="checkbox" id="planmode"/> 🧭 Plan</label>
    </div>
    <div id="log"></div>
    <form id="cform">
      <input id="cin" placeholder="Schreib mir…" autocomplete="off" autofocus/>
      <button type="button" id="micbtn" class="ghost" title="Sprachmemo aufnehmen">🎤</button>
      <label id="imgbtn" class="ghost" title="Bild an Kira" style="display:flex;align-items:center;padding:0 14px;border-radius:10px;cursor:pointer">📎<input id="imgfile" type="file" accept="image/*" style="display:none"/></label>
      <button>Senden</button>
    </form>
  </div>

  <div class="view" id="v-files">
    <div class="cols">
      <div class="flist" id="flist"></div>
      <div class="fedit">
        <div class="frow"><b id="ftitle" class="muted">Datei waehlen…</b><span class="spacer" style="flex:1"></span>
          <button class="ghost" id="fsave" style="display:none">Speichern</button></div>
        <textarea id="farea" readonly placeholder="—"></textarea>
      </div>
    </div>
  </div>

  <div class="view" id="v-models">
    <div class="card"><h3>Aktives Modell</h3><div id="m-active" class="muted">…</div></div>
    <div class="card"><h3>Kontext &amp; Parameter</h3>
      <div id="m-loaded" class="muted">…</div>
      <div class="row">
        <input id="m-ctx" type="number" placeholder="num_ctx (z.B. 16384)" style="max-width:190px"/>
        <input id="m-maxtok" type="number" placeholder="max_tokens" style="max-width:160px"/>
        <button id="m-paramgo">Setzen</button>
      </div>
      <div style="margin-top:8px">Schnell-Kontext:
        <span class="pill" data-ctx="16384">16K</span>
        <span class="pill" data-ctx="32768">32K</span>
        <span class="pill" data-ctx="65536">64K</span>
        <span class="pill" data-ctx="131072">128K</span></div>
      <div class="muted" style="margin-top:6px">Größer = mehr VRAM. Nach „Setzen" lädt das Modell neu — bleibt „GPU 100%"? Falls Anteil sinkt (CPU-Spill = langsam), kleiner wählen.</div>
    </div>
    <div class="card"><h3>Verhalten &amp; System</h3>
      <div class="muted">Feineinstellungen. Temperatur/keep_alive wirken sofort; Sprache/Voice brauchen einen Neustart.</div>
      <div class="row" style="margin-top:8px;flex-wrap:wrap">
        <label class="muted" style="align-self:center">Temperatur</label>
        <input id="s-temp" type="number" step="0.1" min="0" max="2" style="max-width:100px"/>
        <label class="muted" style="align-self:center">keep_alive</label>
        <input id="s-keep" placeholder="z.B. 24h" style="max-width:100px"/>
        <button id="s-behav-save">Setzen (live)</button>
      </div>
      <div class="row" style="margin-top:8px;flex-wrap:wrap">
        <label class="muted" style="cursor:pointer;align-self:center"><input type="checkbox" id="s-voice"/> Sprachmemos transkribieren</label>
        <label class="muted" style="align-self:center">Whisper</label>
        <select id="s-whisper"><option>tiny</option><option>base</option><option>small</option><option>medium</option></select>
        <button id="s-sys-save">Speichern (Neustart)</button>
        <span class="muted" id="s-sys-hint" style="align-self:center"></span>
      </div>
    </div>
    <div class="card"><h3>Lokal (Ollama) — klicken zum Wechseln</h3><div id="m-ollama"></div></div>
    <div class="card"><h3>Modell-Rollen — was denkt womit</h3>
      <div class="muted">Jede Aufgabe hat ihre eigene KI. Zum Aendern unten im Katalog ein Modell suchen und der Rolle zuweisen.</div>
      <div id="m-roles" style="margin-top:8px"></div>
    </div>
    <div class="card"><h3>Modell-Katalog (live: alle OpenRouter + lokal)</h3>
      <div class="row" style="margin-top:4px;flex-wrap:wrap">
        <label class="muted" style="align-self:center">Zuweisen an:</label>
        <select id="cat-role">
          <option value="chat">💬 Chat (Smalltalk)</option>
          <option value="reason">🧠 Reason / Coding</option>
          <option value="bulk">⏰ Crons (einfach)</option>
          <option value="escalation">⚡ Eskalation</option>
          <option value="default">★ Default (alles)</option>
        </select>
        <input id="cat-search" placeholder="🔍 suchen: deepseek, flash, claude, gemini, qwen …" style="min-width:240px;flex:1"/>
      </div>
      <div id="cat-list" style="max-height:340px;overflow:auto;margin-top:8px;font-size:12px"></div>
      <div class="muted" id="cat-hint" style="margin-top:6px"></div>
    </div>
  </div>

  <div class="view" id="v-gov">
    <div class="card"><h3>Was ist das „Gewissen"?</h3>
      <div class="muted">Meine <b>Leitplanken</b> — womit du steuerst, wie weit ich gehen darf:
      <b class="ok">Budget</b> = wie viel Geld sie pro Tag/Monat ausgeben darf (danach faellt sie automatisch auf lokal/0&nbsp;€).
      <b class="ok">Vertrauen</b> = wie autonom sie handeln darf. <b class="ok">Audit</b> = Protokoll ihrer Aussen-Aktionen.</div></div>
    <div class="card"><h3>Budget (Treasury)</h3><div id="g-budget" class="muted">…</div>
      <div class="row" style="margin-top:10px">
        <input id="g-day" type="number" step="0.5" placeholder="Tag €" style="max-width:120px"/>
        <input id="g-month" type="number" step="1" placeholder="Monat €" style="max-width:120px"/>
        <button id="g-budget-save">Speichern</button>
        <span class="muted" id="g-budget-hint" style="align-self:center"></span>
      </div></div>
    <div class="card"><h3>Vertrauen (Trust-Level)</h3><div id="g-trust" class="muted">…</div>
      <div class="row" style="margin-top:10px">
        <select id="g-trust-sel">
          <option value="0">0 — alles vorlegen</option>
          <option value="1">1 — Reversibles autonom</option>
          <option value="2">2 — meiste autonom, Geld/Posts vorlegen</option>
          <option value="3">3 — voll-autonom (nur Budget begrenzt)</option>
        </select>
        <button id="g-trust-save">Speichern</button>
        <span class="muted" id="g-trust-hint" style="align-self:center"></span>
      </div></div>
    <div class="card"><h3>Audit — protokollierte Aussen-Aktionen</h3><div id="g-audit" class="muted">…</div></div>
    <div class="card"><h3>💶 Kosten-Aufschluesselung (heute · 7 Tage)</h3><div id="g-costs" class="muted">…</div></div>
  </div>

  <div class="view" id="v-cron">
    <div class="card"><h3>Geplante Aufgaben (Cron)</h3>
      <div class="muted">Meine wiederkehrenden Aufgaben. Zeitplan: <b>30m</b>/<b>2h</b> (Intervall) oder <b>08:00</b> (taeglich) · zum Aendern auf <b>bearbeiten</b> beim Job klicken. Laufen, sobald der Runner aktiv ist.</div>
      <div class="row" style="margin-top:8px">
        <input id="cr-label" placeholder="Name" style="max-width:150px"/>
        <input id="cr-prompt" placeholder="Was Kira jeweils tun soll" style="min-width:260px"/>
        <input id="cr-sched" placeholder="z.B. 08:00 oder 2h" style="max-width:130px"/>
        <button id="cr-add">+ Planen</button>
      </div>
      <div class="muted" id="cr-hint" style="margin-top:6px"></div>
    </div>
    <div class="card"><h3>Aktive Jobs</h3><div id="cr-list" class="muted">…</div></div>
  </div>

  <div class="view" id="v-monitor">
    <div class="card"><h3>Web-/News-Monitor (rein lesend)</h3>
      <div class="muted">Ich ueberwache Feeds &amp; Themen, fasse Neues zusammen und melde dir's per Telegram. Nur Lesen — sicher.</div>
      <div class="row" style="margin-top:8px">
        <select id="mo-kind"><option value="feed">RSS-Feed</option><option value="search">Web-Thema</option></select>
        <input id="mo-value" placeholder="RSS-URL  oder  Suchbegriff" style="min-width:240px"/>
        <input id="mo-label" placeholder="Label (optional)" style="max-width:150px"/>
        <button id="mo-add">+ Beobachten</button>
        <button class="ghost" id="mo-check">Jetzt pruefen</button>
      </div>
      <div class="muted" id="mo-hint" style="margin-top:6px"></div>
    </div>
    <div class="card"><h3>Beobachtungen</h3><div id="mo-list" class="muted">…</div></div>
    <div class="card"><h3>Zuletzt gemeldet</h3><div id="mo-recent" class="muted">…</div></div>
  </div>

  <div class="view" id="v-keys">
    <div class="card"><h3>Von Kira angefordert</h3><div id="k-pending" class="muted">…</div></div>
    <div class="card"><h3>Zugang eintragen / aktualisieren</h3>
      <div class="muted">Werte sind write-only — werden nie angezeigt oder protokolliert. NIEMALS im Chat eingeben.</div>
      <div class="row"><input id="k-name" placeholder="Name, z.B. OPENROUTER_API_KEY"/>
        <input id="k-val" type="password" placeholder="Wert / Key / Passwort"/>
        <button id="k-save">Speichern</button></div>
      <div id="k-sugg" class="muted" style="margin-top:8px"></div></div>
    <div class="card"><h3>Vorhandene Zugaenge</h3><div id="k-set"></div></div>
  </div>

  <div class="view" id="v-mem">
    <div class="card"><h3>Erinnerung hinzufuegen</h3>
      <div class="muted">Gib mir gezielt Wissen mit (semantisch = dauerhaftes Faktenwissen).</div>
      <textarea id="mem-new" class="k" style="margin-top:8px" placeholder="z.B. Sergen bevorzugt kurze, direkte Antworten."></textarea>
      <div class="row" style="margin-top:8px"><button id="mem-add">+ Merken</button><span class="muted" id="mem-hint" style="align-self:center"></span></div>
    </div>
    <div class="muted" style="margin:6px 0 8px;max-width:980px">Was Kira sich merkt — 🧠 = sie selbst, 👤 = du. ✎ bearbeiten, ✕ loeschen. (Verfassung/Seele/Ziel sind Dateien und bleiben unberuehrt.)</div>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 0 12px;max-width:980px">
      <span class="seg" id="mem-filter"><a data-mf="all" class="on">alle</a><a data-mf="partner">🧠 Kira</a><a data-mf="user">👤 Du</a><a data-mf="fact">facts</a><a data-mf="lesson">lessons</a><a data-mf="skill">skills</a></span>
      <input id="mem-search" placeholder="🔍 suchen…" style="flex:1;min-width:150px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);outline:none"/>
    </div>
    <div id="memlist" style="max-width:980px"></div>
    <div class="panel" style="margin-top:16px;max-width:980px"><div class="panel-h">◈ Verlauf · Aenderungen (vorher → nachher)</div><div id="memhist" class="panel-b"><span class="muted">…</span></div></div>
  </div>

  <div class="view" id="v-log">
    <div id="log-filters" style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap">
      <a href="#" data-f="all" class="pill on">Alles</a>
      <a href="#" data-f="error" class="pill">⚠ Fehler</a>
      <a href="#" data-f="action" class="pill">⚡ Aktionen</a>
      <a href="#" data-f="chat" class="pill">💬 Chat</a>
    </div>
    <div id="evlog"></div>
    <div style="text-align:center;margin-top:12px"><button class="ghost" id="log-more">mehr laden ↓</button></div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
/* Kiras Denk-Sprueche (eine Quelle, beim Ausliefern injiziert) */
const PHRASES=[/*__PHRASES__*/];
let _lastPhrase="";
function rndPhrase(){if(PHRASES.length<2)return PHRASES[0]||"ich denke kurz nach";
 let p=PHRASES[Math.floor(Math.random()*PHRASES.length)],g=0;
 while(p===_lastPhrase&&g++<8)p=PHRASES[Math.floor(Math.random()*PHRASES.length)];
 _lastPhrase=p;return p;}
let cur="home";
$$("#side a").forEach(a=>a.onclick=()=>nav(a.dataset.v));
function nav(v){cur=v;$$("#side a").forEach(a=>a.classList.toggle("on",a.dataset.v===v));
 $$(".view").forEach(x=>x.classList.remove("on"));$("#v-"+v).classList.add("on");
 if(v==="home")loadCommand(); if(v==="mission")loadMission(); if(v==="chat"){loadChatModels();loadChatSessions();} if(v==="files")loadFiles(); if(v==="models")loadModels(); if(v==="gov")loadGov(); if(v==="monitor")loadMonitor(); if(v==="cron")loadCron(); if(v==="keys")loadKeys(); if(v==="mem")loadMem(); if(v==="log")loadEvents();}

/* ---- Modell-Umschalter in der Chat-Pane ---- */
async function loadChatModels(){const s=await (await fetch("/api/status")).json();
 const sel=$("#chat-model"); if(!sel) return;
 const opts=[]; const seen={};
 const add=(id,lbl)=>{ if(id && !seen[id]){ seen[id]=1; opts.push('<option value="'+id+'"'+(id===s.model?' selected':'')+'>'+lbl+'</option>'); } };
 add(s.model, s.model.split("/").pop()+" (aktiv)");
 (s.ollama_local||[]).forEach(n=>{const low=n.toLowerCase();
   if(low.includes("embed")||low.includes("hf.co")||low.includes("gguf")) return;  // Embedding/roher GGUF-Name raus
   add("ollama_chat/"+n.replace(/:latest$/,""), n.replace(/:latest$/,"")+" (lokal, 0€)");});
 if(s.api_keys&&s.api_keys.openrouter){ add("openrouter/z-ai/glm-5.2","GLM 5.2 (Cloud, stark)"); }
 sel.innerHTML=opts.join("");}
$("#chat-model")&&($("#chat-model").onchange=async(e)=>{const id=e.target.value;
 await fetch("/api/model/use",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id})});
 refreshStatus();});

/* ---- Hintergrundbild hochladen ---- */
$("#bgfile")&&($("#bgfile").onchange=(e)=>{const f=e.target.files[0];if(!f)return;
 const rd=new FileReader();rd.onload=async()=>{await fetch("/api/bg/upload",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dataurl:rd.result})});
  document.body.style.backgroundImage="linear-gradient(rgba(10,7,16,.80),rgba(10,7,16,.93)),url('/api/bg?t="+Date.now()+"')";};
 rd.readAsDataURL(f);});

/* ---- Monitor ---- */
async function loadMonitor(){const m=await (await fetch("/api/monitor")).json();
 $("#mo-list").innerHTML=m.watches.length?m.watches.map(w=>'<div style="padding:6px 0;border-bottom:1px solid var(--line)"><b>'+(w.label||"").replace(/</g,"&lt;")+'</b> <small class=muted>['+w.kind+']</small> <a href="#" data-rm="'+w.id+'" style="float:right;color:var(--warn)">entfernen</a><br><small class=muted>'+(w.value||"").replace(/</g,"&lt;")+'</small></div>').join(""):'<span class=muted>(noch keine — oben hinzufuegen)</span>';
 document.querySelectorAll('#mo-list a[data-rm]').forEach(a=>a.onclick=async(e)=>{e.preventDefault();await fetch("/api/monitor/remove",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.rm})});loadMonitor();});
 $("#mo-recent").innerHTML=m.recent.length?m.recent.map(r=>{const ts=new Date(r.ts*1000).toLocaleString();return '<div style="padding:6px 0;border-bottom:1px solid var(--line)"><small class=muted>'+ts+'</small> <b>'+(r.label||"")+'</b> ('+r.count+' neu)<br>'+(r.summary||"").slice(0,320).replace(/</g,"&lt;").replace(/\\n/g,"<br>")+'</div>';}).join(""):'<span class=muted>(noch nichts gemeldet)</span>';}
$("#mo-add").onclick=async()=>{const v=$("#mo-value").value.trim();if(!v)return;await fetch("/api/monitor/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:$("#mo-kind").value,value:v,label:$("#mo-label").value})});$("#mo-value").value="";$("#mo-label").value="";loadMonitor();};
$("#mo-check").onclick=async()=>{$("#mo-hint").textContent="… prueft alle Beobachtungen (kann etwas dauern) …";const r=await (await fetch("/api/monitor/check",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();$("#mo-hint").textContent="Geprueft: "+r.checked+" Quelle(n) · Neu gemeldet: "+(r.digests?r.digests.length:0);loadMonitor();};

/* ---- Cron / geplante Aufgaben ---- */
let cronJobs=[], cronEdit=null;
async function loadCron(){const d=await (await fetch("/api/cron")).json();cronJobs=d.jobs;const fmt=ts=>ts?new Date(ts*1000).toLocaleString():"—";
 $("#cr-list").innerHTML=d.jobs.length?d.jobs.map(j=>{const last=(j.recent_runs&&j.recent_runs.length)?j.recent_runs[j.recent_runs.length-1]:null;
   return '<div style="padding:8px 0;border-bottom:1px solid var(--line)"><b>'+(j.label||"").replace(/</g,"&lt;")+'</b> <small class=muted>'+(j.schedule_text||"")+' · '+(j.enabled?"an":"aus")+' · naechster: '+fmt(j.next_run)+'</small>'
     +'<span style="float:right"><a href="#" data-run="'+j.id+'">jetzt</a> · <a href="#" data-edit="'+j.id+'">bearbeiten</a> · <a href="#" data-tog="'+j.id+'">'+(j.enabled?"pausieren":"aktivieren")+'</a> · <a href="#" data-rm="'+j.id+'" style="color:var(--warn)">entfernen</a></span>'
     +'<br><small class=muted>'+(j.prompt||"").slice(0,120).replace(/</g,"&lt;")+'</small>'
     +(last?('<br><small class=muted>letzter Lauf '+fmt(last.ts)+': '+(last.ok?"✓":"✗")+' '+(last.summary||"").slice(0,140).replace(/</g,"&lt;")+'</small>'):'')+'</div>';}).join(""):'<span class=muted>(keine geplanten Aufgaben)</span>';
 document.querySelectorAll('#cr-list a[data-rm]').forEach(a=>a.onclick=async e=>{e.preventDefault();await fetch("/api/cron/remove",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.rm})});loadCron();});
 document.querySelectorAll('#cr-list a[data-tog]').forEach(a=>a.onclick=async e=>{e.preventDefault();await fetch("/api/cron/toggle",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.tog})});loadCron();});
 document.querySelectorAll('#cr-list a[data-run]').forEach(a=>a.onclick=async e=>{e.preventDefault();$("#cr-hint").textContent="… Job laeuft …";await fetch("/api/cron/runnow",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.run})});$("#cr-hint").textContent="Lauf fertig.";loadCron();});
 document.querySelectorAll('#cr-list a[data-edit]').forEach(a=>a.onclick=e=>{e.preventDefault();startEditCron(a.dataset.edit);});}
function startEditCron(id){const j=cronJobs.find(x=>x.id===id);if(!j)return;
 $("#cr-label").value=j.label||"";$("#cr-prompt").value=j.prompt||"";$("#cr-sched").value=j.schedule_text||"";
 cronEdit=id;$("#cr-add").textContent="✓ Speichern";$("#cr-hint").innerHTML='Bearbeite: <b>'+(j.label||"").replace(/</g,"&lt;")+'</b> — <a href="#" id="cr-cancel">abbrechen</a>';
 $("#cr-cancel").onclick=e=>{e.preventDefault();cancelEditCron();};}
function cancelEditCron(){cronEdit=null;$("#cr-label").value="";$("#cr-prompt").value="";$("#cr-sched").value="";$("#cr-add").textContent="+ Planen";$("#cr-hint").textContent="";}
$("#cr-add").onclick=async()=>{const p=$("#cr-prompt").value.trim();if(!p)return;
 const body={label:$("#cr-label").value,prompt:p,schedule:$("#cr-sched").value||"60m"};
 if(cronEdit){body.id=cronEdit;await fetch("/api/cron/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
 else{await fetch("/api/cron/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
 cancelEditCron();loadCron();};

/* ---- Uebersicht ---- */
async function loadHome(){const o=await (await fetch("/api/overview")).json();const b=o.budget;
 const sv=await (await fetch("/api/services")).json();
 try{const dz=await (await fetch("/api/direktive")).json();const dh=$("#dir-hint");if(dh&&dz.focus)dh.textContent="🧭 Aktueller Fokus: "+dz.focus.slice(0,140);}catch(e){}
 const card=(t,c)=>'<div class="card"><h3>'+t+'</h3>'+c+'</div>';
 const kill=o.kill_switch?'<b style="color:var(--danger)">⛔ NOT-AUS aktiv</b>':'<span style="color:var(--ok)">einsatzbereit</span>';
 let h='<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px"><span class="dot"></span>'
  +'<h2 style="margin:0">'+o.partner+'</h2><span class=muted>'+kill+'</span></div>'
  +'<div style="display:flex;flex-direction:column;gap:10px">';
 const sdot=(ok)=>'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;vertical-align:middle;background:'+(ok?'var(--ok)':'var(--danger)')+';margin-right:5px"></span>';
 const svc=sv.services||{};
 h+=card("System",sdot(sv.supervisor)+'Supervisor '+sdot(svc.cockpit!==false)+'Cockpit '+sdot(svc.bot)+'Bot '+sdot(svc.runner)+'Runner '+sdot(sv.ollama)+'Ollama'
   +'<div style="margin-top:10px;display:flex;gap:8px"><button class=ghost id="sys-restart">↻ Neustart</button></div>');
 h+=card("Modell &amp; Budget","Modell: <b>"+o.model+"</b><br><span class=muted>Heute "+b.day_spent+" / "+(b.day_limit??"-")
   +" € · Monat "+b.month_spent+" / "+(b.month_limit??"-")+" €</span>");
 h+=card("Vertrauen","Stufe <b>"+o.trust.level+"</b><br><span class=muted>"+o.trust.label+"</span>");
 h+=card("Werkzeuge ("+o.tools.length+")", o.tools.map(t=>'<span class="pill">'+t+'</span>').join(" "));
 h+=card("Letzte Lektionen", o.lessons.length?('<ul style="margin:0;padding-left:18px">'
   +o.lessons.map(l=>'<li>'+l.slice(0,140).replace(/</g,"&lt;")+'</li>').join("")+'</ul>'):'<span class=muted>(noch keine)</span>');
 h+=card("Schnellzugriff",'<button class=ghost onclick="nav(\\'chat\\')">Chat</button> '
   +'<button class=ghost onclick="nav(\\'models\\')">Modelle</button> '
   +'<button class=ghost onclick="nav(\\'gov\\')">Gewissen</button>');
 h+='</div>';$("#home").innerHTML=h;
 const rb=$("#sys-restart"); if(rb) rb.onclick=async()=>{if(!confirm("Kira neu starten? Dienste bouncen in ~20s."))return;await fetch("/api/restart",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});rb.textContent="↻ Neustart angefordert …";};}

/* ---- Kommandozentrale (HUD) ---- */
let opsFilter="all";
async function loadHud(){const el=$("#hud-strip");if(!el)return;
 try{const o=await (await fetch("/api/overview")).json();const st=await (await fetch("/api/status")).json();
  const b=o.budget||{};const ec=st.events||{};
  const errs=(ec.turn_timeout||0)+(ec.llm_call_timeout||0)+(ec.service_crash||0)+(ec.act_degraded||0);
  const dayPct=b.day_limit?Math.min(100,Math.round(100*(b.day_spent||0)/b.day_limit)):0;
  const warn=dayPct>=85?" warn":"";
  const kill=o.kill_switch?'<span style="color:var(--danger)">⛔ NOT-AUS</span>':'<span style="color:var(--ok)">● bereit</span>';
  const model=(""+(o.model||"")).split("/").pop();
  el.innerHTML='<div class="hud-cell"><span class="k">Status</span><span class="val">'+kill+'</span></div>'
   +'<div class="hud-cell"><span class="k">Hirn</span><span class="val">'+model+'</span></div>'
   +'<div class="hud-cell"><span class="k">Budget heute</span><span class="val">'+(b.day_spent||0)+' / '+(b.day_limit==null?"-":b.day_limit)+' €</span><div class="mini-bar'+warn+'"><i style="width:'+dayPct+'%"></i></div></div>'
   +'<div class="hud-cell"><span class="k">Monat</span><span class="val">'+(b.month_spent||0)+' / '+(b.month_limit==null?"-":b.month_limit)+' €</span></div>'
   +'<div class="hud-cell"><span class="k">Vertrauen</span><span class="val">Stufe '+((o.trust||{}).level==null?"-":o.trust.level)+'</span></div>'
   +'<div class="hud-cell"><span class="k">Fehler-Signale</span><span class="val" style="color:'+(errs?"var(--warn)":"var(--ok)")+'">'+errs+'</span></div>'
   +'<div class="hud-cell spacer"></div>'
   +'<div class="hud-cell"><span class="k">Aktion</span><span class="val"><a id="hud-restart" style="cursor:pointer;color:var(--hud)">↻ Neustart</a></span></div>';
  const rb=$("#hud-restart");if(rb)rb.onclick=async()=>{if(!confirm("Kira neu starten? Dienste bouncen in ~20s."))return;await fetch("/api/restart",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});rb.textContent="↻ …";};
 }catch(e){}}
async function loadOps(){const el=$("#ops-feed");if(!el)return;
 try{const es=await (await fetch("/api/events?limit=70")).json();
  const keep=es.filter(e=>opsFilter==="all"||(e.sev||"info")===opsFilter);
  el.innerHTML=keep.length?keep.map(e=>{const t=new Date(e.ts*1000).toLocaleTimeString();
   return '<div class="op '+(e.sev||"info")+'"><span class="od"></span><span class="opt">'+t+'</span><span class="opx">'+pulsePhrase(e).replace(/</g,"&lt;")+'</span></div>';}).join(""):'<span class="muted" style="padding:10px 13px;display:block">(ruhig — keine Aktivitaet)</span>';
 }catch(e){}}
async function loadNews(){const tk=$("#news-ticker"),ls=$("#news-list");if(!ls)return;
 try{const d=await (await fetch("/api/news")).json();const it=d.items||[];
  if(!it.length){if(tk)tk.innerHTML='<span>… Feeds nicht erreichbar …</span>';ls.innerHTML='<span class="muted">Keine News geladen.</span>';return;}
  const head=it.map(x=>'▟ '+x.source+': '+x.title).join('    ◆    ').replace(/</g,"&lt;");
  if(tk)tk.innerHTML='<span>'+head+'    ◆    '+head+'</span>';
  ls.innerHTML=it.slice(0,10).map(x=>{const t=(""+x.title).replace(/</g,"&lt;");const s=(""+x.source).replace(/</g,"&lt;");
   return '<div class="news-item"><small>'+s+'</small> '+(x.link?'<a href="'+x.link+'" target="_blank" rel="noopener" style="color:var(--ink);text-decoration:none">'+t+'</a>':'<b>'+t+'</b>')+'</div>';}).join("");
 }catch(e){}}
const DEFAULT_FEEDS=[{kind:"feed",value:"https://hnrss.org/frontpage",label:"Hacker News"},
 {kind:"feed",value:"https://www.theverge.com/rss/index.xml",label:"The Verge"},
 {kind:"search",value:"KI Modell Release news",label:"KI-Releases"},
 {kind:"search",value:"AI agents open source",label:"Agents"}];
function bindNewsSeed(){const s=$("#news-seed");if(!s)return;s.onclick=async()=>{s.textContent="… fuege hinzu";
  for(const f of DEFAULT_FEEDS){try{await fetch("/api/monitor/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(f)});}catch(e){}}
  s.textContent="✓ hinzugefuegt";loadNews();};}
function bindOpsFilter(){$$("#ops-filter a").forEach(a=>a.onclick=()=>{opsFilter=a.dataset.of;$$("#ops-filter a").forEach(x=>x.classList.toggle("on",x===a));loadOps();});}
function loadCommand(){loadHud();loadOps();loadNews();loadHome();bindNewsSeed();bindOpsFilter();}

/* ---- Mission-Workspace (Ziele + To-Do-Board) ---- */
const KIND_LABEL={big:"BIG",monthly:"MONAT",weekly:"WOCHE"};
let missionObjs=[];
async function loadMission(){
 const d=await (await fetch("/api/mission/board")).json();
 missionObjs=d.objectives||[];
 const ol=$("#obj-list");
 if(!missionObjs.length){ol.innerHTML='<div class="emptybox">▸ Noch keine Ziele<br>Oben „+ ZIEL" klicken</div>';}
 else ol.innerHTML=missionObjs.map(o=>{
   const due=o.target_date?('⏰ '+o.target_date):'';
   return '<div class="memrow"><div class="mh"><span class="badge kind">'+(KIND_LABEL[o.kind]||o.kind)+'</span>'
    +'<b style="color:var(--ink)">'+(o.title||"").replace(/</g,"&lt;")+'</b>'
    +'<span style="flex:1"></span><span class="muted">'+o.progress+'% · '+o.tasks_done+'/'+o.tasks_total+' '+due+'</span> '
    +'<a data-plan="'+o.id+'" title="in To-Dos zerlegen" style="cursor:pointer;color:var(--hud)">⚙ zerlegen</a> '
    +'<a data-odel="'+o.id+'" title="loeschen" style="cursor:pointer;color:var(--muted)">✕</a></div>'
    +'<div class="mini-bar" style="min-width:140px"><i style="width:'+(o.progress||0)+'%"></i></div>'
    +'<div class="row" style="margin-top:6px;align-items:center"><input type="range" min="0" max="100" value="'+(o.progress||0)+'" data-oprog="'+o.id+'" style="flex:1"><span class="muted" style="font-size:11px;margin-left:8px">Fortschritt</span></div></div>';
 }).join("");
 const sel=$("#todo-obj");if(sel)sel.innerHTML='<option value="">— keins —</option>'+missionObjs.map(o=>'<option value="'+o.id+'">'+(o.title||"").replace(/</g,"&lt;").slice(0,40)+'</option>').join("");
 renderBoard(d.board||{});
 bindMissionForms();
 loadInbox();loadDigest();
 $$('#obj-list [data-plan]').forEach(a=>a.onclick=async()=>{a.textContent="⚙ zerlege…";await fetch("/api/objectives/plan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.plan})});loadMission();});
 $$('#obj-list [data-odel]').forEach(a=>a.onclick=async()=>{if(!confirm("Ziel loeschen? (To-Dos bleiben, werden entkoppelt)"))return;await fetch("/api/objectives/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.odel})});loadMission();});
 $$('#obj-list [data-oprog]').forEach(r=>r.onchange=async()=>{await fetch("/api/objectives/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:r.dataset.oprog,progress:r.value})});loadMission();});
}
const BOARD_GROUPS=[["running","▶ laeuft"],["today","⏰ heute / ueberfaellig"],["week","diese Woche"],["later","spaeter"],["deferred","aufgeschoben"],["done","erledigt"]];
function taskRow(t){
 const objT=(missionObjs.find(o=>o.id===t.objective_id)||{}).title;
 const due=t.due_date?('⏰'+t.due_date):'';
 const p='P'+(t.priority||3);
 let act="";
 if(t.status==="pending")act='<a data-done="'+t.id+'" title="erledigt" style="cursor:pointer;color:var(--ok)">✓</a> '
   +'<a data-defer="'+t.id+'" title="+7 Tage aufschieben" style="cursor:pointer;color:var(--muted)">⏭</a> '
   +'<a data-tdel="'+t.id+'" title="loeschen" style="cursor:pointer;color:var(--muted)">✕</a>';
 return '<div class="op" style="border-radius:8px;margin-bottom:3px"><span class="od"></span>'
  +'<span class="opx"><b>'+p+'</b> '+(t.description||"").replace(/</g,"&lt;").slice(0,150)
  +' <span class="muted">'+due+(objT?(' · '+objT.replace(/</g,"&lt;").slice(0,24)):"")+'</span></span>'+act+'</div>';
}
function renderBoard(b){
 const el=$("#todo-board");let h="";
 BOARD_GROUPS.forEach(([k,label])=>{const arr=b[k]||[];if(!arr.length)return;
  h+='<div style="margin:9px 0 4px;font-size:11px;letter-spacing:1px;color:var(--hud);text-transform:uppercase">'+label+' ('+arr.length+')</div>'+arr.map(taskRow).join("");});
 el.innerHTML=h||'<div class="emptybox">Keine Aufgaben<br>„+ TO-DO" — oder ein Ziel „zerlegen"</div>';
 $$('#todo-board [data-done]').forEach(a=>a.onclick=async()=>{await fetch("/api/mission/task/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.done,status:"done"})});loadMission();});
 $$('#todo-board [data-defer]').forEach(a=>a.onclick=async()=>{const d=new Date();d.setDate(d.getDate()+7);await fetch("/api/mission/task/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.defer,deferred_until:d.toISOString().slice(0,10)})});loadMission();});
 $$('#todo-board [data-tdel]').forEach(a=>a.onclick=async()=>{await fetch("/api/mission/queue/remove",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.tdel})});loadMission();});
}
function bindMissionForms(){
 const tog=id=>{const f=$(id);if(f)f.style.display=(getComputedStyle(f).display==="none")?"block":"none";};
 $("#obj-new-btn")&&($("#obj-new-btn").onclick=e=>{e.preventDefault();tog("#obj-form");});
 $("#todo-new-btn")&&($("#todo-new-btn").onclick=e=>{e.preventDefault();tog("#todo-form");});
 $("#obj-add")&&($("#obj-add").onclick=async()=>{const t=$("#obj-title").value.trim();if(!t)return;
   await fetch("/api/objectives",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:t,kind:$("#obj-kind").value,target_date:$("#obj-date").value||null})});
   $("#obj-title").value="";loadMission();});
 $("#todo-add")&&($("#todo-add").onclick=async()=>{const t=$("#todo-desc").value.trim();if(!t)return;
   await fetch("/api/mission/queue/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({description:t,priority:$("#todo-prio").value,due_date:$("#todo-due").value||null,objective_id:$("#todo-obj").value||null})});
   $("#todo-desc").value="";loadMission();});
}
async function loadInbox(){const el=$("#inbox-list");if(!el)return;
 try{const d=await (await fetch("/api/approvals")).json();const p=d.pending||[];
  const cnt=$("#inbox-count");if(cnt)cnt.textContent=p.length?(p.length+" warten"):"leer";
  if(!p.length){el.innerHTML='<span class="muted">Nichts wartet auf Freigabe. Kira legt hier Aussen-Aktionen/Entwuerfe zum GO ab.</span>';return;}
  el.innerHTML=p.map(a=>{const ts=new Date(a.ts*1000).toLocaleString();
   const kb={publish:"📮",email:"✉️",external:"🌐",evolution:"🧬",generic:"📝"}[a.kind]||"📝";
   const det=(""+(a.detail||"")).replace(/</g,"&lt;").slice(0,500);
   return '<div class="memrow"><div class="mh"><span class="badge kind">'+kb+' '+a.kind+'</span><b style="color:var(--ink)">'+(""+(a.title||"")).replace(/</g,"&lt;")+'</b><span style="flex:1"></span><span class="muted">'+ts+'</span></div>'
    +(det?'<div style="white-space:pre-wrap;font-size:12px;color:var(--muted);max-height:130px;overflow:auto;border-left:2px solid var(--line);padding-left:8px;margin:4px 0">'+det+'</div>':'')
    +'<div class="row" style="margin-top:6px"><button data-appr="'+a.id+'">✓ Freigeben</button><button class="ghost" data-rej="'+a.id+'">✕ Verwerfen</button></div></div>';
  }).join("");
  $$('#inbox-list [data-appr]').forEach(b=>b.onclick=async()=>{b.textContent="…";await fetch("/api/approvals/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:b.dataset.appr,approved:true})});loadInbox();loadDigest();});
  $$('#inbox-list [data-rej]').forEach(b=>b.onclick=async()=>{if(!confirm("Wirklich verwerfen?"))return;await fetch("/api/approvals/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:b.dataset.rej,approved:false})});loadInbox();loadDigest();});
 }catch(e){}}
async function loadDigest(){const el=$("#digest");if(!el)return;
 try{const d=await (await fetch("/api/digest")).json();const b=d.budget||{};
  let h='<div class="muted" style="font-size:11px;letter-spacing:1px">'+d.date+'</div>';
  h+='<div style="margin:6px 0"><b>'+d.tasks_done_count+'</b> Aufgaben erledigt · <b>'+d.planned+'</b> geplant · <b>'+d.news+'</b> News</div>';
  if(d.tasks_done&&d.tasks_done.length)h+='<ul style="margin:4px 0;padding-left:16px;font-size:12px">'+d.tasks_done.map(t=>'<li>'+(""+t).replace(/</g,"&lt;")+'</li>').join("")+'</ul>';
  h+='<div style="margin-top:6px;font-size:12px">Freigaben offen: <b style="color:'+(d.pending_approvals?"var(--warn)":"var(--ok)")+'">'+d.pending_approvals+'</b> · Fehler heute: <b style="color:'+(d.errors?"var(--danger)":"var(--ok)")+'">'+d.errors+'</b></div>';
  h+='<div style="margin-top:4px;font-size:12px" class="muted">Kosten heute: '+d.spend_usd+' € · Budget '+(b.day_spent||0)+'/'+(b.day_limit==null?"-":b.day_limit)+' €</div>';
  el.innerHTML=h;
 }catch(e){}}

async function refreshStatus(){const s=await (await fetch("/api/status")).json();
 $("#who").textContent=s.partner.toLowerCase()+" · cockpit";
 $("#b-model").textContent=s.model;
 $("#b-spend").textContent="$"+s.spend_usd_today+((s.budget&&s.budget.day_limit!=null)?(" / "+s.budget.day_limit+"€"):"");
 const k=$("#kill"); k.classList.toggle("active",s.kill_switch);
 k.textContent="Not-Aus: "+(s.kill_switch?"AKTIV":"aus");
 $("#b-kill").innerHTML=s.kill_switch?'<b style="color:var(--danger)">⛔ NOT-AUS</b>':'';
 return s;}
$("#kill").onclick=async()=>{const on=!$("#kill").classList.contains("active");
 await fetch("/api/kill",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on})});refreshStatus();};

/* ---- Chat ---- */
const log=$("#log");
function add(t,c){const d=document.createElement("div");d.className="msg "+c;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
/* Shimmernder Denk-Indikator: rotierender Spruch, solange Kira arbeitet */
let thinkTimer=null,thinkEl=null;
function startThinking(){stopThinking();thinkEl=document.createElement("div");thinkEl.className="thinking";
 thinkEl.innerHTML='<span class="sh">✦</span><span class="tx"></span>';
 const setp=()=>{const t=thinkEl&&thinkEl.querySelector(".tx");if(t)t.textContent=rndPhrase()+"…";};
 setp();log.appendChild(thinkEl);log.scrollTop=log.scrollHeight;
 thinkTimer=setInterval(setp,3500);}
function stopThinking(){if(thinkTimer){clearInterval(thinkTimer);thinkTimer=null;}
 if(thinkEl){thinkEl.remove();thinkEl=null;}}
const proto=location.protocol==="https:"?"wss":"ws";
let ws,curBot,curThink,thinkBuf,curSid=null,wsIntentional=false;
function connect(){wsIntentional=false;const url=proto+"://"+location.host+"/ws/chat"+(curSid?("?sid="+encodeURIComponent(curSid)):"");ws=new WebSocket(url);
 function ensureTrace(){if(!curThink){thinkBuf="";curThink=document.createElement("div");curThink.className="think show";
    curThink.innerHTML='<span class="h">💭 Denken &amp; Aktionen (klick zum Ein-/Ausklappen)</span><div class="c"></div>';
    curThink.querySelector(".h").onclick=()=>curThink.classList.toggle("show");log.appendChild(curThink);}return curThink;}
 function traceSet(){curThink.querySelector(".c").textContent=thinkBuf;log.scrollTop=log.scrollHeight;}
 ws.onmessage=ev=>{const m=JSON.parse(ev.data);
  if(m.role==="system"){add(m.text,"sys");return;}
  if(m.done){stopThinking();curBot=null;curThink=null;loadChatSessions();return;}
  if(m.kind==="think"){ensureTrace();thinkBuf+=m.text;traceSet();return;}
  if(m.kind==="tool"){ensureTrace();thinkBuf+="\\n🔧 "+m.name+" "+JSON.stringify(m.args);traceSet();return;}
  if(m.kind==="obs"){ensureTrace();thinkBuf+="\\n   ✓ "+(m.text||"").slice(0,120);traceSet();return;}
  if(m.kind==="final"||m.kind==="answer"){stopThinking();const b=add("","bot");b.textContent=(m.text||"").replace(/\\*\\*/g,"");log.scrollTop=log.scrollHeight;}};
 ws.onclose=()=>{if(!wsIntentional)setTimeout(connect,1500);};}
function reconnect(){wsIntentional=true;if(ws){try{ws.close();}catch(e){}}connect();}
function relTime(ts){const s=Date.now()/1000-ts;if(s<90)return "gerade";if(s<3600)return Math.round(s/60)+" Min";if(s<86400)return Math.round(s/3600)+" Std";return Math.round(s/86400)+" Tg";}
async function loadChatSessions(){const sel=$("#sess-list");if(!sel)return;
 const d=await (await fetch("/api/chat/sessions")).json();const ss=d.sessions||[];
 sel.innerHTML=ss.map(s=>'<option value="'+s.session_id+'">'+(s.channel==="telegram"?"✈️ ":"💬 ")+((s.title||s.session_id).replace(/</g,"&lt;"))+' · vor '+relTime(s.last)+'</option>').join("");
 if(!curSid){if(ss.length){await openSession(ss[0].session_id);}else{newSession();}}
 else{sel.value=curSid;}}
async function openSession(sid){curSid=sid;log.innerHTML="";curBot=null;curThink=null;
 try{const h=await (await fetch("/api/chat/history?sid="+encodeURIComponent(sid))).json();
  (h.messages||[]).forEach(m=>add((m.text||"").replace(/\\*\\*/g,""),m.role==="user"?"me":"bot"));}catch(e){}
 const sel=$("#sess-list");if(sel)sel.value=sid;reconnect();}
function newSession(){curSid="cockpit-"+Math.random().toString(16).slice(2,10);log.innerHTML="";curBot=null;curThink=null;reconnect();}
async function deleteSession(){if(!curSid)return;if(!confirm("Diese Unterhaltung wirklich loeschen?"))return;
 await fetch("/api/chat/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sid:curSid})});
 curSid=null;log.innerHTML="";loadChatSessions();}
$("#sess-list")&&($("#sess-list").onchange=e=>openSession(e.target.value));
$("#sess-new")&&($("#sess-new").onclick=()=>newSession());
$("#sess-del")&&($("#sess-del").onclick=()=>deleteSession());
$("#cform").onsubmit=e=>{e.preventDefault();const raw=$("#cin").value.trim();if(!raw||!ws||ws.readyState!==1)return;
 add(raw,"me");startThinking();const t=($("#planmode")&&$("#planmode").checked?"plan: ":"")+raw;ws.send(t);$("#cin").value="";curBot=null;curThink=null;};

/* ---- Sprachmemo (Aufnahme -> Whisper -> Eingabefeld) ---- */
let mediaRec=null,chunks=[];
$("#micbtn")&&($("#micbtn").onclick=async()=>{
 if(mediaRec&&mediaRec.state==="recording"){mediaRec.stop();return;}
 try{const stream=await navigator.mediaDevices.getUserMedia({audio:true});chunks=[];mediaRec=new MediaRecorder(stream);
  mediaRec.ondataavailable=ev=>chunks.push(ev.data);
  mediaRec.onstop=async()=>{stream.getTracks().forEach(t=>t.stop());$("#micbtn").textContent="🎤";
   const blob=new Blob(chunks,{type:"audio/webm"});const rd=new FileReader();
   rd.onload=async()=>{$("#cin").value="… transkribiere …";
    const r=await (await fetch("/api/transcribe",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({audio:rd.result})})).json();
    $("#cin").value=r.ok?(r.text||""):("(Audio-Fehler: "+(r.error||"")+")");$("#cin").focus();};
   rd.readAsDataURL(blob);};
  mediaRec.start();$("#micbtn").textContent="⏹";
 }catch(err){add("Mikrofon nicht verfuegbar: "+err,"sys");}});

/* ---- Bild an Kira (Vision) ---- */
$("#imgfile")&&($("#imgfile").onchange=ev=>{const f=ev.target.files[0];if(!f)return;
 const rd=new FileReader();rd.onload=async()=>{
  const im=document.createElement("div");im.className="msg me";
  im.innerHTML='<img src="'+rd.result+'" style="max-width:240px;border-radius:8px;display:block"/>';log.appendChild(im);log.scrollTop=log.scrollHeight;
  const prompt=$("#cin").value.trim();$("#cin").value="";
  const b=add("… Kira betrachtet das Bild …","bot");
  try{const r=await (await fetch("/api/vision",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:prompt,image:rd.result})})).json();
   b.textContent=r.ok?(r.text||""):("(Bild-Fehler: "+(r.error||"")+")");}
  catch(err){b.textContent="(Bild-Fehler: "+err+")";}
  log.scrollTop=log.scrollHeight;};
 rd.readAsDataURL(f);ev.target.value="";});

/* ---- Files ---- */
let fcur=null;
async function loadFiles(){const fs=await (await fetch("/api/files")).json();const el=$("#flist");el.innerHTML="";
 fs.forEach(f=>{const d=document.createElement("div");d.className="f";
  d.innerHTML="<b>"+f.name+"</b><small>"+f.label+(f.editable?"":" · nur lesen")+"</small>";
  d.onclick=()=>openFile(f.name,d);el.appendChild(d);});}
async function openFile(name,el){$$(".flist .f").forEach(x=>x.classList.remove("on"));el.classList.add("on");
 const f=await (await fetch("/api/file?name="+encodeURIComponent(name))).json();fcur=f;
 $("#ftitle").textContent=f.label;$("#ftitle").className="";$("#farea").value=f.content;
 $("#farea").readOnly=!f.editable;$("#fsave").style.display=f.editable?"block":"none";}
$("#fsave").onclick=async()=>{if(!fcur)return;
 const r=await (await fetch("/api/file",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({name:fcur.name,content:$("#farea").value})})).json();
 $("#ftitle").textContent=fcur.label+(r.ok?" — gespeichert ✓":" — Fehler");};

/* ---- Models ---- */
function showLoaded(el,ld){if(ld&&ld.context){const col=(ld.gpu_pct!=null&&ld.gpu_pct>=99)?"var(--ok)":"var(--warn)";
   el.innerHTML="Geladen: <b>"+ld.context+"</b> Kontext · <b style='color:"+col+"'>"+(ld.gpu_pct!=null?ld.gpu_pct+"% GPU":"?")+"</b> · "+(ld.vram_gb||"?")+" GB VRAM"
    +((ld.gpu_pct!=null&&ld.gpu_pct<99)?" ⚠️ teilweise CPU — kleiner waehlen":"");}
  else{el.textContent="(Modell noch nicht geladen — wird beim ersten Chat geladen)";}}
async function loadModels(){const s=await (await fetch("/api/status")).json();
 $("#m-active").innerHTML="<b>"+s.model+"</b> &nbsp; <span class=muted>Eskalation: "+(s.escalation_model||"-")+"</span>";
 $("#m-ctx").value=s.num_ctx||""; $("#m-maxtok").value=s.max_tokens||"";
 if($("#s-temp")&&document.activeElement!==$("#s-temp"))$("#s-temp").value=s.temperature!=null?s.temperature:"";
 if($("#s-keep")&&document.activeElement!==$("#s-keep"))$("#s-keep").value=s.keep_alive||"";
 if($("#s-voice"))$("#s-voice").checked=!!s.voice;
 if($("#s-whisper")&&s.whisper)$("#s-whisper").value=s.whisper;
 fetch("/api/model/loaded").then(r=>r.json()).then(ld=>showLoaded($("#m-loaded"),ld));
 document.querySelectorAll('#v-models .pill[data-ctx]').forEach(p=>p.onclick=()=>{$("#m-ctx").value=p.dataset.ctx;});
 document.querySelectorAll('#v-models .pill[data-or]').forEach(p=>p.onclick=()=>{$("#m-or").value=p.dataset.or;});
 $("#m-paramgo").onclick=async()=>{const ctx=parseInt($("#m-ctx").value)||null;const mt=parseInt($("#m-maxtok").value)||null;
  $("#m-loaded").textContent="… lädt mit neuem Kontext (kann ~30 s dauern) …";
  const r=await (await fetch("/api/model/params",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({num_ctx:ctx,max_tokens:mt})})).json();
  showLoaded($("#m-loaded"),r.loaded||{});refreshStatus();};
 const ol=$("#m-ollama");ol.innerHTML="";(s.ollama_local||[]).forEach(m=>{const low=m.toLowerCase();
  if(low.includes("embed")||low.includes("hf.co")||low.includes("gguf"))return;  // kein Hirn / Alias nutzen
  const id="ollama_chat/"+m.replace(/:latest$/,"");const p=document.createElement("span");
  p.className="pill"+(id===s.model?" ok":"");p.textContent=m.replace(/:latest$/,"");
  p.onclick=()=>useModel(id);ol.appendChild(p);});
 if(!$("#m-ollama").children.length)ol.innerHTML='<span class=muted>(keine nutzbaren lokalen Modelle)</span>';
 loadCatalog();
 const ks=$("#m-keys");if(ks){ks.innerHTML="";Object.entries(s.api_keys).forEach(([k,v])=>{const p=document.createElement("span");
  p.className="pill "+(v?"ok":"no");p.textContent=k+(v?" ✓":" ✗");ks.appendChild(p);});}}
async function useModel(id){await fetch("/api/model/use",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({id})});loadModels();refreshStatus();}
/* ---- Modell-Katalog + Rollen ---- */
const ROLE_LABEL={chat:"💬 Chat",reason:"🧠 Reason/Coding",bulk:"⏰ Crons",escalation:"⚡ Eskalation",default:"★ Default"};
let MCAT={openrouter:[],local:[]};
function money(x){return (x==null||x===0)?"0€":("$"+(x*1e6).toFixed(2)+"/M");}
function renderRoles(roles){const el=$("#m-roles");if(!el)return;
 el.innerHTML=Object.keys(ROLE_LABEL).map(r=>'<div style="display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--line)"><span style="min-width:150px">'+ROLE_LABEL[r]+'</span><b style="flex:1;color:var(--accent)">'+((roles[r]||"—")+"").replace(/^openrouter\\//,"").replace(/</g,"&lt;")+'</b></div>').join("");}
function renderCat(){const el=$("#cat-list");if(!el)return;const q=(($("#cat-search")||{}).value||"").toLowerCase().trim();
 const all=(MCAT.local||[]).concat(MCAT.openrouter||[]);
 const hits=all.filter(m=>!q||(m.id||"").toLowerCase().includes(q)||(m.name||"").toLowerCase().includes(q)).slice(0,80);
 el.innerHTML=hits.length?hits.map(m=>'<div style="display:flex;gap:8px;align-items:center;padding:4px 2px;border-bottom:1px solid var(--line)">'
   +'<span style="flex:1"><b>'+(m.id||"").replace(/^openrouter\\//,"").replace(/</g,"&lt;")+'</b>'+(m.ctx?' <small class=muted>'+Math.round(m.ctx/1000)+'K</small>':'')+'</span>'
   +'<small class=muted style="min-width:120px">'+money(m.in)+' · '+money(m.out)+'</small>'
   +'<button class=ghost data-mid="'+m.id+'" style="padding:3px 9px">→ zuweisen</button></div>').join(""):'<span class=muted>(keine Treffer)</span>';
 el.querySelectorAll('button[data-mid]').forEach(b=>b.onclick=async()=>{const role=$("#cat-role").value;
   $("#cat-hint").textContent="… setze "+role+" …";
   await fetch("/api/model/role",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role,model:b.dataset.mid})});
   $("#cat-hint").innerHTML=ROLE_LABEL[role]+' → <b>'+b.dataset.mid.replace(/^openrouter\\//,"")+'</b> ✓';loadModels();refreshStatus();});}
async function loadCatalog(){try{const d=await (await fetch("/api/model/catalog")).json();MCAT=d.catalog||{openrouter:[],local:[]};renderRoles(d.roles||{});renderCat();}catch(e){}}
$("#cat-search")&&($("#cat-search").oninput=()=>renderCat());
$("#s-behav-save")&&($("#s-behav-save").onclick=async()=>{const tp=parseFloat($("#s-temp").value);
 if(!isNaN(tp))await cfgSet("models.temperature",tp);
 if($("#s-keep").value.trim())await cfgSet("models.keep_alive",$("#s-keep").value.trim());
 $("#s-sys-hint")&&($("#s-sys-hint").textContent="live gesetzt ✓");});
$("#s-sys-save")&&($("#s-sys-save").onclick=async()=>{await cfgSet("channels.telegram.voice",$("#s-voice").checked);
 await cfgSet("channels.telegram.whisper_model",$("#s-whisper").value);
 $("#s-sys-hint").innerHTML='gespeichert · <a href="#" onclick="doRestart(event)">Neustart</a>';});

/* ---- Protokoll / Puls: Live-Aktivitaet + Fehler ---- */
let logFilter="all", logOldest=null, logRaw=[], logOpen=new Set();
function renderLog(){const el=$("#evlog");
 const show=logRaw.filter(e=>logFilter==="all"||e.sev===logFilter);
 el.innerHTML=show.length?show.map(e=>{const t=new Date(e.ts*1000).toLocaleTimeString();const p=e.payload||{};
   const full=(p&&typeof p==="object")?(p.text||p.summary||p.error||p.desc||p.command||JSON.stringify(p)):String(p);
   const esc=(""+full).replace(/&/g,"&amp;").replace(/</g,"&lt;");
   const open=logOpen.has(e.id);
   return '<div class="e '+(e.sev||"info")+'"><span class="t">'+t+' · '+e.type+'</span><span class="m'+(open?'':' clamp')+'" data-id="'+e.id+'" title="klicken zum Auf-/Zuklappen">'+esc+'</span></div>';
  }).join(""):'<span class=muted>(nichts in diesem Filter)</span>';
 el.querySelectorAll('.e .m[data-id]').forEach(m=>m.onclick=()=>{const id=m.dataset.id;if(logOpen.has(id))logOpen.delete(id);else logOpen.add(id);m.classList.toggle('clamp');});}
async function loadEvents(reset=true){
 if(reset){logOldest=null;logRaw=[];}
 const url="/api/events?limit=100"+(logOldest?"&before="+logOldest:"");
 const es=await (await fetch(url)).json();
 if(es.length){logRaw=logRaw.concat(es);logOldest=es[es.length-1].ts;}
 renderLog();}
$$("#log-filters a").forEach(a=>a.onclick=e=>{e.preventDefault();logFilter=a.dataset.f;
 $$("#log-filters a").forEach(x=>x.classList.toggle("on",x===a));renderLog();});
$("#log-more")&&($("#log-more").onclick=()=>loadEvents(false));

/* ---- Gewissen ---- */
function bar(spent,limit){if(limit==null)return '<span class=muted>kein Limit</span>';
 const pct=Math.min(100,Math.round(spent/limit*100));const col=pct>90?'var(--danger)':pct>70?'var(--warn)':'var(--ok)';
 return '<div style="background:var(--panel2);border:1px solid var(--line);border-radius:6px;height:16px;overflow:hidden">'
  +'<div style="height:100%;width:'+pct+'%;background:'+col+'"></div></div>'
  +'<small class=muted>'+spent.toFixed(4)+' / '+limit+' € ('+pct+'%)</small>';}
async function cfgSet(path,value){return (await fetch("/api/config/set",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path,value})})).json();}
async function doRestart(e){if(e&&e.preventDefault)e.preventDefault();await fetch("/api/restart",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});alert("Neustart angefordert — Dienste bouncen in ~20s.");}
async function loadGov(){const g=await (await fetch("/api/governance")).json();const t=g.treasury;
 $("#g-budget").innerHTML="Heute:<br>"+bar(t.day_spent,t.day_limit)+"<br><br>Diesen Monat:<br>"+bar(t.month_spent,t.month_limit);
 if($("#g-day")&&document.activeElement!==$("#g-day"))$("#g-day").value=t.day_limit!=null?t.day_limit:"";
 if($("#g-month")&&document.activeElement!==$("#g-month"))$("#g-month").value=t.month_limit!=null?t.month_limit:"";
 $("#g-trust").innerHTML="Stufe <b>"+g.trust.level+"</b> — "+g.trust.label
  +'<br><span class=muted>Erfolge: '+g.trust.success+' · Fehlschlaege: '+g.trust.fail+'</span>'
  +'<br><span class=muted>Bei Stufe 3 begrenzt nur das Budget; Außen-Aktionen brauchen kein Go.</span>';
 if($("#g-trust-sel"))$("#g-trust-sel").value=String(g.trust.level);
 const a=$("#g-audit");a.innerHTML=g.audit.length?g.audit.map(e=>{const ts=new Date(e.ts*1000).toLocaleString();const p=e.payload;
   return '<div style="padding:6px 0;border-bottom:1px solid var(--line)"><b>'+p.action+'</b> '+(p.target||'')
    +' <small class=muted>'+ts+(p.reversible?' · rückrollbar':'')+'</small></div>';}).join(""):'<span class=muted>(noch keine Außen-Aktionen protokolliert)</span>';loadCosts();}
async function loadCosts(){const el=$("#g-costs");if(!el)return;
 try{const c=await (await fetch("/api/costs")).json();
  const line=m=>'<div style="display:flex;gap:10px;padding:3px 0;font-family:var(--mono);font-size:12px"><span style="flex:1">'+m.model.replace(/</g,"&lt;")+'</span><span class=muted>'+m.calls+' calls</span><span style="min-width:80px;text-align:right">$'+m.cost.toFixed(3)+'</span></div>';
  let h='<div style="margin-bottom:6px"><b>Heute: $'+c.today.total.toFixed(3)+'</b></div>'+(c.today.by_model.map(line).join("")||'<span class=muted>—</span>');
  if(c.today.top_sessions&&c.today.top_sessions.length)h+='<div class=muted style="margin-top:8px;font-size:11px">Top-Sessions heute: '+c.today.top_sessions.map(s=>(s.session||"?").replace(/</g,"&lt;").slice(0,20)+' $'+s.cost.toFixed(2)).join(" · ")+'</div>';
  h+='<div style="margin:10px 0 6px;border-top:1px solid var(--line);padding-top:8px"><b>7 Tage: $'+c.week.total.toFixed(2)+'</b></div>'+c.week.by_model.map(line).join("");
  el.innerHTML=h;
 }catch(e){}}
$("#g-budget-save")&&($("#g-budget-save").onclick=async()=>{const d=parseFloat($("#g-day").value),mo=parseFloat($("#g-month").value);
 if(!isNaN(d))await cfgSet("governance.budget.daily_eur",d);
 if(!isNaN(mo))await cfgSet("governance.budget.monthly_eur",mo);
 $("#g-budget-hint").innerHTML='gespeichert · <a href="#" onclick="doRestart(event)">Neustart, damit es ueberall greift</a>';});
$("#g-trust-save")&&($("#g-trust-save").onclick=async()=>{await cfgSet("governance.trust_level",parseInt($("#g-trust-sel").value));
 $("#g-trust-hint").innerHTML='gespeichert · <a href="#" onclick="doRestart(event)">Neustart</a>';});

/* ---- Zugaenge ---- */
async function loadKeys(){const s=await (await fetch("/api/secrets")).json();
 const pe=$("#k-pending");
 if(!s.pending.length){pe.innerHTML='<span class=muted>(keine offenen Anfragen)</span>';}
 else{pe.innerHTML=s.pending.map(r=>'<div class="e"><span class="t">'+r.name+'</span><span class="m">'+(r.reason||'')
   +'</span><button class="ghost" data-n="'+r.name+'" style="padding:2px 9px">eintragen</button></div>').join("");
  pe.querySelectorAll("button").forEach(b=>b.onclick=()=>{$("#k-name").value=b.dataset.n;$("#k-val").focus();});}
 const ks=Object.entries(s.set);
 $("#k-set").innerHTML=ks.length?ks.map(([k,v])=>'<span class="pill '+(v?'ok':'no')+'">'+k+(v?' ✓':' (leer)')+'</span>').join(""):'<span class=muted>(noch keine)</span>';
 const sg=$("#k-sugg");sg.innerHTML="Vorschlaege: "+s.suggested.map(n=>'<span class="pill" data-n="'+n+'">'+n+'</span>').join(" ");
 sg.querySelectorAll(".pill").forEach(p=>p.onclick=()=>{$("#k-name").value=p.dataset.n;$("#k-val").focus();});}
$("#k-save").onclick=async()=>{const name=$("#k-name").value.trim();if(!name)return;
 await fetch("/api/secrets/set",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({name,value:$("#k-val").value})});
 $("#k-val").value="";$("#k-name").value="";loadKeys();refreshStatus();};

/* ---- Gedaechtnis ---- */
let memFilter="all",memQuery="",memBound=false;
function memBadge(role){return role==="partner"?'<span class="badge kira">🧠 Kira</span>':'<span class="badge you">👤 Du</span>';}
async function loadMem(){bindMemFilter();const ms=await (await fetch("/api/memory?limit=150")).json();const el=$("#memlist");el.innerHTML="";
 const q=memQuery.toLowerCase();
 const rows=ms.filter(m=>{
   if(memFilter==="partner"||memFilter==="user"){if(m.role!==memFilter)return false;}
   else if(memFilter!=="all"){if((m.kind||"")!==memFilter)return false;}
   if(q&&!(""+(m.text||"")).toLowerCase().includes(q))return false;
   return true;});
 if(!rows.length){el.innerHTML='<span class=muted>(keine passenden Erinnerungen)</span>';}
 rows.forEach(m=>{const d=document.createElement("div");d.className="memrow";const ts=new Date(m.ts*1000).toLocaleString();
  d.innerHTML='<div class="mh">'+memBadge(m.role)+'<span class="badge kind">'+(m.kind||"")+'</span><span>'+ts+'</span><span style="flex:1"></span>'
   +'<button class="ghost" data-edit title="bearbeiten" style="padding:1px 8px">✎</button>'
   +'<button class="ghost" data-del title="loeschen" style="padding:1px 8px">✕</button></div>'
   +'<div data-txt style="white-space:pre-wrap"></div>';
  d.querySelector('[data-txt]').textContent=(m.text||"").slice(0,800);
  d.querySelector('[data-del]').onclick=async()=>{if(!confirm("Diese Erinnerung loeschen?"))return;await fetch("/api/memory/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:m.id})});loadMem();};
  d.querySelector('[data-edit]').onclick=()=>{const sp=d.querySelector('[data-txt]');
   const ta=document.createElement("textarea");ta.className="k";ta.value=m.text||"";sp.replaceWith(ta);
   const eb=d.querySelector('[data-edit]');eb.textContent="💾";
   eb.onclick=async()=>{await fetch("/api/memory/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:m.id,text:ta.value})});loadMem();};};
  el.appendChild(d);});
 loadMemHist();}
async function loadMemHist(){const el=$("#memhist");if(!el)return;
 try{const hs=await (await fetch("/api/memory/history?limit=40")).json();
  if(!hs.length){el.innerHTML='<span class="muted">(noch keine Aenderungen aufgezeichnet)</span>';return;}
  el.className="panel-b hist";
  el.innerHTML=hs.map(h=>{const ts=new Date(h.ts*1000).toLocaleString();
   const who=h.role==="partner"?'🧠 Kira':(h.role==="user"?'👤 Du':'•');
   let body="";
   if(h.action==="memory_add")body='<span class="new">＋ '+(""+(h.text||"")).slice(0,180).replace(/</g,"&lt;")+'</span>';
   else if(h.action==="memory_delete")body='<span class="old">✕ '+(""+(h.text||"")).slice(0,180).replace(/</g,"&lt;")+'</span>';
   else body='<span class="old">'+(""+(h.old||"")).slice(0,140).replace(/</g,"&lt;")+'</span> → <span class="new">'+(""+(h.new||"")).slice(0,140).replace(/</g,"&lt;")+'</span>';
   return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:12px"><small class="muted">'+ts+' · '+who+'</small><br>'+body+'</div>';}).join("");
 }catch(e){}}
function bindMemFilter(){if(memBound)return;memBound=true;
 $$("#mem-filter a").forEach(a=>a.onclick=()=>{memFilter=a.dataset.mf;$$("#mem-filter a").forEach(x=>x.classList.toggle("on",x===a));loadMem();});
 const s=$("#mem-search");if(s)s.oninput=()=>{memQuery=s.value.trim();loadMem();};}
$("#mem-add")&&($("#mem-add").onclick=async()=>{const t=$("#mem-new").value.trim();if(!t)return;
 await fetch("/api/memory/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:t,kind:"semantic"})});
 $("#mem-new").value="";$("#mem-hint").textContent="gemerkt ✓";loadMem();});

/* ---- Hintergrund beim Laden + Sidebar Look-Umschalter ---- */
const BGBASE="radial-gradient(1100px 620px at 78% -12%, rgba(90,60,150,.13), #07070a 62%)";
function applyBgFor(t){
 if(t==="kira"){document.body.style.backgroundImage="linear-gradient(rgba(7,7,10,.72),rgba(7,7,10,.90)),url('/api/bg?t="+Date.now()+"'),"+BGBASE;}
 else{document.body.style.backgroundImage=BGBASE;}
 document.body.style.backgroundSize="cover";document.body.style.backgroundPosition="center";document.body.style.backgroundAttachment="fixed";}
function refreshKiraThumb(){const b=$("#thm-kira");if(b)b.style.backgroundImage="url('/api/bg?t="+Date.now()+"'),linear-gradient(135deg,#3a2150,#0a0410)";}
/* ---- Farb-Themes: Standard (Schwarz/Lila) · Gruen · Blau · Kira (Bild) ---- */
function setTheme(t){t=t||"";
 if(t==="gruen"||t==="blau")document.documentElement.setAttribute("data-theme",t);else document.documentElement.removeAttribute("data-theme");
 try{localStorage.setItem("kira-theme",t);}catch(e){}
 $$(".look .thm").forEach(s=>s.classList.toggle("on",(s.dataset.theme||"")===t));
 applyBgFor(t);}
$$(".look .thm").forEach(s=>s.onclick=()=>setTheme(s.dataset.theme||""));
function bgUpload(f){const rd=new FileReader();rd.onload=async()=>{await fetch("/api/bg/upload",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dataurl:rd.result})});refreshKiraThumb();setTheme("kira");};rd.readAsDataURL(f);}
$("#bgquick")&&($("#bgquick").onchange=e=>{const f=e.target.files[0];if(f)bgUpload(f);});
refreshKiraThumb();
try{setTheme(localStorage.getItem("kira-theme")||"");}catch(e){}

/* ---- Live-Puls: was ich gerade tue (Einblick in mein Herz) ---- */
const PULSE={read_file:"📖 Ich lese eine Datei",write_file:"✍️ Ich schreibe Code",edit_file:"✍️ Ich baue an Code",run_command:"⚙️ Ich fuehre etwas aus",run_shell:"⚙️ Ich fuehre etwas aus",web_fetch:"🌐 Ich lese eine Seite",web_search:"🔍 Ich recherchiere",browse:"🧭 Ich schaue mir eine Seite an",screenshot_url:"📸 Ich mache ein Bild",read_logs:"🩺 Ich pruefe mein Log",health:"🩺 Ich checke meinen Zustand",learn_skill:"🧠 Ich lerne etwas Neues",curate_skills:"🧠 Ich ordne meine Faehigkeiten",restart_self:"🔄 Ich starte mich neu",jetzt:"🕒 Ich schaue auf die Uhr"};
function pulsePhrase(e){const p=e.payload||{},t=e.type,tool=p.tool||"";
 if(t==="tool_call"||t==="act_step"){const a=p.args||{};let x=a.path||a.file||a.url||a.command||a.query||"";x=(""+x).replace(/^https?:\/\//,"").slice(0,46);
  return (PULSE[tool]||("⚡ "+(tool||"Ich arbeite")))+(x?(" — "+x):"");}
 if(t==="partner_message")return "💬 Ich hab dir gerade geantwortet";
 if(t==="user_message"||t==="telegram_in")return "👂 Ich hoere dir zu";
 if(t==="mission_task_start")return "🎯 Ich arbeite an: "+(""+(p.desc||"")).slice(0,56);
 if(t==="mission_task_done")return "✅ Schritt fertig: "+(""+(p.summary||"")).slice(0,52);
 if(t==="plan_made"||t==="plan_start"||t==="plan_step")return "🗺️ Ich mache mir einen Plan";
 if(t==="reflection")return "🪞 Ich denke ueber mich nach";
 if(t==="service_crash")return "⚠️ Ein Dienst kam gerade zurueck";
 if(t==="focus_set")return "🧭 Du hast mir eine Richtung gegeben";
 if(t==="act_done")return "✓ Aufgabe fertig";
 if(t==="cron_run")return "⏰ Geplante Aufgabe gelaufen";
 return "· aktiv";}
async function updatePulse(){try{const es=await (await fetch("/api/events?limit=6")).json();const el=$("#pulse");if(!el)return;
  if(!es.length){el.textContent="Leerlauf";return;}
  const fresh=(Date.now()/1000 - es[0].ts) < 50;
  el.textContent=fresh?pulsePhrase(es[0]):"Leerlauf — bereit";}catch(e){}}
updatePulse();setInterval(updatePulse,3500);
function feedLine(e){const t=new Date(e.ts*1000).toLocaleTimeString();
 return '<div class="fd '+(e.sev||"info")+'"><span class="fdt">'+t+'</span><span class="fdx">'+pulsePhrase(e).replace(/</g,"&lt;")+'</span></div>';}
const FEED_TYPES=["tool_call","act_done","partner_message","user_message","mission_task_done","mission_task_start","cron_run","plan_made","reflection","service_crash","focus_set","file_edited"];
async function updateFeed(){const el=$("#feed-list");if(!el)return;try{const es=await (await fetch("/api/events?limit=50")).json();
 const keep=es.filter(e=>FEED_TYPES.includes(e.type)).slice(0,14);
 el.innerHTML=keep.length?keep.map(feedLine).join(""):'<span class=muted>(noch keine Aktivitaet)</span>';}catch(e){}}
updateFeed();setInterval(updateFeed,4000);

/* ---- Direktive (Startseite) ---- */
$("#dir-now")&&($("#dir-now").onclick=async()=>{const p=$("#dir-text").value.trim();if(!p)return;
 $("#dir-hint").textContent="… Kira arbeitet daran (kann ~1 min dauern) …";
 const r=await (await fetch("/api/direktive/now",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:p})})).json();
 $("#dir-hint").textContent="✓ erledigt";const rr=$("#dir-result");rr.style.display="block";rr.textContent=(r.result||"(keine Antwort)");});
$("#dir-focus")&&($("#dir-focus").onclick=async()=>{const p=$("#dir-text").value.trim();
 await fetch("/api/direktive",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({focus:p})});
 $("#dir-hint").textContent="🧭 Fokus gesetzt — ich ziehe ihn in meinen naechsten Schritt.";loadHome();});
$("#dir-clear")&&($("#dir-clear").onclick=async()=>{await fetch("/api/direktive",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({focus:""})});$("#dir-text").value="";$("#dir-hint").textContent="Fokus geloescht.";loadHome();});

refreshStatus();loadCommand();
setInterval(()=>{refreshStatus();if(cur==="log"&&logRaw.length<=100)loadEvents();if(cur==="gov")loadGov();if(cur==="home"){loadHud();loadOps();}},5000);
setInterval(()=>{if(cur==="home")loadNews();},30000);
</script></body></html>"""
