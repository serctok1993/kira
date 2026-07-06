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
  /* wechselbares Hintergrundbild (aus dem Cockpit gesetzt, /api/bg) — LED-Rand liegt drueber */
  #bg{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;opacity:.9}
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

  /* dezente Mini-Cockpit-Leiste: leichter Tint im Modus-Farbton, kaum Blur, klar lesbar (kein Zoomen noetig) */
  .topbar{position:fixed;top:0;left:0;right:0;z-index:3;display:flex;flex-direction:column;align-items:center;gap:11px;
    padding:11px 0 12px;pointer-events:none;
    background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 9%,rgba(8,6,12,.40)),rgba(8,6,12,.12) 80%,transparent);
    -webkit-backdrop-filter:blur(2px);backdrop-filter:blur(2px);
    border-bottom:1px solid color-mix(in srgb,var(--accent) 20%,transparent)}
  .srow{display:flex;justify-content:center;gap:38px;flex-wrap:wrap;padding:0 24px}
  .stat{display:flex;flex-direction:column;align-items:center;text-align:center;text-shadow:0 1px 3px rgba(0,0,0,.8)}
  .stat .n{font-family:var(--mono);font-size:22px;font-variant-numeric:tabular-nums;line-height:1;color:#fff;
    filter:drop-shadow(0 0 9px color-mix(in srgb,var(--accent) 45%,transparent))}
  .stat .n.g{color:var(--green)} .stat .n.a{color:var(--amber)}
  .stat .l{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);margin-top:5px}
  .sub{display:flex;gap:20px;flex-wrap:wrap;justify-content:center;font-size:11.5px;color:var(--muted);text-shadow:0 1px 4px #000}
  /* Einstell-Zahnrad (nur klickbar, wenn /wall im Browser/Fenster offen ist — steuert das Wallpaper live) */
  .gear{position:fixed;top:10px;right:14px;z-index:12;pointer-events:auto;cursor:pointer;width:30px;height:30px;border:0;border-radius:9px;
    background:rgba(10,8,16,.5);color:var(--accent);font-size:16px;display:grid;place-items:center;
    border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);backdrop-filter:blur(4px)}
  .gear:hover{background:color-mix(in srgb,var(--accent) 18%,transparent)}
  .wpop{position:fixed;top:46px;right:14px;z-index:12;display:none;min-width:184px;padding:10px;border-radius:12px;
    background:rgba(12,9,18,.95);border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);box-shadow:0 12px 40px rgba(0,0,0,.6);pointer-events:auto}
  .wpop.on{display:block}
  .wpop label{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--ink);padding:6px 4px;cursor:pointer}
  .wpop select{margin-left:auto;background:var(--bg);color:var(--ink);border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);border-radius:7px;font-size:12px;padding:3px 6px}
  .wpop .wt{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);padding:2px 4px 6px}
  .sub b{color:#efeaf6;font-weight:600} .sub .live{color:var(--accent)}

  .talk{position:fixed;left:50%;bottom:94px;transform:translateX(-50%);z-index:5;width:min(680px,88vw);display:flex;flex-direction:column;gap:10px;align-items:center}
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
  .model{font:600 11px var(--mono);color:var(--accent);border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);border-radius:20px;padding:5px 11px;white-space:nowrap;cursor:pointer}
  .model:hover{background:color-mix(in srgb,var(--accent) 14%,transparent)}
  .mpop{position:absolute;bottom:calc(100% + 8px);right:0;z-index:20;min-width:230px;max-height:300px;overflow:auto;
    background:rgba(12,9,18,.97);border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);border-radius:12px;padding:6px;
    box-shadow:0 12px 40px rgba(0,0,0,.6);display:none}
  .mpop.on{display:block}
  .mrow{padding:7px 10px;border-radius:8px;font-size:12px;cursor:pointer;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:var(--mono)}
  .mrow:hover{background:color-mix(in srgb,var(--accent) 18%,transparent)}
  .tag{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:9;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);display:flex;gap:8px;align-items:center}
  .tag .d{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:bl 2s infinite}
  @keyframes bl{50%{opacity:.4}}
  @media (prefers-reduced-motion:reduce){.edge::before,.tx,.sh{animation:none}}
