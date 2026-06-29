"""FastAPI-Cockpit: Chat (mit Live-Thinking), Seele/Dateien, Modelle, Protokoll.

Ein Prozess, eine Seite (Terminal-Look). Start:
    uv run uvicorn core.api.server:app --reload   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

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
from core.kernel.scheduler import heartbeat_on, kill_switch_active, kill_switch_path, set_heartbeat
from core.mind.agent import Agent
from core.mind.memory import store as memory

app = FastAPI(title="Kira Cockpit")
events.init_db()
memory.init_memory()
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
        "mission": {"name": CONFIG.get("mission", {}).get("name"), "heartbeat": bool(CONFIG.get("heartbeat", {}).get("enabled"))},
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
def api_events(limit: int = 60) -> list[dict]:
    return events.recent(limit)


@app.get("/api/memory")
def api_memory(limit: int = 80) -> list[dict]:
    return memory.recent(limit)


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
        "suggested": list(_PROVIDER_KEYS.values()) + ["TELEGRAM_BOT_TOKEN"],
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
        "interval": CONFIG.get("heartbeat", {}).get("interval_seconds", 1800),
        "mission": m.get("name"),
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


# ---------- Chat (Live-Thinking) ----------
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    import uuid

    from core.agency.act import act_chat_stream

    await ws.accept()
    sid = "cockpit-" + uuid.uuid4().hex[:8]
    await ws.send_json({"role": "system", "text": f"Verbunden. Session {sid[-8:]}."})
    try:
        while True:
            user_text = await ws.receive_text()
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
    except WebSocketDisconnect:
        pass


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!doctype html>
<html lang="de"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Kira Cockpit</title>
<style>
:root{--bg:#0a0710;--panel:#150f20;--panel2:#100b18;--line:#2a1f3a;--ink:#f3eef9;
 --muted:#9a8fb0;--accent:#a855f7;--accent2:#7c3aed;--amber:#c4b5fd;--danger:#f0596a;}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;font:14px/1.5 ui-monospace,"Cascadia Code",Consolas,monospace;
 background:linear-gradient(rgba(10,7,16,.80),rgba(10,7,16,.93)),url('/api/bg') center/cover fixed no-repeat,var(--bg);color:var(--ink)}
#side{width:210px;flex-shrink:0;border-right:1px solid var(--line);background:rgba(13,9,20,.72);
 backdrop-filter:blur(8px);display:flex;flex-direction:column}
#side h1{font-size:19px;letter-spacing:3px;padding:16px 16px 2px;color:#fff;margin:0;
 text-shadow:0 0 12px rgba(168,85,247,.9),0 0 26px rgba(124,58,237,.5)}
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
button{padding:0 16px;border:none;border-radius:10px;cursor:pointer;font-weight:600;font-family:inherit;
 background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;box-shadow:0 0 14px rgba(168,85,247,.35)}
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
.card{background:rgba(21,15,32,.62);backdrop-filter:blur(8px);border:1px solid rgba(168,85,247,.18);border-radius:12px;padding:14px;margin-bottom:14px;max-width:880px}
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
.e .m{color:var(--muted);white-space:pre-wrap;flex:1}
.muted{color:var(--muted)}
</style></head><body>
<div id="side">
  <h1>KIRA <span style="color:var(--accent)">&#9829;</span></h1><div class="sub" id="who">cockpit</div>
  <a data-v="home" class="on">› Uebersicht</a>
  <a data-v="chat">› Chat</a>
  <a data-v="files">› Seele &amp; Dateien</a>
  <a data-v="models">› Modelle</a>
  <a data-v="gov">› Gewissen</a>
  <a data-v="mission">› Mission</a>
  <a data-v="monitor">› Monitor</a>
  <a data-v="cron">› Cron</a>
  <a data-v="keys">› Zugaenge</a>
  <a data-v="mem">› Gedaechtnis</a>
  <a data-v="log">› Protokoll</a>
  <div class="spacer"></div>
  <label class="kill" id="bgbtn" style="cursor:pointer;font-size:12px">🖼 Hintergrund<input id="bgfile" type="file" accept="image/*" style="display:none"/></label>
  <div class="kill" id="kill">Not-Aus: aus</div>
</div>
<div id="main">
  <div id="bar">
    <span class="dot"></span><span>ONLINE</span>
    <span>Modell: <b id="b-model">…</b></span>
    <span>Heute: <b id="b-spend">…</b></span>
    <span id="b-kill"></span>
  </div>

  <div class="view on" id="v-home"><div id="home" style="overflow:auto"></div></div>

  <div class="view" id="v-chat">
    <div id="chatbar" style="display:flex;gap:8px;align-items:center;padding:4px 0 8px">
      <small class="muted">Hirn:</small>
      <select id="chat-model" style="max-width:300px"></select>
      <small class="muted" id="chat-model-now"></small>
    </div>
    <div id="log"></div>
    <form id="cform">
      <input id="cin" placeholder="Schreib Kira…" autocomplete="off" autofocus/>
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
    <div class="card"><h3>Lokal (Ollama) — klicken zum Wechseln</h3><div id="m-ollama"></div></div>
    <div class="card"><h3>OpenRouter — ein Key, alle Modelle</h3>
      <div class="muted" id="m-orkey"></div>
      <div class="row"><input id="m-or" placeholder="z.B. anthropic/claude-opus-4-8 oder google/gemini-2.5-pro"/>
        <button id="m-orgo">Aktivieren</button></div></div>
    <div class="card"><h3>API-Schluessel (in .env)</h3><div id="m-keys"></div></div>
  </div>

  <div class="view" id="v-gov">
    <div class="card"><h3>Budget (Treasury)</h3><div id="g-budget" class="muted">…</div></div>
    <div class="card"><h3>Vertrauen (Trust-Level)</h3><div id="g-trust" class="muted">…</div></div>
    <div class="card"><h3>Audit — protokollierte Aussen-Aktionen</h3><div id="g-audit" class="muted">…</div></div>
  </div>

  <div class="view" id="v-mission">
    <div class="card"><h3>24/7-Mission</h3>
      <div id="ms-status" class="muted">…</div>
      <div class="row" style="margin-top:8px">
        <button id="ms-toggle">24/7 an/aus</button>
        <button class="ghost" id="ms-once">Jetzt ein Schritt</button>
      </div>
      <div class="muted" style="margin-top:6px" id="ms-hint">Ziel der Mission setzt du in „Seele &amp; Dateien → config.yaml" (mission.goal).</div>
    </div>
    <div class="card"><h3>Offene Aufgaben</h3><div id="ms-queue" class="muted">…</div></div>
    <div class="card"><h3>Letzte Schritte</h3><div id="ms-recent" class="muted">…</div></div>
  </div>

  <div class="view" id="v-cron">
    <div class="card"><h3>Geplante Aufgaben (Cron)</h3>
      <div class="muted">Wiederkehrende Aufgaben fuer Kira. Zeitplan: <b>30m</b>/<b>2h</b> (Intervall) oder <b>08:00</b> (taeglich). Laufen, sobald der Runner aktiv ist.</div>
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
      <div class="muted">Kira ueberwacht Feeds &amp; Themen, fasst Neues zusammen und meldet per Telegram. Nur Lesen — sicher.</div>
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
    <div class="muted" style="margin-bottom:8px;max-width:980px">Juengste Erinnerungen — mit ✕ loeschen. (Verfassung/Seele/Ziel sind Dateien und bleiben unberuehrt.)</div>
    <div id="memlist"></div>
  </div>

  <div class="view" id="v-log"><div id="evlog"></div></div>
</div>
<script>
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let cur="home";
$$("#side a").forEach(a=>a.onclick=()=>nav(a.dataset.v));
function nav(v){cur=v;$$("#side a").forEach(a=>a.classList.toggle("on",a.dataset.v===v));
 $$(".view").forEach(x=>x.classList.remove("on"));$("#v-"+v).classList.add("on");
 if(v==="home")loadHome(); if(v==="chat")loadChatModels(); if(v==="files")loadFiles(); if(v==="models")loadModels(); if(v==="gov")loadGov(); if(v==="mission")loadMission(); if(v==="monitor")loadMonitor(); if(v==="cron")loadCron(); if(v==="keys")loadKeys(); if(v==="mem")loadMem(); if(v==="log")loadEvents();}

/* ---- Modell-Umschalter in der Chat-Pane ---- */
async function loadChatModels(){const s=await (await fetch("/api/status")).json();
 const sel=$("#chat-model"); if(!sel) return;
 const opts=[]; const seen={};
 const add=(id,lbl)=>{ if(id && !seen[id]){ seen[id]=1; opts.push('<option value="'+id+'"'+(id===s.default?' selected':'')+'>'+lbl+'</option>'); } };
 add(s.default, s.default+" (aktiv)");
 (s.ollama_local||[]).forEach(n=>add("ollama_chat/"+n.replace(/:latest$/,""), n+" (lokal, 0€)"));
 if(s.api_keys&&s.api_keys.openrouter){ add("openrouter/z-ai/glm-5.2","GLM 5.2 (Cloud, stark)"); }
 sel.innerHTML=opts.join("");
 $("#chat-model-now").textContent="aktiv: "+s.default;}
$("#chat-model")&&($("#chat-model").onchange=async(e)=>{const id=e.target.value;
 await fetch("/api/model/use",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id})});
 $("#chat-model-now").textContent="gewechselt zu: "+id; refreshStatus();});

/* ---- Hintergrundbild hochladen ---- */
$("#bgfile")&&($("#bgfile").onchange=(e)=>{const f=e.target.files[0];if(!f)return;
 const rd=new FileReader();rd.onload=async()=>{await fetch("/api/bg/upload",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dataurl:rd.result})});
  document.body.style.backgroundImage="linear-gradient(rgba(10,7,16,.80),rgba(10,7,16,.93)),url('/api/bg?t="+Date.now()+"')";};
 rd.readAsDataURL(f);});

/* ---- Monitor ---- */
async function loadMonitor(){const m=await (await fetch("/api/monitor")).json();
 $("#mo-list").innerHTML=m.watches.length?m.watches.map(w=>'<div style="padding:6px 0;border-bottom:1px solid #1b2a33"><b>'+(w.label||"").replace(/</g,"&lt;")+'</b> <small class=muted>['+w.kind+']</small> <a href="#" data-rm="'+w.id+'" style="float:right;color:#e0a35a">entfernen</a><br><small class=muted>'+(w.value||"").replace(/</g,"&lt;")+'</small></div>').join(""):'<span class=muted>(noch keine — oben hinzufuegen)</span>';
 document.querySelectorAll('#mo-list a[data-rm]').forEach(a=>a.onclick=async(e)=>{e.preventDefault();await fetch("/api/monitor/remove",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.rm})});loadMonitor();});
 $("#mo-recent").innerHTML=m.recent.length?m.recent.map(r=>{const ts=new Date(r.ts*1000).toLocaleString();return '<div style="padding:6px 0;border-bottom:1px solid #1b2a33"><small class=muted>'+ts+'</small> <b>'+(r.label||"")+'</b> ('+r.count+' neu)<br>'+(r.summary||"").slice(0,320).replace(/</g,"&lt;").replace(/\\n/g,"<br>")+'</div>';}).join(""):'<span class=muted>(noch nichts gemeldet)</span>';}
$("#mo-add").onclick=async()=>{const v=$("#mo-value").value.trim();if(!v)return;await fetch("/api/monitor/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:$("#mo-kind").value,value:v,label:$("#mo-label").value})});$("#mo-value").value="";$("#mo-label").value="";loadMonitor();};
$("#mo-check").onclick=async()=>{$("#mo-hint").textContent="… prueft alle Beobachtungen (kann etwas dauern) …";const r=await (await fetch("/api/monitor/check",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();$("#mo-hint").textContent="Geprueft: "+r.checked+" Quelle(n) · Neu gemeldet: "+(r.digests?r.digests.length:0);loadMonitor();};

/* ---- Cron / geplante Aufgaben ---- */
async function loadCron(){const d=await (await fetch("/api/cron")).json();const fmt=ts=>ts?new Date(ts*1000).toLocaleString():"—";
 $("#cr-list").innerHTML=d.jobs.length?d.jobs.map(j=>{const last=(j.recent_runs&&j.recent_runs.length)?j.recent_runs[j.recent_runs.length-1]:null;
   return '<div style="padding:8px 0;border-bottom:1px solid #1b2a33"><b>'+(j.label||"").replace(/</g,"&lt;")+'</b> <small class=muted>'+(j.schedule_text||"")+' · '+(j.enabled?"an":"aus")+' · naechster: '+fmt(j.next_run)+'</small>'
     +'<span style="float:right"><a href="#" data-run="'+j.id+'">jetzt</a> · <a href="#" data-tog="'+j.id+'">'+(j.enabled?"pausieren":"aktivieren")+'</a> · <a href="#" data-rm="'+j.id+'" style="color:#e0a35a">entfernen</a></span>'
     +'<br><small class=muted>'+(j.prompt||"").slice(0,120).replace(/</g,"&lt;")+'</small>'
     +(last?('<br><small class=muted>letzter Lauf '+fmt(last.ts)+': '+(last.ok?"✓":"✗")+' '+(last.summary||"").slice(0,140).replace(/</g,"&lt;")+'</small>'):'')+'</div>';}).join(""):'<span class=muted>(keine geplanten Aufgaben)</span>';
 document.querySelectorAll('#cr-list a[data-rm]').forEach(a=>a.onclick=async e=>{e.preventDefault();await fetch("/api/cron/remove",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.rm})});loadCron();});
 document.querySelectorAll('#cr-list a[data-tog]').forEach(a=>a.onclick=async e=>{e.preventDefault();await fetch("/api/cron/toggle",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.tog})});loadCron();});
 document.querySelectorAll('#cr-list a[data-run]').forEach(a=>a.onclick=async e=>{e.preventDefault();$("#cr-hint").textContent="… Job laeuft …";await fetch("/api/cron/runnow",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.run})});$("#cr-hint").textContent="Lauf fertig.";loadCron();});}
$("#cr-add").onclick=async()=>{const p=$("#cr-prompt").value.trim();if(!p)return;await fetch("/api/cron/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({label:$("#cr-label").value,prompt:p,schedule:$("#cr-sched").value||"60m"})});$("#cr-label").value="";$("#cr-prompt").value="";$("#cr-sched").value="";loadCron();};

/* ---- Mission (24/7) ---- */
async function loadMission(){const m=await (await fetch("/api/mission")).json();
 $("#ms-status").innerHTML="Mission: <b>"+(m.mission||"-")+"</b> · 24/7: "+(m.enabled?'<b style="color:#1fb6a6">AN</b>':'<span class=muted>aus</span>')+" · Takt "+Math.round(m.interval/60)+" min";
 $("#ms-queue").innerHTML=m.pending.length?m.pending.map(t=>"• "+(t.description||"").replace(/</g,"&lt;")).join("<br>"):'<span class=muted>(leer — beim naechsten Lauf plant Kira neue)</span>';
 $("#ms-recent").innerHTML=m.recent.length?m.recent.map(r=>{const ts=new Date(r.ts*1000).toLocaleString();return '<div style="padding:6px 0;border-bottom:1px solid #1b2a33"><small class=muted>'+ts+'</small><br>'+(r.summary||"").slice(0,220).replace(/</g,"&lt;")+'</div>';}).join(""):'<span class=muted>(noch keine)</span>';}
$("#ms-toggle").onclick=async()=>{const m=await (await fetch("/api/mission")).json();
 await fetch("/api/mission/toggle",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on:!m.enabled})});loadMission();};
$("#ms-once").onclick=async()=>{$("#ms-hint").textContent="… Kira macht einen autonomen Schritt (kann ~1 min dauern) …";
 const r=await (await fetch("/api/mission/runonce",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();
 $("#ms-hint").textContent="Fertig.";loadMission();};

/* ---- Uebersicht ---- */
async function loadHome(){const o=await (await fetch("/api/overview")).json();const b=o.budget;
 const card=(t,c)=>'<div class="card"><h3>'+t+'</h3>'+c+'</div>';
 const kill=o.kill_switch?'<b style="color:#e0564e">⛔ NOT-AUS aktiv</b>':'<span style="color:#1fb6a6">einsatzbereit</span>';
 let h='<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px"><span class="dot"></span>'
  +'<h2 style="margin:0">'+o.partner+'</h2><span class=muted>'+kill+'</span></div>'
  +'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;max-width:1120px">';
 h+=card("Modell &amp; Budget","Modell: <b>"+o.model+"</b><br><span class=muted>Heute "+b.day_spent+" / "+(b.day_limit??"-")
   +" € · Monat "+b.month_spent+" / "+(b.month_limit??"-")+" €</span>");
 h+=card("Vertrauen","Stufe <b>"+o.trust.level+"</b><br><span class=muted>"+o.trust.label+"</span>");
 h+=card("Mission","<b>"+(o.mission.name||"-")+"</b><br><span class=muted>24/7-Loop: "
   +(o.mission.heartbeat?'<b style="color:#1fb6a6">AN</b>':'aus')+"</span>"
   +(o.last_mission?'<br><span class=muted>Letzter Schritt: '+o.last_mission.summary.slice(0,150).replace(/</g,"&lt;")+'</span>':''));
 h+=card("Werkzeuge ("+o.tools.length+")", o.tools.map(t=>'<span class="pill">'+t+'</span>').join(" "));
 h+=card("Letzte Lektionen", o.lessons.length?('<ul style="margin:0;padding-left:18px">'
   +o.lessons.map(l=>'<li>'+l.slice(0,140).replace(/</g,"&lt;")+'</li>').join("")+'</ul>'):'<span class=muted>(noch keine)</span>');
 h+=card("Schnellzugriff",'<button class=ghost onclick="nav(\\'chat\\')">Chat</button> '
   +'<button class=ghost onclick="nav(\\'models\\')">Modelle</button> '
   +'<button class=ghost onclick="nav(\\'gov\\')">Gewissen</button>');
 h+='</div>';$("#home").innerHTML=h;}

async function refreshStatus(){const s=await (await fetch("/api/status")).json();
 $("#who").textContent=s.partner.toLowerCase()+" · cockpit";
 $("#b-model").textContent=s.model;
 $("#b-spend").textContent="$"+s.spend_usd_today+((s.budget&&s.budget.day_limit!=null)?(" / "+s.budget.day_limit+"€"):"");
 const k=$("#kill"); k.classList.toggle("active",s.kill_switch);
 k.textContent="Not-Aus: "+(s.kill_switch?"AKTIV":"aus");
 $("#b-kill").innerHTML=s.kill_switch?'<b style="color:#e0564e">⛔ NOT-AUS</b>':'';
 return s;}
$("#kill").onclick=async()=>{const on=!$("#kill").classList.contains("active");
 await fetch("/api/kill",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on})});refreshStatus();};

/* ---- Chat ---- */
const log=$("#log");
function add(t,c){const d=document.createElement("div");d.className="msg "+c;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
const proto=location.protocol==="https:"?"wss":"ws";
let ws,curBot,curThink,thinkBuf;
function connect(){ws=new WebSocket(proto+"://"+location.host+"/ws/chat");
 function ensureTrace(){if(!curThink){thinkBuf="";curThink=document.createElement("div");curThink.className="think show";
    curThink.innerHTML='<span class="h">💭 Denken &amp; Aktionen (klick zum Ein-/Ausklappen)</span><div class="c"></div>';
    curThink.querySelector(".h").onclick=()=>curThink.classList.toggle("show");log.appendChild(curThink);}return curThink;}
 function traceSet(){curThink.querySelector(".c").textContent=thinkBuf;log.scrollTop=log.scrollHeight;}
 ws.onmessage=ev=>{const m=JSON.parse(ev.data);
  if(m.role==="system"){add(m.text,"sys");return;}
  if(m.done){curBot=null;curThink=null;return;}
  if(m.kind==="think"){ensureTrace();thinkBuf+=m.text;traceSet();return;}
  if(m.kind==="tool"){ensureTrace();thinkBuf+="\\n🔧 "+m.name+" "+JSON.stringify(m.args);traceSet();return;}
  if(m.kind==="obs"){ensureTrace();thinkBuf+="\\n   ✓ "+(m.text||"").slice(0,120);traceSet();return;}
  if(m.kind==="final"||m.kind==="answer"){const b=add("","bot");b.textContent=(m.text||"").replace(/\\*\\*/g,"");log.scrollTop=log.scrollHeight;}};
 ws.onclose=()=>setTimeout(connect,1500);}
connect();
$("#cform").onsubmit=e=>{e.preventDefault();const t=$("#cin").value.trim();if(!t||ws.readyState!==1)return;
 add(t,"me");ws.send(t);$("#cin").value="";curBot=null;curThink=null;};

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
function showLoaded(el,ld){if(ld&&ld.context){const col=(ld.gpu_pct!=null&&ld.gpu_pct>=99)?"#1fb6a6":"#e0a35a";
   el.innerHTML="Geladen: <b>"+ld.context+"</b> Kontext · <b style='color:"+col+"'>"+(ld.gpu_pct!=null?ld.gpu_pct+"% GPU":"?")+"</b> · "+(ld.vram_gb||"?")+" GB VRAM"
    +((ld.gpu_pct!=null&&ld.gpu_pct<99)?" ⚠️ teilweise CPU — kleiner waehlen":"");}
  else{el.textContent="(Modell noch nicht geladen — wird beim ersten Chat geladen)";}}
async function loadModels(){const s=await (await fetch("/api/status")).json();
 $("#m-active").innerHTML="<b>"+s.model+"</b> &nbsp; <span class=muted>Eskalation: "+(s.escalation_model||"-")+"</span>";
 $("#m-ctx").value=s.num_ctx||""; $("#m-maxtok").value=s.max_tokens||"";
 fetch("/api/model/loaded").then(r=>r.json()).then(ld=>showLoaded($("#m-loaded"),ld));
 document.querySelectorAll('#v-models .pill[data-ctx]').forEach(p=>p.onclick=()=>{$("#m-ctx").value=p.dataset.ctx;});
 $("#m-paramgo").onclick=async()=>{const ctx=parseInt($("#m-ctx").value)||null;const mt=parseInt($("#m-maxtok").value)||null;
  $("#m-loaded").textContent="… lädt mit neuem Kontext (kann ~30 s dauern) …";
  const r=await (await fetch("/api/model/params",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({num_ctx:ctx,max_tokens:mt})})).json();
  showLoaded($("#m-loaded"),r.loaded||{});refreshStatus();};
 const ol=$("#m-ollama");ol.innerHTML="";(s.ollama_local||[]).forEach(m=>{const p=document.createElement("span");
  p.className="pill"+(("ollama_chat/"+m)===s.model?" ok":"");p.textContent=m;
  p.onclick=()=>useModel("ollama_chat/"+m);ol.appendChild(p);});
 if(!(s.ollama_local||[]).length)ol.innerHTML='<span class=muted>(Ollama aus oder keine Modelle)</span>';
 $("#m-orkey").textContent=s.api_keys.openrouter?"OPENROUTER_API_KEY gesetzt ✓":"OPENROUTER_API_KEY fehlt — in .env eintragen (openrouter.ai/keys)";
 const ks=$("#m-keys");ks.innerHTML="";Object.entries(s.api_keys).forEach(([k,v])=>{const p=document.createElement("span");
  p.className="pill "+(v?"ok":"no");p.textContent=k+(v?" ✓":" ✗");ks.appendChild(p);});}
async function useModel(id){await fetch("/api/model/use",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({id})});loadModels();refreshStatus();}
$("#m-orgo").onclick=async()=>{const m=$("#m-or").value.trim();if(!m)return;
 await fetch("/api/model/openrouter",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({model:m})});$("#m-or").value="";loadModels();refreshStatus();};

/* ---- Protokoll ---- */
async function loadEvents(){const es=await (await fetch("/api/events?limit=80")).json();const el=$("#evlog");el.innerHTML="";
 es.forEach(e=>{const d=document.createElement("div");d.className="e";const t=new Date(e.ts*1000).toLocaleTimeString();
  d.innerHTML='<span class="t">'+t+" · "+e.type+'</span><span class="m">'+JSON.stringify(e.payload).slice(0,180)+"</span>";el.appendChild(d);});}

/* ---- Gewissen ---- */
function bar(spent,limit){if(limit==null)return '<span class=muted>kein Limit</span>';
 const pct=Math.min(100,Math.round(spent/limit*100));const col=pct>90?'#e0564e':pct>70?'#e0a35a':'#1fb6a6';
 return '<div style="background:#0b1217;border:1px solid #1b2a33;border-radius:6px;height:16px;overflow:hidden">'
  +'<div style="height:100%;width:'+pct+'%;background:'+col+'"></div></div>'
  +'<small class=muted>'+spent.toFixed(4)+' / '+limit+' € ('+pct+'%)</small>';}
async function loadGov(){const g=await (await fetch("/api/governance")).json();const t=g.treasury;
 $("#g-budget").innerHTML="Heute:<br>"+bar(t.day_spent,t.day_limit)+"<br><br>Diesen Monat:<br>"+bar(t.month_spent,t.month_limit);
 $("#g-trust").innerHTML="Stufe <b>"+g.trust.level+"</b> — "+g.trust.label
  +'<br><span class=muted>Erfolge: '+g.trust.success+' · Fehlschlaege: '+g.trust.fail+'</span>'
  +'<br><span class=muted>Bei Stufe 3 begrenzt nur das Budget; Außen-Aktionen brauchen kein Go.</span>';
 const a=$("#g-audit");if(!g.audit.length){a.innerHTML='<span class=muted>(noch keine Außen-Aktionen protokolliert)</span>';return;}
 a.innerHTML=g.audit.map(e=>{const ts=new Date(e.ts*1000).toLocaleString();const p=e.payload;
  return '<div style="padding:6px 0;border-bottom:1px solid #1b2a33"><b>'+p.action+'</b> '+(p.target||'')
   +' <small class=muted>'+ts+(p.reversible?' · rückrollbar':'')+'</small></div>';}).join("");}

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
async function loadMem(){const ms=await (await fetch("/api/memory?limit=100")).json();const el=$("#memlist");el.innerHTML="";
 if(!ms.length){el.innerHTML='<span class=muted>(noch keine Erinnerungen)</span>';return;}
 ms.forEach(m=>{const d=document.createElement("div");d.className="e";const ts=new Date(m.ts*1000).toLocaleString();
  const esc=(m.text||"").slice(0,400).replace(/&/g,"&amp;").replace(/</g,"&lt;");
  d.innerHTML='<span class="t">'+m.role+'/'+m.kind+'<br><small class=muted>'+ts+'</small></span>'
   +'<span class="m">'+esc+'</span><button class="ghost" title="loeschen" style="padding:2px 9px">✕</button>';
  d.querySelector("button").onclick=async()=>{await fetch("/api/memory/delete",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify({id:m.id})});loadMem();};
  el.appendChild(d);});}

refreshStatus();setInterval(()=>{refreshStatus();if(cur==="log")loadEvents();if(cur==="gov")loadGov();},5000);
</script></body></html>"""
