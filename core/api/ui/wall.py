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
<title>__AGENT__ · Desktop</title>
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
  /* Modus-Aura: weicher Farbschleier im Akzentton, steigt hinter dem Chat auf und
     wechselt mit dem Modus mit (rein statisches CSS, 0% Last, 1s-Blende beim Wechsel) */
  #aura{position:fixed;inset:0;z-index:0;pointer-events:none;transition:background 1s ease;
    background:radial-gradient(58% 46% at 50% 92%,color-mix(in srgb,var(--accent) 15%,transparent),transparent 72%)}
  body[data-mode="coding"] #aura{background:
    radial-gradient(42% 38% at 30% 94%,rgba(255,0,77,.10),transparent 70%),
    radial-gradient(42% 38% at 50% 96%,rgba(57,255,20,.08),transparent 70%),
    radial-gradient(42% 38% at 70% 94%,rgba(0,229,255,.10),transparent 70%)}
  /* Maske folgt der Graph-Position (--gx/--gy aus JS) — sonst schneidet sie den Graph ab,
     sobald er nicht mittig steht (z.B. oben rechts). */
  #graph{position:fixed;inset:0;width:100%;height:100%;z-index:1;opacity:.82;
    -webkit-mask:radial-gradient(66% 55% at var(--gx,50%) var(--gy,45%),#000 34%,transparent 86%);
    mask:radial-gradient(66% 55% at var(--gx,50%) var(--gy,45%),#000 34%,transparent 86%)}
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
  /* S12b (Sergens Wunsch): der LED-Sweep laeuft in JEDEM Modus in der Modus-Farbe —
     Chat/Work dezent (halbe Leuchtkraft, langsam), Coding = Vollgas-Regenbogen. */
  .edge::before{opacity:.45;animation:spin 10s linear infinite}
  body[data-anim="on"] .edge::before{opacity:1;animation-duration:7s}
  body[data-mode="coding"] .edge::before{opacity:1;animation:spin 6s linear infinite}
  @keyframes spin{to{--ang:360deg}}
  /* SPARMODUS (Werkstatt-Fund 11.07.: Dauer-Animationen halten die GPU wach — bis ~6 GB
     VRAM, die lokale Trainings-/Inferenz-Laeufe brauchen). Schalter im Zahnrad: stoppt
     JEDE Endlos-Animation (LED-Sweep, Chat-Ring, Atmen, Regenbogen) — der statische
     Glow bleibt, die Optik stirbt nicht. !important schlaegt auch die Coding-Overrides. */
  body[data-spar="on"] .edge::before{animation:none !important;opacity:.3}
  body[data-spar="on"] .bar::before{animation:none !important;opacity:.35}
  body[data-spar="on"] .seg button.on{animation:none !important}
  body[data-spar="on"] .tx{animation:none !important;-webkit-text-fill-color:var(--accent)}

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
  /* Gespraech in der Bildmitte (Sergens rote Zone): Verlauf waechst nach oben,
     aeltere Zeilen blenden aus — Text bricht um statt abgeschnitten zu werden. */
  #convo{display:flex;flex-direction:column;justify-content:flex-end;gap:9px;width:100%;
    max-height:44vh;overflow:hidden;-webkit-mask:linear-gradient(180deg,transparent,#000 18%);
    mask:linear-gradient(180deg,transparent,#000 18%)}
  .tline{font-size:13.5px;line-height:1.55;text-shadow:0 1px 5px #000;text-align:center;max-width:100%;
    white-space:pre-wrap;overflow-wrap:break-word}
  .tline.me{color:#fff;font-weight:600} .tline.k{color:#d6cde8}
  .think{display:flex;align-items:center;gap:8px;font-size:12.5px;min-height:18px}
  .sh{width:12px;height:12px;flex:none;display:inline-block;box-sizing:border-box;border-radius:50%;
    border:2px solid color-mix(in srgb,var(--accent) 26%,transparent);border-top-color:var(--accent);animation:sp .8s linear infinite}
  @keyframes sp{to{transform:rotate(360deg)}}
  .tx{font-weight:600;background:linear-gradient(90deg,#b026ff,#ff2d95,#ff8a00,#39ff14,#00e5ff,#b026ff);
    background-size:300% 100%;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;animation:flow 3.2s linear infinite}
  @keyframes flow{to{background-position:-300% 0}}
  .bar{display:flex;align-items:flex-end;gap:8px;width:100%;padding:8px 8px 8px 12px;border-radius:16px;position:relative;
    background:color-mix(in srgb,var(--bg) 62%,transparent);border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);
    backdrop-filter:blur(12px);box-shadow:0 10px 40px rgba(0,0,0,.5),0 0 22px color-mix(in srgb,var(--accent) 22%,transparent);transition:border-color .4s,box-shadow .4s,opacity .3s}
  .bar.off{opacity:.55;filter:saturate(.4)}   /* Chat getrennt -> sichtbar gedimmt statt stummer Nichtreaktion */
  /* LED-RING um den Chat-Balken (Masken-Trick wie der LED-Rand: nur der 2px-Rahmen
     leuchtet, innen bleibt alles lesbar). In JEDEM Modus in der Modus-Farbe — Chat/Work
     dezent + langsam, Coding uebersteuert mit fliessendem Regenbogen. */
  .bar::before{content:"";position:absolute;inset:-2px;border-radius:18px;padding:2px;pointer-events:none;opacity:.5;
    background:conic-gradient(from var(--ang),transparent 0 12%,var(--accent) 26%,transparent 40% 62%,var(--accent) 76%,transparent 90% 100%);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;
    animation:spin 8s linear infinite}
  body[data-mode="coding"] .bar{border-color:transparent}
  body[data-mode="coding"] .bar::before{opacity:1;
    background:conic-gradient(from var(--ang),#ff004d,#ff8a00,#ffe600,#39ff14,#00e5ff,#b026ff,#ff004d);
    animation:spin 4s linear infinite;filter:drop-shadow(0 0 10px rgba(176,38,255,.45))}
  /* aktiver Modus-Knopf: sanftes LED-Atmen in der Modus-Farbe; Coding fliesst im Regenbogen */
  .seg button.on{animation:segglow 3.2s ease-in-out infinite}
  @keyframes segglow{0%,100%{box-shadow:0 0 8px color-mix(in srgb,var(--accent) 45%,transparent)}
    50%{box-shadow:0 0 20px var(--accent)}}
  body[data-mode="coding"] .seg button.on{color:#0a0712;
    background:linear-gradient(90deg,#ff004d,#ff8a00,#ffe600,#39ff14,#00e5ff,#b026ff,#ff004d);
    background-size:300% 100%;animation:segflow 3s linear infinite,segglow 3.2s ease-in-out infinite}
  @keyframes segflow{to{background-position:-300% 0}}
  .seg{display:flex;gap:2px;background:rgba(255,255,255,.05);border-radius:10px;padding:3px}
  .seg button{border:0;background:none;color:var(--muted);font:600 12px var(--sans);letter-spacing:.3px;padding:6px 11px;border-radius:8px;cursor:pointer;transition:.2s}
  .seg button.on{color:#0a0712;background:var(--accent);box-shadow:0 0 14px color-mix(in srgb,var(--accent) 60%,transparent)}
  .ic{width:34px;height:34px;flex:none;border:0;border-radius:10px;cursor:pointer;font-size:17px;background:rgba(255,255,255,.06);color:var(--accent);display:grid;place-items:center}
  #cin{flex:1;background:none;border:0;outline:none;color:var(--ink);font-size:14px;padding:6px 4px;font-family:var(--sans);
    line-height:1.4;resize:none;overflow-y:auto;max-height:120px;white-space:pre-wrap;overflow-wrap:break-word;
    caret-color:var(--accent)}   /* Schreibmarke im Akzentton — im Fenster gut sichtbar (als Hintergrund-Wallpaper blinkt sie systembedingt nur bei Fokus) */
  #cin::placeholder{color:var(--muted)}
  .model{font:600 11px var(--mono);color:var(--accent);border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);border-radius:20px;padding:5px 11px;white-space:nowrap;cursor:pointer}
  .model:hover{background:color-mix(in srgb,var(--accent) 14%,transparent)}
  .mpop{position:absolute;bottom:calc(100% + 8px);right:0;z-index:20;min-width:230px;max-height:300px;overflow:auto;
    background:rgba(12,9,18,.97);border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);border-radius:12px;padding:6px;
    box-shadow:0 12px 40px rgba(0,0,0,.6);display:none}
  .mpop.on{display:block}
  .mrow{padding:7px 10px;border-radius:8px;font-size:12px;cursor:pointer;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:var(--mono)}
  .mrow:hover{background:color-mix(in srgb,var(--accent) 18%,transparent)}
  /* Live-Feed: Aktivitaets-Stream als lesbares Panel oben links (neben dem Vault-Graph) —
     zeigt WAS Kira gerade tut. pointer-events:none -> stoert nie, kein Animations-Loop,
     nur ein Poll alle 10 s -> passt zur 0%-Last-Philosophie des Wallpapers. */
  #ticker{position:fixed;left:16vw;top:13vh;z-index:2;pointer-events:none;display:flex;flex-direction:column;gap:6px;
    max-width:min(540px,33vw);padding:13px 17px 14px;border-radius:14px;
    background:linear-gradient(180deg,rgba(6,4,11,.55),rgba(6,4,11,.26));
    border:1px solid color-mix(in srgb,var(--accent) 20%,transparent);
    -webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);
    font-family:var(--mono);font-size:12.5px;line-height:1.55;text-shadow:0 1px 4px #000}
  #ticker:empty{display:none}
  #ticker .tkh{font-size:9.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--accent);opacity:.95;margin-bottom:3px}
  #ticker .tk{color:#e8e1f4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:opacity .6s}
  #ticker .tk .tt{color:var(--accent);opacity:.95;margin-right:8px}
  #ticker .tk .td{color:var(--muted)}
  #ticker .tk.error{color:var(--amber)}
  /* HUD-Uhr unten rechts: gross, tabellarische Ziffern, weicher Neon-Schein im Akzentton.
     DOM wird nur beim Minutenwechsel angefasst -> keine Dauer-Recomposites. */
  #clock{position:fixed;right:30px;bottom:26px;z-index:2;pointer-events:none;text-align:right;
    text-shadow:0 2px 8px rgba(0,0,0,.95)}
  /* Wochen-Kalender: 7 schmale QUER-Zeilen (Mo–So) mit lesbarem Text statt Kaestchen-Grid.
     Quelle: Lebens-Todos mit Faelligkeit (/api/life/board) — heute leuchtet im Akzent. */
  #week{position:fixed;left:16vw;bottom:14vh;z-index:2;display:flex;flex-direction:column;gap:3px;
    width:min(410px,30vw);padding:12px 14px 13px;border-radius:14px;
    background:linear-gradient(180deg,rgba(6,4,11,.55),rgba(6,4,11,.26));
    border:1px solid color-mix(in srgb,var(--accent) 20%,transparent);
    -webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);
    font-family:var(--mono);font-size:12px;line-height:1.5;text-shadow:0 1px 4px #000}
  body[data-week="off"] #week{display:none}
  #week .wkh{font-size:9.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--accent);margin-bottom:4px}
  #week .wd{display:flex;gap:10px;align-items:baseline;padding:3px 8px;border-radius:8px;border:1px solid transparent}
  #week .wd.today{border-color:color-mix(in srgb,var(--accent) 45%,transparent);background:color-mix(in srgb,var(--accent) 10%,transparent)}
  #week .wd .wtag{flex:none;width:46px;color:var(--muted)}
  #week .wd.today .wtag{color:var(--accent);font-weight:700}
  #week .wd .wtx{color:#e8e1f4;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;min-width:0}
  #week .wd.leer .wtx{color:var(--muted);opacity:.4}
  #week .wsep{color:var(--muted)} #week .wmehr{color:var(--accent)}
  /* frei verschiebbare Bausteine (Uhr/Ticker/Kalender): greifbar, wenn /wall im Fenster offen ist */
  .drag{cursor:grab} .drag.dragging{cursor:grabbing;user-select:none}
  body[data-clock="off"] #clock{display:none}
  #clock .ct{font-family:var(--mono);font-size:56px;line-height:1;color:#fff;font-variant-numeric:tabular-nums;
    filter:drop-shadow(0 0 14px color-mix(in srgb,var(--accent) 45%,transparent))}
  #clock .cd{margin-top:7px;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
  .tag{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:9;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);display:flex;gap:8px;align-items:center}
  .tag .d{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:bl 2s infinite}
  @keyframes bl{50%{opacity:.4}}
  @media (prefers-reduced-motion:reduce){.edge::before,.tx,.sh,.bar::before,.seg button.on{animation:none}}
