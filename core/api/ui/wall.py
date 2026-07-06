"""Desktop-Wallpaper-Seite (/wall): rahmenloses Mini-Cockpit fuers Live-Wallpaper.

Rendert Stats oben als Leiste, den LIVE Obsidian-Vault-Graph zentral & passiv, einen
ephemeren Chat-Balken unten (frisch je Aufruf, spiegelt keinen App-Chat) und einen
LED-Bildschirmrand, der mit dem Modus faerbt. Alle Farben sind CSS-Variablen und uebernehmen
die Cockpit-Anpassung (localStorage 'kira_custom', gleiche Origin) -> individualisierbar.

Eigene, in sich geschlossene Seite (kein Cockpit-Chrome). PHRASES werden wie bei index()
ueber /*__PHRASES__*/ injiziert.
"""
from __future__ import annotations

WALL_HTML = r"""<!doctype html><html lang="de"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="icon" href="data:,"/>
<title>Kira · Desktop</title>
<style>
  @property --ang{syntax:'<angle>';inherits:false;initial-value:0deg}
  :root{
    --bg:#0a0712; --panel:#141019; --ink:#f3eefb; --muted:#9a92ad;
    --chat:#b026ff; --work:#39ff14; --coding:#00e5ff; --green:#39ff14; --amber:#ffb02e;
    --accent:var(--chat);
    --mono:ui-monospace,"Cascadia Code",Menlo,Consolas,monospace;
    --sans:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
  }
  *{box-sizing:border-box} html,body{height:100%}
  body{margin:0;font-family:var(--sans);color:var(--ink);overflow:hidden;
    background:radial-gradient(1200px 700px at 72% 16%,#241536,transparent 60%),
      radial-gradient(900px 700px at 18% 94%,#0b2436,transparent 55%),
      linear-gradient(160deg,var(--bg),#0e0a18 55%,#080a14);}
  #graph{position:fixed;inset:0;width:100%;height:100%;z-index:1;opacity:.55;
    -webkit-mask:radial-gradient(58% 56% at 50% 45%,#000 30%,transparent 82%);
    mask:radial-gradient(58% 56% at 50% 45%,#000 30%,transparent 82%)}
  /* LED-Bildschirmrand, faerbt mit dem Modus */
  .edge{position:fixed;inset:0;z-index:40;pointer-events:none;
    box-shadow:inset 0 0 2px var(--accent),inset 0 0 26px color-mix(in srgb,var(--accent) 42%,transparent),
      inset 0 0 70px color-mix(in srgb,var(--accent) 20%,transparent);transition:box-shadow .5s ease}
  .edge::before{content:"";position:absolute;inset:0;padding:2.5px;
    background:conic-gradient(from var(--ang),transparent 0 8%,var(--accent) 20%,transparent 34% 58%,var(--accent) 72%,transparent 86% 100%);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude;animation:spin 7s linear infinite}
  body[data-mode="coding"] .edge::before{background:conic-gradient(from var(--ang),#ff004d,#ff8a00,#ffe600,#39ff14,#00e5ff,#b026ff,#ff004d);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude}
  @keyframes spin{to{--ang:360deg}}

  .topbar{position:fixed;top:28px;left:0;right:0;z-index:3;display:flex;flex-direction:column;align-items:center;gap:9px;pointer-events:none}
  .srow{display:flex;justify-content:center;gap:44px;flex-wrap:wrap;padding:0 24px}
  .stat{display:flex;flex-direction:column;align-items:center;text-align:center;text-shadow:0 1px 4px rgba(0,0,0,.85),0 0 22px rgba(0,0,0,.55)}
  .stat .n{font-family:var(--mono);font-size:27px;font-variant-numeric:tabular-nums;line-height:1;color:#fff;
    filter:drop-shadow(0 0 12px color-mix(in srgb,var(--accent) 55%,transparent))}
  .stat .n.g{color:var(--green)} .stat .n.a{color:var(--amber)}
  .stat .l{font-size:9.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin-top:4px}
  .sub{display:flex;gap:22px;flex-wrap:wrap;justify-content:center;font-size:12px;color:var(--muted);text-shadow:0 1px 4px #000}
  .sub b{color:#efeaf6;font-weight:600} .sub .live{color:var(--accent)}

  .talk{position:fixed;left:50%;bottom:64px;transform:translateX(-50%);z-index:5;width:min(680px,88vw);display:flex;flex-direction:column;gap:10px;align-items:center}
  .tline{font-size:13.5px;line-height:1.5;text-shadow:0 1px 5px #000;text-align:center;max-width:100%}
  .tline.me{color:#fff} .tline.k{color:var(--muted)}
  .think{display:flex;align-items:center;gap:8px;font-size:12.5px;min-height:18px}
  .sh{color:var(--accent);animation:sp 3.4s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
  .tx{font-weight:600;background:linear-gradient(90deg,#b026ff,#ff2d95,#ff8a00,#39ff14,#00e5ff,#b026ff);
    background-size:300% 100%;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;animation:flow 3.2s linear infinite}
  @keyframes flow{to{background-position:-300% 0}}
  .bar{display:flex;align-items:center;gap:8px;width:100%;padding:8px 8px 8px 12px;border-radius:16px;
    background:color-mix(in srgb,var(--bg) 62%,transparent);border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);
    backdrop-filter:blur(12px);box-shadow:0 10px 40px rgba(0,0,0,.5),0 0 22px color-mix(in srgb,var(--accent) 22%,transparent);transition:border-color .4s,box-shadow .4s}
  .seg{display:flex;gap:2px;background:rgba(255,255,255,.05);border-radius:10px;padding:3px}
  .seg button{border:0;background:none;color:var(--muted);font:600 12px var(--sans);letter-spacing:.3px;padding:6px 11px;border-radius:8px;cursor:pointer;transition:.2s}
  .seg button.on{color:#0a0712;background:var(--accent);box-shadow:0 0 14px color-mix(in srgb,var(--accent) 60%,transparent)}
  .ic{width:34px;height:34px;flex:none;border:0;border-radius:10px;cursor:pointer;font-size:17px;background:rgba(255,255,255,.06);color:var(--accent);display:grid;place-items:center}
  #cin{flex:1;background:none;border:0;outline:none;color:var(--ink);font-size:14px;padding:0 4px;font-family:var(--sans)}
  #cin::placeholder{color:var(--muted)}
  .model{font:600 11px var(--mono);color:var(--accent);border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);border-radius:20px;padding:5px 11px;white-space:nowrap}
  .tag{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:9;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);display:flex;gap:8px;align-items:center}
  .tag .d{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:bl 2s infinite}
  @keyframes bl{50%{opacity:.4}}
  @media (prefers-reduced-motion:reduce){.edge::before,.tx,.sh{animation:none}}
</style></head>
<body data-mode="chat">
  <canvas id="graph"></canvas>
  <div class="edge"></div>
  <div class="tag"><span class="d"></span> Ambienter Desktop · läuft immer</div>

  <div class="topbar">
    <div class="srow" id="srow"></div>
    <div class="sub" id="sub"></div>
  </div>

  <div class="talk">
    <div class="tline me" id="t-me"></div>
    <div class="tline k" id="t-k"></div>
    <div class="think" id="t-think"></div>
    <form class="bar" id="bar" autocomplete="off">
      <div class="seg" id="seg">
        <button type="button" class="on" data-m="chat">Chat</button>
        <button type="button" data-m="work">Work</button>
        <button type="button" data-m="coding">Coding</button>
      </div>
      <label class="ic" title="Bild einfügen">+<input id="imgfile" type="file" accept="image/*" style="display:none"/></label>
      <input id="cin" placeholder="Schreib mir …"/>
      <span class="model" id="model">—</span>
    </form>
  </div>

<script>
const PHRASES=[/*__PHRASES__*/];
const $=s=>document.querySelector(s);
function rndPhrase(){return PHRASES.length?PHRASES[Math.floor(Math.random()*PHRASES.length)]:"denkt";}

/* Cockpit-Farbanpassung uebernehmen (gleiche Origin -> gleicher localStorage) */
(function(){try{const c=JSON.parse(localStorage.getItem("kira_custom")||"{}");
  const map={bg:"--bg",panel:"--panel",accent:"--chat",ink:"--ink",muted:"--muted"};
  for(const k in map){if(c[k])document.documentElement.style.setProperty(map[k],c[k]);}
  if(c.font)document.documentElement.style.setProperty("--sans",c.font);
}catch(e){}})();

/* ---- Stats oben ---- */
function stat(n,l,cls){return '<div class="stat"><div class="n'+(cls?" "+cls:"")+'">'+n+'</div><div class="l">'+l+'</div></div>';}
async function loadStats(){
  let ov={},st={},g={counts:{notes:0,links:0}},bd={board:[]};
  try{ov=await (await fetch("/api/overview")).json();}catch(e){}
  try{st=await (await fetch("/api/status")).json();}catch(e){}
  try{g=await (await fetch("/api/vault/graph")).json();}catch(e){}
  try{bd=await (await fetch("/api/mission/board")).json();}catch(e){}
  const hb=ov.mission&&ov.mission.heartbeat;
  const tasks=Array.isArray(bd.board)?bd.board:(bd.board&&Array.isArray(bd.board.tasks)?bd.board.tasks:[]);
  const open=tasks.filter(t=>t&&t.status&&t.status!=="done").length;
  const spend=(st.spend_usd_today!=null)?st.spend_usd_today:0;
  const cap=(st.budget&&(st.budget.day_limit||st.budget.limit||st.budget.cap))||null;
  const errs=(st.errors_recent!=null)?st.errors_recent:0;
  $("#srow").innerHTML=
     stat(hb?"● an":"● aus","Motor",hb?"g":"")
    +stat(open+(tasks.length?'<span style="font-size:14px;color:var(--muted)">/'+tasks.length+'</span>':""),"Aufgaben")
    +stat(spend.toFixed(2).replace(".",",")+"€"+(cap?'<span style="font-size:14px;color:var(--muted)"> /'+cap+'€</span>':""),"Ausgaben heute","a")
    +stat(errs,"Fehler · 7 Tg",errs?"":"g")
    +stat(g.counts.notes,"Vault-Notizen")
    +stat(g.counts.links,"Verbindungen");
  const model=st.resolved_model||st.model||"—";
  const last=(ov.last_mission&&ov.last_mission.summary)?ov.last_mission.summary.slice(0,42):"—";
  $("#sub").innerHTML=
     '<span>Modell · <b class="live">'+esc(model)+'</b></span>'
    +'<span>Heartbeat · <b class="live">'+(hb?"ok":"aus")+'</b></span>'
    +'<span>Letzte Aktion · <b>'+esc(last)+'</b></span>';
  $("#model").textContent=model;
  return g;
}
function esc(s){return (s==null?"":""+s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

/* ---- Live-Vault-Graph ---- */
let ns=[],ls=[],cv,ctx,W,H,DPR=Math.min(2,devicePixelRatio||1),reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
function sz(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);}
function layout(g){
  const lx=()=>W*(0.27+0.46*Math.random()),ty=()=>H*(0.2+0.52*Math.random());
  const by={};ns=(g.nodes||[]).slice(0,140).map(n=>{const o={id:n.id,c:n.color||"176,38,255",x:lx(),y:ty(),vx:(Math.random()-.5)*.12,vy:(Math.random()-.5)*.12,r:1.7+Math.random()*2.4};by[n.id]=o;return o;});
  ls=(g.links||[]).map(l=>[by[l.source],by[l.target]]).filter(p=>p[0]&&p[1]);
}
function draw(t){ctx.clearRect(0,0,W,H);
  const lx=W*0.26,rx=W*0.74,ty=H*0.2,by=H*0.72;
  if(!reduce)for(const a of ns){a.x+=a.vx;a.y+=a.vy;if(a.x<lx||a.x>rx)a.vx*=-1;if(a.y<ty||a.y>by)a.vy*=-1;a.x=Math.max(lx,Math.min(rx,a.x));a.y=Math.max(ty,Math.min(by,a.y));}
  for(const [a,b] of ls){const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy);if(d>260)continue;const al=Math.max(.12,1-d/260);
    const gr=ctx.createLinearGradient(a.x,a.y,b.x,b.y);gr.addColorStop(0,'rgba('+a.c+','+(al*.5)+')');gr.addColorStop(1,'rgba('+b.c+','+(al*.5)+')');
    ctx.strokeStyle=gr;ctx.lineWidth=al*1.1+.3;ctx.shadowColor='rgba('+a.c+',.5)';ctx.shadowBlur=6;
    const mx=(a.x+b.x)/2-dy*.06,my=(a.y+b.y)/2+dx*.06;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.quadraticCurveTo(mx,my,b.x,b.y);ctx.stroke();}
  ctx.shadowBlur=0;
  for(let k=0;k<ns.length;k++){const n=ns[k],p=reduce?.75:.55+.45*Math.sin(t/700+k);ctx.shadowColor='rgba('+n.c+',.85)';ctx.shadowBlur=10;ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,7);ctx.fillStyle='rgba('+n.c+','+(.85*p)+')';ctx.fill();}
  ctx.shadowBlur=0;if(!reduce)requestAnimationFrame(draw);
}

/* ---- Modus + LED-Rand ---- */
let mode="chat";const COL={chat:"var(--chat)",work:"var(--work)",coding:"var(--coding)"};
document.querySelectorAll('#seg button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#seg button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
  mode=b.dataset.m;document.body.dataset.mode=mode;document.documentElement.style.setProperty('--accent',COL[mode]);
}));

/* ---- ephemerer Chat ueber /ws/chat (frische Session je Aufruf) ---- */
let ws,thinkTimer=null,running=false;
function setThink(on){const el=$("#t-think");if(thinkTimer){clearInterval(thinkTimer);thinkTimer=null;}
  if(on){const put=()=>el.innerHTML='<span class="sh">✦</span><span class="tx">'+esc(rndPhrase())+' …</span>';put();thinkTimer=setInterval(put,2600);}
  else el.innerHTML="";}
function connect(){const proto=location.protocol==="https:"?"wss":"ws";
  const sid="desktop-"+Math.random().toString(16).slice(2,10);   // ephemer: neu je Seitenaufruf
  ws=new WebSocket(proto+"://"+location.host+"/ws/chat?sid="+encodeURIComponent(sid));
  ws.onmessage=ev=>{const m=JSON.parse(ev.data);
    if(m.done){setThink(false);running=false;return;}
    if(m.kind==="final"||m.kind==="answer"){setThink(false);$("#t-k").textContent=(m.text||"").slice(0,320);}
  };
  ws.onclose=()=>{setTimeout(connect,1500);};
}
$("#bar").addEventListener('submit',e=>{e.preventDefault();const raw=$("#cin").value.trim();if(!raw||running)return;
  if(!ws||ws.readyState!==1)return;
  const t=mode==="work"?("work: "+raw):mode==="coding"?("code: "+raw):raw;
  $("#t-me").textContent=raw;$("#t-k").textContent="";$("#cin").value="";running=true;setThink(true);ws.send(t);
});
$("#imgfile").addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;
  const fd=new FormData();fd.append("file",f);
  try{const r=await (await fetch("/api/chat/attach",{method:"POST",body:fd})).json();
    if(r&&r.note)$("#cin").value=(($("#cin").value+" ").trimStart())+r.note;}catch(_){}
  e.target.value="";});

/* ---- Boot ---- */
(async function(){cv=$("#graph");ctx=cv.getContext("2d");sz();
  const g=await loadStats();layout(g);reduce?draw(0):requestAnimationFrame(draw);
  addEventListener('resize',()=>{sz();layout(g);if(reduce)draw(0);});
  connect();setInterval(loadStats,30000);   // Stats leben (alle 30 s frisch)
})();
</script>
</body></html>"""