</style></head>
<body data-mode="chat">
  <img id="bg" src="/api/bg" onerror="this.style.display='none'" alt=""/>
  <canvas id="graph"></canvas>
  <div class="edge"></div>
  <button class="gear" id="gear" title="Desktop-Einstellungen">⚙</button>
  <div class="wpop" id="wpop">
    <div class="wt">Vault-Graph</div>
    <label><input type="checkbox" id="w-labels"/> Worte (Labels)</label>
    <label><input type="checkbox" id="w-motion"/> Bewegung</label>
    <label>Farbe <select id="w-color"><option value="vault">Vault</option><option value="modus">Modus</option><option value="mono">Mono</option></select></label>
    <label>Position <select id="w-pos"><option value="links">Links</option><option value="mitte">Mitte</option><option value="rechts">Rechts</option></select></label>
    <label>Größe <select id="w-size"><option value="klein">Klein</option><option value="mittel">Mittel</option><option value="gross">Groß</option></select></label>
  </div>

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
      <span style="position:relative">
        <span class="model" id="model" title="Modell wechseln (Klick)">—</span>
        <div class="mpop" id="mpop"></div>
      </span>
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
  let ov={},st={},g={counts:{notes:0,links:0}},bd={board:[]},news={};
  try{ov=await (await fetch("/api/overview")).json();}catch(e){}
  try{st=await (await fetch("/api/status")).json();}catch(e){}
  try{g=await (await fetch("/api/vault/graph")).json();}catch(e){}
  try{bd=await (await fetch("/api/mission/board")).json();}catch(e){}
  try{news=await (await fetch("/api/news")).json();}catch(e){}
  let life={board:[]},mail={count:null},sys={};
  try{life=await (await fetch("/api/life/board")).json();}catch(e){}
  try{mail=await (await fetch("/api/mails/unread")).json();}catch(e){}
  try{sys=await (await fetch("/api/system")).json();}catch(e){}
  const newsN=(news.items||news.news||[]).length;
  const lifeB=Array.isArray(life.board)?life.board:(life.board&&Array.isArray(life.board.tasks)?life.board.tasks:[]);
  const todosN=lifeB.filter(t=>t&&t.status&&t.status!=="done").length;
  const mailsN=(mail&&mail.count!=null)?mail.count:null;
  const pc=v=>v==null?"—":v;                       // System-Werte: „—" wenn Quelle fehlt
  const temp=(sys.gpu_temp!=null)?sys.gpu_temp:sys.cpu_temp;
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
    +stat(g.counts.links,"Verbindungen")
    +stat(todosN,"To-Dos")
    +stat(mailsN==null?"—":mailsN,"Mails",mailsN?"a":"")
    +stat(newsN,"News")
    +stat(pc(sys.cpu)+(sys.cpu!=null?"%":""),"CPU")
    +stat(pc(sys.gpu)+(sys.gpu!=null?"%":""),"GPU")
    +stat(pc(temp)+(temp!=null?"°":""),"Temp",temp!=null&&temp>=75?"a":"");
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
let ns=[],ls=[],cv,ctx,W,H,DPR=Math.min(2,devicePixelRatio||1),reduce=matchMedia('(prefers-reduced-motion:reduce)').matches,settle=0;
/* Wallpaper-Einstellungen (Zahnrad) — leben im localStorage, das offene Wallpaper hoert per
   'storage'-Event mit -> aendere sie in einem Browser-Tab, der Desktop uebernimmt live. */
