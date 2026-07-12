"""/setup — Erst-Einrichtung (W3): eigenstaendige, server-gerenderte Seite (Muster wall.py).

Ein frischer Klon landet hier (Onboarding-Gate in server.py) und beantwortet das
Minimum: Wie heisst dein Agent, wie heisst du — optional Telegram + OpenRouter.
Der Abschluss personalisiert die Instanz (Overrides + Secrets-Tresor + Mind-Seed
+ Stammbaum-Wurzel), setzt data/onboarded.flag und bounct Bot+Runner.
"""
from __future__ import annotations

SETUP_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Einrichtung</title>
<style>
:root{--bg:#0b0a12;--panel:#14121f;--line:#2a2540;--txt:#e8e6f2;--muted:#9b97b0;--accent:#8b5cf6;--ok:#34d399;--warn:#f87171}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.55 "Segoe UI",system-ui,sans-serif;
     min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:520px;width:100%;
      padding:28px 30px;box-shadow:0 0 42px rgba(139,92,246,.14)}
h1{font-size:22px;letter-spacing:.4px;margin-bottom:4px}
h1 b{color:var(--accent)}
.sub{color:var(--muted);font-size:13px;margin-bottom:22px}
label{display:block;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin:14px 0 4px}
input{width:100%;background:var(--bg);border:1px solid var(--line);border-radius:8px;color:var(--txt);
      padding:10px 12px;font-size:15px;outline:none}
input:focus{border-color:var(--accent)}
.opt{margin-top:22px;border-top:1px dashed var(--line);padding-top:14px}
.opt .hint{color:var(--muted);font-size:12.5px;margin-bottom:2px}
button{margin-top:24px;width:100%;background:var(--accent);border:0;border-radius:9px;color:#fff;
       padding:12px;font-size:15.5px;font-weight:600;letter-spacing:.4px;cursor:pointer}
button:hover{filter:brightness(1.12)}
button:disabled{opacity:.55;cursor:wait}
#msg{margin-top:14px;font-size:13.5px;min-height:20px}
#msg.ok{color:var(--ok)} #msg.err{color:var(--warn)}
.skip{color:var(--muted);font-size:12.5px;margin-top:10px;text-align:center}
</style>
</head>
<body>
<form class="card" id="f">
  <h1>Willkommen. <b>Richte deinen Agenten ein.</b></h1>
  <div class="sub">Zwei Namen genuegen fuer den Start — Zugaenge kannst du auch spaeter im Cockpit nachtragen.</div>

  <label for="agent">Name deines Agenten</label>
  <input id="agent" name="agent" value="Kira" autocomplete="off">

  <label for="user">Dein Name</label>
  <input id="user" name="user" placeholder="z.B. Alex" autocomplete="off" required>

  <div class="opt">
    <div class="hint">Optional — fuer Telegram-Draht und Cloud-Modelle:</div>
    <label for="tg_token">Telegram Bot-Token (@BotFather)</label>
    <input id="tg_token" name="telegram_token" placeholder="123456:ABC..." autocomplete="off">
    <label for="tg_chat">Telegram Chat-ID (deine)</label>
    <input id="tg_chat" name="telegram_chat_id" placeholder="nur Ziffern" autocomplete="off" inputmode="numeric">
    <label for="orkey">OpenRouter API-Key</label>
    <input id="orkey" name="openrouter_key" placeholder="sk-or-..." autocomplete="off">
  </div>

  <button id="go" type="submit">Los geht's</button>
  <div id="msg"></div>
  <div class="skip">Ohne Zugaenge laeuft alles lokal (Ollama) — nichts verlaesst deinen Rechner.</div>
</form>
<script>
const f=document.getElementById("f"),btn=document.getElementById("go"),msg=document.getElementById("msg");
f.addEventListener("submit",async(e)=>{
  e.preventDefault();
  const body=Object.fromEntries(new FormData(f).entries());
  if(!body.user.trim()){msg.className="err";msg.textContent="Sag mir, wie du heisst.";return}
  btn.disabled=true;msg.className="";msg.textContent="Richte ein ...";
  try{
    const r=await fetch("/api/setup",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const d=await r.json();
    if(d.ok){msg.className="ok";msg.textContent="Fertig — dein Agent startet.";setTimeout(()=>location.href="/",900)}
    else{btn.disabled=false;msg.className="err";msg.textContent=d.error||"Unbekannter Fehler."}
  }catch(err){btn.disabled=false;msg.className="err";msg.textContent="Server nicht erreichbar: "+err}
});
</script>
</body>
</html>"""