</style></head>
<body data-mode="chat">
  <img id="bg" src="/api/bg" onerror="this.style.display='none'" alt=""/>
  <div id="aura"></div>
  <canvas id="graph"></canvas>
  <div class="edge"></div>
  <button class="gear" id="gear" title="Desktop-Einstellungen">⚙</button>
  <div class="wpop" id="wpop">
    <div class="wt">Vault-Graph</div>
    <label><input type="checkbox" id="w-labels"/> Worte (Labels)</label>
    <label><input type="checkbox" id="w-motion"/> Bewegung</label>
    <label>Farbe <select id="w-color"><option value="vault">Vault</option><option value="modus">Modus</option><option value="mono">Mono</option></select></label>
    <label>Position <select id="w-pos"><option value="links">Links</option><option value="mitte">Mitte</option><option value="rechts">Rechts</option></select></label>
    <label>Höhe <select id="w-posy"><option value="oben">Oben</option><option value="mitte">Mitte</option><option value="unten">Unten</option></select></label>
    <label>Größe <select id="w-size"><option value="klein">Klein</option><option value="mittel">Mittel</option><option value="gross">Groß</option><option value="riesig">Riesig</option></select></label>
    <div class="wt" style="padding-top:8px">Leistung</div>
    <label title="Für lokale Trainings-/KI-Läufe: stoppt alle Dauer-Animationen (LED-Sweep, Ring, Atmen) — GPU/VRAM bleibt fürs Modell frei"><input type="checkbox" id="w-spar"/> Sparmodus (GPU schonen)</label>
    <div class="wt" style="padding-top:8px">Aktivität</div>
    <label><input type="checkbox" id="w-ticker"/> Live-Ticker (unten links)</label>
    <label><input type="checkbox" id="w-clock"/> Uhr (unten rechts)</label>
    <label><input type="checkbox" id="w-week"/> Wochen-Kalender</label>
    <div class="wt" style="padding-top:8px">Layout</div>
    <label style="cursor:default;color:var(--muted);font-size:11px">Uhr, Ticker &amp; Kalender lassen sich mit der Maus verschieben</label>
    <label id="w-layout-reset" style="color:var(--accent)">↺ Positionen zurücksetzen</label>
  </div>
  <div id="ticker"></div>
  <div id="clock"><div class="ct">–:–</div><div class="cd"></div></div>
  <div id="week"><div class="wkh">◈ Woche</div><div id="wkrows"></div></div>

  <div class="topbar">
    <div class="srow" id="srow"></div>
    <div class="sub" id="sub"></div>
  </div>

  <div class="talk">
    <div id="convo"></div>
    <div class="think" id="t-think"></div>
    <form class="bar" id="bar" autocomplete="off">
      <div class="seg" id="seg">
        <button type="button" class="on" data-m="chat">Chat</button>
        <button type="button" data-m="work">Work</button>
        <button type="button" data-m="coding">Coding</button>
      </div>
      <label class="ic" title="Bild einfügen">+<input id="imgfile" type="file" accept="image/*" style="display:none"/></label>
      <textarea id="cin" rows="1" placeholder="Schreib mir …"></textarea>
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
  lifeTasks=lifeB;renderWeek();   // Wochen-Kalender speist sich aus demselben Life-Board
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
  // feste Reihenfolge + stabile Schluessel -> der Desktop-Editor (Kira->Wallpaper) waehlt, welche sichtbar sind
  const STATS=[
    {k:"motor",l:"Motor",v:hb?"● an":"● aus",c:hb?"g":""},
    {k:"aufgaben",l:"Aufgaben",v:open+(tasks.length?'<span style="font-size:14px;color:var(--muted)">/'+tasks.length+'</span>':"")},
    {k:"ausgaben",l:"Ausgaben heute",v:spend.toFixed(2).replace(".",",")+"€"+(cap?'<span style="font-size:14px;color:var(--muted)"> /'+cap+'€</span>':""),c:"a"},
    {k:"fehler",l:"Fehler · 7 Tg",v:errs,c:errs?"":"g"},
    {k:"notizen",l:"Vault-Notizen",v:g.counts.notes},
    {k:"verbindungen",l:"Verbindungen",v:g.counts.links},
    {k:"todos",l:"To-Dos",v:todosN},
    {k:"mails",l:"Mails",v:mailsN==null?"—":mailsN,c:mailsN?"a":""},
    {k:"news",l:"News",v:newsN},
    {k:"cpu",l:"CPU",v:pc(sys.cpu)+(sys.cpu!=null?"%":"")},
    {k:"gpu",l:"GPU",v:pc(sys.gpu)+(sys.gpu!=null?"%":"")},
    {k:"temp",l:"Temp",v:pc(temp)+(temp!=null?"°":""),c:temp!=null&&temp>=75?"a":""}
  ];
  const sel=(Array.isArray(WALL.stats)&&WALL.stats.length)?WALL.stats:STATS.map(s=>s.k);
  $("#srow").innerHTML=STATS.filter(s=>sel.indexOf(s.k)>=0).map(s=>stat(s.v,s.l,s.c||"")).join("");
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

