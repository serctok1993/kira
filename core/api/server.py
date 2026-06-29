"""FastAPI-Cockpit: Chat (mit Live-Thinking), Seele/Dateien, Modelle, Protokoll.

Ein Prozess, eine Seite (Terminal-Look). Start:
    uv run uvicorn core.api.server:app --reload   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import time

import anyio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from core.agency.tools import builtin as _builtin  # noqa: F401  (registriert eingebaute Tools)
from core.agency.tools import registry
from core.agency.tools import synthesize as _synth
from core.config import CONFIG, MIND_DIR, ROOT
from core.governance import audit, secrets, treasury, trust
from core.kernel import events, models
from core.kernel.llm_router import today_spend_usd
from core.kernel.scheduler import kill_switch_active, kill_switch_path
from core.mind.agent import Agent
from core.mind.memory import store as memory

app = FastAPI(title="Prometheus Cockpit")
events.init_db()
memory.init_memory()
_synth.load_synthesized()  # selbstgebaute Werkzeuge fuer die Uebersicht verfuegbar machen

# Im Dashboard sichtbare/bearbeitbare Dateien. Alles editierbar — DU bist der Eigentuemer.
# (Die Verfassung ist nur fuer KYROS gesperrt — via evolution.py; du darfst sie hier aendern.)
FILES: dict[str, dict] = {
    "constitution.md": {"path": MIND_DIR / "constitution.md", "editable": True, "label": "Verfassung (fuer Kyros gesperrt, von dir editierbar)"},
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


# ---------- Chat (Live-Thinking) ----------
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()
    agent = Agent()
    await ws.send_json({"role": "system", "text": f"Verbunden. Session {agent.session_id[:8]}."})
    try:
        while True:
            user_text = await ws.receive_text()
            gen = agent.respond_stream_tagged(user_text)

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
<title>Prometheus Cockpit</title>
<style>
:root{--bg:#080c0f;--panel:#0e161b;--panel2:#0b1217;--line:#1b2a33;--ink:#dfeaef;
 --muted:#7791a0;--accent:#1fb6a6;--accent2:#0e7c8c;--amber:#e0a35a;--danger:#e0564e;}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;font:14px/1.5 ui-monospace,"Cascadia Code",Consolas,monospace;
 background:var(--bg);color:var(--ink)}
#side{width:210px;flex-shrink:0;border-right:1px solid var(--line);background:var(--panel2);
 display:flex;flex-direction:column}
#side h1{font-size:15px;letter-spacing:2px;padding:16px 16px 4px;color:var(--amber);margin:0}
#side .sub{font-size:11px;color:var(--muted);padding:0 16px 14px}
#side a{display:block;padding:10px 16px;color:var(--ink);text-decoration:none;cursor:pointer;
 border-left:3px solid transparent}
#side a:hover{background:var(--panel)}
#side a.on{background:var(--panel);border-left-color:var(--accent);color:var(--accent)}
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
.me{align-self:flex-end;background:#13212a}
.bot{align-self:flex-start;background:var(--panel)}
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
 background:linear-gradient(135deg,var(--accent),var(--accent2));color:#04181a}
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
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px;max-width:880px}
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
  <h1>PROMETHEUS</h1><div class="sub" id="who">cockpit</div>
  <a data-v="home" class="on">› Uebersicht</a>
  <a data-v="chat">› Chat</a>
  <a data-v="files">› Seele &amp; Dateien</a>
  <a data-v="models">› Modelle</a>
  <a data-v="gov">› Gewissen</a>
  <a data-v="keys">› Zugaenge</a>
  <a data-v="mem">› Gedaechtnis</a>
  <a data-v="log">› Protokoll</a>
  <div class="spacer"></div>
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
    <div id="log"></div>
    <form id="cform"><input id="cin" placeholder="Schreib Kyros…" autocomplete="off" autofocus/><button>Senden</button></form>
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

  <div class="view" id="v-keys">
    <div class="card"><h3>Von Kyros angefordert</h3><div id="k-pending" class="muted">…</div></div>
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
 if(v==="home")loadHome(); if(v==="files")loadFiles(); if(v==="models")loadModels(); if(v==="gov")loadGov(); if(v==="keys")loadKeys(); if(v==="mem")loadMem(); if(v==="log")loadEvents();}

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
 ws.onmessage=ev=>{const m=JSON.parse(ev.data);
  if(m.role==="system"){add(m.text,"sys");return;}
  if(m.done){curBot=null;curThink=null;return;}
  if(m.kind==="think"){if(!curThink){thinkBuf="";curThink=document.createElement("div");curThink.className="think show";
     curThink.innerHTML='<span class="h">💭 denkt (klick)</span><div class="c"></div>';
     curThink.querySelector(".h").onclick=()=>curThink.classList.toggle("show");log.appendChild(curThink);}
   thinkBuf+=m.text;curThink.querySelector(".c").textContent=thinkBuf;log.scrollTop=log.scrollHeight;return;}
  if(m.kind==="answer"){if(!curBot)curBot=add("","bot");curBot.textContent+=m.text;log.scrollTop=log.scrollHeight;}};
 ws.onclose=()=>setTimeout(connect,1500);}
connect();
$("#cform").onsubmit=e=>{e.preventDefault();const t=$("#cin").value.trim();if(!t||ws.readyState!==1)return;
 add(t,"me");ws.send(t);$("#cin").value="";curBot=null;curThink=null;};

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
async function loadModels(){const s=await (await fetch("/api/status")).json();
 $("#m-active").innerHTML="<b>"+s.model+"</b> &nbsp; <span class=muted>Eskalation: "+(s.escalation_model||"-")+"</span>";
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
