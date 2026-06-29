"""FastAPI: Web-Chat + Status/Events-API + WebSocket-Live-Kanal.

Spaeter speist dieser Live-Kanal das Next.js-Cockpit (Phase 6).
"""
from __future__ import annotations

import anyio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from core.config import CONFIG
from core.kernel import events
from core.mind.agent import Agent

app = FastAPI(title="Prometheus")


@app.get("/health")
def health() -> dict:
    return {
        "status": "alive",
        "harness": CONFIG["identity"]["harness_name"],
        "trust_level": CONFIG["governance"]["trust_level"],
        "events": events.counts_by_type(),
    }


@app.get("/events")
def get_events(limit: int = 50) -> list[dict]:
    return events.recent(limit)


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()
    agent = Agent()
    await ws.send_json({"role": "system", "text": f"Verbunden. Session {agent.session_id[:8]}."})
    try:
        while True:
            user_text = await ws.receive_text()
            # Blockierenden LLM-Call in einen Thread auslagern.
            result = await anyio.to_thread.run_sync(agent.respond, user_text)
            await ws.send_json(
                {
                    "role": "partner",
                    "text": result["text"],
                    "fell_back": result["fell_back"],
                    "model": result["model"],
                }
            )
    except WebSocketDisconnect:
        pass


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return CHAT_HTML


CHAT_HTML = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Prometheus</title>
<style>
  :root { --bg:#0a0f12; --panel:#0f171c; --line:#1c2a32; --ink:#e6f1f5;
          --muted:#7c93a0; --accent:#1fb6a6; --accent2:#0e7c8c; --user:#13212a; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.55 system-ui,Segoe UI,Roboto,sans-serif;
         background:radial-gradient(1200px 600px at 70% -10%, #10262a 0%, var(--bg) 60%);
         color:var(--ink); height:100vh; display:flex; flex-direction:column; }
  header { padding:14px 20px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:10px; }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--accent);
         box-shadow:0 0 12px var(--accent); }
  header b { letter-spacing:.5px; }
  header span { color:var(--muted); font-size:13px; }
  #log { flex:1; overflow-y:auto; padding:24px; display:flex; flex-direction:column; gap:14px;
         max-width:820px; width:100%; margin:0 auto; }
  .msg { padding:12px 16px; border-radius:14px; max-width:80%; white-space:pre-wrap;
         border:1px solid var(--line); }
  .me  { align-self:flex-end; background:var(--user); border-color:#21323d; }
  .bot { align-self:flex-start; background:var(--panel); }
  .sys { align-self:center; color:var(--muted); font-size:12px; border:none; }
  .meta { color:var(--muted); font-size:11px; margin-top:6px; }
  form { display:flex; gap:10px; padding:16px; border-top:1px solid var(--line);
         max-width:820px; width:100%; margin:0 auto; }
  input { flex:1; padding:13px 16px; border-radius:12px; border:1px solid var(--line);
          background:var(--panel); color:var(--ink); outline:none; font-size:15px; }
  input:focus { border-color:var(--accent2); }
  button { padding:0 20px; border-radius:12px; border:none; cursor:pointer; font-weight:600;
           background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#04181a; }
  button:disabled { opacity:.5; cursor:default; }
</style>
</head>
<body>
  <header><span class="dot"></span><b>PROMETHEUS</b><span id="status">verbinde…</span></header>
  <div id="log"></div>
  <form id="f">
    <input id="i" placeholder="Schreib deinem Partner…" autocomplete="off" autofocus />
    <button id="b" type="submit">Senden</button>
  </form>
<script>
  const log = document.getElementById('log');
  const form = document.getElementById('f');
  const input = document.getElementById('i');
  const btn = document.getElementById('b');
  const status = document.getElementById('status');

  function add(text, cls, meta) {
    const d = document.createElement('div');
    d.className = 'msg ' + cls;
    d.textContent = text;
    if (meta) { const m = document.createElement('div'); m.className='meta'; m.textContent=meta; d.appendChild(m); }
    log.appendChild(d); log.scrollTop = log.scrollHeight;
    return d;
  }

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto + '://' + location.host + '/ws/chat');
  let pending = null;

  ws.onopen = () => { status.textContent = 'online'; };
  ws.onclose = () => { status.textContent = 'getrennt'; btn.disabled = true; };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (pending) { pending.remove(); pending = null; }
    if (m.role === 'system') { add(m.text, 'sys'); }
    else {
      const meta = m.fell_back ? 'lokal · 0 €' : (m.model || '');
      add(m.text, 'bot', meta);
    }
    btn.disabled = false;
  };

  form.onsubmit = (e) => {
    e.preventDefault();
    const t = input.value.trim();
    if (!t || ws.readyState !== 1) return;
    add(t, 'me');
    ws.send(t);
    input.value = '';
    btn.disabled = true;
    pending = add('…denkt', 'bot');
  };
</script>
</body>
</html>"""