/* ---- Live-Ticker: die letzten Aktionen als leiser Stream (Text kommt fertig vom Server) ---- */
async function loadTicker(){const el=$("#ticker");if(!el)return;
  if(!WALL.ticker){el.innerHTML="";return;}
  try{const es=await (await fetch("/api/events?limit=8")).json();
    el.innerHTML=(es&&es.length?'<div class="tkh">◈ Live · was __AGENT__ gerade tut</div>':"")
     +(es||[]).map((e,i)=>{
      const t=new Date(e.ts*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
      const txt=esc((e.text||e.type||"").slice(0,64));
      const det=e.detail?' <span class="td">'+esc((""+e.detail).slice(0,64))+'</span>':"";
      return '<div class="tk'+(e.sev==="error"?" error":"")+'" style="opacity:'+(1-i*0.09).toFixed(2)+'"><span class="tt">'+t+'</span>'+txt+det+'</div>';
    }).join("");
  }catch(e){}}

/* ---- HUD-Uhr (unten rechts): minutengenau; DOM nur anfassen, wenn sich die Minute
   aendert -> das Wallpaper wird nicht jede Sekunde neu zusammengesetzt (0%-Last). ---- */
let _clockShown="";
function tickClock(){
  document.body.dataset.clock=(WALL.clock!==false)?"on":"off";
  if(WALL.clock===false)return;
  const d=new Date(),t=d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
  if(t===_clockShown)return;_clockShown=t;
  $("#clock .ct").textContent=t;
  $("#clock .cd").textContent=d.toLocaleDateString("de-DE",{weekday:"long"})+" · "+d.toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
}

/* ---- Wochen-Kalender: Mo–So als schmale Text-Zeilen, heute im Akzent ---- */
let lifeTasks=[];
function isoDay(d){const p=n=>(""+n).padStart(2,"0");return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate());}
function renderWeek(){
  document.body.dataset.week=(WALL.week!==false)?"on":"off";
  if(WALL.week===false)return;
  const now=new Date(),mon=new Date(now);mon.setDate(now.getDate()-((now.getDay()+6)%7));
  const names=["Mo","Di","Mi","Do","Fr","Sa","So"];let html="";
  for(let i=0;i<7;i++){const d=new Date(mon);d.setDate(mon.getDate()+i);const iso=isoDay(d);
    const es=lifeTasks.filter(t=>t&&t.due_date===iso&&t.status!=="done");
    const txt=es.slice(0,3).map(t=>esc((""+(t.description||"")).slice(0,46))).join('<span class="wsep"> · </span>')
      +(es.length>3?' <span class="wmehr">+'+(es.length-3)+'</span>':"");
    html+='<div class="wd'+(iso===isoDay(now)?" today":"")+(es.length?"":" leer")+'">'
      +'<span class="wtag">'+names[i]+' '+d.getDate()+'.</span><span class="wtx">'+(txt||"frei")+'</span></div>';}
  $("#wkrows").innerHTML=html;
}

