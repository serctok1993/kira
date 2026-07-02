"""Cockpit-Logik (vanilla JS): nav, Loader, Chat-WebSocket (Vertrag: role/kind/done)."""

SCRIPT = r"""<script>
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
 if(v==="home")loadCommand(); if(v==="mission")loadMission(); if(v==="chat"){loadChatModels();loadChatSessions();} if(v==="system")syst(sysCur); if(v==="leben")loadLeben(); if(v==="agenten")loadAgenten();}

/* ---- System-Bereich: Sub-Tabs (Modelle/Gewissen/Cron/Monitor/Zugaenge/Gedaechtnis/Dateien/Protokoll) ---- */
let sysCur="models";
const SYS_LOADERS={models:()=>loadModels(),gov:()=>loadGov(),cron:()=>loadCron(),monitor:()=>loadMonitor(),keys:()=>loadKeys(),mem:()=>loadMem(),files:()=>loadFiles(),log:()=>loadEvents()};
function syst(s){sysCur=s;
 $$("#sys-tabs a").forEach(a=>a.classList.toggle("on",a.dataset.s===s));
 $$(".subview").forEach(x=>x.classList.toggle("on",x.id==="v-"+s));
 (SYS_LOADERS[s]||(()=>{}))();}
$$("#sys-tabs a").forEach(a=>a.onclick=()=>syst(a.dataset.s));

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
function loadCommand(){loadHud();loadOps();loadNews();loadHome();loadNeeds();loadZDigest();bindNewsSeed();bindOpsFilter();}

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

/* ---- Direktive (Startseite) ---- */
$("#dir-now")&&($("#dir-now").onclick=async()=>{const p=$("#dir-text").value.trim();if(!p)return;
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
 }catch(e){}
 try{const m=await (await fetch("/api/metrics")).json();const rows=[];
  for(const it of (m.latest||[]).slice(0,6)){
   const sr=await (await fetch("/api/metrics?name="+encodeURIComponent(it.name)+"&days=90")).json();
   rows.push('<div class="memrow"><div class="mh"><b>'+it.name+'</b><span style="flex:1"></span>'+spark(sr.series||[])+'<span style="min-width:110px;text-align:right"><b>'+it.value+'</b>'+(it.delta!=null?(' <span class="muted">('+(it.delta>0?"+":"")+it.delta+')</span>'):'')+'</span></div></div>');}
  $("#life-metrics").innerHTML=rows.join("")||'<div class="emptybox">Noch keine Metriken</div>';
 }catch(e){}}

/* ---- Agenten (S5.3b): Organe, Dienste, MCP ---- */
async function loadAgenten(){try{const d=await (await fetch("/api/agents")).json();
 const rel=ts=>{if(!ts)return "noch nie";const x=(Date.now()/1000-ts);return x<90?"gerade eben":x<3600?Math.round(x/60)+" min":x<86400?Math.round(x/3600)+" h":Math.round(x/86400)+" Tage";};
 $("#ag-organs").innerHTML=(d.organs||[]).map(o=>'<div class="memrow"><div class="mh"><span class="badge kind">'+o.name+'</span><span class="muted" style="font-size:11px">'+(o.event||"&mdash;")+'</span><span style="flex:1"></span><span class="muted">'+rel(o.ts)+'</span></div></div>').join("");
 const sv=await (await fetch("/api/services")).json();const svc=sv.services||{};
 const dot=ok=>'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+(ok?"var(--ok)":"var(--danger)")+';margin-right:6px"></span>';
 let h='<div style="margin-bottom:8px">'+dot(sv.supervisor)+'Supervisor '+dot(svc.cockpit!==false)+'Cockpit '+dot(svc.bot)+'Bot '+dot(svc.runner)+'Runner '+dot(sv.ollama)+'Ollama</div>';
 h+='<div class="muted" style="font-size:11px;letter-spacing:1px;margin:8px 0 4px">MCP-SERVER</div>';
 const mk=Object.keys(d.mcp||{});
 h+=mk.length?mk.map(n=>{const st=d.mcp[n];return '<div class="memrow"><div class="mh">'+dot(st.running)+'<b>'+n+'</b><span style="flex:1"></span><span class="muted">'+(st.enabled?"aktiv":"aus")+' &middot; '+(st.tools||0)+' Tools</span></div></div>';}).join(""):'<span class="muted">(keine konfiguriert)</span>';
 h+='<div class="muted" style="margin-top:8px;font-size:12px">'+d.tools_total+' Werkzeuge &middot; '+d.skills_total+' Skills</div>';
 $("#ag-infra").innerHTML=h;}catch(e){}}

/* ---- Projekte (S5.3b): Venture-Karten + Drilldown ---- */
async function loadVentures(){const el=$("#vent-list");if(!el)return;try{
 const d=await (await fetch("/api/ventures")).json();const vs=d.ventures||[];
 const vc=$("#vent-sum");if(vc)vc.textContent=vs.length?(vs.length+" Standbeine"):"";
 el.innerHTML=vs.length?vs.map(v=>{
  const ms=(v.milestone_progress!=null)?('<div style="height:4px;background:var(--line);border-radius:2px;margin-top:5px"><div style="height:4px;border-radius:2px;background:var(--hud);width:'+v.milestone_progress+'%"></div></div>'):'';
  return '<div class="memrow" data-vent="'+v.id+'" style="cursor:pointer"><div class="mh"><span class="badge kind">'+v.status+'</span><b>'+(v.name||"").replace(/</g,"&lt;")+'</b><span style="flex:1"></span><span class="muted">+'+v.income_eur.toFixed(2)+' / -'+v.expenses_eur.toFixed(2)+' = <b>'+v.balance_eur.toFixed(2)+' &euro;</b></span></div>'+ms+'</div>';}).join("")
  :'<div class="emptybox">Noch keine Ventures<br>Kira, leg ein Venture an: &hellip;</div>';
 $$('#vent-list [data-vent]').forEach(r=>r.onclick=()=>loadVentureTrace(r.dataset.vent));
}catch(e){}}
async function loadVentureTrace(id){const el=$("#vent-detail");try{
 const d=await (await fetch("/api/venture/trace?id="+encodeURIComponent(id))).json();
 if(d.error){el.style.display="none";return;}
 let h='<div style="display:flex;align-items:center;gap:8px"><b>'+(d.venture.name||"").replace(/</g,"&lt;")+'</b><span class="muted">Kasse '+d.balance.toFixed(2)+' &euro;</span><span style="flex:1"></span><a id="vent-close" style="cursor:pointer;color:var(--muted)">&#10005;</a></div>';
 if(!(d.objectives||[]).length)h+='<div class="muted" style="margin-top:6px">Noch keine Ziele an diesem Venture.</div>';
 (d.objectives||[]).forEach(o=>{
  h+='<div style="margin-top:8px"><span class="badge kind">'+(KIND_LABEL[o.kind]||o.kind)+'</span> <b>'+(o.title||"").replace(/</g,"&lt;")+'</b> <span class="muted">'+o.progress+'%</span></div>';
  (o.tasks||[]).slice(0,6).forEach(t=>{h+='<div class="muted" style="font-size:12px;margin-left:12px">'+(t.status==="done"?"&#10003;":"&middot;")+' '+(t.description||"").replace(/</g,"&lt;").slice(0,110)+(t.score!=null?(' <span style="color:var(--hud)">['+t.score+']</span>'):'')+'</div>';});
  if(o.workingset)h+='<div class="muted" style="font-size:11px;margin:4px 0 0 12px;white-space:pre-wrap;border-left:2px solid var(--line);padding-left:8px">'+o.workingset.replace(/</g,"&lt;").slice(-500)+'</div>';});
 el.innerHTML=h;el.style.display="block";
 const cl=$("#vent-close");if(cl)cl.onclick=()=>{el.style.display="none";};
}catch(e){}}

/* ---- Zentrale (S5.3b): Brauche-von-dir + Heute-erledigt ---- */
async function loadNeeds(){const el=$("#needs-list");if(!el)return;try{
 const a=await (await fetch("/api/approvals")).json();
 const k=await (await fetch("/api/secrets")).json();
 const items=[];
 (a.pending||[]).forEach(p=>items.push('<div class="op"><span class="od" style="background:var(--warn)"></span><span class="opx">&#128272; Freigabe: '+(p.title||"").replace(/</g,"&lt;").slice(0,110)+'</span></div>'));
 (k.pending||[]).forEach(p=>items.push('<div class="op"><span class="od" style="background:var(--warn)"></span><span class="opx">&#128273; Zugang: '+((p.name||"")+" &mdash; "+(p.reason||"")).replace(/</g,"&lt;").slice(0,110)+'</span></div>'));
 const nc=$("#needs-count");if(nc)nc.textContent=items.length?(items.length+" offen"):"";
 el.innerHTML=items.join("")||'<div class="emptybox">Nichts offen &mdash; alles bei mir.</div>';
}catch(e){}}
async function loadZDigest(){const el=$("#z-digest");if(!el)return;try{const d=await (await fetch("/api/digest")).json();
 el.innerHTML='<div><b>'+d.tasks_done_count+'</b> Aufgaben erledigt &middot; <b>'+d.planned+'</b> geplant &middot; Fehler: <b style="color:'+(d.errors?"var(--danger)":"var(--ok)")+'">'+d.errors+'</b></div>'
  +((d.tasks_done&&d.tasks_done.length)?('<ul style="margin:6px 0 0;padding-left:16px;font-size:12px">'+d.tasks_done.slice(0,6).map(t=>'<li>'+(""+t).replace(/</g,"&lt;")+'</li>').join("")+'</ul>'):'')
  +'<div class="muted" style="margin-top:6px;font-size:12px">Kosten heute: '+d.spend_usd+' &euro;</div>';}catch(e){}}

refreshStatus();loadCommand();
setInterval(()=>{refreshStatus();if(cur==="system"&&sysCur==="log"&&logRaw.length<=100)loadEvents();if(cur==="system"&&sysCur==="gov")loadGov();if(cur==="home"){loadHud();loadOps();loadNeeds();}},5000);
setInterval(()=>{if(cur==="home")loadNews();},30000);
</script></body></html>"""