const MODE_RGB={chat:"176,38,255",work:"57,255,20",coding:"0,229,255"};
const POSX={links:0.32,mitte:0.5,rechts:0.68},SIZ={klein:0.72,mittel:1,gross:1.4};
let curG=null;   // zuletzt geladener Graph (fuer Re-Layout bei Groesse/Position)
let WALL={labels:true,motion:false,color:"vault",pos:"mitte",size:"mittel"};   // Bewegung AUS = ruhig + spart CPU
function loadWall(){try{Object.assign(WALL,JSON.parse(localStorage.getItem("kira_wall")||"{}"));}catch(e){}}
async function loadWallServer(){try{const s=await (await fetch("/api/wall/settings")).json();if(s&&typeof s==="object")Object.assign(WALL,s);}catch(e){}}
function saveWall(){try{localStorage.setItem("kira_wall",JSON.stringify(WALL));}catch(e){}
  try{fetch("/api/wall/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(WALL)});}catch(e){}}
let _wallSig="";
async function pollWall(){try{const raw=await (await fetch("/api/wall/settings")).text();if(raw===_wallSig)return;_wallSig=raw;
  const s=JSON.parse(raw||"{}");const op=WALL.pos,os=WALL.size;Object.assign(WALL,s);
  try{syncWallUI();}catch(e){}
  if(WALL.pos!==op||WALL.size!==os)relayout();else kick();}catch(e){}}
function nodeColor(n){return WALL.color==="modus"?(MODE_RGB[mode]||"176,38,255"):WALL.color==="mono"?"233,228,244":n.g0;}
function sz(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);}
const CX=()=>W*(POSX[WALL.pos]||0.5), CY=()=>H*0.46, SCALE=()=>SIZ[WALL.size]||1;
function layout(g){
  curG=g;const by={},sc=SCALE();settle=0;
  ns=(g.nodes||[]).slice(0,120).map((n,i)=>{const a=i*2.399,rr=(36+Math.random()*Math.min(W,H)*0.2)*sc;
    const o={id:n.id,g0:n.color||"176,38,255",x:CX()+Math.cos(a)*rr,y:CY()+Math.sin(a)*rr,vx:0,vy:0,deg:0};by[n.id]=o;return o;});
  ls=(g.links||[]).map(l=>[by[l.source],by[l.target]]).filter(p=>p[0]&&p[1]);
  ls.forEach(([a,b])=>{a.deg++;b.deg++;});
  ns.forEach(n=>{n.r=(2.3+Math.min(6.5,n.deg*0.8))*Math.sqrt(sc);});   // groesserer Knoten = mehr Verbindungen
  // vorab fertig rechnen -> der Graph erscheint direkt gesetzt (kein sichtbares Zappeln/Flackern)
  if(!reduce){for(let k=0;k<200;k++)sim();}
  settle=999;   // gilt als gesetzt: der Loop rendert 1x und friert ein (ausser "Bewegung" ist an)
}
function sim(){   // force-directed, ruhig getaktet: Repulsion + Federn + sanfte Zentrierung, starke Daempfung
  const cx=CX(),cy=CY(),sc=SCALE(),REP=470*sc,LEN=60*sc,K=0.012,CL=2.4;
  for(let i=0;i<ns.length;i++){const a=ns[i];
    for(let j=i+1;j<ns.length;j++){const b=ns[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1;
      if(d2<50000){const d=Math.sqrt(d2),f=REP/d2;dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}}}
  for(const [a,b] of ls){let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-LEN)*K;dx/=d;dy/=d;
    a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}
  for(const n of ns){n.vx+=(cx-n.x)*0.005;n.vy+=(cy-n.y)*0.005;
    n.x+=Math.max(-CL,Math.min(CL,n.vx));n.y+=Math.max(-CL,Math.min(CL,n.vy));n.vx*=0.86;n.vy*=0.86;}
}
function render(){ctx.clearRect(0,0,W,H);const sc=SCALE();
  for(const [a,b] of ls){const ca=nodeColor(a),cb=nodeColor(b);const d=Math.hypot(b.x-a.x,b.y-a.y),al=Math.max(.14,1-d/(320*sc));
    const gr=ctx.createLinearGradient(a.x,a.y,b.x,b.y);gr.addColorStop(0,'rgba('+ca+','+(al*.55)+')');gr.addColorStop(1,'rgba('+cb+','+(al*.55)+')');
    ctx.strokeStyle=gr;ctx.lineWidth=al*1.0+.3;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}
  for(const n of ns){const c=nodeColor(n);ctx.shadowColor='rgba('+c+',.85)';ctx.shadowBlur=9;
    ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,7);ctx.fillStyle='rgba('+c+',.92)';ctx.fill();}
  ctx.shadowBlur=0;
  if(WALL.labels){ctx.font=(10*Math.sqrt(sc)|0)+'px "Segoe UI",system-ui,sans-serif';ctx.textAlign='center';
    ctx.shadowColor='rgba(0,0,0,.9)';ctx.shadowBlur=3;ctx.fillStyle='rgba(233,228,244,.8)';
    for(const n of ns){if(n.deg>=2)ctx.fillText(n.id.slice(0,24),n.x,n.y-n.r-4);}
    ctx.shadowBlur=0;}
}
/* Loop stoppt, sobald der Graph gesetzt ist und "Bewegung" aus ist -> 0% CPU im Ruhezustand
   (genau das, was Lively sonst dauernd rendern liess). Aenderungen wecken ihn per kick(). */
const SETTLE_MAX=280;let raf=0;
function frame(){const moving=!reduce&&(WALL.motion||settle<SETTLE_MAX);
  if(moving){sim();settle++;}
  render();
  raf=moving?requestAnimationFrame(frame):0;}
function kick(){if(!raf)raf=requestAnimationFrame(frame);}
function relayout(){if(curG){layout(curG);kick();}}

/* ---- Modus + LED-Rand ---- */
let mode="chat";const COL={chat:"var(--chat)",work:"var(--work)",coding:"var(--coding)"};
document.querySelectorAll('#seg button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#seg button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
  mode=b.dataset.m;document.body.dataset.mode=mode;document.documentElement.style.setProperty('--accent',COL[mode]);kick();
}));