/* ---- Bausteine frei verschieben (Uhr/Ticker/Kalender): Position in % des Bildschirms,
   gespeichert in WALL.layout -> ueberlebt Reloads und synct wie alles andere ueber den
   Server (Einstellung im Browser-Tab aendern, das Lively-Wallpaper zieht nach). ---- */
function applyLayout(){const L=WALL.layout||{};
  for(const k of ["clock","ticker","week"]){const el=$("#"+k);if(!el)continue;
    if(Array.isArray(L[k])){el.style.left=L[k][0]+"%";el.style.top=L[k][1]+"%";el.style.right="auto";el.style.bottom="auto";}
    else{el.style.left=el.style.top=el.style.right=el.style.bottom="";}}}
function makeDrag(el){if(!el)return;el.classList.add("drag");el.style.pointerEvents="auto";
  el.addEventListener("pointerdown",e=>{
    if(e.target.closest("a,button,input,select"))return;   // Bedienelemente nicht kapern
    const r=el.getBoundingClientRect(),ox=e.clientX-r.left,oy=e.clientY-r.top;let moved=false;
    const mv=ev=>{moved=true;el.classList.add("dragging");
      const x=Math.max(0,Math.min(innerWidth-r.width,ev.clientX-ox)),
            y=Math.max(0,Math.min(innerHeight-r.height,ev.clientY-oy));
      el.style.left=(x/innerWidth*100).toFixed(2)+"%";el.style.top=(y/innerHeight*100).toFixed(2)+"%";
      el.style.right="auto";el.style.bottom="auto";};
    const up=()=>{removeEventListener("pointermove",mv);removeEventListener("pointerup",up);
      el.classList.remove("dragging");if(!moved)return;
      WALL.layout=WALL.layout||{};WALL.layout[el.id]=[parseFloat(el.style.left),parseFloat(el.style.top)];saveWall();};
    addEventListener("pointermove",mv);addEventListener("pointerup",up);e.preventDefault();});}

/* ---- Live-Vault-Graph ---- */
let ns=[],ls=[],cv,ctx,W,H,DPR=Math.min(2,devicePixelRatio||1),reduce=matchMedia('(prefers-reduced-motion:reduce)').matches,settle=0,drag=null,graphVault=null,dragStart=null,dragMoved=false,GX={},GMAIN="·",lastFloat=0;
/* Wallpaper-Einstellungen (Zahnrad) — leben im localStorage, das offene Wallpaper hoert per
   'storage'-Event mit -> aendere sie in einem Browser-Tab, der Desktop uebernimmt live. */
const MODE_RGB={chat:"176,38,255",work:"57,255,20",coding:"0,229,255"};
/* Cockpit-THEME uebernehmen (gruen/blau/amber/rot aus localStorage 'kira-theme'):
   die Wallpaper-Akzentfarbe folgt der Cockpit-Wahl. Eigene Farben (kira_custom-Accent
   oder Desktop-Editor WALL.colors) gewinnen weiterhin — Hierarchie Editor > Theme. */
