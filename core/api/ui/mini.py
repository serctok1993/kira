"""Mini-Chat-Seite (/chat-mini): das kleine Schwebe-Fenster fuer den schnellen Gedanken.

Wird vom Desktop-App-Hotkey in einem rahmenlosen, immer-oben Fenster geladen (Phase 4). Anders
als der Wallpaper-Chat hat DIESES Fenster echten Tastatur-Fokus -> tippen, einfuegen, kopieren
funktioniert nativ. Ephemerer Chat ueber /ws/chat (frische Session je Aufruf), spiegelt keinen
App-Chat. Ein „Kira oeffnen"-Knopf holt die volle App (ueber die pywebview-Bruecke, sonst Cockpit
im Browser). PHRASES werden wie bei index()/wall ueber /*__PHRASES__*/ injiziert.
"""
from __future__ import annotations

MINI_HTML = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="icon" href="/api/icon"/>
<title>Kira</title>
<style>
  :root{
    --bg:#0a0712; --panel:#141019; --ink:#f3eefb; --muted:#9a92ad;
    --chat:#b026ff; --work:#39ff14; --coding:#00e5ff; --accent:var(--chat);
    --sans:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
  }
  *{box-sizing:border-box} html,body{height:100%}
  body{margin:0;font-family:var(--sans);color:var(--ink);overflow:hidden;background:transparent}
  /* die ganze Karte ist ziehbar (rahmenloses Fenster); Eingaben/Buttons bleiben klickbar */
  .card{height:100vh;display:flex;flex-direction:column;gap:8px;padding:10px;
    background:linear-gradient(160deg,color-mix(in srgb,var(--bg) 94%,transparent),#0e0a18);
    border:1px solid color-mix(in srgb,var(--accent) 42%,transparent);border-radius:16px;
    box-shadow:0 14px 44px rgba(0,0,0,.6),0 0 26px color-mix(in srgb,var(--accent) 22%,transparent)}
  .top{display:flex;align-items:center;gap:8px;-webkit-app-region:drag;cursor:move}
  .logo{width:22px;height:22px;border-radius:6px;object-fit:cover;flex:none}
  .name{font-weight:700;letter-spacing:.4px;font-size:13px;color:#efeaf6}
  .top .sp{flex:1}
  .kbtn,.xbtn{-webkit-app-region:no-drag;border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);
    background:rgba(255,255,255,.05);color:var(--accent);border-radius:8px;cursor:pointer;font:600 11px var(--sans)}
  .kbtn{padding:5px 10px} .xbtn{width:26px;height:26px;font-size:14px;display:grid;place-items:center}
  .kbtn:hover,.xbtn:hover{background:color-mix(in srgb,var(--accent) 16%,transparent)}
  .reply{-webkit-app-region:no-drag;min-height:0;flex:1;overflow:auto;font-size:13.5px;line-height:1.5;
    color:var(--ink);white-space:pre-wrap;padding:2px 2px}
  .reply.empty{color:var(--muted)}
  .think{display:flex;align-items:center;gap:8px;font-size:12px;min-height:16px;color:var(--muted)}
  .sh{color:var(--accent);animation:sp 3.4s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
  .tx{font-weight:600;background:linear-gradient(90deg,#b026ff,#ff2d95,#ff8a00,#39ff14,#00e5ff,#b026ff);
    background-size:300% 100%;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;animation:flow 3.2s linear infinite}
  @keyframes flow{to{background-position:-300% 0}}
  form{-webkit-app-region:no-drag;display:flex;align-items:center;gap:7px;padding:6px 6px 6px 10px;border-radius:12px;
    background:color-mix(in srgb,var(--bg) 62%,transparent);border:1px solid color-mix(in srgb,var(--accent) 40%,transparent)}
  .seg{display:flex;gap:2px;background:rgba(255,255,255,.05);border-radius:9px;padding:2px}
  .seg button{border:0;background:none;color:var(--muted);font:600 11px var(--sans);padding:5px 9px;border-radius:7px;cursor:pointer}
  .seg button.on{color:#0a0712;background:var(--accent)}
  #cin{flex:1;background:none;border:0;outline:none;color:var(--ink);font-size:14px;padding:0 4px;font-family:var(--sans)}
  #cin::placeholder{color:var(--muted)}
  .send{border:0;border-radius:9px;background:var(--accent);color:#0a0712;font:700 13px var(--sans);padding:7px 14px;cursor:pointer}
  @media (prefers-reduced-motion:reduce){.tx,.sh{animation:none}}
</style></head>
<body data-mode="chat">
  <div class="card">
    <div class="top">
      <img class="logo" src="/api/icon" onerror="this.style.display='none'" alt=""/>
      <span class="name">Kira</span>
      <span class="sp"></span>
      <button class="kbtn" id="open" title="Volle App oeffnen">Kira öffnen</button>
      <button class="xbtn" id="close" title="Schließen (Hotkey holt mich zurück)">✕</button>
    </div>
    <div class="reply empty" id="reply">Was geht dir durch den Kopf?</div>
    <div class="think" id="think"></div>
    <form id="bar" autocomplete="off">
      <div class="seg" id="seg">
        <button type="button" class="on" data-m="chat">Chat</button>
        <button type="button" data-m="work">Work</button>
        <button type="button" data-m="coding">Coding</button>
      </div>
      <input id="cin" placeholder="Schreib mir …" autofocus/>
      <button class="send" type="submit">↑</button>
    </form>
  </div>
<script>
const PHRASES=[/*__PHRASES__*/];
const $=s=>document.querySelector(s);
function rndPhrase(){return PHRASES.length?PHRASES[Math.floor(Math.random()*PHRASES.length)]:"denkt";}
function esc(s){return (s==null?"":""+s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

/* Cockpit-Farbanpassung uebernehmen (gleiche Origin -> gleicher localStorage) */
(function(){try{const c=JSON.parse(localStorage.getItem("kira_custom")||"{}");
  const map={bg:"--bg",panel:"--panel",accent:"--chat",ink:"--ink",muted:"--muted"};
  for(const k in map){if(c[k])document.documentElement.style.setProperty(map[k],c[k]);}
  if(c.font)document.documentElement.style.setProperty("--sans",c.font);
}catch(e){}})();

/* Modus + Akzentfarbe */
let mode="chat";const COL={chat:"var(--chat)",work:"var(--work)",coding:"var(--coding)"};
document.querySelectorAll('#seg button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#seg button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
  mode=b.dataset.m;document.body.dataset.mode=mode;document.documentElement.style.setProperty('--accent',COL[mode]);
  $("#cin").focus();
}));

/* ephemerer Chat ueber /ws/chat (frische Session je Aufruf) */
let ws,thinkTimer=null,running=false,reasonBuf="";
function stopPhrase(){if(thinkTimer){clearInterval(thinkTimer);thinkTimer=null;}}
function setThink(on){const el=$("#think");stopPhrase();
  if(on){const put=()=>el.innerHTML='<span class="sh">✦</span><span class="tx">'+esc(rndPhrase())+' …</span>';put();thinkTimer=setInterval(put,2600);}
  else el.innerHTML="";}
function connect(){const proto=location.protocol==="https:"?"wss":"ws";
  const sid="mini-"+Math.random().toString(16).slice(2,10);
  ws=new WebSocket(proto+"://"+location.host+"/ws/chat?sid="+encodeURIComponent(sid));
  ws.onmessage=ev=>{const m=JSON.parse(ev.data);
    if(m.done){setThink(false);running=false;return;}
    if(m.kind==="think"){stopPhrase();reasonBuf=(reasonBuf+" "+(m.text||"")).slice(-260);
      $("#think").innerHTML='<span class="sh">✦</span><span class="tx">'+esc(reasonBuf.trim())+'</span>';return;}
    if(m.kind==="tool"){stopPhrase();
      $("#think").innerHTML='<span class="sh">✦</span><span class="tx">▷ '+esc(m.name||"werkzeug")+' …</span>';return;}
    if(m.kind==="final"||m.kind==="answer"){setThink(false);reasonBuf="";
      const r=$("#reply");r.classList.remove('empty');r.textContent=(m.text||"");}
  };
  ws.onclose=()=>{setTimeout(connect,1500);};
}
$("#bar").addEventListener('submit',e=>{e.preventDefault();const raw=$("#cin").value.trim();if(!raw||running)return;
  if(!ws||ws.readyState!==1)return;
  const t=mode==="work"?("work: "+raw):mode==="coding"?("code: "+raw):raw;
  const r=$("#reply");r.classList.remove('empty');r.textContent="";
  $("#cin").value="";reasonBuf="";running=true;setThink(true);ws.send(t);
});

/* „Kira oeffnen" -> volle App via pywebview-Bruecke, sonst Cockpit im Browser */
$("#open").addEventListener('click',()=>{
  try{if(window.pywebview&&pywebview.api&&pywebview.api.open_app){pywebview.api.open_app();return;}}catch(e){}
  window.open(location.origin+"/","_blank");
});
/* Schliessen -> Fenster verstecken (Hotkey holt es zurueck); im Browser nur leeren */
$("#close").addEventListener('click',()=>{
  try{if(window.pywebview&&pywebview.api&&pywebview.api.hide_mini){pywebview.api.hide_mini();return;}}catch(e){}
});

connect();window.addEventListener('focus',()=>$("#cin").focus());$("#cin").focus();
</script>
</body></html>"""
