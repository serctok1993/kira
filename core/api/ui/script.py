"""Cockpit-Logik (vanilla JS): nav, Loader, Chat-WebSocket (Vertrag: role/kind/done)."""

SCRIPT = r"""<script>
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
/* Zentrales HTML-Escaping: JEDER dynamische Anzeigetext geht hier durch (XSS-Wache). */
function esc(x){return (""+(x==null?"":x)).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
/* ---- S6.4: Toast-Fehlerflaeche + Fetch-Wrapper J() (Fehler werden SICHTBAR, nicht stumm verschluckt) ---- */
function toast(msg,kind){let box=$("#toasts");if(!box){box=document.createElement("div");box.id="toasts";document.body.appendChild(box);}
 const t=document.createElement("div");t.className="toast"+(kind==="err"?" err":kind==="ok"?" ok":"");t.textContent=msg;box.appendChild(t);
 setTimeout(()=>{t.classList.add("out");setTimeout(()=>t.remove(),400);},kind==="err"?5200:2600);}
let pollFails=0;
async function J(url,opts){try{const r=await fetch(url,opts);
  if(!r.ok){pollFails++;let d=null;try{d=await r.clone().json();}catch(e){}
   if(r.status!==409)toast((d&&(d.error||d.detail))||("Fehler "+r.status+" bei "+url.split("?")[0]),"err");
   const e=new Error("http "+r.status);e.status=r.status;e.data=d;throw e;}
  pollFails=0;return await r.json();
 }catch(e){if(e.status===undefined){pollFails++;toast("Netzwerkfehler: "+url.split("?")[0],"err");}throw e;}}
/* Kiras Denk-Sprueche (eine Quelle, beim Ausliefern injiziert) */
const PHRASES=[/*__PHRASES__*/];
let _lastPhrase="";
function rndPhrase(){if(PHRASES.length<2)return PHRASES[0]||"ich denke kurz nach";
 let p=PHRASES[Math.floor(Math.random()*PHRASES.length)],g=0;
 while(p===_lastPhrase&&g++<8)p=PHRASES[Math.floor(Math.random()*PHRASES.length)];
 _lastPhrase=p;return p;}
let cur="home";
$$("#side a").forEach(a=>a.onclick=()=>{nav(a.dataset.v);document.body.classList.remove("side-open");});
/* S6.4: mobiles Seitenmenue ein-/ausklappen */
$("#burger")&&($("#burger").onclick=()=>document.body.classList.toggle("side-open"));
function nav(v){cur=v;const go=()=>{$$("#side a").forEach(a=>a.classList.toggle("on",a.dataset.v===v));
 $$(".view").forEach(x=>x.classList.remove("on"));$("#v-"+v).classList.add("on");};
 if(document.startViewTransition&&!matchMedia("(prefers-reduced-motion: reduce)").matches){document.startViewTransition(go);}else{go();}
 if(v==="home")loadCommand();
 if(v==="chat"){loadChatModels();loadChatSessions();loadChatProjects();}
 if(v==="me")loadMe();
 if(v==="projekte")loadProjekte();  /* S9.3: eine Uebersicht statt Subtabs */
 if(SUBTABS[v])subnav(v,SUBTABS[v].cur);}

/* ==== S7a: modulare Shell — EINE Subtab-Mechanik fuer alle Bereiche ====
   Neue Bereiche/Unterreiter andocken = Eintrag hier + Markup (subview id="v-<s>").
   Kein Spezialcode pro Tab mehr (vorher: syst() + kirat() doppelt). */
const SUBTABS={
 kira:    {bar:"#kira-tabs", cur:"files",
           loaders:{files:()=>loadFiles(),charakter:()=>loadCharakter(),mem:()=>loadMem(),wissen:()=>loadWissen(),
                    playbooks:()=>loadPlaybooks(),
                    anatomie:()=>loadAgenten(),evolution:()=>loadEvolution(),stats:()=>loadStats(),
                    keys:()=>loadKeys(),checkliste:()=>loadCheckliste(),
                    /* Config aufgeloest: Technik lebt jetzt unter Kira */
                    models:()=>loadModels(),bench:()=>loadBench(),steuer:()=>loadSteuer(),gov:()=>loadGov(),
                    cron:()=>loadCron(),monitor:()=>loadMonitor(),log:()=>loadEvents(),cockpit:()=>loadDesktop(),
                    wall:()=>loadWallEditor()}},
 me:      {bar:"#me-tabs", cur:"todos",
           loaders:{todos:()=>loadLeben(),freigaben:()=>{loadInbox();loadTodoSecrets();},
                    routinen:()=>loadMeCrons(),post:()=>{},metriken:()=>loadZiele()}}};

/* ---- Desktop-Pflege (S8.5) ---- */
async function loadDesktop(){const st=$("#dw-status");if(!st)return;try{
 const d=await (await fetch("/api/desktop")).json();const c=d.config||{};
 if($("#dw-enabled"))$("#dw-enabled").checked=!!c.enabled;
 if($("#dw-folders")&&document.activeElement!==$("#dw-folders"))$("#dw-folders").value=(c.folders||[]).join("; ");
 const p=d.preview||{};
 st.textContent=c.enabled?((p.suggestions||[]).length+" von "+(p.scanned||0)+" Dateien haetten einen Sortier-Vorschlag"):"aus — aktiviere, damit ich aufraeume";
}catch(e){}}
$("#dw-save")&&($("#dw-save").onclick=async()=>{
 const folders=$("#dw-folders").value.split(";").map(x=>x.trim()).filter(Boolean);
 await fetch("/api/desktop/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:$("#dw-enabled").checked,folders})});
 toast("Desktop-Pflege gespeichert","ok");loadDesktop();});
$("#dw-scan")&&($("#dw-scan").onclick=async()=>{$("#dw-status").textContent="… scanne";
 const r=await (await fetch("/api/desktop/scan",{method:"POST"})).json();
 $("#dw-status").textContent=r.suggestions?("✓ "+r.suggestions+" Dateien — Vorschlag liegt bei Me unter Von Kira"):(r.skipped?"erst aktivieren":"nichts zu sortieren");});
/* ---- Wallpaper-Editor (Desktop Phase 2): /wall live einstellen, serverseitig gespeichert ---- */
const WP_STATS=[["motor","Motor"],["aufgaben","Aufgaben"],["ausgaben","Ausgaben"],["fehler","Fehler"],
 ["notizen","Vault-Notizen"],["verbindungen","Verbindungen"],["todos","To-Dos"],["mails","Mails"],
 ["news","News"],["cpu","CPU"],["gpu","GPU"],["temp","Temp"]];
async function loadWallEditor(){if(!$("#wp-stats"))return;
 let s={};try{s=await (await fetch("/api/wall/settings")).json();}catch(e){}
 const sel=(Array.isArray(s.stats)&&s.stats.length)?s.stats:WP_STATS.map(x=>x[0]);
 $("#wp-stats").innerHTML=WP_STATS.map(([k,l])=>'<label class="muted" style="cursor:pointer"><input type="checkbox" data-st="'+k+'"'+(sel.indexOf(k)>=0?' checked':'')+'/> '+esc(l)+'</label>').join("");
 $("#wp-labels").checked=s.labels!==false;
 $("#wp-motion").checked=!!s.motion;
 $("#wp-color").value=s.color||"vault";
 $("#wp-pos").value=s.pos||"mitte";
 $("#wp-size").value=s.size||"gross";
 const c=s.colors||{};
 $("#wp-c-chat").value=c.chat||"#b026ff";$("#wp-c-work").value=c.work||"#39ff14";$("#wp-c-coding").value=c.coding||"#00e5ff";}
function wpGather(){
 const stats=$$("#wp-stats input[data-st]").filter(x=>x.checked).map(x=>x.dataset.st);
 return {labels:$("#wp-labels").checked,motion:$("#wp-motion").checked,color:$("#wp-color").value,
  pos:$("#wp-pos").value,size:$("#wp-size").value,stats:stats,
  colors:{chat:$("#wp-c-chat").value,work:$("#wp-c-work").value,coding:$("#wp-c-coding").value}};}
async function wpSave(body){
 try{await fetch("/api/wall/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||wpGather())});}catch(e){}
 const f=$("#wp-prev");if(f)f.contentWindow.location.reload();   // Vorschau sofort aktualisieren
 if($("#wp-status")){$("#wp-status").textContent="gespeichert ✓";setTimeout(()=>{if($("#wp-status"))$("#wp-status").textContent="";},1600);}}
$("#wp-save")&&($("#wp-save").onclick=()=>wpSave());
$("#wp-reset")&&($("#wp-reset").onclick=async()=>{await wpSave({labels:true,motion:false,color:"vault",pos:"mitte",size:"gross",stats:null,colors:null});loadWallEditor();});
$("#wp-open")&&($("#wp-open").onclick=()=>window.open("/wall","_blank"));

/* ---- Playbooks (S11): feste Ablaeufe mit Reifegrad + Lernschleife ---- */
async function loadPlaybooks(){const el=$("#pb-list");if(!el)return;try{
 const d=await (await fetch("/api/playbooks")).json();const pbs=d.playbooks||[];
 if(!pbs.length){el.innerHTML='<span class="muted">Noch keine Playbooks — kopiere playbooks/_VORLAGE.md als Start.</span>';return;}
 const badge=g=>g==="autonom"?"kira":(g==="begleitet"?"you":"kind");
 el.innerHTML=pbs.map(p=>'<div class="memrow"><div class="mh">'
  +'<span class="badge '+badge(p.reifegrad)+'">'+esc(p.reifegrad)+'</span>'
  +'<b style="color:var(--ink);font-size:13px">'+esc(p.titel||p.name)+'</b>'
  +'<span class="muted" style="font-size:11px">'+(p.erfolge|0)+' Erfolge · '+(p.fehlschlaege|0)+' Fehlschlaege · '
  +(p.lektionen|0)+' Lektionen · Serie '+(p.serie|0)+'/'+(d.promote_after||5)
  +(p.letzte?(' · zuletzt '+esc(p.letzte)):'')+'</span>'
  +'</div><div style="font-size:12.5px">'+esc(p.wann||'')+'</div></div>').join("");
}catch(e){el.innerHTML='<span class="muted">Playbooks nicht ladbar.</span>';}}

/* ---- System-Checkliste (HANDBUCH-Paragraphen als Live-Ampeln) ---- */
async function loadCheckliste(){const el=$("#ck-list");if(!el)return;try{
 const [ck,ov,dg,pb]=await Promise.all([
  fetch("/api/checkliste").then(r=>r.json()),
  fetch("/api/overview").then(r=>r.json()),
  fetch("/api/digest").then(r=>r.json()).catch(()=>({})),
  fetch("/api/playbooks").then(r=>r.json()).catch(()=>({playbooks:[]}))]);
 const rows=[];
 const row=(ampel,titel,detail)=>rows.push('<div class="memrow"><div class="mh">'
  +'<span class="badge" style="color:var(--'+(ampel==="ok"?"ok":ampel==="warn"?"warn":"danger")+')">'
  +(ampel==="ok"?"OK":ampel==="warn"?"WARTET":"KLEMMT")+'</span>'
  +'<b style="color:var(--ink);font-size:13px">'+titel+'</b></div>'
  +'<div style="font-size:12.5px" class="muted">'+detail+'</div></div>');
 const hb=(ov.mission&&ov.mission.heartbeat);
 row(hb?"ok":"warn","§2 Heartbeat",hb?"laeuft — sammelt Erfahrung":"aus — begleitete Aktivierung steht aus");
 row(ov.kill_switch?"bad":"ok","§3 Not-Aus",ov.kill_switch?"AKTIV — alles haelt":"bereit, nicht ausgeloest");
 const pend=(dg.pending_approvals|0);
 row(pend?"warn":"ok","§3 Freigaben",pend?pend+" warten in der Inbox auf dich":"nichts offen");
 row(ck.journal_heute?"ok":"warn","§4 Tages-Journal",ck.journal_heute?"heutige Seite existiert":"heute noch keine Seite ("+(ck.journal_anzahl|0)+" bisher) — Cron aktiv? (HANDBUCH §8)");
 row((ck.stammbaum_luecken|0)===0?"ok":"warn","§4 Stammbaum",(ck.stammbaum_dateien|0)+" Dateien · "+(ck.stammbaum_luecken|0)+" ???-Luecken offen (Briefing fragt 1/Tag)");
 const pbs=(pb.playbooks||[]);
 row(pbs.length?"ok":"warn","§7 Playbooks",pbs.length+" vorhanden · "+pbs.filter(p=>p.reifegrad!=="entwurf").length+" ueber Entwurf hinaus");
 row(ck.handbuch?"ok":"bad","HANDBUCH",ck.handbuch?"docs/HANDBUCH.md vorhanden (auch hier links unter Dateien)":"fehlt!");
 el.innerHTML=rows.join("");
}catch(e){el.innerHTML='<span class="muted">Checkliste nicht ladbar.</span>';}}

function subnav(tab,s){const g=SUBTABS[tab];if(!g)return;g.cur=s;
 $$(g.bar+" a").forEach(a=>a.classList.toggle("on",a.dataset.s===s));
 $$("#v-"+tab+" .subview").forEach(x=>x.classList.toggle("on",x.id==="v-"+s));
 if(tab==="kira"&&typeof syncKiraGroup==="function")syncKiraGroup(s);  /* Gruppen-Zeile mitfuehren */
 (g.loaders[s]||(()=>{}))();}
Object.keys(SUBTABS).forEach(t=>$$(SUBTABS[t].bar+" a").forEach(a=>a.onclick=()=>subnav(t,a.dataset.s)));
/* Kira-Tab: 2 Ebenen — 5 Gruppen filtern die Sub-Tabs. Views/Loader bleiben unveraendert;
   nur sichtbar ist immer NUR die aktive Gruppe -> 16 flache Reiter werden zu 5 klaren Gruppen. */
const KIRA_GROUPS=[
 {key:"geist",   subs:["files","charakter","mem","wissen"]},
 {key:"gewissen",subs:["gov"]},
 {key:"automatik",subs:["cron","monitor","playbooks"]},
 {key:"technik", subs:["models","bench","steuer","keys","cockpit","wall"]},
 {key:"zustand", subs:["checkliste","anatomie","stats","evolution","log"]}];
function _kiraGroupOf(s){const g=KIRA_GROUPS.find(x=>x.subs.includes(s));return g?g.key:"geist";}
function syncKiraGroup(s){const gk=_kiraGroupOf(s);const grp=KIRA_GROUPS.find(x=>x.key===gk);
 $$("#kira-groups a").forEach(a=>a.classList.toggle("on",a.dataset.g===gk));
 $$("#kira-tabs a").forEach(a=>{a.style.display=grp.subs.includes(a.dataset.s)?"":"none";});}
function kiraGroup(gk){const grp=KIRA_GROUPS.find(x=>x.key===gk);if(!grp)return;
 if(grp.subs.includes(SUBTABS.kira.cur))syncKiraGroup(SUBTABS.kira.cur);  /* schon in der Gruppe -> nur filtern */
 else subnav("kira",grp.subs[0]);}                                        /* sonst zum ersten Sub-Tab */
$$("#kira-groups a").forEach(a=>a.onclick=()=>kiraGroup(a.dataset.g));
/* ⚙ Einstellungen-Shortcut in der Topbar: springt direkt in die Einstellungs-Gruppe (Modelle/
   Steuerpult/Zugaenge/Cockpit/Wallpaper) — nur echte Settings, Kira-Inhalte bleiben bei Kira. */
$("#gear")&&($("#gear").onclick=()=>{nav("kira");kiraGroup("technik");});
syncKiraGroup(SUBTABS.kira.cur||"files");  /* Startzustand: Gruppe 'geist' aktiv */
/* Icons pro Tab anpassbar (localStorage kira_icons: {"home":"◈",...}) — Pflege in Kira->Cockpit */
function applyIcons(){try{const ic=JSON.parse(localStorage.getItem("kira_icons")||"{}");
 $$("#side a .ti").forEach(i=>{const v=i.closest("a").dataset.v;if(ic[v])i.textContent=ic[v];});}catch(e){}}
applyIcons();

/* ---- Me (S7a/S8.4/S9.4): beide Todo-Richtungen + Zugangs-Anfragen + Mails + Routinen ---- */
function loadMe(){loadInbox();loadTodoSecrets();loadLeben();loadMeCrons();}
/* S9.4: Todo direkt anlegen (Enter oder +) */
async function meTodoAdd(){const i=$("#me-todo-in");const t=(i.value||"").trim();if(!t)return;
 await fetch("/api/life/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({description:t})});
 i.value="";toast("notiert","ok");loadLeben();}
$("#me-todo-add")&&($("#me-todo-add").onclick=meTodoAdd);
$("#me-todo-in")&&($("#me-todo-in").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();meTodoAdd();}}));
async function loadMeCrons(){const el=$("#me-crons");if(!el)return;try{
 const d=await (await fetch("/api/cron")).json();
 const mine=(d.jobs||[]).filter(j=>(j.scope||"system")==="me");
 el.innerHTML=mine.length?mine.map(j=>{
  const nxt=j.next_run?new Date(j.next_run*1000).toLocaleString([],{weekday:"short",hour:"2-digit",minute:"2-digit"}):"—";
  return '<div class="memrow"><div class="mh"><span class="badge kind">'+(j.enabled?"AN":"aus")+'</span>'
   +'<b>'+esc(j.label||"")+'</b><span class="muted" style="font-size:11px">'+esc(j.schedule_text||"")+' · naechster: '+nxt+'</span>'
   +'<span style="flex:1"></span><a data-ctog="'+esc(j.id)+'" style="cursor:pointer;color:var(--hud)">'+(j.enabled?"pausieren":"aktivieren")+'</a></div></div>';}).join("")
  :'<div class="emptybox">Noch keine Routinen.<br>Unten eine Automatisierung einrichten — oder sag es mir per Telegram.</div>';
 el.querySelectorAll("[data-ctog]").forEach(a=>a.onclick=async()=>{
  await fetch("/api/cron/toggle",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.ctog})});loadMeCrons();});
}catch(e){}}
/* Automatisierungspanel: Uhrzeit/Intervall + freier Auftrag -> Routine (scope me). */
$$('.au-preset').forEach(a=>a.onclick=()=>{
 const w=$("#au-what");if(w)w.value=a.dataset.what||"";
 if(a.dataset.time){const t=$("#au-time");if(t)t.value=a.dataset.time;}
 const iv=$("#au-interval");if(iv)iv.value="";if(w)w.focus();});
$("#au-add")&&($("#au-add").onclick=async()=>{
 const what=($("#au-what").value||"").trim();
 const hint=$("#au-hint");
 if(!what){if(hint)hint.textContent="Was soll ich tun?";return;}
 const iv=($("#au-interval").value||"").trim();
 const schedule=iv||($("#au-time").value||"08:00");
 const label=(what.length>44?what.slice(0,44)+"…":what);
 const enabled=$("#au-now").checked;
 const r=await (await fetch("/api/cron/add",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({label:label,prompt:what,schedule:schedule,scope:"me",enabled:enabled})})).json();
 if(hint)hint.textContent=r.ok?("✓ eingerichtet "+(enabled?"(aktiv)":"(aus — oben aktivieren)")):"Fehler";
 $("#au-what").value="";$("#au-interval").value="";$("#au-now").checked=false;
 loadMeCrons();});

/* ---- Evolution (S8.1): was Kira zuletzt an sich verbessert hat ---- */
async function loadEvolution(){try{
 const d=await J("/api/evolution");
 const rel=ts=>{const s=Date.now()/1000-ts;return s<3600?Math.round(s/60)+" min":s<86400?Math.round(s/3600)+" h":Math.round(s/86400)+" Tg";};
 const tl=d.timeline||[];
 $("#ev-timeline").innerHTML=tl.length?tl.map(e=>
  '<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);font-size:12.5px">'
  +'<span style="min-width:70px;color:var(--muted)">'+rel(e.ts)+'</span>'
  +'<span style="flex:1"><b>'+esc(e.label)+'</b>'+(e.detail?' <span class="muted">— '+esc(e.detail)+'</span>':'')+'</span></div>').join("")
  :'<div class="emptybox">Noch keine Selbst-Verbesserungen aufgezeichnet.<br>Fuellt sich, sobald der Heartbeat laeuft (jeder 3. Tick).</div>';
 const sk=d.skills||[];
 const scnt=$("#ev-skillcount");if(scnt)scnt.textContent=sk.length?(sk.length+" Skills"):"";
 $("#ev-skills").innerHTML=sk.length?sk.map(s=>'<div class="memrow"><div style="font-size:12.5px">'+esc((""+(s.text||s)).slice(0,180))+'</div></div>').join("")
  :'<span class="muted">(noch keine Skills gelernt)</span>';
 $("#ev-lessons").innerHTML=(d.lessons||[]).length?'<ul style="margin:0;padding-left:18px;font-size:12.5px">'
  +d.lessons.map(l=>'<li>'+esc((""+l).slice(0,160))+'</li>').join("")+'</ul>':'<span class="muted">(noch keine)</span>';
}catch(e){}}

/* ---- Statistik (S6.6c): Lern-Kurve aus dem Outcome-Ledger ---- */
async function loadStats(){try{
 const d=await J("/api/insights");const st=d.stats||{};const pat=d.patterns||{};
 const pct=v=>v==null?"—":Math.round(v*100)+"%";
 const kpi=(label,val,sub)=>'<div><div class="muted" style="font-size:11px;letter-spacing:1px">'+label+'</div>'
  +'<div style="font-size:26px;font-weight:600;color:var(--hud)">'+val+'</div>'
  +(sub?('<div class="muted" style="font-size:11px">'+sub+'</div>'):'')+'</div>';
 $("#st-kpi").innerHTML=st.attempts
  ? kpi("PASS-RATE",pct(st.pass_rate),st.passed+" von "+st.attempts+" Versuchen")
    +kpi("Ø-SCORE",st.avg_score==null?"—":st.avg_score,"Ziel: ueber 70")
    +kpi("ZEITRAUM",d.days+" Tage","")
  : '<span class="muted">Noch keine gepruefte Arbeit — Statistik fuellt sich, sobald der Heartbeat Aufgaben abarbeitet.</span>';
 const row=(cells,head)=>'<div style="display:flex;gap:10px;padding:5px 0;border-bottom:1px solid var(--line);font-size:12.5px'+(head?';color:var(--muted)':'')+'">'
  +cells.map((c,i)=>'<span style="'+(i===0?'flex:1':'min-width:92px;text-align:right')+'">'+c+'</span>').join("")+'</div>';
 const kinds=pat.by_kind||[];
 $("#st-kinds").innerHTML=kinds.length
  ? row(["Task-Art","Versuche","bestanden","Ø-Score","$/Erfolg"],true)
    +kinds.map(g=>row([esc(g.key),g.attempts,pct(g.pass_rate),g.avg_score==null?"—":g.avg_score,
      g.cost_per_success==null?"—":("$"+g.cost_per_success)])).join("")
  : '<span class="muted">(keine Daten)</span>';
 const tk=d.tokens_heute||{};const fmt=n=>n>=1e6?(n/1e6).toFixed(1)+"M":n>=1e3?(n/1e3).toFixed(1)+"k":""+n;
 $("#st-tokens")&&($("#st-tokens").innerHTML=(tk.total_calls
  ? row(["Rolle","Calls","Tokens","$"],true)
    +(tk.by_role||[]).map(g=>row([esc(g.role),g.calls,fmt(g.tokens),g.cost_usd?("$"+g.cost_usd):"0"])).join("")
    +row(["<b>Gesamt</b>",tk.total_calls,"<b>"+fmt(tk.total_tokens)+"</b>",""],false)
  : '<span class="muted">Heute noch keine LLM-Calls.</span>'));
 const objs=(pat.by_objective||[]).filter(g=>g.attempts>=2).slice(0,5);
 $("#st-objs").innerHTML=objs.length
  ? objs.map(g=>row([esc((""+(g.title||g.key)).slice(0,70)),g.attempts+" Versuche",pct(g.pass_rate)])).join("")
  : '<span class="muted">(kein Ziel auffaellig)</span>';
 $("#st-themes").innerHTML=(pat.themes||[]).length
  ? pat.themes.map(t=>'<span class="pill">'+esc(t)+'</span>').join(" ")
  : '<span class="muted">(keine wiederkehrende Kritik)</span>';
 const strats=d.strategies||{};const sk=Object.keys(strats);
 $("#st-strats").innerHTML=sk.length
  ? sk.map(s=>row([esc(s),strats[s].attempts+" Versuche",pct(strats[s].pass_rate)])).join("")
  : '<span class="muted">(noch keine Retries — gut!)</span>';
 const c=await J("/api/costs");const wk=(c.week&&c.week.by_model)||[];
 $("#st-costs").innerHTML=wk.length
  ? row(["Modell","Calls","Kosten"],true)
    +wk.map(m=>row([esc((""+m.model).replace(/^openrouter\//,"")),m.calls,"$"+m.cost.toFixed(3)])).join("")
    +'<div class="muted" style="margin-top:6px;font-size:12px">7-Tage-Summe: <b>$'+(c.week.total||0).toFixed(3)+'</b> · heute: $'+(c.today.total||0).toFixed(3)+'</div>'
  : '<span class="muted">(noch keine Cloud-Kosten)</span>';
}catch(e){}}
/* ---- Modell-Umschalter in der Chat-Pane ---- */
function shortModel(id){return (id||"").replace(/^openrouter\//,"").replace(/^ollama_chat\//,"").split("/").pop();}
function setChatModel(id){const h=$("#chat-model");if(h)h.value=id||"";
 const b=$("#model-btn");if(b)b.textContent=id?shortModel(id):"Modell";syncDenk();}
async function loadChatModels(){const s=await (await fetch("/api/status")).json();
 REASON_MARKERS=s.reasoning_markers||REASON_MARKERS;
 setChatModel(s.resolved_model||s.model);}   /* das Modell, das der Chat WIRKLICH nutzt */
async function useChatModel(id){
 /* NUR die Chat-Rolle setzen — NICHT default (das wuerde reason/bulk mitreissen und den GLM-Denker kapern). */
 await fetch("/api/model/role",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role:"chat",model:id})});
 setChatModel(id);const p=$("#model-pop");if(p)p.style.display="none";refreshStatus();}
/* Modell-Popover: ALLE Modelle (wie in den Einstellungen), mit ehrlichem Reasoning-Hinweis pro Modell. */
let MODEL_CACHE=null;
async function renderModelRows(term){const box=$("#model-rows");if(!box)return;
 if(!MODEL_CACHE){try{const d=await (await fetch("/api/model/catalog")).json();const c=d.catalog||{};
   MODEL_CACHE=[].concat(c.local||[],c.openrouter||[],c.aimlapi||[]);}catch(e){MODEL_CACHE=[];}}
 const cur=($("#chat-model")&&$("#chat-model").value)||"";
 term=(term||"").toLowerCase();
 const rows=MODEL_CACHE.filter(m=>!term||((m.id+" "+(m.name||"")).toLowerCase().includes(term))).slice(0,60);
 box.innerHTML=rows.length?rows.map(m=>{const rc=isReasoningModel(m.id);
   const badge=rc?'<span class="rbadge" style="color:var(--ok)">🧠 denkt</span>':'<span class="rbadge muted">kein Reasoning</span>';
   const act=(m.id===cur)?' style="border:1px solid var(--chat-accent)"':'';
   const tip=rc?'Reasoning-faehig — der Denk-Tiefe-Regler wird aktiv':'Kein eingebautes Reasoning';
   return '<div class="cmd-row" data-mid="'+esc(m.id)+'" title="'+tip+'"'+act+'><span class="cmd-k">'+esc((m.name||m.id).slice(0,44))+'</span><span style="flex:1"></span>'+badge+'</div>';}).join("")
  :'<div class="muted" style="padding:8px">nichts gefunden</div>';
 $$('#model-rows .cmd-row').forEach(r=>r.onclick=()=>useChatModel(r.dataset.mid));}
$("#model-btn")&&($("#model-btn").onclick=async e=>{e.stopPropagation();const el=$("#model-pop");if(!el)return;
 const show=el.style.display==="none";
 if(show){el.innerHTML='<input class="mq" id="model-q" placeholder="Modell suchen (Fable, Opus, GLM …)"/><div class="mrows" id="model-rows"><div class="muted" style="padding:8px">… lade Modelle …</div></div>';
  el.style.display="block";const q=$("#model-q");if(q){q.oninput=()=>renderModelRows(q.value);q.focus();}renderModelRows("");}
 else el.style.display="none";});
document.addEventListener("click",e=>{const p=$("#model-pop");
 if(p&&p.style.display!=="none"&&!e.target.closest("#model-pop")&&e.target.id!=="model-btn")p.style.display="none";});

/* ---- Monitor ---- */
async function loadMonitor(){const m=await (await fetch("/api/monitor")).json();
 $("#mo-list").innerHTML=m.watches.length?m.watches.map(w=>'<div style="padding:6px 0;border-bottom:1px solid var(--line)"><b>'+(w.label||"").replace(/</g,"&lt;")+'</b> <small class=muted>['+w.kind+']</small> <a href="#" data-rm="'+w.id+'" style="float:right;color:var(--warn)">entfernen</a><br><small class=muted>'+(w.value||"").replace(/</g,"&lt;")+'</small></div>').join(""):'<span class=muted>(noch keine — oben hinzufuegen)</span>';
 document.querySelectorAll('#mo-list a[data-rm]').forEach(a=>a.onclick=async(e)=>{e.preventDefault();await fetch("/api/monitor/remove",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.rm})});loadMonitor();});
 $("#mo-recent").innerHTML=m.recent.length?m.recent.map(r=>{const ts=new Date(r.ts*1000).toLocaleString();return '<div style="padding:6px 0;border-bottom:1px solid var(--line)"><small class=muted>'+ts+'</small> <b>'+(r.label||"")+'</b> ('+r.count+' neu)<br>'+(r.summary||"").slice(0,320).replace(/</g,"&lt;").replace(/\n/g,"<br>")+'</div>';}).join(""):'<span class=muted>(noch nichts gemeldet)</span>';}
$("#mo-add").onclick=async()=>{const v=$("#mo-value").value.trim();if(!v)return;await fetch("/api/monitor/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:$("#mo-kind").value,value:v,label:$("#mo-label").value})});$("#mo-value").value="";$("#mo-label").value="";loadMonitor();};
$("#mo-check").onclick=async()=>{$("#mo-hint").textContent="… prueft alle Beobachtungen (kann etwas dauern) …";const r=await (await fetch("/api/monitor/check",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();$("#mo-hint").textContent="Geprueft: "+r.checked+" Quelle(n) · Neu gemeldet: "+(r.digests?r.digests.length:0);loadMonitor();};

/* ---- Cron / geplante Aufgaben ---- */
let cronJobs=[], cronEdit=null;
async function loadCron(){const d0=await (await fetch("/api/cron")).json();cronJobs=d0.jobs;const fmt=ts=>ts?new Date(ts*1000).toLocaleString():"—";
 /* S8.4: Config zeigt nur System-Jobs — Me-Routinen leben bei Me, Projekt-Crons in der Akte */
 const d={jobs:(d0.jobs||[]).filter(j=>(j.scope||"system")==="system")};
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
/* S6.7b: Zentrale entruempelt — System/Modell/Budget/Vertrauen leben im HUD-Streifen,
   die 73-Werkzeuge-Wolke gehoert (gruppiert) nach Kira->Anatomie. Hier nur noch:
   Fokus-Hinweis, Lektionen (3) und Schnellzugriff. */
async function loadHome(){const o=await (await fetch("/api/overview")).json();
 try{const dz=await (await fetch("/api/direktive")).json();const dh=$("#dir-hint");if(dh&&dz.focus)dh.textContent="🧭 Aktueller Fokus: "+dz.focus.slice(0,140);}catch(e){}
 const card=(t,c)=>'<div class="card"><h3>'+t+'</h3>'+c+'</div>';
 let h='<div style="display:flex;flex-direction:column;gap:10px">';
 /* Schnellzugriff ZUERST (haeufig genutzt, war vorher unter der Falz versteckt) */
 h+=card("Schnellzugriff",'<button class=ghost data-go="chat">Chat</button> '
   +'<button class=ghost data-go="models">Modelle</button> '
   +'<button class=ghost data-go="gov">Gewissen</button> '
   +'<button class=ghost data-go="stats">Statistik</button> '
   +'<button class=ghost data-go="me">Me</button>');
 /* Lektionen nur wenn vorhanden — sonst kein leerer Platzhalter */
 if((o.lessons||[]).length)h+=card("Letzte Lektionen",'<ul style="margin:0;padding-left:18px">'
   +o.lessons.slice(0,3).map(l=>'<li>'+esc(l.slice(0,140))+'</li>').join("")+'</ul>');
 h+='</div>';$("#home").innerHTML=h;
 /* Subtab-Ziele brauchen nav(config)+syst — nackte nav() darauf war der Weisser-Screen-Bug */
 $$('#home [data-go]').forEach(b=>b.onclick=()=>{const g=b.dataset.go;
  if(g==="stats"){nav("kira");subnav("kira","stats");}
  else if(g==="models"||g==="gov"){nav("kira");subnav("kira",g);}
  else nav(g);});
 loadZielePinned();
 const gz=$("#go-ziele");if(gz)gz.onclick=()=>{nav("me");subnav("me","metriken");};}

/* ---- Kira-Avatar (S6.6d): einmal proben, Hero + Chat nutzen ihn ---- */
let hasAvatar=false,avatarV=Date.now();  // Cache-Buster: aendert sich beim Avatar-Wechsel
(function(){const hv=$("#hero-av");if(!hv)return;
 hv.onerror=()=>{hasAvatar=false;hv.style.display="none";};
 hv.onload=()=>{hasAvatar=true;hv.style.display="";};
 hv.src="/api/avatar?t="+avatarV;})();

/* ---- Kommandozentrale (HUD) ---- */
let opsFilter="all";
async function loadHud(){const el=$("#hud-strip");if(!el)return;
 try{const o=await (await fetch("/api/overview")).json();const st=await (await fetch("/api/status")).json();
  let sv=null;try{sv=await (await fetch("/api/services")).json();}catch(e){}
  /* S9.1: HUD-Streifen erweitert — Heartbeat, offene Aufgaben/Todos, letzte Aktion */
  let mb=null,lb=null;
  try{mb=await (await fetch("/api/mission/board")).json();}catch(e){}
  try{lb=await (await fetch("/api/life/board")).json();}catch(e){}
  const b=o.budget||{};const ec=st.events||{};
  const dd=(ok,name)=>'<span title="'+name+'" style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;background:'+(ok?'var(--ok)':'var(--danger)')+'"></span>';
  const svc=(sv&&sv.services)||{};
  const dienste=sv?('<div class="hud-cell"><span class="k">Dienste</span><span class="val">'
   +dd(sv.supervisor,"Supervisor")+dd(svc.cockpit!==false,"Cockpit")+dd(svc.bot,"Telegram-Bot")+dd(svc.runner,"Runner")+dd(sv.ollama,"Ollama")+'</span></div>'):'';
  /* S11: ehrliches 7-Tage-Fenster (nicht mehr kumulativ seit DB-Beginn) — klickbar zum Protokoll */
  const errs=(st.errors_recent!=null)?st.errors_recent:((ec.turn_timeout||0)+(ec.llm_call_timeout||0)+(ec.service_crash||0)+(ec.act_degraded||0));
  const dayPct=b.day_limit?Math.min(100,Math.round(100*(b.day_spent||0)/b.day_limit)):0;
  const warn=dayPct>=85?" warn":"";
  const kill=o.kill_switch?'<span style="color:var(--danger)">⛔ NOT-AUS</span>':'<span style="color:var(--ok)">● bereit</span>';
  const model=(""+(o.model||"")).split("/").pop();
  const on=o.mission&&o.mission.heartbeat;
  const motor='<a id="hud-motor" title="Klicken zum Umschalten" style="cursor:pointer;border-bottom:1px dotted var(--muted);color:'+(on?"var(--ok)":"var(--muted)")+'">'+(on?"● laeuft · AUS?":"○ aus · AN?")+'</a>';
  const hf=(typeof handsFree!=="undefined")&&handsFree;
  const assist='<a id="hud-assist" title="Assistenz-Modus: freihaendig zuhoeren, reagiert auf \'Kira …\', antwortet mit Stimme" style="cursor:pointer;border-bottom:1px dotted var(--muted);color:'+(hf?"var(--ok)":"var(--muted)")+'">'+(hf?"🎙️ hoert zu · AUS?":"🎙️ Zuhoeren?")+'</a>';
  const jobs=mb?((mb.board&&(((mb.board.today||[]).length)+((mb.board.week||[]).length)+((mb.board.later||[]).length)))||0):0;
  const running=mb&&mb.board?((mb.board.running||[]).length):0;
  const todos=lb&&lb.board?(((lb.board.today||[]).length)+((lb.board.week||[]).length)):0;
  const cell=(k,v,extra)=>'<div class="hud-cell"><span class="k">'+k+'</span><span class="val">'+v+'</span>'+(extra||"")+'</div>';
  el.innerHTML=cell("Status",kill)
   +cell("Heartbeat",motor)
   +cell("Assistenz",assist)
   +cell("Modell",esc(model))
   +cell("Budget heute",(b.day_spent||0)+' / '+(b.day_limit==null?"-":b.day_limit)+' €','<div class="mini-bar'+warn+'"><i style="width:'+dayPct+'%"></i></div>')
   +cell("Monat",(b.month_spent||0)+' / '+(b.month_limit==null?"-":b.month_limit)+' €')
   +cell("Aufgaben",'<b style="color:var(--hud)">'+jobs+'</b> offen'+(running?' · '+running+' laeuft':''))
   +cell("Deine Todos",'<b>'+todos+'</b>')
   +dienste
   +cell("Fehler · 7 Tg",'<a id="hud-errs" title="Timeouts/Crashes der letzten 7 Tage — klick fuers Protokoll" style="cursor:pointer;color:'+(errs?"var(--warn)":"var(--ok)")+'">'+errs+'</a>')
   +'<div class="hud-cell spacer"></div>'
   +cell("Aktion",'<a id="hud-restart" style="cursor:pointer;color:var(--hud)">↻ Neustart</a>');
  const rb=$("#hud-restart");if(rb)rb.onclick=async()=>{if(!confirm("Kira neu starten? Dienste bouncen in ~20s."))return;await fetch("/api/restart",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});rb.textContent="↻ …";};
  const eb=$("#hud-errs");if(eb)eb.onclick=()=>{nav("kira");if(typeof subnav==="function")subnav("kira","log");};  /* Fehler-Zahl -> Protokoll */
  /* Assistenz-Modus direkt in der Zentrale (freihaendiges Zuhoeren, Weckwort "Kira"). */
  const ha=$("#hud-assist");if(ha&&typeof toggleAssist==="function")ha.onclick=toggleAssist;
  /* S11.4: DER Heartbeat-Schalter — begleitete Aktivierung passiert hier, bewusst per Klick. */
  const mt=$("#hud-motor");if(mt)mt.onclick=async()=>{const to=!on;
   if(!confirm(to?"Heartbeat EINSCHALTEN?\n\nKira plant und arbeitet dann autonom im Takt (alle 30 min). Budget-Bremse, Freigabe-Gates und Not-Aus bleiben aktiv.":"Heartbeat ausschalten? Der aktuelle Tick laeuft noch zu Ende."))return;
   await fetch("/api/mission/toggle",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on:to})});
   toast(to?"Heartbeat AN — erster Tick startet im Takt":"Heartbeat aus","ok");loadCommand();};
  /* S6.6d: Hero-Status + Aura (Heartbeat an = Avatar leuchtet) */
  const hs=$("#hero-status");
  if(hs){const on=o.mission&&o.mission.heartbeat;
   hs.textContent=(o.kill_switch?"⛔ NOT-AUS aktiv":(on?"Heartbeat laeuft — arbeitet autonom":"Heartbeat aus — wartet auf dich"));
   /* Budget-Dopplung raus — steht schon als HUD-Zelle oben. */
   const hv=$("#hero-av");if(hv)hv.classList.toggle("aura",!!on&&!o.kill_switch);}
 }catch(e){}}
let _opsCache=[];
function _opsCounts(){const c={all:_opsCache.length,action:0,info:0,chat:0,error:0};
 _opsCache.forEach(e=>{const s=e.sev||"info";if(c[s]!==undefined)c[s]++;});return c;}
function renderOps(){const el=$("#ops-feed");if(!el)return;
 const keep=_opsCache.filter(e=>opsFilter==="all"||(e.sev||"info")===opsFilter);
 el.innerHTML=keep.length?keep.map(e=>{const t=new Date(e.ts*1000).toLocaleTimeString();
  return '<div class="op '+(e.sev||"info")+'"><span class="od"></span><span class="opt">'+t+'</span><span class="opx">'+pulsePhrase(e).replace(/</g,"&lt;")+'</span></div>';}).join(""):'<span class="muted" style="padding:10px 13px;display:block">(ruhig — keine Aktivitaet)</span>';
 const c=_opsCounts();$$("#ops-filter a").forEach(a=>{const b=a.querySelector(".ofc");if(b)b.textContent=c[a.dataset.of]||"";});}
async function loadOps(){const el=$("#ops-feed");if(!el)return;  // holt+cached; Filter rendert clientseitig (kein Refetch)
 try{_opsCache=await (await fetch("/api/events?limit=70")).json();renderOps();}catch(e){}}
/* S9.1: Intel zeigt KIRAS eigene Monitor-News (kuratiert, mit Zusammenfassung) statt roher RSS. */
async function loadNews(){const tk=$("#news-ticker"),ls=$("#news-list");if(!ls)return;
 try{const d=await (await fetch("/api/monitor")).json();const rec=d.recent||[];
  if(!rec.length){if(tk)tk.innerHTML='<span>Noch keine Meldungen — Kira faellt hier ein, was ihre Beobachtungen ergeben (Monitor unter Config).</span>';
   ls.innerHTML='<div class="emptybox" style="min-height:80px">Kira hat noch nichts gemeldet.<br>Themen/Feeds richtest du unter Config → Monitor ein.</div>';return;}
  const head=rec.map(x=>'▟ '+(x.label||"")+': '+((x.summary||"").replace(/\n/g," ").slice(0,90))).join('     ◆     ');
  if(tk)tk.innerHTML='<span>'+esc(head)+'</span>';
  const item=x=>{const t=new Date(x.ts*1000).toLocaleString([], {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
   return '<div class="news-item"><small>'+esc(x.label||"")+' · '+t+' · '+(x.count||0)+' neu</small><br>'+esc((x.summary||"").slice(0,220))+'</div>';};
  /* Nur 4 zeigen (kein innerer Scroll mehr) — Rest hinter einem "mehr", damit nichts unerreichbar wird. */
  const restArr=rec.slice(4,12);
  const rest=restArr.length?('<div id="news-more" style="display:none">'+restArr.map(item).join("")+'</div>'
   +'<a id="news-moretog" class="muted" style="cursor:pointer;font-size:11px;display:inline-block;margin-top:4px">+ '+restArr.length+' mehr</a>'):"";
  ls.innerHTML=rec.slice(0,4).map(item).join("")+rest;
  const mt=$("#news-moretog");if(mt)mt.onclick=()=>{const m=$("#news-more");if(!m)return;const open=m.style.display!=="none";
   m.style.display=open?"none":"block";mt.textContent=open?("+ "+restArr.length+" mehr"):"− weniger";};
 }catch(e){}}
const DEFAULT_FEEDS=[{kind:"feed",value:"https://hnrss.org/frontpage",label:"Hacker News"},
 {kind:"feed",value:"https://www.theverge.com/rss/index.xml",label:"The Verge"},
 {kind:"search",value:"KI Modell Release news",label:"KI-Releases"},
 {kind:"search",value:"AI agents open source",label:"Agents"}];
function bindNewsSeed(){const s=$("#news-seed");if(!s)return;s.onclick=async()=>{s.textContent="… fuege hinzu";
  for(const f of DEFAULT_FEEDS){try{await fetch("/api/monitor/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(f)});}catch(e){}}
  s.textContent="✓ hinzugefuegt";loadNews();};}
function bindOpsFilter(){$$("#ops-filter a").forEach(a=>a.onclick=()=>{opsFilter=a.dataset.of;$$("#ops-filter a").forEach(x=>x.classList.toggle("on",x===a));renderOps();});}
function loadCommand(){loadHud();loadOps();loadNews();loadHome();loadDigest();bindNewsSeed();bindOpsFilter();}

/* ---- Projekte (S9.3): eine Uebersicht — Standbeine + Ziele/Backlog + Radar zusammen ---- */
let _openVent=null;
function closeVent(){const vd=$("#vent-detail");if(vd)vd.style.display="none";
 const pv=$("#v-projekte");if(pv)pv.classList.remove("drill");_openVent=null;}
function loadProjekte(){closeVent();loadVentures();loadMission();loadRadar();}

/* ---- Mission-Workspace (Ziele + To-Do-Board) ---- */
const KIND_LABEL={big:"BIG",monthly:"MONAT",weekly:"WOCHE"};
let missionObjs=[];
async function loadMission(){
 loadVentures();
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
   const kb={publish:"📮",email:"✉️",email_stranger:"✉️",external:"🌐",evolution:"🧬",playbook:"📘",generic:"📝"}[a.kind]||"📝";
   /* S11.4: E-Mail-Entwuerfe lesbar rendern (An/Betreff/Text) statt rohem JSON */
   let raw=(""+(a.detail||""));
   if(a.kind==="email"||a.kind==="email_stranger"){
    try{const m=JSON.parse((raw.match(/\{[\s\S]*\}/)||[raw])[0]);
     if(m&&(m.to||m.subject||m.body))raw="An: "+(m.to||"?")+"\nBetreff: "+(m.subject||"")+"\n\n"+(m.body||"");}catch(e){}}
   const det=esc(raw.slice(0,900));
   return '<div class="memrow"><div class="mh"><span class="badge kind">'+kb+' '+esc(a.kind)+'</span><b style="color:var(--ink)">'+esc(a.title||"")+'</b><span style="flex:1"></span><span class="muted">'+ts+'</span></div>'
    +(det?'<div style="white-space:pre-wrap;font-size:12px;color:var(--muted);max-height:130px;overflow:auto;border-left:2px solid var(--line);padding-left:8px;margin:4px 0">'+det+'</div>':'')
    +'<div class="row" style="margin-top:6px"><button data-appr="'+a.id+'">✓ Freigeben</button><button class="ghost" data-rej="'+a.id+'">✕ Verwerfen</button></div></div>';
  }).join("");
  const decideOnce=async(b,id,approved,label)=>{ /* Doppelklick-Wache: Buttons sofort sperren; 409 = bereits entschieden */
   const row=b.closest(".memrow");row.querySelectorAll("button").forEach(x=>x.disabled=true);b.textContent="…";
   try{const r=await fetch("/api/approvals/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:id,approved:approved})});
    if(!r.ok&&r.status!==409){row.querySelectorAll("button").forEach(x=>x.disabled=false);b.textContent=label;}
   }catch(e){row.querySelectorAll("button").forEach(x=>x.disabled=false);b.textContent=label;}
   loadInbox();loadDigest();};
  $$('#inbox-list [data-appr]').forEach(b=>b.onclick=()=>decideOnce(b,b.dataset.appr,true,"✓ Freigeben"));
  $$('#inbox-list [data-rej]').forEach(b=>b.onclick=()=>{if(!confirm("Wirklich verwerfen?"))return;decideOnce(b,b.dataset.rej,false,"✕ Verwerfen");});
 }catch(e){}}
async function loadDigest(){const el=$("#digest");if(!el)return;
 try{const d=await (await fetch("/api/digest")).json();const b=d.budget||{};
  let h='<div class="muted" style="font-size:11px;letter-spacing:1px">'+d.date+'</div>';
  h+='<div style="margin:6px 0"><b>'+d.tasks_done_count+'</b> Aufgaben erledigt · <b>'+d.planned+'</b> geplant · <b>'+d.news+'</b> News</div>';
  if(d.tasks_done&&d.tasks_done.length){h+='<ul style="margin:4px 0;padding-left:16px;font-size:12px">'+d.tasks_done.slice(0,4).map(t=>'<li>'+(""+t).replace(/</g,"&lt;")+'</li>').join("")+'</ul>';
   if(d.tasks_done.length>4)h+='<div class="muted" style="font-size:11px">+ '+(d.tasks_done.length-4)+' weitere &middot; <span style="cursor:pointer;text-decoration:underline" onclick="nav(\'me\')">Me</span></div>';}
  /* S11: heute angefasste Dateien (der greifbarste "was wurde gebaut"-Beleg) + Tagesausgabe */
  if(d.artifacts&&d.artifacts.length)h+='<div style="margin-top:6px;font-size:12px"><span class="muted">Heute angefasst ('+d.artifacts.length+'):</span> '+d.artifacts.slice(0,6).map(a=>'<code style="font-size:11px">'+(""+a).replace(/</g,"&lt;").split("/").pop()+'</code>').join(", ")+'</div>';
  if(d.spend_usd!=null&&d.spend_usd>0)h+='<div style="margin-top:4px;font-size:12px" class="muted">Ausgaben heute: '+(d.spend_usd).toFixed(2)+' $</div>';
  h+='<div style="margin-top:6px;font-size:12px">Freigaben offen: <b style="color:'+(d.pending_approvals?"var(--warn)":"var(--ok)")+'">'+d.pending_approvals+'</b> · Fehler heute: <b style="color:'+(d.errors?"var(--danger)":"var(--ok)")+'">'+d.errors+'</b></div>';
  /* ruhiger Tag? nicht leer wirken lassen */
  if(!d.tasks_done_count&&!(d.artifacts&&d.artifacts.length)&&!d.news)h+='<div class="muted" style="margin-top:6px;font-size:12px">Noch ruhig heute — gib mir oben einen Auftrag, dann fuellt sich das hier.</div>';
  /* S9.1: Budget-Dopplung raus — steht schon im HUD-Streifen oben. */
  el.innerHTML=h;
 }catch(e){}}

async function refreshStatus(){let s;try{s=await J("/api/status");}catch(e){return null;}  // Backoff via pollFails in J()
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
/* S6.6b: Mini-Markdown fuer Kiras Antworten — sicher (esc() ZUERST), keine Bibliothek.
   Kann: **fett**, *kursiv*, `code`, ```bloecke```, - Listen, ## Ueberschriften, [Links](https://…) */
function md(src){
 let s=esc(""+(src||""));
 const blocks=[];
 s=s.replace(/```[a-zA-Z0-9_-]*\n?([\s\S]*?)```/g,(w,code)=>{blocks.push(code.replace(/^\n+|\n+$/g,""));return "@@MDB"+(blocks.length-1)+"@@";});
 s=s.replace(/`([^`\n]+)`/g,'<code>$1</code>');
 s=s.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');
 s=s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/gm,'$1<i>$2</i>');
 s=s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
 const out=[];let ul=false;
 for(const line of s.split("\n")){
  const li=line.match(/^\s*[-*•]\s+(.+)$/);
  if(li){if(!ul){out.push("<ul>");ul=true;}out.push("<li>"+li[1]+"</li>");continue;}
  if(ul){out.push("</ul>");ul=false;}
  const hd=line.match(/^\s*#{1,4}\s+(.+)$/);
  out.push(hd?('<b class="mdh">'+hd[1]+"</b>"):line);
 }
 if(ul)out.push("</ul>");
 s=out.join("\n").replace(/\n?(<\/?ul>)\n?/g,"$1").replace(/(<\/li>)\n/g,"$1");
 s=s.replace(/\n/g,"<br>");
 return s.replace(/@@MDB(\d+)@@/g,(w,i)=>'<pre class="mdc"><code>'+blocks[+i]+'</code></pre>');}
/* Nachricht mit Koerper + Meta (Uhrzeit, Kopieren). Bot-Antworten rendern Markdown. */
function msgEl(text,cls,ts){const d=document.createElement("div");d.className="msg "+cls;
 if(cls==="bot"&&hasAvatar){d.classList.add("withav");
  const av=document.createElement("img");av.className="mav";av.src="/api/avatar?t="+avatarV;d.appendChild(av);}
 const body=document.createElement("div");body.className="mbody";
 if(cls==="bot")body.innerHTML=md(text);else body.textContent=text;
 d.appendChild(body);
 const meta=document.createElement("div");meta.className="mmeta";
 const t=new Date((ts?ts*1000:Date.now()));
 meta.innerHTML='<span>'+t.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})+'</span><a class="mcopy" title="Nachricht kopieren">⧉</a>';
 meta.querySelector(".mcopy").onclick=()=>{if(navigator.clipboard){navigator.clipboard.writeText(text);toast("kopiert","ok");}};
 d.appendChild(meta);
 log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
/* Shimmernder Denk-Indikator: rotierender Spruch, solange Kira arbeitet */
let thinkTimer=null,thinkEl=null;
/* Eine rotierende Phrase, ueberall live: der Vor-Trace-Puls UND die Rainbow-Ueberschrift des Traces
   (Thinking/Cooking/Clauding…) lesen dieselbe Phrase — nur EIN Timer, kein Flackern. */
function refreshPhrase(){const p=rndPhrase()+"…";document.querySelectorAll(".tx.live").forEach(t=>{t.textContent=p;});}
function startThinking(){stopThinking();thinkEl=document.createElement("div");thinkEl.className="thinking";
 thinkEl.innerHTML='<span class="sh"></span><span class="tx live"></span>';
 log.appendChild(thinkEl);log.scrollTop=log.scrollHeight;refreshPhrase();
 thinkTimer=setInterval(refreshPhrase,2600);}
function stopThinking(){if(thinkTimer){clearInterval(thinkTimer);thinkTimer=null;}
 if(thinkEl){thinkEl.remove();thinkEl=null;}}
const proto=location.protocol==="https:"?"wss":"ws";
let ws,curBot,curThink,thinkBuf,traceC=null,curThinkLine=null,curSid=null,wsIntentional=false,wsDelay=1000;
/* Werkzeug -> Icon, Klarname, Schluessel-Argument (fuer den Claude-Code-Look im Trace) */
const TOOLMAP={read_file:["📖","Lesen","path"],code_suche:["🔎","Suche","muster"],datei_finden:["🗂","Finden","muster"],
 edit_datei:["✏️","Edit","pfad"],self_edit:["✏️","Edit","path"],write_file:["📄","Neu anlegen","path"],
 append_file:["➕","Anhaengen","path"],list_dir:["📂","Ordner","path"],make_dir:["📁","Ordner+","path"],
 run_command:["▷","Terminal","command"],web_search:["🌐","Websuche","query"],web_fetch:["🌐","Web","url"],
 remember_fact:["🧠","Merken","fact"],request_approval:["🛎","Freigabe","title"],read_file_lines:["📖","Lesen","path"]};
function shortArgs(a){try{const s=JSON.stringify(a||{});return s==="{}"?"":s.slice(0,90);}catch(e){return "";}}
function toolLabel(name,args){const t=TOOLMAP[name];
 if(!t)return {icon:"🔧",label:name,target:shortArgs(args)};
 const v=args&&args[t[2]]!=null?(""+args[t[2]]):shortArgs(args);
 return {icon:t[0],label:t[1],target:v};}
function renderDiff(box,txt){const pre=document.createElement("pre");pre.className="tdiff";
 (txt||"").split("\n").forEach(ln=>{const c=ln[0];const s=document.createElement("span");
  s.className="dl "+(c==="+"?"add":c==="-"?"del":c==="@"?"hunk":"ctx");s.textContent=ln+"\n";pre.appendChild(s);});
 box.appendChild(pre);}
function wsDot(ok){const d=$("#ws-dot");if(d){d.classList.toggle("on",ok);d.classList.toggle("off",!ok);d.title=ok?"Chat verbunden":"Chat getrennt — verbinde neu";}}
function connect(){wsIntentional=false;const url=proto+"://"+location.host+"/ws/chat"+(curSid?("?sid="+encodeURIComponent(curSid)):"");ws=new WebSocket(url);
 ws.onopen=()=>{wsDelay=1000;wsDot(true);};
 /* eingeklappt neu generieren: kommt ein neuer Schritt, klappt ein manuell geoeffneter Trace wieder zu */
 function traceLive(){if(curThink&&curThink.classList.contains("show"))curThink.classList.remove("show");}
 /* nach dem Lauf: Rainbow-Ueberschrift beruhigen (statischer Titel statt fliessender Phrase) */
 function settleTrace(){if(curThink){const tx=curThink.querySelector(".h .tx");if(tx){tx.classList.remove("live");tx.textContent="Denken & Aktionen";}}}
 function ensureTrace(){if(!curThink){curThink=document.createElement("div");curThink.className="think";
    curThink.innerHTML='<span class="h"><span class="chev">▸</span> <span class="tx live">…</span> <span class="hint">— klick zum Ein-/Ausklappen</span></span><div class="c"></div>';
    curThink.querySelector(".h").onclick=()=>curThink.classList.toggle("show");log.appendChild(curThink);
    traceC=curThink.querySelector(".c");curThinkLine=null;
    if(thinkEl){thinkEl.remove();thinkEl=null;}   /* Vor-Trace-Puls in die Trace-Ueberschrift falten (Timer laeuft weiter) */
    refreshPhrase();}return curThink;}
 function traceScroll(){log.scrollTop=log.scrollHeight;}
 /* Denkstrom tippt sich rein statt als Block zu spawnen (Typewriter, Rueckstau-adaptiv). */
 function traceThink(t){ensureTrace();
  if(!curThinkLine){traceLive();curThinkLine=document.createElement("div");curThinkLine.className="tthink";curThinkLine._buf="";curThinkLine._shown=0;traceC.appendChild(curThinkLine);}
  const el=curThinkLine;el._buf+=t;
  const rm=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if(rm){el._shown=el._buf.length;el.textContent=el._buf;traceScroll();return;}
  if(!el._raf){const tick=()=>{
    if(el._shown>=el._buf.length){el._raf=0;return;}
    const step=Math.max(2,Math.ceil((el._buf.length-el._shown)/40));  /* mehr Rueckstau -> groessere Schritte, nie zaeh */
    el._shown=Math.min(el._buf.length,el._shown+step);
    el.textContent=el._buf.slice(0,el._shown);traceScroll();
    el._raf=requestAnimationFrame(tick);};
   el._raf=requestAnimationFrame(tick);}}
 function traceTool(name,args){ensureTrace();traceLive();curThinkLine=null;
  const L=toolLabel(name,args);const row=document.createElement("div");row.className="trow";
  row.innerHTML='<span class="ti">'+esc(L.icon)+'</span><span class="tl">'+esc(L.label)+'</span>'
   +(L.target?'<span class="tt">'+esc(L.target)+'</span>':'');
  traceC.appendChild(row);traceScroll();}
 function traceObs(name,text){ensureTrace();traceLive();curThinkLine=null;
  const t=text||"";const m=t.match(/```diff\n([\s\S]*?)```/);
  const head=(m?t.slice(0,m.index):t).trim();
  const bad=/Fehlgeschlagen|ROT|⚠|Fehler|blockiert|nicht gefunden/i.test(head);
  const row=document.createElement("div");row.className="orow";
  if(head){const hd=document.createElement("div");hd.className="ostat "+(bad?"err":"ok");
   hd.textContent="↳ "+head.slice(0,240);row.appendChild(hd);}
  if(m)renderDiff(row,m[1]);
  traceC.appendChild(row);traceScroll();}
 ws.onmessage=ev=>{const m=JSON.parse(ev.data);
  if(m.role==="system"){add(m.text,"sys");return;}
  if(m.done){stopThinking();settleTrace();setStreaming(false);curBot=null;curThink=null;traceC=null;curThinkLine=null;loadChatSessions();return;}
  if(m.kind==="think"){traceThink(m.text);return;}
  if(m.kind==="tool"){traceTool(m.name,m.args);return;}
  if(m.kind==="obs"){traceObs(m.name,m.text);return;}
  if(m.kind==="final"||m.kind==="answer"){stopThinking();settleTrace();msgEl(m.text||"","bot");onKiraReply(m.text||"");}};
 ws.onclose=()=>{wsDot(false);setStreaming(false);if(!wsIntentional){wsDelay=Math.min(wsDelay*2,30000);setTimeout(connect,wsDelay);}};}
function reconnect(){wsIntentional=true;if(ws){try{ws.onclose=null;ws.close();}catch(e){}}connect();}  /* alten onclose stummschalten -> kein Doppel-Socket/doppeltes "Verbunden" */
function relTime(ts){const s=Date.now()/1000-ts;if(s<90)return "gerade";if(s<3600)return Math.round(s/60)+" Min";if(s<86400)return Math.round(s/3600)+" Std";return Math.round(s/86400)+" Tg";}
/* ==== S7c: Chat 2.0 — Tages-Sessions, aufklappbares Panel, Archiv, Modus-Schalter ==== */
function dailySid(){const d=new Date();const p=n=>(""+n).padStart(2,"0");
 return "cockpit-"+d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate());}
function dayLabel(ts){const d=new Date(ts*1000);const today=new Date();const y=new Date(Date.now()-86400000);
 const same=(a,b)=>a.getFullYear()===b.getFullYear()&&a.getMonth()===b.getMonth()&&a.getDate()===b.getDate();
 if(same(d,today))return "Heute";if(same(d,y))return "Gestern";
 return d.toLocaleDateString([], {day:"2-digit",month:"2-digit",year:"2-digit"});}
let showArchived=false;
function markActiveSession(){$$("#sess-items .sess").forEach(r=>r.classList.toggle("on",r.dataset.sid===curSid));}
async function loadChatSessions(){const box=$("#sess-items");if(!box)return;
 const d=await (await fetch("/api/chat/sessions"+(showArchived?"?archived=1":""))).json();const ss=d.sessions||[];
 let html="",lastDay=null;
 ss.forEach(s=>{const dl=dayLabel(s.last);
  if(dl!==lastDay){html+='<div class="sday">'+dl+'</div>';lastDay=dl;}
  const t=esc(((s.title||s.session_id)+"").slice(0,44));
  html+='<div class="sess'+(s.archived?" arch":"")+'" data-sid="'+esc(s.session_id)+'"><span class="si">'+(s.channel==="telegram"?"✈️":"💬")+'</span>'
   +'<span class="st">'+t+'</span><span class="sd">'+relTime(s.last)+'</span>'
   +'<a class="sa" title="'+(s.archived?"aus dem Archiv holen":"archivieren")+'">'+(s.archived?"↩":"🗄")+'</a>'
   +'<a class="sx" title="loeschen">✕</a></div>';});
 box.innerHTML=html||'<div class="muted" style="padding:10px">noch keine Unterhaltungen</div>';
 box.querySelectorAll(".sess").forEach(r=>{
  r.onclick=e=>{if(e.target.classList.contains("sx")||e.target.classList.contains("sa"))return;openSession(r.dataset.sid);};
  r.querySelector(".sa").onclick=async e=>{e.stopPropagation();
   const wasArch=r.classList.contains("arch");
   await fetch("/api/chat/archive",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sid:r.dataset.sid,archived:!wasArch})});
   loadChatSessions();};
  r.querySelector(".sx").onclick=async e=>{e.stopPropagation();if(!confirm("Diese Unterhaltung loeschen? (Verlauf weg — Kiras Fakten/Lektionen bleiben)"))return;
   await fetch("/api/chat/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sid:r.dataset.sid})});
   if(curSid===r.dataset.sid){curSid=null;log.innerHTML="";}
   loadChatSessions();};});
 if(!curSid)await openSession(dailySid());  /* Standard: EINE Session pro Tag */
 else markActiveSession();}
async function openSession(sid){curSid=sid;log.innerHTML="";curBot=null;curThink=null;traceC=null;curThinkLine=null;
 try{const h=await (await fetch("/api/chat/history?sid="+encodeURIComponent(sid))).json();
  (h.messages||[]).forEach(m=>msgEl(m.text||"",m.role==="user"?"me":"bot",m.ts));}catch(e){}
 syncChatProject(sid);markActiveSession();reconnect();}
function newSession(){curSid="cockpit-"+Math.random().toString(16).slice(2,10);log.innerHTML="";curBot=null;curThink=null;traceC=null;curThinkLine=null;const cp=$("#chat-project");if(cp)cp.value="";markActiveSession();reconnect();}
$("#sess-new")&&($("#sess-new").onclick=()=>newSession());
/* Test-Chat: sid mit 'test-'-Praefix -> gefahrloses Ausprobieren, leckt NICHT ins Langzeit-Gedaechtnis */
function newTestSession(){curSid="test-"+Math.random().toString(16).slice(2,10);log.innerHTML="";curBot=null;curThink=null;traceC=null;curThinkLine=null;const cp=$("#chat-project");if(cp)cp.value="";markActiveSession();reconnect();try{toast("🧪 Test-Chat — dieser Verlauf bleibt aussen vor (kein Langzeit-Gedaechtnis)");}catch(e){}}
$("#sess-test")&&($("#sess-test").onclick=()=>newTestSession());
/* Projekt-Chats (#15): je Projekt eine eigene Session (sid 'venture-<id>') — Kira bekommt das
   Briefing als Kontext (serverseitig in build_system_prompt). Wahl schaltet die Session um. */
async function loadChatProjects(){const sel=$("#chat-project");if(!sel)return;
 try{const d=await (await fetch("/api/ventures")).json();const vs=d.ventures||[];
  const keep=sel.value;
  sel.innerHTML='<option value="">— keins (allgemein) —</option>'+vs.map(v=>'<option value="'+esc(v.id)+'">'+esc(v.name||v.id)+'</option>').join("");
  sel.value=keep;}catch(e){}}
function syncChatProject(sid){const sel=$("#chat-project");if(!sel)return;
 sel.value=(sid&&sid.indexOf("venture-")===0)?sid.slice(8):"";}
$("#chat-project")&&($("#chat-project").onchange=e=>{const id=e.target.value;
 openSession(id?("venture-"+id):dailySid());});
/* Gespraeche: Hover-Intent — Drueberfahren oeffnet, Klick PINNT (bleibt offen bis zum
   naechsten Klick). Bleibt offen solange die Maus ueber Button ODER Panel ist; schliesst
   erst 400ms nach Verlassen beider -> keine Zuschnapp-Macke beim diagonalen Rueberziehen.
   Der Pin-Zustand wird gemerkt (localStorage), Klick bleibt der Touch-/Fallback-Weg. */
(function(){const p=$("#sess-panel"),b=$("#sess-toggle");if(!p||!b)return;
 let t=null,pinned=localStorage.getItem("kira_sess_open")==="1";
 const show=()=>p.classList.add("open"),hide=()=>{if(!pinned)p.classList.remove("open");};
 const open=()=>{clearTimeout(t);show();},later=()=>{clearTimeout(t);t=setTimeout(hide,400);};
 const setPin=v=>{pinned=v;localStorage.setItem("kira_sess_open",v?"1":"0");b.classList.toggle("pinned",v);};
 setPin(pinned); if(pinned)show();
 b.addEventListener("mouseenter",open);
 b.addEventListener("mouseleave",later);
 p.addEventListener("mouseenter",()=>clearTimeout(t));
 p.addEventListener("mouseleave",later);
 b.addEventListener("click",()=>{setPin(!pinned);pinned?open():hide();});
})();
$("#sess-archtoggle")&&($("#sess-archtoggle").onclick=()=>{showArchived=!showArchived;
 $("#sess-archtoggle").textContent=showArchived?"Archiv ausblenden":"Archiv anzeigen";loadChatSessions();});
/* Modus-Schalter: Chat = Dialog · Research = /work (Werkzeug-Budget) · Coding = code: (Plan->Schritte + Coding-Regeln) */
let chatMode="chat";
const MODE_HINT={
 chat:"Chat — schneller Dialog (guenstiges Modell). Fragen, Ideen, Kurzes.",
 work:"Work — echter Auftrag mit vollem Werkzeug-Budget auf GLM 5.2: Recherche, mehrere Schritte, Web/Dateien.",
 coding:"Coding — an Kira selbst schrauben (GLM 5.2): lesen → chirurgisch editieren → Tests + Diff-Review."};
function applyChatMode(){const m=$("#chat-main");if(m)m.setAttribute("data-mode",chatMode);
 const seg=$("#chat-mode-seg");if(seg)seg.style.setProperty("--i",{chat:0,work:1,coding:2}[chatMode]||0);}  /* Slider gleitet */
$$("#chat-mode-seg a").forEach(a=>a.onclick=()=>{chatMode=a.dataset.m;
 $$("#chat-mode-seg a").forEach(x=>x.classList.toggle("on",x===a));
 applyChatMode();});
applyChatMode();  /* Startzustand faerben (Chat) */
/* S9.2: Befehls-Chips fuegen Kuerzel ins Eingabefeld ein (nicht sofort senden) */
function chipInsert(txt,prefix){const i=$("#cin");
 if(prefix){if(!new RegExp("^"+txt.replace(/[./]/g,"\\$&")).test(i.value.trim()))i.value=(txt+" "+i.value).trim();}
 else if(!i.value.includes(txt))i.value=(i.value+" "+txt).replace(/^\s+/,"");
 i.focus();if(typeof growCin==="function")growCin();}
/* Befehls-Palette: ALLE echten Befehle auf einen Klick. Klick fuellt das Eingabefeld.
   Chat/Work/Coding sind oben Modi — hier stehen die uebrigen Befehle. */
const CMDS=[
 ["grp","Denken & Planen"],
 ["/plan ","Erst planen, dann Schritt fuer Schritt",false],
 ["reason: ","Staerkstes Modell (Richter/Fable)",false],
 ["grp","Abfragen"],
 ["/status","Heartbeat, Budget & Modell auf einen Blick",true],
 ["/mission","Missions- & Ziel-Lage abfragen",true],
 ["grp","Steuerung"],
 ["/model ","Modell anzeigen oder wechseln",false],
 ["@ziel:","Arbeit einem Ziel zuordnen",false],
 ["/schwarm arbeiter Vorlage | A | B","Schwarm-Auftrag an die Armee",false],
 ["/delegiere ","An einen einzelnen Sub-Agenten delegieren",false],
];
function renderCmdPop(){const el=$("#cmd-pop");if(!el)return;
 el.innerHTML=CMDS.map(c=>c[0]==="grp"?('<div class="cmd-grp">'+esc(c[1])+'</div>')
  :('<div class="cmd-row" data-cmd="'+esc(c[0])+'" data-send="'+(c[2]?1:0)+'"><span class="cmd-k">'+esc(c[0])+'</span><span class="cmd-d">'+esc(c[1])+'</span></div>')).join("");
 $$('#cmd-pop .cmd-row').forEach(r=>r.onclick=()=>{chipInsert(r.dataset.cmd,r.dataset.send==="1");$("#cmd-pop").style.display="none";});}
$("#cmd-help")&&($("#cmd-help").onclick=e=>{e.stopPropagation();const el=$("#cmd-pop");if(!el)return;
 const show=el.style.display==="none";if(show)renderCmdPop();el.style.display=show?"block":"none";});
document.addEventListener("click",e=>{const p=$("#cmd-pop");
 if(p&&p.style.display!=="none"&&!e.target.closest("#cmd-pop")&&e.target.id!=="cmd-help")p.style.display="none";});
/* S11: Denk-Tiefe-Regler ist LIVE — nur sichtbar, wenn das aktuelle Modell wirklich denken kann. */
let REASON_MARKERS=[];
function isReasoningModel(id){id=(id||"").toLowerCase();return REASON_MARKERS.some(m=>id.includes(m));}
function syncDenk(){const chip=$("#chip-denk");if(!chip)return;
 const sel=$("#chat-model");const id=sel?sel.value:"";
 chip.style.display=isReasoningModel(id)?"inline-flex":"none";}
/* Reasoning-Regler: eigenes Chip+Popover (einheitlich mit Commands/Modell, transparent statt weiss). */
function setReason(v){const rl=$("#reason-level");if(rl)rl.value=v||"";
 const chip=$("#chip-denk");if(chip){chip.textContent="Reasoning: "+(v||"Standard");chip.classList.toggle("on",!!v);}
 const p=$("#reason-pop");if(p)p.style.display="none";}
$("#chip-denk")&&($("#chip-denk").onclick=e=>{e.stopPropagation();const p=$("#reason-pop");if(!p)return;
 p.style.display=p.style.display==="none"?"block":"none";});
$$('#reason-pop .cmd-row').forEach(r=>r.onclick=()=>setReason(r.dataset.rl));
document.addEventListener("click",e=>{const p=$("#reason-pop");
 if(p&&p.style.display!=="none"&&!e.target.closest("#reason-pop")&&e.target.id!=="chip-denk")p.style.display="none";});
function sendText(raw,opts){raw=(raw||"").trim();if(!raw||!ws||ws.readyState!==1)return false;
 opts=opts||{};
 msgEl((opts.voice?"🎙️ ":"")+raw,"me");startThinking();
 let t=raw;
 if(opts.voice){t="sprich: "+raw;}  /* Assistenz-Modus: knappe, vorgelesene Antwort */
 else{
  /* Slash-Befehle (/model, /status, ...) NIE mit Modus-Praefix verschlucken */
  if(chatMode==="coding"&&!/^(\/|work:|plan:|code:)/i.test(raw))t="code: "+raw;       /* code: = plan + Coding-Regeln */
  else if(chatMode==="work"&&!/^(\/|work:|plan:|code:|reason:)/i.test(raw))t="work: "+raw; /* work: = volles Werkzeug-Budget */
  /* Denk-Tiefe nur, wenn der Regler sichtbar (= Modell denk-faehig) und gesetzt ist */
  const rl=$("#reason-level");const chip=$("#chip-denk");
  if(rl&&rl.value&&chip&&chip.style.display!=="none"&&!/^denk:/i.test(t))t="denk:"+rl.value+" "+t;
 }
 ws.send(t);curBot=null;curThink=null;traceC=null;curThinkLine=null;setStreaming(true);return true;}
/* Senden wird zu Stop, solange eine Antwort laeuft — Klick bricht ab und gibt dir die Kontrolle zurueck. */
let streaming=false;
function setStreaming(on){streaming=on;const b=$("#sendbtn");if(b){b.textContent=on?"⏹ Stop":"Senden";b.classList.toggle("stopping",on);}}
function stopStream(){if(!streaming)return;reconnect();stopThinking();
 curBot=null;curThink=null;traceC=null;curThinkLine=null;add("— gestoppt —","sys");setStreaming(false);}
$("#cform").onsubmit=e=>{e.preventDefault();
 if(streaming){stopStream();return;}                                   /* im Lauf: Stop statt neue Nachricht */
 if(sendText($("#cin").value)){$("#cin").value="";growCin();}};
/* Eingabefeld waechst mit dem Text (kein Seit-Scrollen); Enter sendet, Shift+Enter = neue Zeile */
function growCin(){const c=$("#cin");if(!c)return;c.style.height="auto";c.style.height=Math.min(c.scrollHeight,200)+"px";}
$("#cin")&&$("#cin").addEventListener("input",growCin);
$("#cin")&&$("#cin").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();
 if(streaming){stopStream();return;} if(sendText($("#cin").value)){$("#cin").value="";growCin();}}});

/* ---- Sprachmemo (Aufnahme -> Whisper) + Assistenz-Modus (freihaendige Schleife) ---- */
let mediaRec=null,chunks=[],recAutoSend=false,vadSpoke=false,liveTimer=null,liveBusy=false;
/* Live-Transkription (lokal): waehrend der Aufnahme alle ~2s die bisherige Aufnahme durch Whisper
   jagen und den wachsenden Text ins Feld schreiben. Nur EINE Transkription gleichzeitig (kein Stau);
   am Aufnahme-Ende laeuft die finale (genauere) Transkription und ersetzt die Vorschau. */
function startLive(){stopLive();liveBusy=false;
 liveTimer=setInterval(async()=>{
  if(liveBusy||!mediaRec||mediaRec.state!=="recording"||!chunks.length)return;
  liveBusy=true;
  try{const blob=new Blob(chunks,{type:"audio/webm"});
   const url=await new Promise(res=>{const r=new FileReader();r.onload=()=>res(r.result);r.readAsDataURL(blob);});
   const r=await (await fetch("/api/transcribe",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({audio:url})})).json();
   if(r&&r.ok&&r.text&&mediaRec&&mediaRec.state==="recording"){$("#cin").value=r.text;growCin();}
  }catch(e){}
  liveBusy=false;
 },2000);}
function stopLive(){if(liveTimer){clearInterval(liveTimer);liveTimer=null;}}
let ttsOn=localStorage.getItem("kira_tts")==="1";      /* 🔊 Antworten vorlesen */
let handsFree=false;                                    /* 🎙️ Assistenz: Kira hoert freihaendig zu */
let curAudio=null;
const WAKE=/\bk[iy]e?ra\b/i;                             /* Weckwort "Kira" (mit Whisper-Varianten) */
$("#tts-on")&&($("#tts-on").checked=ttsOn,$("#chip-tts")&&$("#chip-tts").classList.toggle("on",ttsOn),
 $("#tts-on").onchange=()=>{ttsOn=$("#tts-on").checked;localStorage.setItem("kira_tts",ttsOn?"1":"0");
  $("#chip-tts")&&$("#chip-tts").classList.toggle("on",ttsOn);});
/* Text -> ElevenLabs-MP3 -> abspielen. Bricht nie (204/Fehler = still). */
function speak(text){text=(text||"").trim();if(!text)return Promise.resolve();
 return fetch("/api/voice/say",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:text})})
  .then(r=>(r.ok&&r.status===200)?r.blob():null)
  .then(b=>{if(!b)return;try{if(curAudio)curAudio.pause();}catch(e){}
   const url=URL.createObjectURL(b);curAudio=new Audio(url);
   return new Promise(res=>{curAudio.onended=()=>{URL.revokeObjectURL(url);res();};
    curAudio.onerror=()=>res();curAudio.play().catch(()=>res());});})
  .catch(()=>{});}
/* Kira hat geantwortet: vorlesen (wenn an oder Assistenz), dann ggf. wieder lauschen. */
async function onKiraReply(text){
 if(ttsOn||handsFree)await speak(text);
 if(handsFree)armListen();}
function armListen(){if(handsFree&&!(mediaRec&&mediaRec.state==="recording"))startRec(true);}
/* Stille-Erkennung: stoppt die Aufnahme automatisch nach einer Sprechpause (freihaendig).
   Ohne WebAudio faellt es sanft aus -> dann stoppt Sergen per Knopf. */
function attachVAD(stream,rec){
 let ctx,an,raf,silence=0,last=performance.now(),started=last;vadSpoke=false;
 try{ctx=new (window.AudioContext||window.webkitAudioContext)();
  const src=ctx.createMediaStreamSource(stream);an=ctx.createAnalyser();an.fftSize=512;src.connect(an);
  const buf=new Uint8Array(an.fftSize);
  rec.addEventListener("stop",()=>{try{cancelAnimationFrame(raf);}catch(e){}try{ctx.close();}catch(e){}},{once:true});
  const tick=()=>{if(rec.state!=="recording")return;
   an.getByteTimeDomainData(buf);let s=0;for(let i=0;i<buf.length;i++){const v=(buf[i]-128)/128;s+=v*v;}
   const rms=Math.sqrt(s/buf.length),now=performance.now(),dt=now-last;last=now;
   if(rms>0.045)vadSpoke=true;
   if(vadSpoke){silence=rms<0.02?silence+dt:0;if(silence>1200){try{rec.stop();}catch(e){}return;}}
   else if(now-started>7000){try{rec.stop();}catch(e){}return;}  /* nur Stille -> Runde beenden */
   if(now-started>15000){try{rec.stop();}catch(e){}return;}      /* Sicherheitslimit */
   raf=requestAnimationFrame(tick);};
  raf=requestAnimationFrame(tick);
 }catch(e){/* kein WebAudio -> Nutzer stoppt per Knopf */}}
async function startRec(autoSend){recAutoSend=!!autoSend;
 try{const stream=await navigator.mediaDevices.getUserMedia({audio:true});chunks=[];mediaRec=new MediaRecorder(stream);
  mediaRec.ondataavailable=ev=>chunks.push(ev.data);
  mediaRec.onstop=async()=>{stopLive();stream.getTracks().forEach(t=>t.stop());$("#micbtn")&&($("#micbtn").textContent="🎤");
   if(recAutoSend&&!vadSpoke){if(handsFree)armListen();return;}  /* nur Stille -> nicht transkribieren */
   const blob=new Blob(chunks,{type:"audio/webm"});const rd=new FileReader();
   rd.onload=async()=>{if(!recAutoSend)$("#cin").value="… transkribiere …";
    let txt="",ok=false;
    try{const r=await (await fetch("/api/transcribe",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({audio:rd.result})})).json();
     ok=!!r.ok;txt=ok?(r.text||""):"";if(!ok&&!recAutoSend)$("#cin").value="(Audio-Fehler: "+(r.error||"")+")";}catch(e){}
    if(recAutoSend){
     const heard=(txt||"").trim();
     if(heard&&WAKE.test(heard)){                     /* nur reagieren, wenn "Kira" gesagt wurde */
      const instr=heard.replace(new RegExp(".*?"+WAKE.source+"[\\s,:!.-]*","i"),"").trim();
      if(instr)sendText(instr,{voice:true});           /* Weckwort abgestreift -> Auftrag */
      else{add("🎙️ Ja? Ich hoere.","sys");armListen();} /* nur "Kira" -> weiterlauschen */
     }else if(handsFree)armListen();                   /* nicht angesprochen -> still weiterlauschen */
    }else if(ok){$("#cin").value=txt;growCin();$("#cin").focus();}};
   rd.readAsDataURL(blob);};
  /* manuelles Mikro (kein Weckwort-Lauschen) -> Aufnahme in Haeppchen + Live-Transkription */
  if(recAutoSend){mediaRec.start();}else{$("#cin").value="";growCin();mediaRec.start(1200);startLive();}
  $("#micbtn")&&($("#micbtn").textContent="⏹");
  if(autoSend)attachVAD(stream,mediaRec);              /* freihaendig -> Pause stoppt automatisch */
 }catch(err){add("Mikrofon nicht verfuegbar: "+err,"sys");handsFree=false;paintAssist();}}
$("#micbtn")&&($("#micbtn").onclick=()=>{if(mediaRec&&mediaRec.state==="recording"){mediaRec.stop();return;}startRec(false);});
/* Assistenz-Modus lebt in der Zentrale (#hud-assist). Toggle: an -> lauschen + vorlesen; aus -> stumm. */
function paintAssist(){const b=$("#hud-assist");if(b){b.textContent=handsFree?"🎙️ hoert zu · AUS?":"🎙️ Zuhoeren?";
 b.style.color=handsFree?"var(--ok)":"var(--muted)";}}
function toggleAssist(){handsFree=!handsFree;paintAssist();
 if(handsFree){add("🎙️ Assistenz-Modus an — sag \"Kira\" + deine Anweisung, ich hoere zu und antworte knapp.","sys");armListen();}
 else{try{if(mediaRec&&mediaRec.state==="recording")mediaRec.stop();}catch(e){}
  try{if(curAudio)curAudio.pause();}catch(e){}add("Assistenz-Modus aus.","sys");}}

/* ---- Bild an Kira (Vision) ---- */
$("#imgfile")&&($("#imgfile").onchange=ev=>{const f=ev.target.files[0];if(!f)return;
 if(f.type&&f.type.startsWith("image/")){                       /* Bild -> Vision-Beschreibung -> in den Chat */
  const rd=new FileReader();rd.onload=async()=>{
   const im=document.createElement("div");im.className="msg me";
   im.innerHTML='<img src="'+rd.result+'" style="max-width:240px;border-radius:8px;display:block"/>';log.appendChild(im);log.scrollTop=log.scrollHeight;
   const prompt=$("#cin").value.trim();$("#cin").value="";
   const b=msgEl("… Kira betrachtet das Bild …","bot");
   let desc="";
   try{const r=await (await fetch("/api/vision",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:prompt,image:rd.result})})).json();
    if(!r.ok){b.querySelector(".mbody").innerHTML=md("(Bild-Fehler: "+(r.error||"")+")");log.scrollTop=log.scrollHeight;return;}
    desc=r.text||"";}
   catch(err){b.querySelector(".mbody").textContent="(Bild-Fehler: "+err+")";return;}
   /* Beschreibung in den laufenden Chat einspeisen -> Kira kann darauf aufbauen (nachfragen,
      Mail schreiben, merken). Kein Chat verbunden -> wenigstens die Beschreibung zeigen. */
   if(ws&&ws.readyState===1){
    b.remove();
    const full=(prompt?prompt:"Schau dir das Bild an und sag mir, was du siehst.")
     +"\n\n[Angehaengtes Bild — Kiras Bildbeschreibung: "+desc+"]";
    startThinking();ws.send(full);setStreaming(true);curBot=null;curThink=null;traceC=null;curThinkLine=null;
   } else { b.querySelector(".mbody").innerHTML=md(desc); }
   log.scrollTop=log.scrollHeight;};
  rd.readAsDataURL(f);
 } else { attachFile(f); }                                       /* PDF/Datei -> Text an Kira in den Chat */
 ev.target.value="";});
/* Datei anhaengen: Text extrahieren (Server) + als Kontext an Kira senden — sie kann dann
   analysieren ODER (mit email_send) eine Mail schreiben. Die Blase zeigt nur 📎 Name + dein Auftrag. */
async function attachFile(f){
 const b=msgEl("… Kira liest "+f.name+" …","bot");
 try{const fd=new FormData();fd.append("file",f);
  const r=await (await fetch("/api/chat/attach",{method:"POST",body:fd})).json();
  if(!r.ok){b.querySelector(".mbody").textContent="(Datei-Fehler: "+(r.error||"?")+")";return;}
  b.remove();
  const prompt=$("#cin").value.trim();$("#cin").value="";
  msgEl("📎 "+r.name+(r.truncated?" (gekuerzt)":"")+(prompt?(" — "+prompt):""),"me");
  const full=(prompt?prompt+"\n\n":"Fasse mir diese Datei zusammen.\n\n")
   +"[Angehaengte Datei: "+r.name+(r.truncated?" — auf "+Math.round(12000/1000)+"k Zeichen gekuerzt, gesamt "+r.chars+"]":"]")+"\n\n"+r.text;
  if(ws&&ws.readyState===1){startThinking();ws.send(full);setStreaming(true);curBot=null;curThink=null;traceC=null;curThinkLine=null;}
 }catch(err){b.querySelector(".mbody").textContent="(Fehler: "+err+")";}}

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
 // Verfassung ist Kiras Kern -> Sicherheits-Rueckfrage (andere Dateien speichern direkt)
 if(fcur.name==="constitution.md"&&!confirm("Kiras Verfassung ändern?\n\nGilt sofort für alle Antworten. Ein Backup wird automatisch angelegt (core/mind/history) — rückgängig machbar."))return;
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
  if(low.includes("embed")||low.includes("hf.co")||low.includes("gguf"))return;  // kein Modell / Alias nutzen
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
const ROLE_LABEL={chat:"💬 Chat",reason:"🧠 Denker (Reason/Coding)",bulk:"⏰ Crons",classify:"🐜 Reflex (lokal)",worker:"🔧 Arbeiter (Delegation)",escalation:"⚡ Eskalation",default:"★ Default"};
let MCAT={openrouter:[],local:[],aimlapi:[]};
function money(x){return (x==null||x===0)?"0€":("$"+(x*1e6).toFixed(2)+"/M");}
function renderRoles(roles){const el=$("#m-roles");if(!el)return;
 el.innerHTML=Object.keys(ROLE_LABEL).map(r=>'<div style="display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--line)"><span style="min-width:150px">'+ROLE_LABEL[r]+'</span><b style="flex:1;color:var(--accent)">'+((roles[r]||"—")+"").replace(/^openrouter\//,"").replace(/</g,"&lt;")+'</b></div>').join("");}
function renderCat(){const el=$("#cat-list");if(!el)return;const q=(($("#cat-search")||{}).value||"").toLowerCase().trim();
 const all=(MCAT.local||[]).concat(MCAT.openrouter||[]).concat(MCAT.aimlapi||[]);
 const hits=all.filter(m=>!q||(m.id||"").toLowerCase().includes(q)||(m.name||"").toLowerCase().includes(q)).slice(0,80);
 el.innerHTML=hits.length?hits.map(m=>'<div style="display:flex;gap:8px;align-items:center;padding:4px 2px;border-bottom:1px solid var(--line)">'
   +'<span style="flex:1"><b>'+(m.id||"").replace(/^openrouter\//,"").replace(/</g,"&lt;")+'</b>'+(m.ctx?' <small class=muted>'+Math.round(m.ctx/1000)+'K</small>':'')+'</span>'
   +'<small class=muted style="min-width:120px">'+money(m.in)+' · '+money(m.out)+'</small>'
   +'<button class=ghost data-mid="'+m.id+'" style="padding:3px 9px">→ zuweisen</button></div>').join(""):'<span class=muted>(keine Treffer)</span>';
 el.querySelectorAll('button[data-mid]').forEach(b=>b.onclick=async()=>{const role=$("#cat-role").value;
   $("#cat-hint").textContent="… setze "+role+" …";
   await fetch("/api/model/role",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role,model:b.dataset.mid})});
   $("#cat-hint").innerHTML=ROLE_LABEL[role]+' → <b>'+b.dataset.mid.replace(/^openrouter\//,"")+'</b> ✓';loadModels();refreshStatus();});}
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

/* ---- Steuerpult: Sergens Riegel ueber die Schwarmintelligenz ---- */
const RANG_ICON={reflex:"🐜",arbeiter:"🔧",denker:"🧠",richter:"⚖"};
async function loadSteuer(){const el=$("#st-raenge");if(!el)return;
 try{const d=await (await fetch("/api/steuer")).json();
  el.innerHTML=(d.raenge||[]).map(r=>{const real=(r.real||"").replace(/^openrouter\//,"");
   const gesetzt=((r.modell||"—")+"").replace(/^openrouter\//,"").replace(/</g,"&lt;");
   return '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 2px;border-bottom:1px solid var(--line)">'
    +'<span style="min-width:150px">'+(RANG_ICON[r.rang]||"")+' <b>'+r.rang+'</b> <small class=muted>'+r.info+'</small></span>'
    +'<span style="flex:1;min-width:180px"><b style="color:var(--accent)">'+gesetzt+'</b>'
    +(r.fallback?' <small class="no">läuft real: '+real.replace(/</g,"&lt;")+' [FALLBACK]</small>':'')
    +' <small class=muted>· '+r.schritte+' Schritte</small></span>'
    +'<input list="st-modelle" data-strang="'+r.rolle+'" placeholder="Modell suchen…" style="min-width:200px"/>'
    +'<button class=ghost data-stgo="'+r.rolle+'" style="padding:3px 9px">zuweisen</button></div>';}).join("");
  el.querySelectorAll("button[data-stgo]").forEach(b=>b.onclick=async()=>{
   const inp=el.querySelector('input[data-strang="'+b.dataset.stgo+'"]');const mid=(inp.value||"").trim();
   if(!mid)return;$("#st-rang-hint").textContent="… setze "+b.dataset.stgo+" …";
   await fetch("/api/model/role",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role:b.dataset.stgo,model:mid})});
   $("#st-rang-hint").innerHTML="✓ gesetzt";loadSteuer();refreshStatus();});
  const set=(id,v)=>{const x=$(id);if(x&&document.activeElement!==x)x.value=v;};
  const st={};(d.raenge||[]).forEach(r=>st[r.rang]=r.schritte);
  set("#st-s-reflex",st.reflex);set("#st-s-arbeiter",st.arbeiter);set("#st-s-denker",st.denker);set("#st-s-richter",st.richter);
  set("#st-breite",d.schwarm_max);set("#st-kosten",d.max_kosten_eur);
  const dl=$("#st-modelle");if(dl&&!dl.children.length){try{const c=await (await fetch("/api/model/catalog")).json();
   const cat=c.catalog||{};const all=(cat.local||[]).concat(cat.openrouter||[]).concat(cat.aimlapi||[]);
   dl.innerHTML=all.slice(0,600).map(m=>'<option value="'+(m.id||"").replace(/"/g,"&quot;")+'">').join("");}catch(e){}}
 }catch(e){el.innerHTML='<span class=muted>Steuerpult nicht erreichbar.</span>';}}
$("#st-regler-save")&&($("#st-regler-save").onclick=async()=>{
 const n=id=>parseFloat(($(id)||{}).value);
 for(const [id,path] of [["#st-s-reflex","agency.delegate.schritte.reflex"],["#st-s-arbeiter","agency.delegate.schritte.arbeiter"],
   ["#st-s-denker","agency.delegate.schritte.denker"],["#st-s-richter","agency.delegate.schritte.richter"],
   ["#st-breite","agency.delegate.schwarm_max"]]){const v=n(id);if(!isNaN(v))await cfgSet(path,Math.round(v));}
 const k=n("#st-kosten");if(!isNaN(k))await cfgSet("agency.delegate.max_kosten_eur",k);
 $("#st-regler-hint").textContent="✓ live übernommen";loadSteuer();});
$("#st-cmd-schwarm")&&($("#st-cmd-schwarm").onchange=e=>{$("#st-cmd-items").style.display=e.target.checked?"":"none";});
$("#st-cmd-go")&&($("#st-cmd-go").onclick=()=>{
 const rang=$("#st-cmd-rang").value;const auftrag=($("#st-cmd-auftrag").value||"").trim().replace(/\s*\n\s*/g," ");
 if(!auftrag)return;let cmd;
 if($("#st-cmd-schwarm").checked){const items=($("#st-cmd-items").value||"").split("\n").map(s=>s.trim()).filter(Boolean);
  if(!items.length){$("#st-cmd-items").focus();return;}
  cmd="/schwarm "+rang+" "+auftrag+" | "+items.join(" | ");}
 else{cmd="/delegiere "+rang+" "+auftrag;}
 nav("chat");const ci=$("#cin");if(ci){ci.value=cmd;ci.focus();}});
async function doRestart(e){if(e&&e.preventDefault)e.preventDefault();await fetch("/api/restart",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});alert("Neustart angefordert — Dienste bouncen in ~20s.");}
/* S8.3: Autonomie-Karte — echte Schalter statt Vertrauensbarometer */
const GATE_KINDS={money:"💶 Geld bewegen",email_stranger:"✉️ Mails/Nachrichten an Fremde",
 publish:"📮 Veroeffentlichen (Posts, Deploys nach aussen)",external:"🌐 Externe Dienste schreiben",
 email:"📧 Mails an dich/Bekannte"};
async function loadAutonomy(){try{const d=await J("/api/autonomy");
 const box=$("#au-box");if(!box)return;
 let h='<label style="cursor:pointer;display:flex;gap:8px;align-items:center"><input type="checkbox" id="au-chains" '+(d.chains_off?"":"checked")+'/> '
  +'<span><b>Ketten an</b> — ALLES Externe braucht deine Freigabe (Vorsichts-Modus)</span></label>'
  +'<div class="muted" style="margin:10px 0 4px;font-size:11px;letter-spacing:1px">FREIGABE-PFLICHT (wenn Ketten aus):</div>';
 (d.kinds||[]).forEach(k=>{h+='<label style="cursor:pointer;display:flex;gap:8px;align-items:center;padding:2px 0">'
  +'<input type="checkbox" data-gate="'+k+'" '+((d.hard_gate||[]).includes(k)?"checked":"")+'/> <span>'+(GATE_KINDS[k]||k)+'</span></label>';});
 h+='<div class="muted" style="margin-top:8px;font-size:12px">Vor Geld-Aktionen debattiert zusaetzlich der Rat: '+esc((d.council_gate||[]).join(", ")||"aus")+'</div>';
 box.innerHTML=h;
}catch(e){}}
$("#au-save")&&($("#au-save").onclick=async()=>{
 const hard=[...document.querySelectorAll('#au-box [data-gate]')].filter(x=>x.checked).map(x=>x.dataset.gate);
 const chains_off=!$("#au-chains").checked;
 await fetch("/api/autonomy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chains_off:chains_off,hard_gate:hard})});
 $("#au-hint").textContent="✓ gespeichert — greift sofort";toast("Autonomie-Schalter gespeichert","ok");});
async function loadGov(){const g=await (await fetch("/api/governance")).json();const t=g.treasury;
 $("#g-budget").innerHTML="Heute:<br>"+bar(t.day_spent,t.day_limit)+"<br><br>Diesen Monat:<br>"+bar(t.month_spent,t.month_limit);
 if($("#g-day")&&document.activeElement!==$("#g-day"))$("#g-day").value=t.day_limit!=null?t.day_limit:"";
 if($("#g-month")&&document.activeElement!==$("#g-month"))$("#g-month").value=t.month_limit!=null?t.month_limit:"";
 loadAutonomy();
 const a=$("#g-audit");a.innerHTML=g.audit.length?g.audit.map(e=>{const ts=new Date(e.ts*1000).toLocaleString();const p=e.payload;
   return '<div style="padding:6px 0;border-bottom:1px solid var(--line)"><b>'+esc(p.action)+'</b> '+esc(p.target||'')
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

/* ---- Zugaenge ---- */
async function loadKeys(){const s=await (await fetch("/api/secrets")).json();
 /* Kira-Stimme: Status + Schalter befuellen */
 const t=s.tts||{};const vs=$("#voice-stat");
 if(vs)vs.innerHTML="Key: "+(t.key_set?'<b class=ok>gesetzt ✓</b>':'<b class=no>fehlt</b>')
   +" · Stimme: "+(t.enabled?'<b class=ok>an</b>':'<b class=no>aus</b>');
 if($("#voice-on")&&document.activeElement!==$("#voice-on"))$("#voice-on").checked=!!t.enabled;
 if($("#voice-id")&&document.activeElement!==$("#voice-id"))$("#voice-id").value=t.voice_id||"";
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
/* ---- Kira-Stimme: Key speichern + An/Aus + Stimme (alles im Zugaenge-Tab) ---- */
$("#voice-key-save")&&($("#voice-key-save").onclick=async()=>{const v=$("#voice-key").value;
 if(!v.trim()){$("#voice-hint").textContent="Key ist leer.";return;}
 await fetch("/api/secrets/set",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({name:"ELEVENLABS_API_KEY",value:v})});
 $("#voice-key").value="";$("#voice-hint").textContent="Key gespeichert ✓";loadKeys();});
$("#voice-save")&&($("#voice-save").onclick=async()=>{
 await cfgSet("channels.telegram.tts.enabled",$("#voice-on").checked);
 await cfgSet("channels.telegram.tts.voice_id",$("#voice-id").value.trim());
 $("#voice-hint").textContent="Übernommen ✓ — schick Kira eine Sprachnachricht.";loadKeys();refreshStatus();});
$("#voice-test")&&($("#voice-test").onclick=async()=>{const o=$("#voice-testout");
 o.innerHTML="… teste die Stimme (kann ~5 s dauern) …";
 try{const r=await (await fetch("/api/voice/test",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();
  o.innerHTML=(r.ok?'<b class=ok>':'<b class=no>')+(r.reason||(r.ok?"OK":"Fehler"))+'</b>';
 }catch(e){o.innerHTML='<b class=no>Test nicht erreichbar: '+e+'</b>';}});

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
/* ---- Eigene Farben: Hintergrund / Kästen / Neon (überschreibt das Theme, in localStorage) ---- */
function loadCustom(){try{return JSON.parse(localStorage.getItem("kira_custom")||"{}");}catch(e){return {};}}
function saveCustom(c){try{localStorage.setItem("kira_custom",JSON.stringify(c));}catch(e){}}
function applyCustom(c){c=c||{};const r=document.documentElement.style;
 if(c.bg)r.setProperty("--bg",c.bg);
 if(c.panel){r.setProperty("--panel",c.panel);r.setProperty("--panel2",c.panel);}
 if(c.accent){r.setProperty("--accent",c.accent);r.setProperty("--glow",c.accent);r.setProperty("--hud",c.accent);}
 if(c.hud)r.setProperty("--hud",c.hud);        /* eigener HUD-Regler gewinnt ueber den Accent */
 if(c.ink)r.setProperty("--ink",c.ink);        /* Schrift-Farbe (auch Seitenleiste) */
 if(c.muted)r.setProperty("--muted",c.muted);  /* gedaempfte Schrift */
 if(c.line)r.setProperty("--line",c.line);     /* Linien & Rahmen */
 if(c.font)r.setProperty("--font",c.font);}    /* Schriftart fuers ganze Dashboard */
function bindColor(sel,key,fallback){const el=$(sel);if(!el)return;const c=loadCustom();
 el.value=c[key]||fallback;
 el.oninput=()=>{const cc=loadCustom();cc[key]=el.value;saveCustom(cc);applyCustom(cc);};}
bindColor("#col-bg","bg","#0a0a0d");bindColor("#col-panel","panel","#0e0e13");bindColor("#col-accent","accent","#8b5cf6");
bindColor("#col-hud","hud","#c084fc");bindColor("#col-ink","ink","#eceef4");bindColor("#col-muted","muted","#9b97b0");bindColor("#col-line","line","#26203a");
(function(){const el=$("#font-sel");if(!el)return;const c=loadCustom();el.value=c.font||"";
 el.onchange=()=>{const cc=loadCustom();cc.font=el.value;saveCustom(cc);applyCustom(cc);};})();
$("#col-reset")&&($("#col-reset").onclick=()=>{localStorage.removeItem("kira_custom");location.reload();});
applyCustom(loadCustom());  /* eigene Farben beim Start anwenden (nach setTheme, gewinnt) */

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
updatePulse();

/* ---- Direktive (Startseite) ---- */
/* Diktier-Knopf (Voice -> Textfeld), unabhaengig vom Chat-Mikro/Assistenz-Modus */
function simpleRecord(btnSel,targetSel){const btn=$(btnSel);if(!btn)return;let rec=null,ch=[];
 btn.onclick=async()=>{if(rec&&rec.state==="recording"){rec.stop();return;}
  try{const stream=await navigator.mediaDevices.getUserMedia({audio:true});ch=[];rec=new MediaRecorder(stream);
   rec.ondataavailable=e=>ch.push(e.data);
   rec.onstop=async()=>{stream.getTracks().forEach(t=>t.stop());btn.textContent="🎤";
    const t=$(targetSel);const old=(t&&t.value||"").trim();const blob=new Blob(ch,{type:"audio/webm"});const rd=new FileReader();
    rd.onload=async()=>{t.value=(old?old+" ":"")+"… transkribiere …";
     try{const r=await (await fetch("/api/transcribe",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({audio:rd.result})})).json();
      t.value=(old?old+" ":"")+(r.ok?(r.text||""):"(Audio-Fehler)");}catch(e){t.value=old;}t.focus();};
    rd.readAsDataURL(blob);};
   rec.start();btn.textContent="⏹";
  }catch(err){add("Mikrofon nicht verfuegbar: "+err,"sys");}};}
simpleRecord("#dir-mic","#dir-text");
/* Schwarm-Umschalter: blendet den Rang ein, ändert den Knopf */
$("#dir-schwarm")&&($("#dir-schwarm").onchange=()=>{const on=$("#dir-schwarm").checked;
 const rg=$("#dir-rang");if(rg)rg.style.display=on?"":"none";
 const b=$("#dir-now");if(b)b.textContent=on?"🐝 An den Schwarm":"⚡ Sofort ausfuehren";
 const t=$("#dir-text");if(t)t.placeholder=on
   ?"1. Zeile = Auftrag mit {item}  (z.B. „Finde 5 Telefonnummern fuer {item} in Koblenz“)\ndann je eine Zeile pro Ziel:\nFriseure\nHotels"
   :"Sag mir, worauf ich mich konzentrieren soll — oder gib mir einen Sofort-Auftrag…";
 $("#dir-hint").textContent=on?"🐝 Jede Zeile unter dem Auftrag wird ein eigener Agent (bis schwarm_max, sonst in Wellen).":"";});
$("#dir-now")&&($("#dir-now").onclick=async()=>{const p=$("#dir-text").value.trim();if(!p)return;
 if($("#dir-schwarm")&&$("#dir-schwarm").checked){                       /* Schwarm-Auftrag -> im Chat vorbereiten (Finger am Abzug bleibt bei dir) */
  const rang=($("#dir-rang")&&$("#dir-rang").value)||"arbeiter";
  /* 1. Zeile = Vorlage (mit {item}), weitere Zeilen = Ziele -> korrektes "/schwarm rang vorlage | a | b" */
  const lines=p.split("\n").map(s=>s.trim()).filter(Boolean);
  if(lines.length<2){$("#dir-hint").textContent="🐝 Schwarm braucht Ziele: 1. Zeile der Auftrag (mit {item}), dann je eine Zeile pro Ziel (z.B. Friseure / Hotels).";return;}
  const vorlage=lines[0],items=lines.slice(1);
  const cin=$("#cin");if(cin)cin.value="/schwarm "+rang+" "+vorlage+" | "+items.join(" | ");
  nav("chat");if(cin)cin.focus();$("#dir-hint").textContent="🐝 "+items.length+" Auftraege im Chat vorbereitet — druecke Senden.";return;}
 $("#dir-hint").textContent="… Kira arbeitet daran (kann ~1 min dauern) …";
 const r=await (await fetch("/api/direktive/now",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:p})})).json();
 $("#dir-hint").textContent="✓ erledigt";const rr=$("#dir-result");rr.style.display="block";rr.textContent=(r.result||"(keine Antwort)");});
$("#dir-focus")&&($("#dir-focus").onclick=async()=>{const p=$("#dir-text").value.trim();
 await fetch("/api/direktive",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({focus:p})});
 $("#dir-hint").textContent="🧭 Fokus gesetzt — ich ziehe ihn in meinen naechsten Schritt.";loadHome();});
$("#dir-clear")&&($("#dir-clear").onclick=async()=>{await fetch("/api/direktive",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({focus:""})});$("#dir-text").value="";$("#dir-hint").textContent="Fokus geloescht.";loadHome();});

/* ---- Leben (S5.3b): Todos, Ziele, Metrik-Sparklines ---- */
function spark(series){if(!series||series.length<2)return'<span class="muted" style="margin-right:8px">&mdash;</span>';
 const vs=series.map(p=>p.value),mn=Math.min(...vs),mx=Math.max(...vs),W=120,H=26;
 const pts=vs.map((v,i)=>((i/(vs.length-1))*W).toFixed(1)+","+(H-3-((mx===mn)?H/2-3:(v-mn)/(mx-mn)*(H-6))).toFixed(1)).join(" ");
 return '<svg width="'+W+'" height="'+H+'" style="margin-right:8px;overflow:visible"><polyline points="'+pts+'" fill="none" stroke="var(--hud)" stroke-width="1.5"/></svg>';}
async function loadLeben(){
 try{const d=await (await fetch("/api/life/board")).json();const b=d.board||{};let h="";
  BOARD_GROUPS.forEach(([k,label])=>{const arr=b[k]||[];if(!arr.length)return;
   h+='<div style="margin:9px 0 4px;font-size:11px;letter-spacing:1px;color:var(--hud);text-transform:uppercase">'+label+' ('+arr.length+')</div>'
    +arr.map(t=>{const due=t.due_date?('&#9200;'+t.due_date):'';
     const act=t.status==="pending"?' <a data-ldone="'+t.id+'" style="cursor:pointer;color:var(--ok)" title="abhaken">&#10003;</a>':'';
     return '<div class="op" style="border-radius:8px;margin-bottom:3px"><span class="od"></span><span class="opx">'+(t.description||"").replace(/</g,"&lt;").slice(0,150)+' <span class="muted">'+due+'</span></span>'+act+'</div>';}).join("");});
  $("#life-board").innerHTML=h||'<div class="emptybox">Keine offenen Todos<br>Sag mir einfach, was ansteht.</div>';
  $$('#life-board [data-ldone]').forEach(a=>a.onclick=async()=>{await fetch("/api/mission/task/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.ldone,status:"done"})});loadLeben();});
  const objs=d.objectives||[];
  $("#life-goals").innerHTML=objs.length?objs.map(o=>'<div class="memrow"><div class="mh"><span class="badge kind">'+(KIND_LABEL[o.kind]||o.kind)+'</span><b>'+(o.title||"").replace(/</g,"&lt;")+'</b><span style="flex:1"></span><span class="muted">'+o.progress+'%'+(o.target_date?(' &middot; &#9200;'+o.target_date):'')+'</span></div></div>').join("")
   :'<div class="emptybox">Noch keine Lebens-Ziele<br>z.B. Kira, neues Ziel: 85kg bis Dezember</div>';
 }catch(e){}}

/* ---- Ziele-Dashboard (S10): Kennzahlen mit Zielwert, Fortschritt, Zentrale-Anheftung ----
   Kira schreibt per metric_log/metric_ziel selbst rein; hier nur Anzeige + Feinsteuerung. */
function sparkVals(vals){return spark((vals||[]).map(v=>({value:v})));}
function zieleCard(d){
 const em=d.emoji?(esc(d.emoji)+' '):'';
 const unit=d.unit?(' <span class="muted">'+esc(d.unit)+'</span>'):'';
 const delta=d.delta!=null?(' <span class="muted">('+(d.delta>0?'+':'')+d.delta+')</span>'):'';
 const bar=(d.target!=null)?('<div class="mini-bar" style="margin-top:6px"><i style="width:'+(d.progress||0)+'%"></i></div>'
   +'<div class="muted" style="font-size:10px;margin-top:2px">Ziel '+d.target+(d.unit?(' '+esc(d.unit)):'')+' · '+(d.progress||0)+'%</div>'):'';
 const pin=d.pinned?'📌':'📍';
 return '<div class="memrow" data-zn="'+esc(d.name)+'"><div class="mh"><b>'+em+esc(d.name)+'</b>'
  +'<span style="flex:1"></span>'+sparkVals(d.series)
  +'<span style="min-width:92px;text-align:right"><b>'+d.value+'</b>'+unit+delta+'</span>'
  +' <a data-zpin="'+esc(d.name)+'" data-zon="'+(d.pinned?1:0)+'" title="in die Zentrale heften/loesen" style="cursor:pointer;margin-left:6px">'+pin+'</a></div>'
  +bar+'</div>';
}
async function loadZiele(){const el=$("#life-metrics");if(!el)return;
 try{const m=await (await fetch("/api/metrics?days=90")).json();const ds=m.dashboard||[];
  el.innerHTML=ds.length?ds.map(zieleCard).join("")
   :'<div class="emptybox">Noch keine Kennzahlen<br>Sag mir: „Kira, tracke meine Follower — Ziel 10000, zeig&#39;s in der Zentrale.“</div>';
  $$('#life-metrics [data-zpin]').forEach(a=>a.onclick=async()=>{
   await fetch("/api/metrics/meta",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name:a.dataset.zpin,pinned:a.dataset.zon!=="1"})});
   loadZiele();loadZielePinned();});
 }catch(e){}}
$("#zm-add")&&($("#zm-add").onclick=async()=>{
 const name=($("#zm-name").value||"").trim();if(!name){toast("Kennzahl braucht einen Namen","warn");return;}
 const val=($("#zm-val").value||"").trim();
 if(val!==""){await fetch("/api/metrics/log",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:name,value:val})});}
 const tgt=($("#zm-target").value||"").trim(),unit=($("#zm-unit").value||"").trim();
 if(tgt!==""||unit!==""){await fetch("/api/metrics/meta",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.assign({name:name},tgt!==""?{target:tgt}:{},unit!==""?{unit:unit}:{}))});}
 $("#zm-name").value="";$("#zm-val").value="";$("#zm-target").value="";$("#zm-unit").value="";
 toast("eingetragen","ok");loadZiele();loadZielePinned();});
/* Angeheftete Kennzahlen in der Zentrale (nur wenn welche angeheftet sind). */
async function loadZielePinned(){const el=$("#z-ziele");if(!el)return;
 try{const m=await (await fetch("/api/metrics?days=90")).json();const ps=m.pinned||[];
  const wrap=$("#z-ziele-panel");
  if(!ps.length){if(wrap)wrap.style.display="none";return;}
  if(wrap)wrap.style.display="";
  el.innerHTML=ps.map(d=>{const em=d.emoji?(esc(d.emoji)+' '):'';
   const bar=(d.target!=null)?('<div class="mini-bar" style="margin-top:4px"><i style="width:'+(d.progress||0)+'%"></i></div>'):'';
   return '<div style="margin-bottom:9px"><div style="display:flex;align-items:center;gap:6px"><span>'+em+esc(d.name)+'</span><span style="flex:1"></span><b style="color:var(--hud)">'+d.value+'</b>'+(d.unit?' <span class="muted">'+esc(d.unit)+'</span>':'')+(d.target!=null?' <span class="muted">/ '+d.target+'</span>':'')+'</div>'+bar+'</div>';
  }).join("");
 }catch(e){}}

/* ---- Agenten (S5.3b): Organe, Dienste, MCP ---- */
/* S6.7b: Werkzeug-Wolke gruppieren — 'mcp github ×12' statt zwoelf mcp_github_*-Pillen.
   Hover auf der Gruppen-Pille zeigt die vollen Namen (title). */
function toolGroups(names){
 const groups={};
 (names||[]).forEach(n=>{
  const m=n.match(/^mcp_([a-z0-9]+)_/);
  const p=m?("mcp "+m[1]):((n.match(/^(venture|todo|metric|knowledge|trigger|watch|cron|opportunity|email)_/)||[])[1]||null);
  const key=p||n;(groups[key]=groups[key]||[]).push(n);});
 return Object.keys(groups).sort().map(k=>{const g=groups[k];
  return g.length>1?'<span class="pill" title="'+esc(g.join(", "))+'">'+esc(k)+' ×'+g.length+'</span>'
                   :'<span class="pill">'+esc(g[0])+'</span>';}).join(" ");}
async function loadAgenten(){try{const d=await (await fetch("/api/agents")).json();
 const rel=ts=>{if(!ts)return "noch nie";const x=(Date.now()/1000-ts);return x<90?"gerade eben":x<3600?Math.round(x/60)+" min":x<86400?Math.round(x/3600)+" h":Math.round(x/86400)+" Tage";};
 $("#ag-organs").innerHTML=(d.organs||[]).map(o=>'<div class="memrow"><div class="mh"><span class="badge kind">'+o.name+'</span><span class="muted" style="font-size:11px">'+(o.event||"&mdash;")+'</span><span style="flex:1"></span><span class="muted">'+rel(o.ts)+'</span></div></div>').join("");
 const sv=await (await fetch("/api/services")).json();const svc=sv.services||{};
 const dot=ok=>'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+(ok?"var(--ok)":"var(--danger)")+';margin-right:6px"></span>';
 let h='<div style="margin-bottom:8px">'+dot(sv.supervisor)+'Supervisor '+dot(svc.cockpit!==false)+'Cockpit '+dot(svc.bot)+'Bot '+dot(svc.runner)+'Runner '+dot(sv.ollama)+'Ollama</div>';
 h+='<div class="muted" style="font-size:11px;letter-spacing:1px;margin:8px 0 4px">MCP-SERVER</div>';
 const mk=Object.keys(d.mcp||{});
 h+=mk.length?mk.map(n=>{const st=d.mcp[n];return '<div class="memrow"><div class="mh">'+dot(st.running)+'<b>'+n+'</b><span style="flex:1"></span><span class="muted">'+(st.enabled?"aktiv":"aus")+' &middot; '+(st.tools||0)+' Tools</span></div></div>';}).join(""):'<span class="muted">(keine konfiguriert)</span>';
 try{const ov=await (await fetch("/api/overview")).json();
  h+='<div class="muted" style="font-size:11px;letter-spacing:1px;margin:10px 0 4px">WERKZEUGKASTEN ('+((ov.tools||[]).length||d.tools_total)+')</div>';
  h+='<div>'+toolGroups(ov.tools)+'</div>';
 }catch(e){h+='<div class="muted" style="margin-top:8px;font-size:12px">'+d.tools_total+' Werkzeuge</div>';}
 h+='<div class="muted" style="margin-top:6px;font-size:12px">'+d.skills_total+' Skills gelernt</div>';
 if(d.doctor){const dr=d.doctor;const okd=dr.ok;
  h+='<div class="muted" style="font-size:11px;letter-spacing:1px;margin:10px 0 4px">SELBST-CHECK</div>';
  h+='<div>'+dot(okd)+(okd?'alles gesund':((dr.problems||[]).length+' Problem(e)'))+'</div>';
  if(!okd)h+='<ul style="margin:4px 0;padding-left:16px;font-size:12px;color:var(--warn)">'+(dr.problems||[]).map(p=>'<li>'+(""+p).replace(/</g,"&lt;")+'</li>').join("")+'</ul>';}
 $("#ag-infra").innerHTML=h;}catch(e){}}

/* ---- Projekte (S5.3b): Projekt-Karten + Drilldown ---- */
async function loadVentures(){const el=$("#vent-list");if(!el)return;try{
 const d=await (await fetch("/api/ventures")).json();const vs=d.ventures||[];
 const vc=$("#vent-sum");if(vc)vc.textContent=vs.length?(vs.length+" Projekte"):"";
 el.innerHTML=vs.length?vs.map(v=>{
  const ms=(v.milestone_progress!=null)?('<div style="height:4px;background:var(--line);border-radius:2px;margin-top:5px"><div style="height:4px;border-radius:2px;background:var(--hud);width:'+v.milestone_progress+'%"></div></div>'):'';
  return '<div class="memrow" data-vent="'+v.id+'" style="cursor:pointer"><div class="mh"><span class="badge kind">'+v.status+'</span><b>'+(v.name||"").replace(/</g,"&lt;")+'</b><span style="flex:1"></span><span class="muted">+'+v.income_eur.toFixed(2)+' / -'+v.expenses_eur.toFixed(2)+' = <b>'+v.balance_eur.toFixed(2)+' &euro;</b></span></div>'+ms+'</div>';}).join("")
  :'<div class="emptybox">Noch keine Projekte<br>Kira, leg ein Projekt an: &hellip;</div>';
 $$('#vent-list [data-vent]').forEach(r=>r.onclick=()=>{const id=r.dataset.vent;
  /* nochmal auf dasselbe offene Projekt -> wieder zuklappen (zurueck zu Ziele/Backlog/Radar) */
  if(_openVent===id&&$("#v-projekte").classList.contains("drill"))closeVent();
  else loadVentureTrace(id);});
}catch(e){}}
/* S8.2: Projekt-AKTE — Unterreiter Uebersicht/Ziele/Aktivitaet/Finanzen je Projekt */
async function loadVentureTrace(id){const el=$("#vent-detail");try{
 const d=await (await fetch("/api/venture/trace?id="+encodeURIComponent(id))).json();
 if(d.error){el.style.display="none";return;}
 const v=d.venture;
 let goals='',act='';
 if(!(d.objectives||[]).length)goals='<div class="muted">Noch keine Ziele an diesem Projekt.</div>';
 (d.objectives||[]).forEach(o=>{
  goals+='<div style="margin-top:8px"><span class="badge kind">'+(KIND_LABEL[o.kind]||o.kind)+'</span> <b>'+esc(o.title||"")+'</b> <span class="muted">'+o.progress+'%</span></div>';
  (o.tasks||[]).slice(0,6).forEach(t=>{goals+='<div class="muted" style="font-size:12px;margin-left:12px">'+(t.status==="done"?"&#10003;":"&middot;")+' '+esc((t.description||"").slice(0,110))+(t.score!=null?(' <span style="color:var(--hud)">['+t.score+']</span>'):'')+'</div>';});
  if(o.workingset)act+='<div style="margin-top:6px"><b style="font-size:12px">'+esc(o.title||"")+'</b><div class="muted" style="font-size:11px;white-space:pre-wrap;border-left:2px solid var(--line);padding-left:8px;margin-top:3px">'+esc(o.workingset.slice(-700))+'</div></div>';});
 if(!act)act='<div class="muted">Noch kein Arbeitsstand aufgezeichnet.</div>';
 const files=(d.files||[]).map(f=>'<div class="muted" style="font-size:12px">📎 '+esc(f.name)+' <span style="opacity:.6">('+Math.round(f.bytes/1024)+' KB)</span></div>').join("")||'<div class="muted" style="font-size:12px">(keine Dateien)</div>';
 /* Auf-einen-Blick: was fuer dieses Projekt schon getan wurde */
 const allTasks=(d.objectives||[]).reduce((a,o)=>a.concat(o.tasks||[]),[]);
 const doneTasks=allTasks.filter(t=>t.status==="done");
 const gstat=(lbl,val)=>'<div class="pg-cell"><div class="muted" style="font-size:10px;letter-spacing:.5px">'+lbl+'</div><b>'+val+'</b></div>';
 const glance='<div class="proj-glance">'
   +gstat("Ziele",(d.objectives||[]).length)
   +gstat("Aufgaben",doneTasks.length+'/'+allTasks.length+' erledigt')
   +gstat("Kosten",(d.costs||0).toFixed(2)+' €')
   +gstat("Kasse",(d.balance||0).toFixed(2)+' €')
   +'</div>';
 const lastDone=doneTasks.slice(-6).reverse().map(t=>'<div class="muted" style="font-size:12px">&#10003; '+esc((t.description||"").slice(0,120))+(t.score!=null?(' <span style="color:var(--hud)">['+t.score+']</span>'):'')+'</div>').join("");
 const doneBlock=lastDone?('<div class="muted" style="font-size:11px;letter-spacing:1px;margin:10px 0 4px">ZULETZT ERLEDIGT</div>'+lastDone):'';
 const ueb='<div class="muted" style="margin-bottom:6px">'+esc(v.hypothesis||"(keine Hypothese)")+' · Status: <b>'+esc(v.status||"?")+'</b></div>'
  +glance+doneBlock
  +'<div class="muted" style="font-size:11px;letter-spacing:1px;margin:8px 0 4px">ANWEISUNGEN AN KIRA (fliessen in jeden Projekt-Task)</div>'
  +'<textarea id="ak-brief" class="k" style="min-height:90px"></textarea>'
  +'<div class="row" style="margin-top:6px"><button class="ghost" id="ak-brief-save">Briefing speichern</button>'
  +'<input id="ak-note" placeholder="Neue Daueranweisung (eine Zeile)…" style="flex:1;min-width:200px"/><button id="ak-note-add">+ Notiz</button></div>'
  +'<div class="muted" style="font-size:11px;letter-spacing:1px;margin:12px 0 4px">DATEIEN</div>'+files
  +'<div class="row" style="margin-top:6px"><label class="ghost" style="display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border:1px solid var(--line);border-radius:8px;cursor:pointer">📎 Datei hochladen<input id="ak-file" type="file" style="display:none"/></label><span class="muted" id="ak-hint" style="align-self:center;font-size:12px"></span></div>';
 const fin='<div style="font-size:13px"><b>Kosten bislang:</b> '+(d.costs||0).toFixed(2)+' € <span class="muted">(LLM-Arbeit an diesem Projekt)</span></div>'
  +'<div class="muted" style="font-size:12px;margin-top:4px">Einnahmen/Ausgaben: Kasse '+d.balance.toFixed(2)+' €</div>'
  +((d.ledger||[]).slice(0,8).map(l=>'<div class="muted" style="font-size:12px">'+(l.direction==="in"?"+":"−")+(l.amount_eur||0).toFixed(2)+' € · '+esc((l.note||l.category||"").slice(0,60))+'</div>').join("")||'');
 /* S8.4: Projekt-Routinen (Crons mit scope projekt:<id>) */
 let rout='<div class="muted">Keine Projekt-Routinen. Sag mir z.B. per Telegram: "richte fuer '+esc(v.name||"")+' woechentlich einen Status-Check ein".</div>';
 try{const cj=await (await fetch("/api/cron")).json();
  const mine=(cj.jobs||[]).filter(j=>(j.scope||"")==="projekt:"+v.id);
  if(mine.length)rout=mine.map(j=>'<div class="memrow"><div class="mh"><span class="badge kind">'+(j.enabled?"AN":"aus")+'</span><b>'+esc(j.label||"")+'</b><span class="muted" style="font-size:11px">'+esc(j.schedule_text||"")+'</span></div></div>').join("");
 }catch(e2){}
 el.innerHTML='<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><b>'+esc(v.name||"")+'</b>'
  +'<span class="seg" id="akte-tabs"><a data-at="ueb" class="on">Uebersicht</a><a data-at="ziele">Ziele &amp; Tasks</a><a data-at="akt">Aktivitaet</a><a data-at="fin">Finanzen</a><a data-at="rout">Routinen</a></span>'
  +'<span style="flex:1"></span><a id="vent-close" style="cursor:pointer;color:var(--muted)">&#10005;</a></div>'
  +'<div class="at" id="at-ueb">'+ueb+'</div><div class="at" id="at-ziele" style="display:none">'+goals+'</div>'
  +'<div class="at" id="at-akt" style="display:none">'+act+'</div><div class="at" id="at-fin" style="display:none">'+fin+'</div>'
  +'<div class="at" id="at-rout" style="display:none">'+rout+'</div>';
 el.style.display="block";
 const pv=$("#v-projekte");if(pv)pv.classList.add("drill");   /* Akte in den Vordergrund, 3 Spalten weichen */
 _openVent=id;
 $("#ak-brief").value=d.briefing||"";
 $$("#akte-tabs a").forEach(a=>a.onclick=()=>{$$("#akte-tabs a").forEach(x=>x.classList.toggle("on",x===a));
  el.querySelectorAll(".at").forEach(x=>x.style.display="none");$("#at-"+a.dataset.at).style.display="block";});
 $("#ak-brief-save").onclick=async()=>{await fetch("/api/ventures/briefing",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:v.id,text:$("#ak-brief").value})});toast("Briefing gespeichert","ok");};
 $("#ak-note-add").onclick=async()=>{const n=$("#ak-note").value.trim();if(!n)return;
  await fetch("/api/ventures/briefing",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:v.id,note:n})});
  toast("Notiert — gilt ab jetzt fuer jeden Projekt-Task","ok");loadVentureTrace(v.id);};
 $("#ak-file").onchange=async e2=>{const f=e2.target.files[0];if(!f)return;
  $("#ak-hint").textContent="… lade "+f.name;
  const fd=new FormData();fd.append("id",v.id);fd.append("file",f);
  const r=await (await fetch("/api/ventures/upload",{method:"POST",body:fd})).json();
  $("#ak-hint").textContent=r.ok?"✓ "+f.name:"Fehler: "+(r.error||"?");if(r.ok)loadVentureTrace(v.id);};
 const cl=$("#vent-close");if(cl)cl.onclick=()=>closeVent();
}catch(e){}}

/* ---- To-Do (S6.6a): Zugangs-Anfragen — was Kira an Keys/Zugaengen braucht ---- */
async function loadTodoSecrets(){const el=$("#todo-secrets");if(!el)return;try{
 const k=await (await fetch("/api/secrets")).json();
 el.innerHTML=(k.pending||[]).length?k.pending.map(p=>
  '<div class="memrow"><div class="mh"><span class="badge kind">&#128273;</span><b>'+esc(p.name||"")+'</b></div>'
  +'<div class="muted" style="font-size:12px;margin-top:3px">'+esc((p.reason||"").slice(0,300))+'</div></div>').join("")
  :'<div class="emptybox">Keine offenen Zugangs-Anfragen.</div>';
}catch(e){}}

/* ---- Wissen (S5.4): fuettern, suchen, verwalten ---- */
async function loadWissen(){try{const d=await (await fetch("/api/knowledge")).json();const docs=d.docs||[];
 const kc=$("#kn-count");if(kc)kc.textContent=docs.length?(docs.length+" Dokumente, "+docs.reduce((a,x)=>a+(x.chunks||0),0)+" Abschnitte"):"";
 $("#kn-docs").innerHTML=docs.length?docs.map(x=>'<div class="memrow"><div class="mh"><span class="badge kind">'+x.source+'</span><b>'+(x.title||"").replace(/</g,"&lt;").slice(0,80)+'</b><span style="flex:1"></span><span class="muted">'+Math.round((x.bytes||0)/1024)+' KB &middot; '+x.chunks+' Abschnitte</span> <a data-kdel="'+x.id+'" style="cursor:pointer;color:var(--muted)" title="loeschen">&#10005;</a></div></div>').join("")
  :'<div class="emptybox">Archiv ist leer<br>Fuettere mich: Datei, Notiz oder Telegram-Anhang.</div>';
 $$('#kn-docs [data-kdel]').forEach(a=>a.onclick=async()=>{await fetch("/api/knowledge/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.kdel})});loadWissen();});
}catch(e){}}
$("#kn-add")&&($("#kn-add").onclick=async()=>{const txt=$("#kn-text").value.trim();if(!txt)return;
 $("#kn-hint").textContent="…";
 const r=await (await fetch("/api/knowledge/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:$("#kn-title").value.trim()||"Notiz",text:txt})})).json();
 $("#kn-hint").textContent=r.ok?(r.duplicate?"kenne ich schon (Duplikat)":"&#10003; abgelegt ("+r.chunks+" Abschnitte)"):("Fehler: "+(r.error||"?"));
 if(r.ok&&!r.duplicate){$("#kn-text").value="";$("#kn-title").value="";}loadWissen();});
$("#kn-file")&&($("#kn-file").onchange=async()=>{const f=$("#kn-file").files[0];if(!f)return;
 $("#kn-file-hint").textContent="… lade "+f.name+" …";
 const fd=new FormData();fd.append("file",f);
 const r=await (await fetch("/api/knowledge/upload",{method:"POST",body:fd})).json();
 $("#kn-file-hint").textContent=r.ok?(r.duplicate?"kenne ich schon (Duplikat)":"&#10003; "+f.name+" ("+r.chunks+" Abschnitte)"):("Fehler: "+(r.error||"?"));
 $("#kn-file").value="";loadWissen();});
let knTimer=null;
$("#kn-q")&&($("#kn-q").oninput=()=>{clearTimeout(knTimer);knTimer=setTimeout(async()=>{
 const q=$("#kn-q").value.trim();const el=$("#kn-results");
 if(q.length<3){el.innerHTML='<span class="muted">&hellip;</span>';return;}
 const d=await (await fetch("/api/knowledge/search?q="+encodeURIComponent(q))).json();
 el.innerHTML=(d.hits||[]).length?d.hits.map(h=>'<div class="memrow"><div class="mh"><b>'+(h.title||"").replace(/</g,"&lt;").slice(0,60)+'</b><span class="muted"> &middot; Abschnitt '+(h.chunk_no+1)+(h.score!=null?(' &middot; '+h.score):'')+'</span></div><div class="muted" style="font-size:12px;margin-top:3px">'+(h.text||"").replace(/</g,"&lt;").slice(0,260)+'&hellip;</div></div>').join("")
  :'<span class="muted">nichts gefunden</span>';},350);});

/* ---- Radar (S5.5): Chancen-Pipeline ---- */
const OPP_BADGE={new:"var(--hud)",shortlist:"var(--ok)",converted:"var(--accent)",rejected:"var(--muted)"};
async function loadRadar(){try{const d=await (await fetch("/api/opportunities")).json();const os=d.opportunities||[];
 $("#rd-list").innerHTML=os.length?os.map(o=>{
  let act="";
  if(o.status==="new"||o.status==="shortlist")act=' <a data-oconv="'+o.id+'" style="cursor:pointer;color:var(--ok)" title="als Projekt uebernehmen">&rarr; Projekt</a>'
   +(o.status==="new"?' <a data-oshort="'+o.id+'" style="cursor:pointer;color:var(--hud)" title="merken">&#9733;</a>':'')
   +' <a data-orej="'+o.id+'" style="cursor:pointer;color:var(--muted)" title="verwerfen">&#10005;</a>';
  return '<div class="memrow"><div class="mh"><span class="badge kind" style="color:'+(OPP_BADGE[o.status]||"var(--muted)")+'">'+o.status+'</span><b>['+o.score+']</b> <b>'+(o.title||"").replace(/</g,"&lt;").slice(0,90)+'</b><span style="flex:1"></span>'+act+'</div>'
   +(o.hypothesis?('<div class="muted" style="font-size:12px;margin-top:3px">'+(o.hypothesis||"").replace(/</g,"&lt;").slice(0,200)+'</div>'):'')+'</div>';}).join("")
  :'<div class="emptybox">Pipeline leer<br>&bdquo;jetzt scannen&ldquo; klicken oder auf den Wochen-Scan warten.</div>';
 const wire=(sel,fn)=>$$(sel).forEach(a=>a.onclick=fn(a));
 wire('#rd-list [data-oconv]',a=>async()=>{await fetch("/api/opportunities/convert",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.oconv})});loadRadar();});
 wire('#rd-list [data-oshort]',a=>async()=>{await fetch("/api/opportunities/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.oshort,status:"shortlist"})});loadRadar();});
 wire('#rd-list [data-orej]',a=>async()=>{await fetch("/api/opportunities/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.dataset.orej,status:"rejected"})});loadRadar();});
}catch(e){}}
$("#rd-scan")&&($("#rd-scan").onclick=async()=>{$("#rd-hint").textContent="… scanne (kann ~1 min dauern) …";
 const r=await (await fetch("/api/radar/scan",{method:"POST"})).json();
 $("#rd-hint").textContent=r.error?("Fehler: "+r.error):("Scan fertig — "+(r.found||0)+" neue Chance(n).");loadRadar();});
/* Radar-Fokus: Sergen sagt, wonach gesucht wird (persistent, deckt sich mit Kiras radar_fokus). */
$("#rd-focus-edit")&&($("#rd-focus-edit").onclick=async()=>{
 const box=$("#rd-focus-box");if(!box)return;
 const show=box.style.display==="none";box.style.display=show?"block":"none";
 if(show){try{const d=await (await fetch("/api/radar/focus")).json();
  $("#rd-focus").value=(d.themes||[]).join(";\n");
  $("#rd-focus-hint").textContent=d.default?"(noch kein eigener Fokus — Standardthemen)":"";}catch(e){}}});
$("#rd-focus-save")&&($("#rd-focus-save").onclick=async()=>{
 const r=await (await fetch("/api/radar/focus",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({themes:$("#rd-focus").value})})).json();
 const n=(r.themes||[]).length;
 $("#rd-focus-hint").textContent=r.ok?("✓ gespeichert — "+n+" Thema/Themen"):"Fehler";});

/* ---- S6.6a: neue Quer-Verdrahtungen ---- */
$("#m-or-add")&&($("#m-or-add").onclick=async()=>{const id=$("#m-or").value.trim();if(!id)return;
 $("#m-or-hint").textContent="…";
 try{const r=await J("/api/model/openrouter",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model:id})});
  $("#m-or-hint").textContent="✓ aktiv: "+(r.active||id);refreshStatus();loadModels();
 }catch(e){$("#m-or-hint").textContent="Fehler — Modell-ID pruefen";}});
$("#go-todo")&&($("#go-todo").onclick=()=>nav("me"));
/* Theme-Popover (S7a): dezentes ◐-Icon in der Topbar statt praesenter Leiste in der Nav */
$("#theme-btn")&&($("#theme-btn").onclick=e=>{e.stopPropagation();const p=$("#theme-pop");p.classList.toggle("open");});
document.addEventListener("click",e=>{const p=$("#theme-pop");
 if(p&&p.classList.contains("open")&&!e.target.closest("#theme-wrap"))p.classList.remove("open");});
/* Tab-Icons anpassen (Config -> Cockpit) */
$("#icons-save")&&($("#icons-save").onclick=()=>{const ic={};
 $$('#icon-row input[data-ic]').forEach(i=>{const v=i.value.trim();if(v)ic[i.dataset.ic]=v.slice(0,3);});
 localStorage.setItem("kira_icons",JSON.stringify(ic));applyIcons();toast("Icons gespeichert","ok");});
$("#icons-reset")&&($("#icons-reset").onclick=()=>{localStorage.removeItem("kira_icons");location.reload();});
$("#go-keys")&&($("#go-keys").onclick=()=>{nav("kira");subnav("kira","keys");});  /* S8.4: Zugaenge leben bei Kira */
$("#set-restart")&&($("#set-restart").onclick=async()=>{if(!confirm("Kira neu starten? Dienste bouncen in ~20s."))return;
 await fetch("/api/restart",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
 $("#set-restart-hint").textContent="↻ Neustart angefordert …";});
$("#set-bg-clear")&&($("#set-bg-clear").onclick=async()=>{await fetch("/api/bg/clear",{method:"POST"});
 $("#set-optik-hint").textContent="✓ Hintergrund entfernt";document.body.style.backgroundImage="";});
$("#set-avatar")&&($("#set-avatar").onchange=e=>{const f=e.target.files[0];if(!f)return;
 const rd=new FileReader();rd.onload=async()=>{
  const r=await (await fetch("/api/avatar/upload",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dataurl:rd.result})})).json();
  $("#set-avatar-hint").textContent=r.ok?"✓ Avatar gesetzt":("Fehler: "+(r.error||"?"));
  if(r.ok){hasAvatar=true;avatarV=Date.now();const hv=$("#hero-av");if(hv){hv.style.display="";hv.src="/api/avatar?t="+avatarV;}}};
 rd.readAsDataURL(f);e.target.value="";});
$("#set-avatar-clear")&&($("#set-avatar-clear").onclick=async()=>{await fetch("/api/avatar/clear",{method:"POST"});
 hasAvatar=false;const hv=$("#hero-av");if(hv)hv.style.display="none";$("#set-avatar-hint").textContent="✓ entfernt";});
/* App-Logo (Cockpit-Kopf + /wall-Favicon + Desktop-Tray) direkt hier hochladen — kein Datei-Geschiebe */
/* Logo = NUR Fenster-/Taskleisten-/Desktop-Symbol + /wall-Favicon (nicht mehr der Cockpit-Kopf,
   der bleibt der Neon-„KIRA"-Schriftzug). Hier nur die Vorschau + das Browser-Tab-Favicon frischen. */
function refreshLogo(){const t=Date.now();
 const p=$("#logo-prev");if(p){p.style.visibility="";p.src="/api/icon?t="+t;}
 const fav=document.querySelector('link[rel="icon"]');if(fav)fav.href="/api/icon?t="+t;}
$("#set-logo")&&($("#set-logo").onchange=e=>{const f=e.target.files[0];if(!f)return;
 const rd=new FileReader();rd.onload=async()=>{
  const r=await (await fetch("/api/icon/upload",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dataurl:rd.result})})).json();
  $("#set-logo-hint").textContent=r.ok?(r.ico?"✓ Logo gesetzt — Desktop-App einmal neu starten (Tray-Menue), dann sitzt es auch im Fenster + in der Taskleiste":"✓ Logo gesetzt — fuer Fenster-/Taskleisten-Symbol einmal kira-einrichten.bat"):("Fehler: "+(r.error||"?"));
  if(r.ok)refreshLogo();};
 rd.readAsDataURL(f);e.target.value="";});
$("#set-logo-clear")&&($("#set-logo-clear").onclick=async()=>{await fetch("/api/icon/clear",{method:"POST"});
 $("#set-logo-hint").textContent="✓ entfernt";const p=$("#logo-prev");if(p)p.style.visibility="hidden";});
/* Ein-Klick: Desktop-Verknuepfung 'Kira' + Autostart anlegen (nur Windows; ruft desktop-setup.ps1) */
$("#make-shortcut")&&($("#make-shortcut").onclick=async()=>{
 $("#make-shortcut-hint").textContent="… lege an";
 try{const r=await (await fetch("/api/desktop/shortcut",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})).json();
  $("#make-shortcut-hint").textContent=r.ok?"✓ Desktop-Icon angelegt — jetzt das Fenster per Rechtsklick an die Taskleiste anheften":("Fehler: "+(r.error||r.output||"?"));}
 catch(e){$("#make-shortcut-hint").textContent="Fehler beim Anlegen";}});

/* Sauberer Neustart: gesamten Chat-Verlauf (episodisch) auf null — Fakten/Skills bleiben, Backup vorher */
$("#reset-episodic")&&($("#reset-episodic").onclick=async()=>{
 if(!confirm("Gesamten Chat-Verlauf auf null setzen?\n\nAlle Unterhaltungen (alle Sessions) werden geloescht — fuer einen frischen Start. Deine FAKTEN und SKILLS bleiben. Alles Geloeschte wird vorher in data/backups gesichert."))return;
 $("#reset-episodic-hint").textContent="… setze zurueck";
 try{const r=await (await fetch("/api/memory/reset-episodic",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirm:true})})).json();
  $("#reset-episodic-hint").textContent=r.ok?("✓ "+r.deleted+" Nachrichten geloescht ("+r.kept+" Fakten/Skills behalten) — Backup gesichert"):("Fehler: "+(r.error||"?"));}
 catch(e){$("#reset-episodic-hint").textContent="Fehler beim Zuruecksetzen";}});

/* ---- Charakter-Editor: charakter-praegende Prompts als Text (Erklaerung + Feld + Speichern) ---- */
const CHARAKTER=[
 {name:"SOUL.md",t:"Seele — wer sie ist",h:"Kiras Identität, Haltung, Rolle als Counterweight."},
 {name:"GOAL.md",t:"Ziel — wofür sie da ist",h:"Zweck, Nordstern, Antriebe. Die Meilensteine (§6) gehören Dir."},
 {name:"USER.md",t:"Über Dich (Sergen)",h:"Wer Du bist — Kira baut ihr Bild von Dir daraus."},
 {name:"PERSONA.md",t:"Verhalten & Ton",h:"Wie sie spricht, mitdenkt, nachschaut — der Verhaltens-Kern (schlank halten, ~4200 Zeichen)."}];
async function loadCharakter(){const w=$("#charakter-list");if(!w)return;w.innerHTML='<div class="muted" style="padding:10px">lädt …</div>';
 let html="";
 for(const it of CHARAKTER){let c="";try{const r=await (await fetch("/api/file?name="+encodeURIComponent(it.name))).json();c=r.content||"";}catch(e){}
  html+='<div class="card"><h3>'+esc(it.t)+' <span class="muted" style="font-size:11px;font-weight:400">('+esc(it.name)+')</span></h3>'
   +'<div class="muted" style="margin-bottom:6px">'+esc(it.h)+'</div>'
   +'<textarea class="char-ta" data-name="'+esc(it.name)+'" spellcheck="false" style="width:100%;min-height:160px;font-family:monospace;font-size:12px;line-height:1.45">'+esc(c)+'</textarea>'
   +'<div class="row" style="margin-top:6px;align-items:center;gap:10px"><button class="char-save" data-name="'+esc(it.name)+'">Speichern</button><span class="muted char-hint" data-h="'+esc(it.name)+'" style="font-size:12px"></span></div></div>';}
 w.innerHTML=html;
 $$(".char-save").forEach(b=>b.onclick=async()=>{const n=b.dataset.name;const ta=w.querySelector('.char-ta[data-name="'+n+'"]');const hint=w.querySelector('.char-hint[data-h="'+n+'"]');hint.textContent="… speichere";
  try{const r=await (await fetch("/api/file",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:n,content:ta.value})})).json();hint.textContent=r.ok?"✓ gespeichert — Backup angelegt, wirkt sofort":("Fehler: "+(r.error||"?"));}
  catch(e){hint.textContent="Fehler beim Speichern";}});}

/* ---- Coding-Benchmark: Live-Lauf ueber /ws/bench (isolierter Worktree, Live-Gedankenstrom) ---- */
let benchWs=null,benchPassed=0,benchTotal=0;
function benchLog(html){const l=$("#bench-log");if(!l)return;const d=document.createElement("div");d.style.padding="3px 0";d.innerHTML=html;l.appendChild(d);l.scrollTop=l.scrollHeight;}
function updateBenchScore(){const s=$("#bench-score");if(!s)return;const pct=benchTotal?Math.round(100*benchPassed/benchTotal):0;const col=pct>=70?"ok":pct>=40?"warn":"danger";s.innerHTML='Score: <span style="color:var(--'+col+')">'+benchPassed+'/'+benchTotal+'</span> ('+pct+'%)';}
let _benchRows=[];
async function loadBenchResults(){const w=$("#bench-results");if(!w)return;
 try{const d=await (await fetch("/api/bench/results")).json();const rs=d.results||[];
  _benchRows=[...rs].sort((a,b)=>((b.pass_at_1==null?-1:b.pass_at_1)-(a.pass_at_1==null?-1:a.pass_at_1)));
  if(!rs.length){w.innerHTML='<span class="muted">Noch keine Läufe — der Endstand jedes Laufs landet automatisch hier.</span>';return;}
  const dt=t=>{const d2=new Date(t*1000);return d2.toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit"})+" "+d2.toLocaleTimeString("de-DE",{hour:"2-digit",minute:"2-digit"});};
  const cell=(c,w2)=>'<span style="'+(w2?('min-width:'+w2+'px;'):'flex:1;')+'padding:0 6px;white-space:nowrap">'+c+'</span>';
  const line=(cs,head)=>'<div style="display:flex;padding:5px 0;border-bottom:1px solid var(--line);font-size:12.5px'+(head?';color:var(--muted)':'')+'">'+cs+'</div>';
  w.innerHTML=line(cell("Modell")+cell("Test",84)+cell("Rolle",70)+cell("Aufgaben",64)+cell("Score",64)+cell("Datum",92),true)
   +_benchRows.map(r=>line(cell(esc((r.model||"?").replace("openrouter/","")))
    +cell(r.suite==="humaneval"?"HumanEval":"Smoke",84)+cell(esc(r.role||"—"),70)
    +cell((r.passed!=null?r.passed:"?")+"/"+(r.total!=null?r.total:"?"),64)
    +cell(r.pass_at_1!=null?("<b>"+r.pass_at_1+"%</b>"):"—",64)+cell(dt(r.ts),92))).join("");
 }catch(e){w.innerHTML='<span class="muted">Leaderboard nicht ladbar.</span>';}}
function copyBenchResults(){const rows=_benchRows;if(!rows.length){$("#bench-copy-hint").textContent="nichts zu kopieren";return;}
 const md="| Modell | Test | Rolle | Aufgaben | pass@1 | Datum |\n|---|---|---|---|---|---|\n"
  +rows.map(r=>"| "+(r.model||"?")+" | "+(r.suite==="humaneval"?"HumanEval":"Smoke")+" | "+(r.role||"—")+" | "
   +(r.passed!=null?r.passed:"?")+"/"+(r.total!=null?r.total:"?")+" | "+(r.pass_at_1!=null?(r.pass_at_1+"%"):"—")+" | "
   +new Date(r.ts*1000).toLocaleString("de-DE")+" |").join("\n");
 const done=()=>{$("#bench-copy-hint").textContent="✓ kopiert (Markdown-Tabelle)";};
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(md).then(done).catch(()=>fallbackCopy(md,done));}
 else fallbackCopy(md,done);}
function fallbackCopy(text,done){const ta=document.createElement("textarea");ta.value=text;document.body.appendChild(ta);ta.select();
 try{document.execCommand("copy");done();}catch(e){$("#bench-copy-hint").textContent="Kopieren fehlgeschlagen";}ta.remove();}
function loadBench(){const b=$("#bench-start");if(!b)return;
 fetch("/api/status").then(r=>r.json()).then(s=>{const m=$("#bench-model");if(m&&s&&s.model)m.textContent="Aktuelles Modell: "+s.model;}).catch(()=>{});
 loadBenchResults();
 const cp=$("#bench-copy");if(cp)cp.onclick=()=>copyBenchResults();
 b.onclick=()=>startBench();const st=$("#bench-stop");if(st)st.onclick=()=>stopBench();}
function startBench(){if(benchWs){try{benchWs.close();}catch(e){}}
 $("#bench-log").innerHTML="";$("#bench-score").textContent="";benchPassed=0;benchTotal=0;
 $("#bench-start").style.display="none";$("#bench-stop").style.display="";
 const allow=$("#bench-allow-llm")?$("#bench-allow-llm").checked:true;
 const suite=$("#bench-suite")?$("#bench-suite").value:"harness";
 const role=$("#bench-role")?$("#bench-role").value:"reason";
 const limit=$("#bench-limit")?parseInt($("#bench-limit").value||"20",10):20;
 const proto=location.protocol==="https:"?"wss":"ws";
 benchWs=new WebSocket(proto+"://"+location.host+"/ws/bench");
 benchWs.onopen=()=>{benchWs.send(JSON.stringify({allow_llm:!!allow,suite:suite,role:role,limit:limit}));
  benchLog('<span class="muted">'+(suite==="humaneval"?("HumanEval startet — "+limit+" Aufgaben auf Rolle '"+role+"' (Datensatz laedt beim ersten Mal kurz) …"):"Sandbox wird vorbereitet … (jeder Lauf ist isoliert)")+'</span>');};
 benchWs.onmessage=e=>{let ev;try{ev=JSON.parse(e.data);}catch(x){return;}renderBenchEvent(ev);};
 benchWs.onclose=()=>{$("#bench-start").style.display="";$("#bench-stop").style.display="none";benchWs=null;};
 benchWs.onerror=()=>{benchLog('<span style="color:var(--danger)">Verbindungsfehler</span>');};}
function stopBench(){if(benchWs){try{benchWs.close();}catch(e){}}benchWs=null;$("#bench-start").style.display="";$("#bench-stop").style.display="none";benchLog('<span class="muted">Abgebrochen.</span>');}
function renderBenchEvent(ev){const k=ev.kind,a=ev.ev||{};
 if(k==="suite_start"){benchTotal=ev.total;benchPassed=0;updateBenchScore();benchLog('<b>Benchmark: '+ev.total+' Aufgabe(n)</b>');}
 else if(k==="task_start")benchLog('<div style="margin-top:8px;border-top:1px solid var(--line);padding-top:6px"><b>▶ '+esc(ev.id)+'</b> <span class="muted">'+esc(ev.prompt||"")+'</span></div>');
 else if(k==="act"){let s="";if(a.kind==="think")s='<span class="muted">💭 '+esc((a.text||"").slice(0,300))+'</span>';else if(a.kind==="tool")s='🔧 '+esc(a.name||"")+' <span class="muted">'+esc(JSON.stringify(a.args||{}).slice(0,120))+'</span>';else if(a.kind==="obs")s='<span class="muted">↳ '+esc(((a.name||"")+" "+(a.text||"")).slice(0,300))+'</span>';else if(a.kind==="final")s='<span class="muted">'+esc((a.text||"").slice(0,200))+'</span>';if(s)benchLog(s);}
 else if(k==="task_done"){if(ev.passed)benchPassed++;updateBenchScore();benchLog((ev.passed?'<span style="color:var(--ok)">✓ bestanden</span>':'<span style="color:var(--danger)">✗ nicht bestanden (rc='+ev.rc+')</span>')+' — '+esc(ev.id));}
 else if(k==="summary"){benchPassed=ev.passed;benchTotal=ev.total;updateBenchScore();
  benchLog('<div style="margin-top:8px"><b>Fertig: '+ev.passed+'/'+ev.total+' bestanden</b>'
   +(ev.pass_at_1!=null?(' — <b>pass@1 = '+ev.pass_at_1+'%</b> <span class="muted">(Referenz: Frontier ~90%+, starke offene Modelle ~70–90%)</span>'):'')+'</div>');
  loadBenchResults();}
 else if(k==="error")benchLog('<span style="color:var(--danger)">Fehler: '+esc(ev.text||"")+'</span>');}

refreshStatus();loadCommand();
/* ---- S6.4: EIN Poll-Scheduler statt zweier nackter setInterval ----
   - pausiert bei document.hidden (kein Polling im Hintergrund-Tab)
   - Backoff x2 bis 60s bei Fehler-Serien (pollFails), sofort zurueck auf 5s bei Erfolg
   - sofortiger Refresh, wenn der Tab wieder sichtbar wird */
let _pollN=0,_pollTimer=null;
function pollTick(){
 if(_pollTimer){clearTimeout(_pollTimer);_pollTimer=null;}  // nie zwei Schleifen parallel
 if(!document.hidden){
   updatePulse();
   refreshStatus();
   if(cur==="kira"&&SUBTABS.kira.cur==="log"&&logRaw.length<=100)loadEvents();
   if(cur==="kira"&&SUBTABS.kira.cur==="gov")loadGov();
   if(cur==="home"){loadHud();loadOps();}   /* 'Von Kira'-Panel lebt im Me-Tab (loadInbox); loadNeeds war toter Code -> ReferenceError */
   if(cur==="home"&&(_pollN%6===0))loadNews();  // News seltener (~alle 30s)
   _pollN++;
 }
 const base=document.hidden?15000:5000;
 const delay=Math.min(base*Math.pow(2,Math.min(pollFails,4)),60000);  // Backoff bei Fehler-Serien
 _pollTimer=setTimeout(pollTick,delay);
}
_pollTimer=setTimeout(pollTick,5000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden){pollFails=0;pollTick();}});
/* ===== Inline-Rename (Sergen): Beschriftungen per Doppelklick aendern, im Browser gespeichert ===== */
(function(){
 var K="kiraLabels",m={};try{m=JSON.parse(localStorage.getItem(K)||"{}")}catch(e){}
 function save(){try{localStorage.setItem(K,JSON.stringify(m))}catch(e){}}
 function ftn(el){for(var i=0;i<el.childNodes.length;i++){var n=el.childNodes[i];if(n.nodeType===3&&n.textContent.trim())return n;}return null;}
 function wire(el){
  if(el.getAttribute("data-lblkey"))return;
  var card=el.tagName==="H3",node=card?el:ftn(el);
  if(!node)return;
  var orig=(node.textContent||"").trim();
  if(!orig)return;
  el.setAttribute("data-lblkey",orig);
  var set=function(v){if(card)el.textContent=v;else node.textContent=v+" ";};
  if(m[orig]!==undefined)set(m[orig]);
  el.title="Doppelklick: Beschriftung aendern";
  el.addEventListener("dblclick",function(ev){
   ev.preventDefault();ev.stopPropagation();
   var cur=m[orig]!==undefined?m[orig]:orig;
   var nv=window.prompt("Beschriftung aendern (leer = Standard):",cur);
   if(nv===null)return;nv=nv.trim();
   if(nv===""||nv===orig){delete m[orig];set(orig);}else{m[orig]=nv;set(nv);}
   save();
  });
 }
 function apply(){var els=document.querySelectorAll(".card h3, .panel-h");for(var i=0;i<els.length;i++)wire(els[i]);}
 apply();
 document.addEventListener("click",function(e){if(e.target&&e.target.closest&&e.target.closest("#side"))setTimeout(apply,60);});
})();
</script></body></html>"""