(function(){try{
  const c=JSON.parse(localStorage.getItem("kira_custom")||"{}");if(c.accent)return;
  const TH={gruen:["#39ff14","57,255,20"],blau:["#22d3ee","34,211,238"],amber:["#ffb02e","255,176,46"],rot:["#ff2d55","255,45,85"]};
  const t=TH[localStorage.getItem("kira-theme")||""];if(!t)return;
  document.documentElement.style.setProperty("--chat",t[0]);MODE_RGB.chat=t[1];
}catch(e){}})();
const POSX={links:0.32,mitte:0.5,rechts:0.68},POSY={oben:0.32,mitte:0.46,unten:0.6},SIZ={klein:0.72,mittel:1,gross:2.6,riesig:3.6};
let curG=null;   // zuletzt geladener Graph (fuer Re-Layout bei Groesse/Position)
// Standard-Layout nach Sergens Desktop-Plan: Graph oben RECHTS, Live-Feed oben links,
// Mitte bleibt frei fuers Artwork. Standbild default (0% Last); stats=null -> alle.
let WALL={labels:true,motion:false,color:"vault",pos:"rechts",posy:"oben",size:"gross",stats:null,colors:null,ticker:true,clock:true,week:true,layout:null,spar:false};
function loadWall(){try{const s=JSON.parse(localStorage.getItem("kira_wall")||"{}");
  if(!("posy" in s)&&s.pos==="mitte")delete s.pos;   // Migration 3-Zonen-Layout: altes Default faellt, bewusste Wahl bleibt
  Object.assign(WALL,s);}catch(e){}}