/* ---- ephemerer Chat ueber /ws/chat (frische Session je Aufruf) ---- */
let ws,thinkTimer=null,running=false,reasonBuf="";
function stopPhrase(){if(thinkTimer){clearInterval(thinkTimer);thinkTimer=null;}}
function setThink(on){const el=$("#t-think");stopPhrase();
  if(on){const put=()=>el.innerHTML='<span class="sh">✦</span><span class="tx">'+esc(rndPhrase())+' …</span>';put();thinkTimer=setInterval(put,2600);}
  else el.innerHTML="";}
function connect(){const proto=location.protocol==="https:"?"wss":"ws";
  const sid="desktop-"+Math.random().toString(16).slice(2,10);   // ephemer: neu je Seitenaufruf
  ws=new WebSocket(proto+"://"+location.host+"/ws/chat?sid="+encodeURIComponent(sid));
  ws.onmessage=ev=>{const m=JSON.parse(ev.data);
    if(m.done){setThink(false);running=false;return;}
    if(m.kind==="think"){stopPhrase();reasonBuf=(reasonBuf+" "+(m.text||"")).slice(-260);   // echtes Reasoning
      $("#t-think").innerHTML='<span class="sh">✦</span><span class="tx">'+esc(reasonBuf.trim())+'</span>';return;}
    if(m.kind==="tool"){stopPhrase();
      $("#t-think").innerHTML='<span class="sh">✦</span><span class="tx">▷ '+esc(m.name||"werkzeug")+' …</span>';return;}
    if(m.kind==="final"||m.kind==="answer"){setThink(false);reasonBuf="";$("#t-k").textContent=(m.text||"").slice(0,340);}
  };
  ws.onclose=()=>{setTimeout(connect,1500);};
}
$("#bar").addEventListener('submit',e=>{e.preventDefault();const raw=$("#cin").value.trim();if(!raw||running)return;
  if(!ws||ws.readyState!==1)return;
  const t=mode==="work"?("work: "+raw):mode==="coding"?("code: "+raw):raw;
  $("#t-me").textContent=raw;$("#t-k").textContent="";$("#cin").value="";reasonBuf="";running=true;setThink(true);ws.send(t);
});
$("#imgfile").addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;
  const fd=new FormData();fd.append("file",f);
  try{const r=await (await fetch("/api/chat/attach",{method:"POST",body:fd})).json();
    if(r&&r.note)$("#cin").value=(($("#cin").value+" ").trimStart())+r.note;}catch(_){}
  e.target.value="";});

