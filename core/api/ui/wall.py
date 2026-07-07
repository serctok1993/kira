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
<link rel="icon" href="/api/icon"/>
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
  #graph{position:fixed;inset:0;width:100%;height:100%;z-index:1;opacity:.82;
    -webkit-mask:radial-gradient(66% 50% at 50% 45%,#000 34%,transparent 86%);
    mask:radial-gradient(66% 50% at 50% 45%,#000 34%,transparent 86%)}
  /* LED-Bildschirmrand, faerbt mit dem Modus */
  .edge{position:fixed;inset:0;z-index:40;pointer-events:none;
    box-shadow:inset 0 0 2px var(--accent),inset 0 0 26px color-mix(in srgb,var(--accent) 42%,transparent),
      inset 0 0 70px color-mix(in srgb,var(--accent) 20%,transparent);transition:box-shadow .5s ease}
  /* rotierender LED-Sweep NUR wenn Bewegung an ist (data-anim=on). Standard: aus -> kein
     pausenloses Neu-Rendern des Wallpapers (spart Lively viel GPU/CPU), nur der ruhige Glow bleibt. */
  .edge::before{content:"";position:absolute;inset:0;padding:2.5px;opacity:0;
    background:conic-gradient(from var(--ang),transparent 0 8%,var(--accent) 20%,transparent 34% 58%,var(--accent) 72%,transparent 86% 100%);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
    -webkit-mask-composite:xor;mask-composite:exclude}
  body[data-anim="on"] .edge::before{opacity:1;animation:spin 7s linear infinite}
  body[data-mode="coding"] .edge::before{background:conic-gradient(from var(--ang),#ff004d,#ff8a00,#ffe600,#39ff14,#00e5ff,#b026ff,#ff004d);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude}
  @keyframes spin{to{--ang:360deg}}

  /* dezente Mini-Cockpit-Leiste: leichter Tint im Modus-Farbton, kaum Blur, klar lesbar (kein Zoomen noetig) */
  .topbar{position:fixed;top:0;left:0;right:0;z-index:3;display:flex;flex-direction:column;align-items:center;gap:11px;
    padding:11px 0 12px;pointer-events:none;
    background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 10%,rgba(6,4,11,.72)),rgba(6,4,11,.34) 82%,transparent);
    -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
    border-bottom:1px solid color-mix(in srgb,var(--accent) 22%,transparent)}
  .srow{display:flex;justify-content:center;gap:38px;flex-wrap:wrap;padding:0 24px}
  .stat{display:flex;flex-direction:column;align-items:center;text-align:center;text-shadow:0 1px 4px rgba(0,0,0,.95),0 0 2px rgba(0,0,0,.9)}
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
    <label>Größe <select id="w-size"><option value="klein">Klein</option><option value="mittel">Mittel</option><option value="gross">Groß</option><option value="riesig">Riesig</option></select></label>
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
  graphVault=(g&&g.vault)||graphVault;   // Vault-Name fuer obsidian://open beim Node-Klick
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
let ns=[],ls=[],cv,ctx,W,H,DPR=Math.min(2,devicePixelRatio||1),reduce=matchMedia('(prefers-reduced-motion:reduce)').matches,settle=0,drag=null,graphVault=null,dragStart=null,dragMoved=false,GX={},lastFloat=0;
/* Wallpaper-Einstellungen (Zahnrad) — leben im localStorage, das offene Wallpaper hoert per
   'storage'-Event mit -> aendere sie in einem Browser-Tab, der Desktop uebernimmt live. */
const MODE_RGB={chat:"176,38,255",work:"57,255,20",coding:"0,229,255"};
const POSX={links:0.32,mitte:0.5,rechts:0.68},SIZ={klein:0.72,mittel:1,gross:2.6,riesig:3.6};
let curG=null;   // zuletzt geladener Graph (fuer Re-Layout bei Groesse/Position)
let WALL={labels:true,motion:false,color:"vault",pos:"mitte",size:"gross"};   // Standard: Standbild (0% Last, smoother Desktop) + grosser Graph; Bewegung ueber das Zahnrad zuschaltbar
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
function setHomes(){for(const n of ns){n.hx=n.x;n.hy=n.y;if(n.ph==null){n.ph=Math.random()*6.283;n.sp=0.5+Math.random()*0.7;}}}
function layout(g){
  curG=g;const by={},sc=SCALE();settle=0;
  const raw=(g.nodes||[]).slice(0,120);
  // Gruppen (Ordner/Bereich) auf Baender ueber die Breite verteilen -> sichtbare Ordnung + Querformat.
  // Position verschiebt das ganze Feld (links/mitte/rechts), Groesse spreizt die Baender.
  const groups=[...new Set(raw.map(n=>n.group||"·"))],gN=groups.length||1,base=POSX[WALL.pos]||0.5;
  const span=Math.min(0.7,0.16+0.12*gN);GX={};
  groups.forEach((gp,k)=>{GX[gp]=base+((gN===1)?0:((k/(gN-1))-0.5)*span);});
  ns=raw.map((n,i)=>{const a=i*2.399,rr=(30+Math.random()*Math.min(W,H)*0.18)*sc,gx=GX[n.group||"·"]||base;
    const o={id:n.id,g0:n.color||"176,38,255",grp:(n.group||"·"),gx:gx,
      x:W*gx+Math.cos(a)*rr,y:CY()+Math.sin(a)*rr*0.7,vx:0,vy:0,deg:0};by[n.id]=o;return o;});
  ls=(g.links||[]).map(l=>[by[l.source],by[l.target]]).filter(p=>p[0]&&p[1]);
  ls.forEach(([a,b])=>{a.deg++;b.deg++;});
  ns.forEach(n=>{n.r=(2.3+Math.min(6.5,n.deg*0.8))*Math.sqrt(sc);});   // groesserer Knoten = mehr Verbindungen
  // vorab fertig rechnen -> der Graph erscheint direkt gesetzt & sauber verteilt (kein Zappeln)
  if(!reduce){for(let k=0;k<350;k++)sim();}
  setHomes();settle=999;   // Ruhelage merken; gilt als gesetzt (Loop schwebt sanft oder friert ein)
}
function sim(){   // force-directed, ruhig getaktet: Repulsion + Federn + Gruppen-Baender, starke Daempfung
  const cy=CY(),sc=SCALE(),REP=560*sc,LEN=64*sc,K=0.011,CL=2.4;
  for(let i=0;i<ns.length;i++){const a=ns[i];
    for(let j=i+1;j<ns.length;j++){const b=ns[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1;
      if(d2<50000){const d=Math.sqrt(d2),f=REP/d2;dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}}}
  for(const [a,b] of ls){let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-LEN)*K;dx/=d;dy/=d;
    a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}
  for(const n of ns){if(n.fx)continue;   // angefasster Knoten haengt an der Maus -> nicht integrieren
    n.vx+=(W*n.gx-n.x)*0.006;            // horizontal ans Gruppen-Band -> ordnet + zieht in die Breite
    n.vy+=(cy-n.y)*0.011;                // vertikal enger halten -> Querformat statt Kreis
    n.x+=Math.max(-CL,Math.min(CL,n.vx));n.y+=Math.max(-CL,Math.min(CL,n.vy));n.vx*=0.86;n.vy*=0.86;}
}
function render(){ctx.clearRect(0,0,W,H);const sc=SCALE();ctx.shadowBlur=0;
  // Schattierung: weicher dunkler Schleier hinter dem Graphen (folgt den Knoten) -> Punkte/Striche/
  // Labels bleiben auf JEDEM Hintergrund lesbar. Die Graph-Maske blendet die Raender ohnehin weich aus.
  if(ns.length){let mnx=1e9,mny=1e9,mxx=-1e9,mxy=-1e9;
    for(const n of ns){if(n.x<mnx)mnx=n.x;if(n.x>mxx)mxx=n.x;if(n.y<mny)mny=n.y;if(n.y>mxy)mxy=n.y;}
    const gx=(mnx+mxx)/2,gy=(mny+mxy)/2,rad=Math.hypot(mxx-mnx,mxy-mny)/2+120*Math.sqrt(sc);
    const sg=ctx.createRadialGradient(gx,gy,0,gx,gy,rad);
    sg.addColorStop(0,'rgba(5,3,11,.66)');sg.addColorStop(.55,'rgba(5,3,11,.44)');sg.addColorStop(1,'rgba(5,3,11,0)');
    ctx.fillStyle=sg;ctx.fillRect(0,0,W,H);}
  // Kanten: dunkle Unterlage + farbige Linie darueber = Kontrast auch auf hellen Stellen
  for(const [a,b] of ls){const ca=nodeColor(a),cb=nodeColor(b);const d=Math.hypot(b.x-a.x,b.y-a.y),al=Math.max(.42,1-d/(360*sc));
    ctx.strokeStyle='rgba(0,0,0,'+(al*.55)+')';ctx.lineWidth=2.4;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
    const gr=ctx.createLinearGradient(a.x,a.y,b.x,b.y);gr.addColorStop(0,'rgba('+ca+','+al+')');gr.addColorStop(1,'rgba('+cb+','+al+')');
    ctx.strokeStyle=gr;ctx.lineWidth=1.3;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}
  // Knoten: dunkler Ring (Absetzung) + heller Kern + farbiger Glow
  for(const n of ns){const c=nodeColor(n);
    ctx.shadowBlur=0;ctx.beginPath();ctx.arc(n.x,n.y,n.r+1.7,0,7);ctx.fillStyle='rgba(3,2,9,.72)';ctx.fill();
    ctx.shadowColor='rgba('+c+',.9)';ctx.shadowBlur=11;
    ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,7);ctx.fillStyle='rgba('+c+',1)';ctx.fill();}
  ctx.shadowBlur=0;
  // Labels: dunkle Kontur (strokeText) unter hellem Text -> scharf auf jedem Hintergrund
  if(WALL.labels){ctx.font='600 '+(11*Math.sqrt(sc)|0)+'px "Segoe UI",system-ui,sans-serif';ctx.textAlign='center';
    ctx.lineJoin='round';ctx.lineWidth=3.4;ctx.strokeStyle='rgba(0,0,0,.94)';ctx.fillStyle='rgba(246,242,254,.98)';
    for(const n of ns){if(n.deg>=2){const t=n.id.slice(0,24),y=n.y-n.r-5;ctx.strokeText(t,n.x,y);ctx.fillText(t,n.x,y);}}}
}
/* Loop stoppt, sobald der Graph gesetzt ist und "Bewegung" aus ist -> 0% CPU im Ruhezustand
   (genau das, was Lively sonst dauernd rendern liess). Aenderungen wecken ihn per kick(). */
const SETTLE_MAX=280;let raf=0;
function frame(ts){ts=ts||0;
  const active=!reduce&&(drag||settle<SETTLE_MAX);   // echte Physik: nur beim Setzen/Ziehen
  if(active){sim();settle++;if(settle>=SETTLE_MAX)setHomes();render();raf=requestAnimationFrame(frame);return;}
  if(reduce||!WALL.motion){render();raf=0;return;}   // "Bewegung" aus -> Standbild, 0% CPU
  if(ts-lastFloat<45){raf=requestAnimationFrame(frame);return;}   // ~22 fps: sanftes Schweben, sparsam
  lastFloat=ts;const A=3.4*Math.sqrt(SCALE());
  for(const n of ns){if(n.fx)continue;n.x=n.hx+Math.sin(ts*0.0005*n.sp+n.ph)*A;n.y=n.hy+Math.cos(ts*0.00042*n.sp+n.ph)*A*0.75;}
  render();raf=requestAnimationFrame(frame);}
function kick(){if(!raf)raf=requestAnimationFrame(frame);}
function relayout(){if(curG){layout(curG);kick();}}
/* Node anfassen & ziehen — der Rest folgt ueber die Federn (Obsidian-Gefuehl). Greift, wenn /wall
   in einem Fenster/Tab offen ist; die Wallpaper-Ebene hinter den Icons nimmt keine Maus an. */
function nodeAt(mx,my){let best=null,bd=1e9;for(const n of ns){const d=Math.hypot(n.x-mx,n.y-my),hit=Math.max(14,n.r+10);if(d<hit&&d<bd){bd=d;best=n;}}return best;}
function openObs(id){if(!graphVault)return;try{location.href="obsidian://open?vault="+encodeURIComponent(graphVault)+"&file="+encodeURIComponent(id);}catch(e){}}
function setupDrag(){cv.style.pointerEvents='auto';cv.style.cursor='default';
  cv.addEventListener('pointerdown',e=>{const r=cv.getBoundingClientRect(),n=nodeAt(e.clientX-r.left,e.clientY-r.top);
    if(n){drag=n;dragStart={x:e.clientX,y:e.clientY};dragMoved=false;n.fx=true;try{cv.setPointerCapture(e.pointerId);}catch(_){}settle=0;kick();}});
  cv.addEventListener('pointermove',e=>{const r=cv.getBoundingClientRect();
    if(!drag){cv.style.cursor=nodeAt(e.clientX-r.left,e.clientY-r.top)?'pointer':'default';return;}
    if(dragStart&&Math.hypot(e.clientX-dragStart.x,e.clientY-dragStart.y)>5)dragMoved=true;
    drag.x=e.clientX-r.left;drag.y=e.clientY-r.top;drag.vx=drag.vy=0;kick();});
  const up=()=>{if(!drag)return;const n=drag;n.fx=false;drag=null;settle=0;kick();
    if(!dragMoved)openObs(n.id);};   // kurzer Klick (nicht gezogen) -> Notiz in Obsidian oeffnen
  cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',up);}

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
function applyAnim(){document.body.dataset.anim=WALL.motion?"on":"off";}   // LED-Sweep nur bei Bewegung -> Standard spart Last
function syncWallUI(){$("#w-labels").checked=WALL.labels;$("#w-motion").checked=WALL.motion;$("#w-color").value=WALL.color;$("#w-pos").value=WALL.pos;$("#w-size").value=WALL.size;applyAnim();}
$("#gear").addEventListener('click',()=>{const p=$("#wpop");p.classList.toggle('on');if(p.classList.contains('on'))syncWallUI();});
$("#w-labels").addEventListener('change',e=>{WALL.labels=e.target.checked;saveWall();kick();});
$("#w-motion").addEventListener('change',e=>{WALL.motion=e.target.checked;saveWall();applyAnim();kick();});
$("#w-color").addEventListener('change',e=>{WALL.color=e.target.value;saveWall();kick();});
$("#w-pos").addEventListener('change',e=>{WALL.pos=e.target.value;saveWall();relayout();});
$("#w-size").addEventListener('change',e=>{WALL.size=e.target.value;saveWall();relayout();});
window.addEventListener('storage',e=>{if(e.key==="kira_wall"){loadWall();syncWallUI();relayout();}});   // aus einem Browser-Tab geaendert -> Wallpaper zieht live nach
document.addEventListener('click',e=>{if(!e.target.closest('#gear')&&!e.target.closest('#wpop')){const p=$("#wpop");if(p)p.classList.remove('on');}});

/* ---- Boot ---- */
(async function(){loadWall();await loadWallServer();applyAnim();cv=$("#graph");ctx=cv.getContext("2d");sz();setupDrag();
  const g=await loadStats();layout(g);kick();
  addEventListener('resize',()=>{sz();relayout();});
  connect();setInterval(loadStats,30000);   // Stats leben (alle 30 s frisch) — Graph bleibt ruhig
  setInterval(pollWall,3000);                // Einstellungen serverseitig -> Lively-Wallpaper zieht nach
})();
</script>
</body></html>"""