async function loadWallServer(){try{const s=await (await fetch("/api/wall/settings")).json();if(s&&typeof s==="object")Object.assign(WALL,s);}catch(e){}}
function saveWall(){try{localStorage.setItem("kira_wall",JSON.stringify(WALL));}catch(e){}
  try{fetch("/api/wall/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(WALL)});}catch(e){}}
let _wallSig="";
async function pollWall(){try{const raw=await (await fetch("/api/wall/settings")).text();if(raw===_wallSig)return;_wallSig=raw;
  const s=JSON.parse(raw||"{}");const op=WALL.pos,oy=WALL.posy,os=WALL.size;Object.assign(WALL,s);
  try{syncWallUI();}catch(e){}try{applyColors();}catch(e){}try{loadStats();}catch(e){}try{loadTicker();}catch(e){}   // Farben + Stats-Auswahl + Ticker live nachziehen (Editor)
  if(WALL.pos!==op||WALL.posy!==oy||WALL.size!==os)relayout();else kick();}catch(e){}}
function nodeColor(n){return WALL.color==="modus"?(MODE_RGB[mode]||"176,38,255"):WALL.color==="mono"?"233,228,244":n.g0;}
function sz(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);}
const CX=()=>W*(POSX[WALL.pos]||0.5), CY=()=>H*(POSY[WALL.posy]||0.46), SCALE=()=>SIZ[WALL.size]||1;
function setHomes(){for(const n of ns){n.hx=n.x;n.hy=n.y;if(n.ph==null){n.ph=Math.random()*6.283;n.sp=0.5+Math.random()*0.7;}}}
function layout(g){
  curG=g;const by={},sc=SCALE();settle=0;
  const raw=(g.nodes||[]).slice(0,120);
  // KONSTELLATIONS-Layout (aufgeraeumt statt Wildwuchs): jede Gruppe (Ordner/Bereich)
  // bekommt einen festen Cluster-Anker auf einem Ring um die Graph-Position — klar
  // getrennte Sternbilder wie in der Obsidian-'Constellations'-Optik. Groesste Gruppe
  // sitzt in der Mitte, der Rest kreist darum.
  const groups=[...new Set(raw.map(n=>n.group||"·"))],gN=groups.length||1;
  const bx=POSX[WALL.pos]||0.5,byy=POSY[WALL.posy]||0.46;
  const cnt={};raw.forEach(n=>{const gp=n.group||"·";cnt[gp]=(cnt[gp]||0)+1;});
  groups.sort((a,b)=>(cnt[b]||0)-(cnt[a]||0));
  // BREIT gezogen (Sergens Feedback: alles klebte aneinander): flache, weite Ellipse —
  // die Cluster bekommen Luft zueinander, das Querformat des Monitors wird genutzt.
  const rx=(WALL.pos==="mitte"?0.32:0.19)*Math.sqrt(sc/2.6),ry=0.105*Math.sqrt(sc/2.6);
  GX={};GMAIN=groups[0]||"·";
  groups.forEach((gp,k)=>{
    if(k===0){GX[gp]={fx:bx,fy:byy};return;}                    // Hauptgruppe = Zentrum
    const a=((k-1)/Math.max(1,gN-1))*Math.PI*2-Math.PI/2;       // Rest auf dem Ring
    GX[gp]={fx:bx+Math.cos(a)*rx,fy:byy+Math.sin(a)*ry};});
  ns=raw.map((n,i)=>{const a=i*2.399,rr=(16+Math.random()*Math.min(W,H)*0.06)*sc,g=GX[n.group||"·"]||{fx:bx,fy:byy};
    const o={id:n.id,g0:n.color||"176,38,255",grp:(n.group||"·"),cx:g.fx,cy2:g.fy,
      x:W*g.fx+Math.cos(a)*rr,y:H*g.fy+Math.sin(a)*rr*0.8,vx:0,vy:0,deg:0};by[n.id]=o;return o;});
  ls=(g.links||[]).map(l=>[by[l.source],by[l.target]]).filter(p=>p[0]&&p[1]);
  ls.forEach(([a,b])=>{a.deg++;b.deg++;});
  // Knoten bewusst KLEIN halten (Sergens Feedback: Kreise zu gross) — Hubs heben sich
  // ueber Orbit-Ring + Label ab, nicht ueber fette Blobs. Groesse waechst nur gedaempft
  // mit dem Zoom (Wurzel gedeckelt), sonst werden die Punkte bei 'gross' wieder Buttons.
  const nsc=Math.min(1.25,Math.sqrt(sc));
  ns.forEach(n=>{n.r=(1.2+Math.min(3,n.deg*0.35))*nsc;});
  // vorab fertig rechnen -> der Graph erscheint direkt gesetzt & sauber verteilt (kein Zappeln)
  if(!reduce){for(let k=0;k<350;k++)sim();}
  setHomes();settle=999;   // Ruhelage merken; gilt als gesetzt (Loop schwebt sanft oder friert ein)
}
function sim(){   // force-directed, ruhig getaktet: Repulsion + Federn + Cluster-Anker, starke Daempfung
  const sc=SCALE(),REP=520*sc,LEN=58*sc,CL=2.4;
  for(let i=0;i<ns.length;i++){const a=ns[i];
    for(let j=i+1;j<ns.length;j++){const b=ns[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1;
      if(d2<50000){const d=Math.sqrt(d2),f=REP/d2;dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}}}
  // ENTWIRRUNG: Federn INNERHALB einer Gruppe halten das Sternbild zusammen (K stark),
  // Federn ZWISCHEN Gruppen sind lang + weich (K schwach) — sonst ziehen die Querlinks
  // alle Cluster zu einem Knaeuel in die Mitte (genau Sergens 'klebt alles aneinander').
  for(const [a,b] of ls){const same=a.grp===b.grp,K=same?0.011:0.0022,L=same?LEN:LEN*2.6;
    let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-L)*K;dx/=d;dy/=d;
    a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}
  for(const n of ns){if(n.fx)continue;   // angefasster Knoten haengt an der Maus -> nicht integrieren
    n.vx+=(W*n.cx-n.x)*0.008;            // Zug zum eigenen Cluster-Anker (x UND y)
    n.vy+=(H*n.cy2-n.y)*0.010;           // -> Sternbilder sitzen fest an ihren Ring-Plaetzen
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
  // Sci-Fi-HUD hinter dem Graph: duenne konzentrische Ringe + Tick-Marken um den Anker.
  // Rein statisch (kein Animations-Loop) -> 0% Last, gibt dem Feld einen aufgeraeumten,
  // futuristischen Rahmen statt frei schwebendem Wildwuchs.
  {const hx=CX(),hy=CY(),acc=MODE_RGB[mode]||"176,38,255",rs=Math.sqrt(sc);
   ctx.lineWidth=1;
   for(const r of [96,158,224]){ctx.strokeStyle='rgba('+acc+',.10)';
     ctx.beginPath();ctx.arc(hx,hy,r*rs,0,7);ctx.stroke();}
   ctx.strokeStyle='rgba('+acc+',.26)';
   for(let k=0;k<36;k++){const a=k*Math.PI/18,rr=224*rs;
     ctx.beginPath();ctx.moveTo(hx+Math.cos(a)*(rr-3),hy+Math.sin(a)*(rr-3));
     ctx.lineTo(hx+Math.cos(a)*(rr+3),hy+Math.sin(a)*(rr+3));ctx.stroke();}}
  // Kanten: DUENN + GEBUENDELT (Edge-Bundling-Idee): der Bogen zieht Richtung der
  // Cluster-Anker beider Enden -> Verbindungen laufen in ruhigen Straengen statt
  // kreuz und quer. Eine Linie pro Kante (keine dicke Unterlage mehr) = weniger Laerm.
  // Sichtbarkeits-Hierarchie: Kanten IM Sternbild klar, Kanten ZWISCHEN Sternbildern
  // stark gedimmt + hauchduenn — die Quervernetzung bleibt ablesbar, dominiert aber
  // nicht mehr das Bild (das war der 'Gewusel'-Eindruck).
  for(const [a,b] of ls){const ca=nodeColor(a),cb=nodeColor(b),same=a.grp===b.grp;
    const d=Math.hypot(b.x-a.x,b.y-a.y)||1;
    let al=Math.max(.26,.8-d/(420*sc));if(!same)al*=0.38;
    const mx=(a.x+b.x)/2,my=(a.y+b.y)/2;
    const qx=(mx+ (W*(a.cx+b.cx)/2))/2,qy=(my+(H*(a.cy2+b.cy2)/2))/2;   // Zug zum Cluster -> Buendel
    const gr=ctx.createLinearGradient(a.x,a.y,b.x,b.y);gr.addColorStop(0,'rgba('+ca+','+al.toFixed(2)+')');gr.addColorStop(1,'rgba('+cb+','+al.toFixed(2)+')');
    ctx.strokeStyle=gr;ctx.lineWidth=same?0.9:0.6;
    ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.quadraticCurveTo(qx,qy,b.x,b.y);ctx.stroke();}
  // Knoten: klein & praezise — feiner Neon-Punkt mit hellem Kern. Hubs (viele Links)
  // tragen einen duennen ORBIT-RING statt eines fetten Blobs -> Sci-Fi, nicht Bubble.
  for(const n of ns){const c=nodeColor(n);
    ctx.shadowBlur=0;ctx.beginPath();ctx.arc(n.x,n.y,n.r+1.1,0,7);ctx.fillStyle='rgba(3,2,9,.7)';ctx.fill();
    ctx.shadowColor='rgba('+c+',.75)';ctx.shadowBlur=6;
    ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,7);ctx.fillStyle='rgba('+c+',.95)';ctx.fill();
    ctx.shadowBlur=0;ctx.beginPath();ctx.arc(n.x,n.y,Math.max(.8,n.r*0.4),0,7);ctx.fillStyle='rgba(255,255,255,.88)';ctx.fill();
    if(n.deg>=6){ctx.strokeStyle='rgba('+c+',.5)';ctx.lineWidth=1;
      ctx.beginPath();ctx.arc(n.x,n.y,n.r+4,0,7);ctx.stroke();}}
  ctx.shadowBlur=0;
  // Labels: KLEIN + FEST (Sergens Feedback: Riesen-Schriften). Feste Pixelgroesse
  // unabhaengig vom Graph-Zoom (Lesbarkeit statt Mitwachsen), nur echte Hubs (ab 4
  // Links), kuehle Eis-Cyan-Toene mit Hauch Letter-Spacing = Sci-Fi statt Plakat.
  if(WALL.labels){ctx.textAlign='center';ctx.lineJoin='round';
    try{ctx.letterSpacing='0.06em';}catch(e){}
    for(const n of ns){if(n.deg<4)continue;
      const fs=n.deg>=8?12:10,al=Math.min(.95,.5+n.deg*0.06);
      ctx.font='600 '+fs+'px "Segoe UI",system-ui,sans-serif';
      const t=n.id.slice(0,24),y=n.y-n.r-6;
      ctx.lineWidth=2.8;ctx.strokeStyle='rgba(2,4,12,'+(al*.9).toFixed(2)+')';
      ctx.fillStyle='rgba(182,222,244,'+al.toFixed(2)+')';   // Eis-Cyan, kuehl + dezent
      ctx.strokeText(t,n.x,y);ctx.fillText(t,n.x,y);}
    // Cluster-Beschriftung: Gruppenname klein in GROSSBUCHSTABEN ueber jedem Sternbild.
    // Die ZENTRAL-Gruppe bleibt unbeschriftet — ihr Hub-Label (z.B. SERGEN) reicht,
    // sonst kollidieren beide Schriften uebereinander.
    ctx.font='600 9px "Segoe UI",system-ui,sans-serif';
    try{ctx.letterSpacing='0.22em';}catch(e){}
    for(const gp in GX){if(gp==="·"||gp===GMAIN)continue;const g=GX[gp];
      const t=gp.toUpperCase().slice(0,20),xx=W*g.fx,yy=H*g.fy-56*Math.sqrt(sc);
      ctx.lineWidth=2.6;ctx.strokeStyle='rgba(2,4,12,.8)';ctx.fillStyle='rgba(148,196,224,.62)';
      ctx.strokeText(t,xx,yy);ctx.fillText(t,xx,yy);}
    try{ctx.letterSpacing='0px';}catch(e){}}
}
/* Loop stoppt, sobald der Graph gesetzt ist und "Bewegung" aus ist -> 0% CPU im Ruhezustand
   (genau das, was Lively sonst dauernd rendern liess). Aenderungen wecken ihn per kick(). */
const SETTLE_MAX=280;let raf=0;
function frame(ts){ts=ts||0;
  const active=!reduce&&(drag||settle<SETTLE_MAX);   // echte Physik: nur beim Setzen/Ziehen
  if(active){sim();settle++;if(settle>=SETTLE_MAX)setHomes();render();raf=requestAnimationFrame(frame);return;}
  if(reduce||!WALL.motion||WALL.spar){render();raf=0;return;}   // "Bewegung" aus / Sparmodus -> Standbild, 0% CPU
  if(ts-lastFloat<45){raf=requestAnimationFrame(frame);return;}   // ~22 fps: sanftes Schweben, sparsam
  lastFloat=ts;const A=3.4*Math.sqrt(SCALE());
  for(const n of ns){if(n.fx)continue;n.x=n.hx+Math.sin(ts*0.0005*n.sp+n.ph)*A;n.y=n.hy+Math.cos(ts*0.00042*n.sp+n.ph)*A*0.75;}
  render();raf=requestAnimationFrame(frame);}
function kick(){if(!raf)raf=requestAnimationFrame(frame);}
function applyMask(){const d=document.documentElement;   // Sichtfenster folgt dem Graph
  d.style.setProperty('--gx',Math.round((POSX[WALL.pos]||0.5)*100)+'%');
  d.style.setProperty('--gy',Math.round((POSY[WALL.posy]||0.46)*100)+'%');}
function relayout(){applyMask();if(curG){layout(curG);kick();}}
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

/* ---- ephemerer Chat ueber /ws/chat (frische Session je Aufruf) ----
   Traegheits-Fixes (Sergens Fund): 1) Nachricht bei getrennter Verbindung NICHT mehr
   stumm wegwerfen, sondern vormerken + beim Reconnect senden; 2) running wird beim
   Verbindungsabriss zurueckgesetzt (vorher blockierte ein haengender Lauf den Chat
   dauerhaft); 3) getrennte Leiste ist sichtbar gedimmt (.bar.off). ---- */
let ws,thinkTimer=null,running=false,reasonBuf="",pending=null;
function stopPhrase(){if(thinkTimer){clearInterval(thinkTimer);thinkTimer=null;}}
function setThink(on){const el=$("#t-think");stopPhrase();
  if(on){const put=()=>el.innerHTML='<span class="sh"></span><span class="tx">'+esc(rndPhrase())+' …</span>';put();thinkTimer=setInterval(put,2600);}
  else el.innerHTML="";}
function connect(){const proto=location.protocol==="https:"?"wss":"ws";
  const sid="desktop-"+Math.random().toString(16).slice(2,10);   // ephemer: neu je Seitenaufruf
  ws=new WebSocket(proto+"://"+location.host+"/ws/chat?sid="+encodeURIComponent(sid));
  ws.onopen=()=>{$("#bar").classList.remove("off");
    if(pending){ws.send(pending);pending=null;}};   // vorgemerkte Nachricht geht jetzt raus
  ws.onmessage=ev=>{const m=JSON.parse(ev.data);
    if(m.done){setThink(false);running=false;return;}
    if(m.kind==="think"){stopPhrase();reasonBuf=(reasonBuf+" "+(m.text||"")).slice(-260);   // echtes Reasoning
      $("#t-think").innerHTML='<span class="sh"></span><span class="tx">'+esc(reasonBuf.trim())+'</span>';return;}
    if(m.kind==="tool"){stopPhrase();
      $("#t-think").innerHTML='<span class="sh"></span><span class="tx">▷ '+esc(m.name||"werkzeug")+' …</span>';return;}
    if(m.kind==="final"||m.kind==="answer"){setThink(false);reasonBuf="";pushTurn("k",(m.text||"").slice(0,600));}
  };
  ws.onclose=()=>{$("#bar").classList.add("off");
    if(running){running=false;setThink(false);}    // haengender Lauf blockiert den Chat nicht mehr
    setTimeout(connect,1500);};
}
$("#bar").addEventListener('submit',e=>{e.preventDefault();const raw=$("#cin").value.trim();if(!raw||running)return;
  const t=mode==="work"?("work: "+raw):mode==="coding"?("code: "+raw):raw;
  pushTurn("me",raw);$("#cin").value="";growCin();reasonBuf="";running=true;setThink(true);
  if(ws&&ws.readyState===1)ws.send(t);else pending=t;   // getrennt -> vormerken statt verlieren
  $("#cin").focus();
});
/* Klick irgendwo auf die Leiste fokussiert das Eingabefeld (weniger Zielen noetig) */
$("#bar").addEventListener('click',e=>{
  if(!e.target.closest("button,select,label,.model,.mpop"))$("#cin").focus();});
/* Gespraechsverlauf in der Mitte: die letzten Runden, aeltere gedimmt */
let convo=[];
function pushTurn(who,text){convo.push({who:who,text:text});convo=convo.slice(-6);
  $("#convo").innerHTML=convo.map((m,i)=>'<div class="tline '+m.who+'" style="opacity:'
   +(0.5+0.5*(i+1)/convo.length).toFixed(2)+'">'+esc(m.text)+'</div>').join("");}
/* Eingabefeld waechst mit dem Text; Enter sendet, Shift+Enter = neue Zeile */
function growCin(){const c=$("#cin");if(!c)return;c.style.height="auto";c.style.height=Math.min(c.scrollHeight,120)+"px";}
$("#cin").addEventListener('input',growCin);
$("#cin").addEventListener('keydown',e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();$("#bar").dispatchEvent(new Event('submit',{cancelable:true}));}});
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
function applyAnim(){document.body.dataset.anim=(WALL.motion&&!WALL.spar)?"on":"off";
  document.body.dataset.spar=WALL.spar?"on":"off";}   // Sparmodus uebersteuert alles Pulsierende (GPU/VRAM frei fuers lokale Modell)