/* ---- Modellwechsel per Klick ---- */
$("#model").addEventListener('click',async ()=>{
  const pop=$("#mpop");
  if(pop.classList.contains('on')){pop.classList.remove('on');return;}
  pop.innerHTML='<div class="mrow">lädt …</div>';pop.classList.add('on');
  try{const d=await (await fetch("/api/model/catalog")).json();
    const all=[];const cat=d.catalog||{};
    for(const k in cat){if(Array.isArray(cat[k]))cat[k].forEach(m=>{if(m&&m.id)all.push(m);});}
    pop.innerHTML=all.slice(0,50).map(m=>'<div class="mrow" data-id="'+esc(m.id)+'" title="'+esc(m.id)+'">'+esc((m.name||m.id))+'</div>').join('')||'<div class="mrow">keine Modelle</div>';
    pop.querySelectorAll('.mrow[data-id]').forEach(r=>r.addEventListener('click',async ()=>{
      const id=r.dataset.id;
      try{await fetch("/api/model/role",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role:"chat",model:id})});}catch(_){}
      $("#model").textContent=id.split("/").pop();pop.classList.remove('on');loadStats();
    }));
  }catch(e){pop.innerHTML='<div class="mrow">Fehler</div>';}
});
document.addEventListener('click',e=>{if(!e.target.closest('#model')&&!e.target.closest('#mpop')){const p=$("#mpop");if(p)p.classList.remove('on');}});

/* ---- Zahnrad: Graph-Einstellungen (Worte/Bewegung/Farbe), live ueber localStorage ---- */
function syncWallUI(){$("#w-labels").checked=WALL.labels;$("#w-motion").checked=WALL.motion;$("#w-color").value=WALL.color;$("#w-pos").value=WALL.pos;$("#w-size").value=WALL.size;}
$("#gear").addEventListener('click',()=>{const p=$("#wpop");p.classList.toggle('on');if(p.classList.contains('on'))syncWallUI();});
$("#w-labels").addEventListener('change',e=>{WALL.labels=e.target.checked;saveWall();kick();});
$("#w-motion").addEventListener('change',e=>{WALL.motion=e.target.checked;saveWall();kick();});
$("#w-color").addEventListener('change',e=>{WALL.color=e.target.value;saveWall();kick();});
$("#w-pos").addEventListener('change',e=>{WALL.pos=e.target.value;saveWall();relayout();});
$("#w-size").addEventListener('change',e=>{WALL.size=e.target.value;saveWall();relayout();});
window.addEventListener('storage',e=>{if(e.key==="kira_wall"){loadWall();syncWallUI();relayout();}});   // aus einem Browser-Tab geaendert -> Wallpaper zieht live nach
document.addEventListener('click',e=>{if(!e.target.closest('#gear')&&!e.target.closest('#wpop')){const p=$("#wpop");if(p)p.classList.remove('on');}});

/* ---- Boot ---- */
(async function(){loadWall();await loadWallServer();cv=$("#graph");ctx=cv.getContext("2d");sz();
  const g=await loadStats();layout(g);kick();
  addEventListener('resize',()=>{sz();relayout();});
  connect();setInterval(loadStats,30000);   // Stats leben (alle 30 s frisch) — Graph bleibt ruhig
  setInterval(pollWall,3000);                // Einstellungen serverseitig -> Lively-Wallpaper zieht nach
})();
</script>
</body></html>"""