function applyColors(){const c=WALL.colors||{},d=document.documentElement;   // Modus-Akzente aus dem Desktop-Editor
  if(c.chat)d.style.setProperty('--chat',c.chat);if(c.work)d.style.setProperty('--work',c.work);if(c.coding)d.style.setProperty('--coding',c.coding);
  d.style.setProperty('--accent',COL[mode]||'var(--chat)');}
function syncWallUI(){$("#w-labels").checked=WALL.labels;$("#w-motion").checked=WALL.motion;$("#w-spar").checked=!!WALL.spar;$("#w-color").value=WALL.color;$("#w-pos").value=WALL.pos;$("#w-posy").value=WALL.posy||"oben";$("#w-size").value=WALL.size;$("#w-ticker").checked=WALL.ticker!==false;$("#w-clock").checked=WALL.clock!==false;$("#w-week").checked=WALL.week!==false;applyAnim();tickClock();renderWeek();applyLayout();}
$("#gear").addEventListener('click',()=>{const p=$("#wpop");p.classList.toggle('on');if(p.classList.contains('on'))syncWallUI();});
$("#w-labels").addEventListener('change',e=>{WALL.labels=e.target.checked;saveWall();kick();});
$("#w-motion").addEventListener('change',e=>{WALL.motion=e.target.checked;saveWall();applyAnim();kick();});
$("#w-spar").addEventListener('change',e=>{WALL.spar=e.target.checked;saveWall();applyAnim();kick();});
$("#w-color").addEventListener('change',e=>{WALL.color=e.target.value;saveWall();kick();});
$("#w-pos").addEventListener('change',e=>{WALL.pos=e.target.value;saveWall();relayout();});
$("#w-posy").addEventListener('change',e=>{WALL.posy=e.target.value;saveWall();relayout();});
$("#w-size").addEventListener('change',e=>{WALL.size=e.target.value;saveWall();relayout();});
$("#w-ticker").addEventListener('change',e=>{WALL.ticker=e.target.checked;saveWall();loadTicker();});
$("#w-clock").addEventListener('change',e=>{WALL.clock=e.target.checked;saveWall();tickClock();});
$("#w-week").addEventListener('change',e=>{WALL.week=e.target.checked;saveWall();renderWeek();});
$("#w-layout-reset").addEventListener('click',()=>{WALL.layout=null;saveWall();applyLayout();});
window.addEventListener('storage',e=>{if(e.key==="kira_wall"){loadWall();syncWallUI();relayout();}});   // aus einem Browser-Tab geaendert -> Wallpaper zieht live nach
document.addEventListener('click',e=>{if(!e.target.closest('#gear')&&!e.target.closest('#wpop')){const p=$("#wpop");if(p)p.classList.remove('on');}});

/* ---- Boot ---- */
(async function(){loadWall();await loadWallServer();applyAnim();applyColors();applyMask();cv=$("#graph");ctx=cv.getContext("2d");sz();setupDrag();
  const g=await loadStats();layout(g);kick();
  addEventListener('resize',()=>{sz();relayout();});
  connect();setInterval(loadStats,30000);   // Stats leben (alle 30 s frisch) — Graph bleibt ruhig
  setInterval(pollWall,3000);                // Einstellungen serverseitig -> Lively-Wallpaper zieht nach
  loadTicker();setInterval(loadTicker,10000); // Aktivitaets-Ticker: 1 leichter Poll alle 10 s, keine Animation
  tickClock();setInterval(tickClock,10000);   // Uhr: minutengenau, DOM nur bei Minutenwechsel
  renderWeek();applyLayout();                 // Wochen-Kalender + gespeicherte Positionen
  makeDrag($("#clock"));makeDrag($("#ticker"));makeDrag($("#week"));   // frei verschiebbar
  $("#cin").focus();                          // Schreibmarke direkt bereit (im Fenster/Tab)
})();
</script>
</body></html>"""
