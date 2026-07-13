"""Cockpit-Kopf + komplettes CSS (Sci-Fi-HUD-DNA: --accent/--hud/--glow, .panel)."""

from core.api.ui.fontdata import AUDIOWIDE_WOFF2_B64

HEAD_AND_CSS = r"""<!doctype html>
<html lang="de"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Kira Cockpit</title>
<link rel="manifest" href="/manifest.webmanifest"/>
<meta name="theme-color" content="#0a0a0d"/>
<link rel="apple-touch-icon" href="/api/icon"/>
<style>
:root{--bg:#0a0a0d;--panel:#0e0e13;--panel2:var(--panel);--line:#26203a;--ink:#eceef4;
 --muted:#9b97b0;--accent:#b026ff;--accent2:#7c3aed;--hud:#c084fc;--glow:#b026ff;
 --amber:#d8b4fe;--danger:#ff3d68;--ok:#39ff8e;--warn:#f5a623;}
/* S6.7: Tuerkis raus — --hud ist helles Lila; Neon-Gruen lebt in --ok (live/positiv/Budget). */
html[data-theme="gruen"]{--accent:#39ff14;--accent2:#16a34a;--hud:#adff2f;--glow:#39ff14;--amber:#bbf7d0;}
html[data-theme="blau"]{--accent:#22d3ee;--accent2:#0891b2;--hud:#38bdf8;--glow:#22d3ee;--amber:#a5f3fc;}
/* S12: zwei neue Stimmungen — Amber (Retro-Terminal) und Rot (Crimson-Alarm) */
html[data-theme="amber"]{--accent:#ffb02e;--accent2:#d97706;--hud:#ffd166;--glow:#ffb02e;--amber:#fde68a;}
html[data-theme="rot"]{--accent:#ff2d55;--accent2:#e11d48;--hud:#ff7a90;--glow:#ff2d55;--amber:#fecdd3;}
.thm{width:30px;height:30px;border-radius:8px;cursor:pointer;padding:0;border:2px solid var(--line);background:var(--panel);
 display:inline-flex;align-items:center;justify-content:center;background-size:cover;background-position:center}
.thm:hover{border-color:var(--accent)}
.thm.on{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent),0 0 14px var(--glow)}
.thm .td{width:15px;height:15px;border-radius:50%;display:inline-block}
.thm.kira{background:linear-gradient(135deg,#3a2150,#0a0410)}
.live{width:7px;height:7px;border-radius:50%;background:var(--ok);display:inline-block;animation:ping 2.4s ease-out infinite}
@keyframes ping{0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}70%,100%{box-shadow:0 0 0 7px rgba(52,211,153,0)}}
.pulse{color:var(--muted);font-weight:500;letter-spacing:.2px}
#feed-list{font-size:12.5px;max-height:280px;overflow:auto;margin-top:6px}
.fd{display:flex;gap:12px;padding:5px 2px;border-bottom:1px solid var(--line)}
.fd .fdt{color:var(--muted);min-width:72px;font-variant-numeric:tabular-nums}
.fd .fdx{flex:1;color:var(--ink)}
.fd.error .fdx{color:var(--danger)} .fd.chat .fdx{color:var(--accent)} .fd.info .fdx{color:var(--muted)}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;font:14px/1.5 ui-monospace,"Cascadia Code",Consolas,monospace;
 background:var(--bg);color:var(--ink)}  /* S6.7: flaches Schwarz/Anthrazit statt Glow-Gradient */
#side{width:210px;flex-shrink:0;border-right:1px solid var(--line);background:var(--bg);
 backdrop-filter:blur(8px);display:flex;flex-direction:column}
/* Wordmark KIRA: Audiowide + Neon-Lila-Regenbogen (Verlauf IM Text, Glow ueber drop-shadow,
   weil text-shadow bei transparentem Verlaufstext nicht greift). Untertitel entfaellt. */
#side h1{margin:0;padding:0;line-height:1.02}
/* App-Logo (data/kira-icon.png) als Kopf; fehlt es, faellt onerror auf den KIRA-Schriftzug zurueck */
#side h1 img{display:block;width:calc(100% - 24px);max-width:170px;height:auto;margin:14px 12px 8px;
 border-radius:16px;box-shadow:0 0 0 1px rgba(176,38,255,.25);
 filter:drop-shadow(0 0 10px rgba(176,38,255,.45)) drop-shadow(0 0 22px rgba(176,38,255,.25))}
#side h1:has(img) .txt{display:none}   /* Bild da -> Schriftzug aus */
#side h1 .txt{display:block;font-family:'Audiowide',ui-sans-serif,system-ui,sans-serif;font-size:33px;
 letter-spacing:1px;padding:18px 16px 14px;line-height:1.02;
 background:linear-gradient(100deg,#e9d5ff,#c084fc,#b026ff,#d946ef,#9333ea,#c084fc,#e9d5ff);
 background-size:260% 100%;-webkit-background-clip:text;background-clip:text;
 -webkit-text-fill-color:transparent;color:transparent;
 filter:drop-shadow(0 0 4px rgba(176,38,255,.85)) drop-shadow(0 0 15px rgba(176,38,255,.5))}
#side a{display:block;padding:10px 16px;color:var(--ink);text-decoration:none;cursor:pointer;
 border-left:3px solid transparent}
#side a:hover{background:rgba(168,85,247,.10)}
#side a.on{background:rgba(168,85,247,.14);border-left-color:var(--accent);color:var(--ink)}
#side .spacer{flex:1}
#side .kill{margin:12px;padding:9px;text-align:center;border:1px solid var(--line);border-radius:8px;
 cursor:pointer;color:var(--muted)}
#side .kill.active{border-color:var(--danger);color:var(--danger)}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#bar{padding:9px 18px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center;
 font-size:12px;color:var(--muted);background:var(--bg)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent);display:inline-block}
#v-home h2{font-size:18px;letter-spacing:1px}
#bar b{color:var(--ink)}
.view{flex:1;overflow:auto;display:none;padding:18px}
.view.on{display:flex;flex-direction:column}
/* chat */
#log{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:12px;max-width:880px;margin:0 auto;width:100%;padding-bottom:4px}
.msg{padding:11px 14px;border-radius:12px;border:1px solid var(--line);white-space:pre-wrap;max-width:84%}
.me{align-self:flex-end;background:rgba(124,58,237,.22);border-color:rgba(168,85,247,.35)}
.bot{align-self:flex-start;background:rgba(21,15,32,.72)}
.sys{align-self:center;color:var(--muted);font-size:12px;border:none}
.think{align-self:flex-start;max-width:84%;color:var(--muted);font-size:12px;font-style:italic;
 border-left:2px solid var(--accent2);padding:4px 10px;margin:-4px 0 0;white-space:pre-wrap;display:block}
.think .h{color:var(--accent2);font-style:normal;cursor:pointer;user-select:none}
.think .chev{display:inline-block;transition:transform .3s ease}
.think.show .chev{transform:rotate(90deg)}
#cform{display:flex;gap:10px;max-width:880px;margin:10px auto 0;width:100%;align-items:flex-end}
#cform>button{flex-shrink:0;height:46px;padding:0 24px}   /* Senden/Stop bleibt unten buendig, waechst nicht mit */
/* S11: unauffaelliges "+" links am Eingabefeld — Bild/Datei hochladen */
.plus{flex-shrink:0;width:46px;height:46px;align-self:flex-end;border-radius:10px;border:1px solid var(--line);background:var(--panel);
 color:var(--muted);font-size:22px;line-height:1;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;transition:.15s}
.plus:hover{border-color:var(--chat-accent);color:var(--chat-accent)}
/* Stop-Zustand: Senden wird rot, solange eine Antwort laeuft */
#sendbtn.stopping{background:var(--danger)!important;box-shadow:0 0 14px color-mix(in srgb,var(--danger) 45%,transparent)}
/* mehrzeiliges Eingabefeld: waechst mit dem Text (bis max), dann vertikal scrollbar — kein Seit-Scrollen mehr */
#cin{flex:1;padding:11px 12px;border-radius:10px;border:1px solid var(--line);background:var(--panel);color:var(--ink);
 outline:none;font:inherit;line-height:1.45;resize:none;overflow-y:auto;min-height:46px;max-height:200px;
 white-space:pre-wrap;overflow-wrap:break-word}
#cin:focus{border-color:var(--accent2)}
button{padding:0 16px;border:none;border-radius:8px;cursor:pointer;font-weight:600;font-family:inherit;
 background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
button.ghost{background:var(--panel);color:var(--ink);border:1px solid var(--line)}
/* files */
.cols{display:flex;gap:16px;flex:1;min-height:0;align-items:flex-start}
/* Kein Scrollfestival (Praxis-Fund): die DATEI-LISTE scrollt intern in eigener Spalte,
   der EDITOR klebt daneben im Blickfeld (sticky) — Datei unten anklicken, Text sofort sehen. */
.flist{width:250px;flex-shrink:0;display:flex;flex-direction:column;gap:6px;
  max-height:calc(100vh - 190px);overflow-y:auto;padding-right:4px}
.fedit{position:sticky;top:8px;max-height:calc(100vh - 190px)}
.fedit textarea{flex:1;min-height:calc(100vh - 280px)}
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
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px;max-width:880px}
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
.e .m{color:var(--muted);white-space:pre-wrap;flex:1;cursor:pointer}
.e .m.clamp{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.e.error{background:rgba(240,89,106,.09);border-left:3px solid var(--danger)}
.e.error .t{color:var(--danger)}
.e.action .t{color:var(--accent)}
.e.chat .t{color:#67e8c9}
.e.info .t{color:var(--muted)}
.pill.on{color:#fff;border-color:var(--accent);background:rgba(168,85,247,.14)}
.card:hover{border-color:rgba(139,92,246,.26)}
#side{background:var(--bg)}
.ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--danger)}
.look{display:flex;gap:10px;align-items:center;justify-content:center;padding:8px 12px;
 border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:12px}
.look label,.look a{cursor:pointer;color:var(--muted);text-decoration:none}
.look label:hover,.look a:hover{color:var(--accent)}
/* S7a: Theme-Umschalter als dezentes Popover in der Topbar (statt Dauer-Leiste in der Nav) */
#theme-wrap{position:relative}
#theme-btn{cursor:pointer;color:var(--muted);font-size:15px;user-select:none;line-height:1}
#theme-btn:hover{color:var(--accent)}
#theme-pop{display:none;position:absolute;top:26px;right:0;z-index:500;background:var(--panel);
 box-shadow:0 12px 34px rgba(0,0,0,.6)}
#theme-pop.open{display:flex}
#side a .ti{display:inline-block;width:18px;text-align:center;margin-right:2px;color:var(--accent)}
.direktive{max-width:560px;margin:0 0 16px;border:1px solid color-mix(in srgb,var(--accent) 22%,var(--line));
 border-radius:12px;padding:15px 16px;background:
  linear-gradient(180deg,color-mix(in srgb,var(--accent) 6%,var(--panel)),var(--panel));
 box-shadow:0 0 0 1px color-mix(in srgb,var(--accent) 8%,transparent),0 10px 30px rgba(0,0,0,.45)}
/* S11: Zentrale = Epicness, keine grossen Emojis — der Befehl-Header traegt Glow, kein Icon */
.direktive h3{margin:0 0 10px;color:var(--hud);text-transform:uppercase;letter-spacing:2.5px;font-size:12.5px;
 text-shadow:0 0 14px color-mix(in srgb,var(--glow) 45%,transparent)}
.home-cols{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;max-width:1400px}
.home-main{flex:3 1 520px;min-width:0;display:flex;flex-direction:column;gap:14px}
.home-side{flex:1 1 300px;min-width:280px;display:flex;flex-direction:column;gap:10px}
.home-main .direktive,.home-main .home-feed{max-width:none;margin:0;width:100%}
.home-side .card{max-width:none;margin:0;padding:11px 13px}
.home-side .card h3{font-size:12px;margin:0 0 6px}
.home-feed #feed-list{max-height:440px}
textarea.k{width:100%;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;
 padding:10px;font-family:inherit;font-size:13px;resize:vertical;outline:none;min-height:52px}
textarea.k:focus{border-color:var(--accent2)}
.muted{color:var(--muted)}
/* ===== Kira-Signature: UI-Font, Aura/Glow, Motion (additiv, ueberschreibt via Quellreihenfolge) ===== */
:root{--mono:ui-monospace,"Cascadia Code",Consolas,monospace}
body{font-family:var(--font,-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,"Helvetica Neue",Arial,sans-serif)}
.think,#farea,#evlog,#memlist,#feed-list,.e{font-family:var(--mono)}
/* S6.7: Scanline-/Karo-Overlay und Farb-Glows entfernt — der Nutzer will glattes Schwarz/Anthrazit. */
#side h1{animation:kiraflow 8s linear infinite,flickerin 1.3s ease both}  /* Verlauf fliesst + Boot-Flackern */
@keyframes kiraflow{to{background-position:260% 0}}
@keyframes flickerin{0%{opacity:0}10%{opacity:.6}13%{opacity:.2}22%{opacity:.95}27%{opacity:.4}33%,100%{opacity:1}}
#side a{transition:background .18s ease,border-color .18s ease,color .18s ease}
#side a.on{box-shadow:inset 3px 0 0 var(--accent),inset 0 0 22px color-mix(in srgb,var(--glow) 14%,transparent)}
button{transition:transform .12s ease,box-shadow .2s ease,filter .2s ease;box-shadow:0 0 14px color-mix(in srgb,var(--glow) 28%,transparent)}
button:hover{filter:brightness(1.12);transform:translateY(-1px);box-shadow:0 0 20px var(--glow)}
button:active{transform:translateY(0)}
button.ghost{box-shadow:none}
button.ghost:hover{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 0 12px color-mix(in srgb,var(--glow) 30%,transparent)}
button.ghost.on{border-color:var(--accent);color:#fff;background:rgba(168,85,247,.16);box-shadow:0 0 0 1px var(--accent),0 0 14px var(--glow)}
/* Chat-Modus-Feedback: Coding faerbt den Chat gruen/Terminal, Chat bleibt Neon-Violett */
/* ---- Chat/Coding-Werkbank: Modus-Farbe fix (Chat=Violett, Coding=Gruen), unabhaengig vom Theme ---- */
:root{--accent-chat:#b026ff;--coding-accent:#00e5ff;--work-accent:#39ff14}
#chat-main{--chat-accent:var(--accent-chat)}
#chat-main[data-mode="work"]{--chat-accent:var(--work-accent)}     /* Work = Gruen */
#chat-main[data-mode="coding"]{--chat-accent:var(--coding-accent)} /* Coding = Rainbow (Chrome: Cyan) */
/* Modus-Umschalter UNTEN-LINKS in der Werkzeugleiste — direkt ueber dem "+"/Eingabefeld.
   Segmented-Slider: der aktive Teil (.pill) gleitet weich rueber. */
#chat-tools #chat-mode-seg{flex:0 0 auto;width:330px}
#chat-mode-seg{--i:0;position:relative;display:flex;padding:4px;isolation:isolate;border:1px solid var(--line);
 border-radius:12px;background:var(--panel);font-family:inherit;font-size:13.5px}
#chat-mode-seg .pill{position:absolute;top:4px;bottom:4px;left:4px;width:calc((100% - 8px)/3);border-radius:9px;z-index:-1;
 background:color-mix(in srgb,var(--chat-accent) 20%,transparent);border:1px solid color-mix(in srgb,var(--chat-accent) 55%,transparent);
 box-shadow:0 0 18px color-mix(in srgb,var(--chat-accent) 30%,transparent);
 transform:translateX(calc(var(--i) * 100%));
 transition:transform .38s cubic-bezier(.22,.61,.36,1),background .3s,border-color .3s,box-shadow .3s}
#chat-mode-seg a{flex:1;display:flex;align-items:center;justify-content:center;gap:7px;padding:10px 0;border-radius:9px;
 color:var(--muted);font-weight:600;letter-spacing:.3px;cursor:pointer;transition:color .25s}
#chat-mode-seg a.on{color:#fff}
/* generierte SVG-Icons statt Emojis — bewusst gedaempftes Grau-Lila (bleibt subtil, auch aktiv) */
#chat-mode-seg a .mi{width:15px;height:15px;flex:none;color:#7d768f}
@media (prefers-reduced-motion:reduce){#chat-mode-seg .pill{transition:none}}
/* Eingabe/Senden faerben mit dem Modus */
#chat-main #cin{caret-color:var(--chat-accent)}
#chat-main #cin:focus{border-color:var(--chat-accent);box-shadow:0 0 0 1px var(--chat-accent),0 0 12px color-mix(in srgb,var(--chat-accent) 38%,transparent);outline:none}
#chat-main #cform>button:last-child{background:linear-gradient(135deg,var(--chat-accent),var(--accent2))}
#chat-main[data-mode="coding"] #cin{font-family:var(--mono)}
/* Modus-Farbe blutet in die Werkbank + den Verlauf durch (verstaerkter Kontrast) */
#chat-main .chip:hover{border-color:var(--chat-accent);background:color-mix(in srgb,var(--chat-accent) 10%,transparent)}
#chat-main .chip.tog.on{color:var(--chat-accent);border-color:var(--chat-accent)}
#chat-main .sess.on{border-left-color:var(--chat-accent)}
#chat-main .msg.bot .mbody .mdh{color:var(--chat-accent)}
#chat-tools #micbtn,#chat-tools #imgbtn{color:var(--chat-accent);background:none;display:inline-flex;align-items:center;line-height:1.4}
/* Modus-LED-Balken ganz oben am Chat: die Farben rotieren wie bei einer LED-Tastatur von
   links nach rechts durch (kein Puls/Flackern) — dicker & praesenter, ruhig getaktet.
   Chat = Lila-Fluss · Work = Gruen-Fluss · Coding = voller Regenbogen. */
#chat-main{position:relative}
#chat-main::before{content:"";position:absolute;top:0;left:0;right:0;height:5px;border-radius:0 0 5px 5px;z-index:3;
 background-size:200% 100%;
 background-image:linear-gradient(90deg,#7d2fff,#b026ff,#d16bff,#ff2d95,#b026ff,#7d2fff);
 box-shadow:0 0 12px var(--chat-accent),0 0 26px color-mix(in srgb,var(--chat-accent) 60%,transparent),
  0 0 44px color-mix(in srgb,var(--chat-accent) 34%,transparent);
 animation:ledflow 7s linear infinite;transition:box-shadow .35s}
#chat-main[data-mode="work"]::before{background-image:linear-gradient(90deg,#0aff9d,#39ff14,#9bff3c,#00e5a8,#39ff14,#0aff9d)}
#chat-main[data-mode="coding"]::before{background-image:linear-gradient(90deg,#ff004d,#ff8a00,#ffe600,#39ff14,#00e5ff,#b026ff,#ff004d);animation-duration:5.5s}
@keyframes ledflow{to{background-position:-200% 0}}
@media (prefers-reduced-motion:reduce){#chat-main::before{animation:none}}
/* Engine-Leiste: Modell als sichtbare Neon-Pille (färbt mit dem Modus mit) */
#chatbar{gap:10px}
select.engine-pill,button.engine-pill{background:var(--panel);color:var(--ink);border:1px solid var(--chat-accent);border-radius:999px;
 padding:6px 14px;font-size:12px;cursor:pointer;max-width:210px;
 box-shadow:0 0 10px color-mix(in srgb,var(--chat-accent) 22%,transparent);transition:box-shadow .18s ease,border-color .18s ease}
select.engine-pill:hover,select.engine-pill:focus,button.engine-pill:hover,button.engine-pill:focus{outline:none;border-color:var(--chat-accent);
 box-shadow:0 0 0 1px var(--chat-accent),0 0 14px color-mix(in srgb,var(--chat-accent) 42%,transparent)}
/* Me-Subtabs: zwei Panels nebeneinander (bricht auf schmalem Screen um) */
.me-grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;align-items:start}
/* Farbwähler im Optik-Popover */
#theme-pop .colrow{display:flex;gap:8px;align-items:center;margin-top:9px;padding-top:9px;border-top:1px solid var(--line);flex-wrap:wrap}
#theme-pop .colrow label{display:flex;flex-direction:column;align-items:center;gap:2px;font-size:9px;color:var(--muted);letter-spacing:.3px}
#theme-pop .colrow input[type=color]{width:26px;height:22px;border:1px solid var(--line);border-radius:6px;background:none;cursor:pointer;padding:0}
#theme-pop #col-reset{cursor:pointer;color:var(--muted);font-size:14px;margin-left:auto}
#theme-pop #col-reset:hover{color:var(--accent)}
#theme-pop .fontrow{border-top:none;margin-top:6px;padding-top:0}
#theme-pop #font-sel{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:6px;font-size:11px;padding:2px 5px;outline:none;cursor:pointer}
.card{transition:border-color .2s ease,transform .2s ease,box-shadow .2s ease}
.card:hover{transform:translateY(-1px);box-shadow:0 10px 30px rgba(0,0,0,.35)}
.pill{transition:border-color .15s ease,color .15s ease,background .15s ease}
.view.on{animation:viewin .32s ease both}
@keyframes viewin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.msg{animation:msgin .28s cubic-bezier(.2,.7,.2,1) both;border-radius:14px;box-shadow:0 2px 10px rgba(0,0,0,.22);line-height:1.5}
.me{background:linear-gradient(135deg,rgba(124,58,237,.26),rgba(109,40,217,.18));border-color:rgba(168,85,247,.38)}
.bot{background:rgba(20,16,30,.82);border-color:rgba(139,92,246,.14)}
@keyframes msgin{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.think{background:rgba(139,92,246,.05);border-left:2px solid var(--accent);border-radius:10px;padding:8px 12px;box-shadow:inset 0 0 0 1px rgba(139,92,246,.06)}
/* ---- Code-Modus-Trace: strukturierte Schritte + farbige Diffs (Claude-Code-Look) ---- */
/* Eingeklappt = Peek der ersten ~4 Zeilen mit Fade-Auslauf; ausgeklappt = voll. Smooth, kein Verschwinden. */
.think .c{white-space:normal;overflow:hidden;max-height:5.4em;transition:max-height .4s ease;
 -webkit-mask-image:linear-gradient(180deg,#000 62%,transparent);mask-image:linear-gradient(180deg,#000 62%,transparent)}
.think.show .c{max-height:9999px;-webkit-mask-image:none;mask-image:none}
@media (prefers-reduced-motion:reduce){.think .c{transition:none}}
.tthink{white-space:pre-wrap;color:var(--muted);font-style:italic;margin:2px 0 4px}
.trow{display:flex;align-items:baseline;gap:8px;margin:3px 0;font-style:normal;padding:2px 6px;
 border-radius:7px;background:rgba(255,255,255,.02)}
.trow .ti{flex:none;width:18px;text-align:center}
.trow .tl{color:var(--accent2);font-weight:600;flex:none}
.trow .tt{color:var(--fg);opacity:.82;word-break:break-all;font-size:11.5px}
.orow{margin:0 0 6px 26px}
.ostat{font-style:normal;font-size:11.5px;color:var(--muted)}
.ostat.ok{color:#7fd88a}
.ostat.err{color:#ff8f8f}
.tdiff{margin:5px 0 2px;padding:7px 10px;border-radius:8px;overflow-x:auto;font-size:11.5px;line-height:1.5;
 background:rgba(0,0,0,.28);border:1px solid rgba(139,92,246,.14);white-space:pre}
.tdiff .dl{display:block}
.tdiff .add{color:#7fd88a;background:rgba(63,185,80,.10)}
.tdiff .del{color:#ff8f8f;background:rgba(248,81,73,.10)}
.tdiff .hunk{color:var(--accent2);opacity:.9}
.tdiff .ctx{color:var(--muted)}
.thinking{align-self:flex-start;display:flex;align-items:center;gap:9px;margin:2px 0;padding:7px 14px;
 font-size:13.5px;font-weight:500;border-radius:12px;
 background:linear-gradient(90deg,transparent,rgba(139,92,246,.08),transparent)}
/* CSS-gezeichneter Ring-Spinner statt eines Glyphs (kein "Tofu"-Kaestchen, wenn ein Zeichen fehlt) */
.thinking .sh{width:13px;height:13px;flex:none;box-sizing:border-box;border-radius:50%;
 border:2px solid color-mix(in srgb,var(--accent) 26%,transparent);border-top-color:var(--accent);
 filter:drop-shadow(0 0 6px color-mix(in srgb,var(--accent) 55%,transparent));animation:spin .8s linear infinite}
/* Denk-Status im Neon-Rainbow-Fluss (wie Claude-Code "Cooking…") — die Farbe wandert durch den Text.
   Gilt fuer den Vor-Trace-Puls UND die Live-Ueberschrift des Denk-Traces (Thinking/Cooking/Clauding…). */
.tx.live{background:linear-gradient(90deg,#b026ff,#ff2d95,#ff8a00,#39ff14,#00e5ff,#b026ff);
 background-size:300% 100%;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;
 font-weight:600;animation:rainflow 3.2s linear infinite}
@keyframes rainflow{to{background-position:-300% 0}}
@media (prefers-reduced-motion:reduce){.tx.live{animation:none}.thinking .sh{animation:none}}
/* Vorlesen als sauberer Toggle-Chip (kein rohes weisses Kaestchen mehr) */
#chip-tts input{display:none}
/* dezenter Hinweis in der Trace-Ueberschrift */
.think .h .hint{opacity:.5;font-weight:400;font-size:11px}
@keyframes spin{to{transform:rotate(360deg)}}
/* ===== HUD-Kommandozentrale ===== */
/* --hud kommt jetzt pro Theme aus dem :root/data-theme oben (faerbt beim Wechsel mit) */
.hud-strip{display:flex;flex-wrap:nowrap;align-items:stretch;margin-bottom:14px;border:1px solid var(--line);
 border-radius:10px;overflow-x:auto;overflow-y:hidden;background:var(--panel);font-family:var(--mono)}
.hud-cell{padding:8px 14px;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:3px;min-width:118px}
.hud-cell:last-child{border-right:none}
.hud-cell .k{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted)}
.hud-cell .val{font-size:13px;color:var(--ink)}
.hud-cell.spacer{flex:1;min-width:0}
.mini-bar{height:5px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:5px;min-width:96px}
.mini-bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--ok),var(--accent))}  /* neon-gruen -> lila */
.mini-bar.warn>i{background:linear-gradient(90deg,var(--warn),var(--danger))}
.cmd-grid{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;max-width:1500px}
.cmd-main{flex:2 1 520px;min-width:0;display:flex;flex-direction:column;gap:14px}
.cmd-side{flex:1 1 320px;min-width:300px;display:flex;flex-direction:column;gap:14px}
.panel{position:relative;border:1px solid var(--line);border-radius:10px;background:var(--panel)}  /* S6.7: opak statt milchig */
.panel::before,.panel::after{content:"";position:absolute;width:9px;height:9px;border:1px solid var(--hud);opacity:.5}
.panel::before{top:-1px;left:-1px;border-right:none;border-bottom:none}
.panel::after{bottom:-1px;right:-1px;border-left:none;border-top:none}
.panel-h{display:flex;align-items:center;gap:8px;padding:9px 13px;border-bottom:1px solid var(--line);
 font-family:var(--mono);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--hud)}
.panel-h .sp{flex:1}
.panel-b{padding:10px 13px}
#ops-feed{max-height:52vh;overflow:auto;font-family:var(--mono);font-size:12px}
#ops-filter .ofc{font-weight:600;opacity:.75;font-size:10px;font-variant-numeric:tabular-nums}
#ops-filter a.on .ofc{opacity:1}
#ops-filter a[data-of=error] .ofc{color:var(--danger);opacity:.9}  /* Fehler faellt auf */
.op{display:flex;gap:10px;padding:5px 13px;border-bottom:1px solid rgba(255,255,255,.04);align-items:flex-start}
.op .opt{color:var(--muted);min-width:62px;font-variant-numeric:tabular-nums}
.op .opx{flex:1;color:var(--ink);word-break:break-word}
.op.error{background:rgba(240,89,106,.08)} .op.error .opx{color:var(--danger)}
.op.action .opx{color:var(--hud)} .op.chat .opx{color:var(--accent)} .op.info .opx{color:var(--muted)}
.op .od{width:6px;height:6px;border-radius:50%;margin-top:6px;background:var(--muted);flex-shrink:0}
.op.action .od{background:var(--hud)} .op.error .od{background:var(--danger)} .op.chat .od{background:var(--accent)}
/* Live-Ops-Transparenz: Detail (Werkzeug/Datei/Label) + Typ-Badge + aufklappbare Payload */
.op{cursor:pointer} .op:hover{background:rgba(255,255,255,.03)}
.op .opd{color:var(--muted);font-size:11px}
.op .opk{display:block;color:var(--muted);opacity:.55;font-size:9.5px;letter-spacing:.4px;margin-top:1px}
.oppay{margin:0;padding:7px 13px 9px 31px;font-size:10.5px;line-height:1.45;color:var(--muted);
 background:rgba(0,0,0,.28);border-bottom:1px solid rgba(255,255,255,.05);white-space:pre-wrap;word-break:break-word;max-height:220px;overflow:auto}
.ticker{overflow:hidden;white-space:nowrap;border-bottom:1px solid var(--line);background:rgba(0,0,0,.25)}
.ticker>span{display:inline-block;padding:7px 0;font-family:var(--mono);font-size:12px;color:var(--hud);animation:tick 140s linear infinite}
@keyframes tick{from{transform:translateX(100%)}to{transform:translateX(-100%)}}
.ticker:hover>span{animation-play-state:paused}  /* S9.1: viel langsamer (140s) + Hover pausiert */
.news-item{padding:8px 13px;border-bottom:1px solid rgba(255,255,255,.05);font-size:12px}
.news-item b{color:var(--ink)} .news-item small{color:var(--muted)}
.badge{display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;letter-spacing:.5px;border:1px solid var(--line);font-family:var(--mono)}
.badge.kira{color:var(--accent);border-color:var(--accent2)}
.badge.you{color:var(--hud);border-color:color-mix(in srgb,var(--hud) 40%,transparent)}
.badge.kind{color:var(--muted)}
.memrow{border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin-bottom:8px;background:var(--panel)}
.memrow .mh{display:flex;gap:7px;align-items:center;margin-bottom:5px;font-size:11px;color:var(--muted);flex-wrap:wrap}
.hist .old{color:var(--danger);text-decoration:line-through;opacity:.75}
.hist .new{color:var(--ok)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;font-family:var(--mono);font-size:11px}
/* S6.7-BUGFIX: Subtab-Leisten (Kira/Config) leben in einer Flex-Spalte (.view.on) — ohne
   flex-shrink:0 quetscht ein grosser Subview-Inhalt die Leiste auf 2px (Rand) zusammen ->
   'Gedaechtnis-Falle': man kommt nicht mehr aus dem Tab raus. */
#sys-tabs,#kira-tabs,#kira-groups,#settings-tabs,#me-tabs{flex-shrink:0;align-self:flex-start}
.seg a{padding:5px 10px;color:var(--muted);cursor:pointer;border-right:1px solid var(--line)}
.seg a:last-child{border-right:none}
.seg a.on{background:color-mix(in srgb,var(--hud) 14%,transparent);color:var(--hud)}
/* Feedback 09.07.: Befehl + Widgets teilen sich eine Reihe — keine tote Luecke mehr */
.dir-row{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;margin:0 0 16px;max-width:1500px}
.dir-row .direktive{flex:0 1 560px;margin:0}
.dir-row .wslot{flex:1 1 320px;min-width:280px}
/* EINE Zeile pro Listenpunkt (Digest/Lektionen) — voller Text im Tooltip, kein Scrollfenster */
.clamp1{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
/* Werkbank PR 8: Widget-Slots — leere Slots kollabieren, gefuellte werden ein Kachel-Raster */
.wslot{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.wslot:empty{display:none}
.wslot .panel{margin:0}
/* Werkbank PR 7: Freigaben-Badge am Me-Eintrag in der Sidebar */
.frei-badge{margin-left:6px;background:var(--warn);color:#000;border-radius:9px;font-size:10px;padding:0 6px;font-weight:700;line-height:16px;display:inline-block}
/* S11: Me- & Kira-Subtableiste komplett lila mit weisser Schrift; Aktiv = schwarz mit lilaner Schrift */
#me-tabs,#kira-groups{background:var(--accent);border-color:var(--accent)}
#me-tabs a,#kira-groups a{color:#fff;border-right-color:color-mix(in srgb,#fff 28%,transparent)}
#me-tabs a:hover,#kira-groups a:hover{background:color-mix(in srgb,#000 16%,var(--accent))}
#me-tabs a.on,#kira-groups a.on{background:var(--bg);color:var(--accent)}
/* 2-Ebenen-Navi: Gruppen (lila, oben) prominent · Sub-Tabs (unten) dezent-sekundaer */
#kira-groups{font-size:12px;margin-bottom:8px}
#kira-tabs{background:transparent;border-color:var(--line)}
#kira-tabs a{color:var(--muted);border-right-color:var(--line)}
#kira-tabs a:hover{background:color-mix(in srgb,var(--accent) 10%,transparent);color:var(--ink)}
#kira-tabs a.on{background:color-mix(in srgb,var(--accent) 16%,transparent);color:var(--accent)}
.thinking .tx{color:var(--hud)}
/* ===== NEON v2: Scrollbars + Panel-Glow + Theme-follow + Mission-Grid ===== */
/* S12: Textauswahl + Tastatur-Fokus folgen dem Theme (Mikro-Feinschliff) */
::selection{background:color-mix(in srgb,var(--accent) 40%,transparent);color:#fff}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
*{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--accent) 45%,#2a2440) transparent}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--accent) 34%,transparent);border-radius:8px;border:2px solid transparent;background-clip:padding-box}
::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--glow) 70%,transparent);box-shadow:0 0 8px var(--glow)}
::-webkit-scrollbar-corner{background:transparent}
/* vorher hartkodierte Tuerkis-Werte -> folgen jetzt dem Theme */
.badge.you{border-color:color-mix(in srgb,var(--hud) 50%,transparent)}
.seg a.on{background:color-mix(in srgb,var(--hud) 16%,transparent)}
/* Panels: staerkerer Neon-Rahmen + leuchtende Ecken + Header-Glow */
.panel{border-color:color-mix(in srgb,var(--hud) 22%,var(--line));box-shadow:0 0 0 1px color-mix(in srgb,var(--hud) 8%,transparent),0 10px 34px rgba(0,0,0,.55)}
.panel::before,.panel::after{width:12px;height:12px;border-color:var(--hud);opacity:.9;filter:drop-shadow(0 0 4px var(--hud))}
.panel-h{color:var(--hud);text-shadow:0 0 10px color-mix(in srgb,var(--hud) 60%,transparent);border-bottom-color:color-mix(in srgb,var(--hud) 20%,var(--line))}
.card{border-color:color-mix(in srgb,var(--accent) 16%,var(--line))}
.card h3{color:var(--accent);text-shadow:0 0 10px color-mix(in srgb,var(--glow) 45%,transparent)}
h2{text-shadow:0 0 14px color-mix(in srgb,var(--glow) 45%,transparent)}
.ticker>span{color:var(--hud);text-shadow:0 0 8px color-mix(in srgb,var(--hud) 55%,transparent)}
.live{box-shadow:0 0 9px var(--ok)}
.pill.ok,.pill.on{box-shadow:0 0 10px color-mix(in srgb,var(--glow) 30%,transparent)}
/* Mission: ausgewogenes 2-Spalten-Grid (kein Stranden), gleiche Hoehen */
.mgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:stretch;max-width:1560px;margin-bottom:14px}
.mgrid>.panel{min-height:210px;display:flex;flex-direction:column}
.mgrid>.panel>.panel-b,.mgrid>.panel>[class*="-list"],.mgrid>.panel>#todo-board,.mgrid>.panel>#obj-list{flex:1}
@media(max-width:1000px){.mgrid{grid-template-columns:1fr}}
.emptybox{display:flex;align-items:center;justify-content:center;min-height:150px;color:var(--muted);
 border:1px dashed color-mix(in srgb,var(--hud) 30%,var(--line));border-radius:10px;font-family:var(--mono);text-align:center;padding:16px}
@media (prefers-reduced-motion: reduce){
 *{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important}
 body::after{animation:none}
}
.subview{display:none}.subview.on{display:block}
/* ===== S5.3c · Motion-Politur (Huly-Anspruch: Physik vor Quantitaet) ===== */
.view.on .panel{animation:panein .42s cubic-bezier(.16,.84,.28,1) backwards}
.view.on .panel:nth-of-type(2){animation-delay:.05s}
.view.on .panel:nth-of-type(3){animation-delay:.1s}
.view.on .mgrid .panel:nth-child(2){animation-delay:.07s}
@keyframes panein{from{opacity:0;transform:translateY(10px) scale(.985)}to{opacity:1;transform:none}}
.memrow,.op{animation:rowin .26s ease backwards}
@keyframes rowin{from{opacity:0;transform:translateX(-4px)}to{opacity:1;transform:none}}
.memrow{transition:border-color .18s,transform .18s}
.memrow:hover{border-color:color-mix(in srgb,var(--hud) 35%,var(--line));transform:translateX(2px)}
.seg a{transition:background .16s,color .16s}
#side a{transition:color .16s,background .16s,padding-left .16s}
#side a:hover{padding-left:14px}
#log{scroll-behavior:smooth}
.panel-h{transition:color .18s}
@media (prefers-reduced-motion: reduce){
 .view.on .panel,.memrow,.op{animation:none}
 .memrow:hover{transform:none}
 #side a:hover{padding-left:inherit}
 #log{scroll-behavior:auto}
}
/* ===== S6.4 · Toasts, WS-Statuspunkt, Burger + mobiles Seitenmenue ===== */
#toasts{position:fixed;right:16px;bottom:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:min(360px,90vw)}
.toast{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--hud);border-radius:8px;
 padding:9px 13px;font-size:12.5px;color:var(--ink);box-shadow:0 6px 24px rgba(0,0,0,.45);animation:toastin .22s ease}
.toast.err{border-left-color:var(--danger)} .toast.ok{border-left-color:var(--ok)}
.toast.out{opacity:0;transform:translateY(6px);transition:opacity .38s,transform .38s}
@keyframes toastin{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
#ws-dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:var(--muted)}
#ws-dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
#ws-dot.off{background:var(--danger);box-shadow:0 0 8px var(--danger)}
#burger{display:none;cursor:pointer;font-size:18px;color:var(--ink);user-select:none;line-height:1}
@media(max-width:900px){
 #burger{display:inline-block}
 #side{position:fixed;z-index:1000;top:0;bottom:0;left:0;transform:translateX(-100%);transition:transform .24s ease}
 body.side-open #side{transform:none;box-shadow:0 0 40px rgba(0,0,0,.6)}
 .cmd-grid{grid-template-columns:1fr!important}
 .view{padding:12px}
}
@media (prefers-reduced-motion: reduce){#side{transition:none}.toast{animation:none}#side h1{animation:none;background-position:40% 0}}
/* ===== S6.6b · Chat: Session-Panel, Markdown, Nachrichten-Meta, Chips ===== */
#chat-wrap{flex:1;display:flex;gap:0;min-height:0}  /* kein flex-gap -> das Panel bringt seinen Abstand selbst mit (animierbar) */
#chat-main{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0}
/* Gespraeche gleiten SANFT rein statt hart zu erscheinen: wir animieren Breite+Rand+Opacity
   (order:2 -> rechts). Zu = width:0, transparenter Rand, kein Abstand -> kein Fussabdruck.
   Kein display:none noetig -> die Breiten-Transition kann sauber laufen (auf und zu). */
#sess-panel{width:0;margin-left:0;flex-shrink:0;order:2;border:1px solid transparent;border-radius:12px;
 background:var(--panel);display:flex;flex-direction:column;overflow:hidden;opacity:0;
 transition:width .42s cubic-bezier(.22,.61,.36,1),margin-left .42s cubic-bezier(.22,.61,.36,1),
  opacity .34s ease,border-color .42s ease}
#sess-panel.open{width:250px;margin-left:14px;opacity:1;border-color:var(--line)}  /* Hover oeffnet, Klick pinnt (JS) */
#sess-toggle.pinned{border-color:var(--accent);color:var(--accent);background:rgba(168,85,247,.12)}
@media(prefers-reduced-motion:reduce){#sess-panel{transition:none}}
#sess-panel .sp-f{padding:7px 12px;border-top:1px solid var(--line);text-align:center}
.sday{padding:7px 12px 3px;font-size:10px;letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;
 border-bottom:1px solid var(--line);background:var(--panel2)}
.sess .sa{color:var(--muted);visibility:hidden;padding:0 2px}
.sess:hover .sa{visibility:visible}
.sess .sa:hover{color:var(--hud)}
.sess.arch{opacity:.55}
#sess-panel .sp-h{display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid var(--line)}
#sess-items{flex:1;overflow:auto}
.sess{display:flex;align-items:center;gap:7px;padding:8px 10px;cursor:pointer;border-bottom:1px solid var(--line);font-size:12.5px}
.sess:hover{background:rgba(168,85,247,.08)}
.sess.on{background:rgba(168,85,247,.14);border-left:3px solid var(--accent);padding-left:7px}
.sess .st{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sess .sd{color:var(--muted);font-size:10.5px;flex-shrink:0}
.sess .sx{color:var(--muted);visibility:hidden;padding:0 2px}
.sess:hover .sx{visibility:visible}
.sess .sx:hover{color:var(--danger)}
.msg .mbody{min-width:0}
.msg.bot .mbody{white-space:normal;line-height:1.55}
.msg.bot .mbody ul,.msg.bot .mbody ol{margin:6px 0;padding-left:20px}
.msg.bot .mbody .mdh{display:block;margin:8px 0 2px;color:var(--accent)}
.msg.bot .mbody .mdh.mdh1{font-size:15px;letter-spacing:.3px}
.msg.bot .mbody .mdh.mdh2{font-size:13.5px}
.msg .mbody code{background:rgba(124,58,237,.16);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12.5px}
.msg .mbody pre.mdc{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px 12px;
 overflow:auto;margin:8px 0;white-space:pre}
.msg .mbody pre.mdc code{background:none;border:none;padding:0}
.msg .mbody a{color:var(--hud)}
/* S12: Markdown 2.0 — Tabellen, Zitate, Trennlinien, Code-Block-Kopf (Sprache + Kopieren) */
.msg .mbody table.mdt{border-collapse:collapse;margin:8px 0;font-size:12.5px;display:block;max-width:100%;overflow-x:auto}
.msg .mbody table.mdt th,.msg .mbody table.mdt td{border:1px solid var(--line);padding:4px 10px;text-align:left}
.msg .mbody table.mdt th{background:rgba(124,58,237,.14);color:var(--hud);font-weight:600}
.msg .mbody table.mdt tr:nth-child(even) td{background:rgba(124,58,237,.05)}
.msg .mbody blockquote.mdq{margin:6px 0;padding:4px 12px;border-left:3px solid var(--accent2);
 color:var(--muted);background:rgba(124,58,237,.07);border-radius:0 8px 8px 0}
.msg .mbody hr.mdhr{border:none;border-top:1px solid var(--line);margin:10px 0}
.mdcw{position:relative;margin:8px 0}
.mdcw pre.mdc{margin:0}
.mdcw .cblang{position:absolute;top:6px;right:32px;font-size:10px;color:var(--muted);text-transform:lowercase;user-select:none}
.mdcw .cbcopy{position:absolute;top:4px;right:10px;cursor:pointer;color:var(--muted);visibility:hidden}
.msg:hover .mdcw .cbcopy{visibility:visible}
.mdcw .cbcopy:hover{color:var(--accent)}
.mmeta{display:flex;gap:8px;justify-content:flex-end;align-items:center;margin-top:6px;font-size:10.5px;color:var(--muted)}
.mmeta .mcopy{cursor:pointer;visibility:hidden}
.msg:hover .mmeta .mcopy{visibility:visible}
.mmeta .mcopy:hover{color:var(--accent)}
#chips{display:flex;gap:8px;max-width:880px;margin:0 auto 6px;width:100%;flex-wrap:wrap}
/* S9.2: Werkzeug-Leiste unter dem Verlauf */
#chat-tools{display:flex;gap:8px;align-items:center;max-width:880px;margin:0 auto 6px;width:100%;flex-wrap:wrap}
#chat-tools select{max-width:190px;padding:4px 8px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font-size:12px;outline:none}
/* S10: die vier Werkzeuge (Reasoning/Vorlesen/Memo/Anhang) in einer eigenen, dezent gerahmten Box */
#chat-tools .toolbox{display:inline-flex;align-items:center;gap:7px;padding:3px 8px;border:1px solid var(--line);
 border-radius:14px;background:color-mix(in srgb,var(--panel) 70%,transparent)}
#chat-tools .toolbox .chip{border-color:transparent;background:none}
#chat-tools .toolbox .chip:hover{border-color:var(--chat-accent);background:color-mix(in srgb,var(--chat-accent) 10%,transparent)}
/* S11: Befehls-Palette (Hilfebefehlleiste) — alle echten Befehle auf einen Klick */
.cmd-pop{position:absolute;bottom:calc(100% + 6px);left:0;z-index:40;min-width:308px;max-width:360px;
 background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:6px;
 box-shadow:0 12px 34px rgba(0,0,0,.55)}
.cmd-pop .cmd-grp{font-size:10px;letter-spacing:1px;color:var(--muted);text-transform:uppercase;padding:6px 8px 2px}
.cmd-pop .cmd-row{display:flex;gap:9px;align-items:baseline;padding:6px 8px;border-radius:7px;cursor:pointer}
.cmd-pop .cmd-row:hover{background:color-mix(in srgb,var(--chat-accent) 14%,transparent)}
.cmd-pop .cmd-k{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--chat-accent);font-size:12px;white-space:nowrap}
.cmd-pop .cmd-d{color:var(--muted);font-size:11.5px}
/* S11: Modell-Auswahl-Popover (alle Modelle, rechtsbuendig ueber dem Senden-Knopf) */
.model-pop{right:0;left:auto;min-width:340px;max-width:420px}
.model-pop input.mq{width:100%;box-sizing:border-box;padding:7px 9px;margin-bottom:6px;border:1px solid var(--line);
 border-radius:8px;background:var(--panel2);color:var(--ink);font-size:12px;outline:none}
.model-pop .mrows{max-height:320px;overflow:auto}
.model-pop .cmd-grp{position:sticky;top:0;background:var(--panel)}
.model-pop .rbadge{font-size:10px;white-space:nowrap}
/* Reasoning-Popover: schmal, einheitlich mit Commands/Modell */
.reason-pop{min-width:150px}
.reason-pop .cmd-row{justify-content:flex-start}
.chip{cursor:pointer;border:1px solid var(--line);border-radius:14px;padding:3px 11px;font-size:11.5px;color:var(--hud);white-space:nowrap}
.chip:hover{border-color:var(--accent);background:rgba(168,85,247,.10)}
.chip.tog{display:inline-flex;align-items:center;gap:5px;color:var(--muted)}
.chip.tog input{margin:0}
.chip.tog.on{color:var(--accent);border-color:var(--accent)}
@media(max-width:900px){#sess-panel.open{display:none}}
/* ===== S6.6d · Kira-Avatar: Hero in der Zentrale + Mini-Avatar im Chat ===== */
#hero{display:flex;align-items:center;gap:13px;margin:0 0 10px}
#hero-av{width:50px;height:50px;border-radius:50%;object-fit:cover;border:2px solid var(--line);
 box-shadow:0 0 0 2px rgba(0,0,0,.35);background:var(--panel);flex:none}
#hero-av.aura{border-color:var(--accent);animation:aurapulse 3.2s ease-in-out infinite}
@keyframes aurapulse{0%,100%{box-shadow:0 0 10px var(--glow)}50%{box-shadow:0 0 26px var(--glow)}}
#hero-name{font-size:21px;letter-spacing:5px;color:#fff;text-shadow:0 0 12px rgba(139,92,246,.40)}
#hero-status{font-size:12px;margin-top:2px}
.msg.bot.withav{position:relative;margin-left:36px}
.msg.bot.withav .mav{position:absolute;left:-36px;top:2px;width:27px;height:27px;border-radius:50%;
 object-fit:cover;border:1px solid var(--line)}
@media (prefers-reduced-motion: reduce){#hero-av.aura{animation:none;box-shadow:0 0 14px var(--glow)}}
/* ===== S6.7b · Zentrale als FESTER Kommandostand (kein Seiten-Scroll, Panels scrollen innen) ===== */
@media(min-width:1050px){
 #v-home.on{overflow:hidden}
 #v-home .cmd-grid{flex:1;min-height:0;align-items:stretch;flex-wrap:nowrap;max-width:none}
 #v-home .cmd-main{min-height:0}
 #v-home .cmd-main .panel{flex:1;display:flex;flex-direction:column;min-height:0;margin:0}
 #v-home #ops-feed{flex:1;max-height:none;overflow:auto}
 #v-home .cmd-side{min-height:0;overflow:auto;padding-right:2px}
 /* KEIN innerer News-Scroll mehr: die Seitenspalte scrollt als EINES (Scroll-Falle weg). */
}
/* ===== S9.3/S9.5 · Kein-Scroll-Disziplin: Seite scrollt nicht, Panels scrollen innen ===== */
/* Basis (schmal, gestapelt) MUSS vor der Media-Query stehen — sonst ueberstimmt die
   spaetere 1fr-Regel bei gleicher Spezifitaet die 3-Spalten in der @media (Quell-Reihenfolge). */
.me-grid{display:grid;grid-template-columns:1fr;gap:14px}
/* Auf-einen-Blick-Kennzahlen in der Projekt-Uebersicht (Beispiel-Projekt & Co.) */
@media(min-width:1050px){
 /* Me: 3 App-Style-Spalten, jede stapelt schlanke Panels mit internem Scroll — kein Seiten-Scroll */
 #v-me.on{overflow:hidden}
 .me-grid{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
 .me-col{min-height:0;display:flex;flex-direction:column;gap:14px}
 .me-col>.panel{display:flex;flex-direction:column;min-height:0;margin:0}
 .me-col>.panel.me-grow{flex:1}
 .me-scroll{overflow:auto}
 /* Kira: Subtab-Leiste fest, aktiver Unterreiter scrollt intern (kein Seiten-Scroll) */
 #v-kira.on{overflow:hidden}
 #v-kira .subview.on{flex:1;min-height:0;overflow:auto;padding-right:2px}
 /* Einstellungen genauso — sonst quetscht ein grosser Subview (Modelle/Benchmark)
    die Leiste zusammen und man kommt nicht mehr zurueck (Praxis-Fund 09.07.) */
 #v-settings.on{overflow:hidden}
 #v-settings .subview.on{flex:1;min-height:0;overflow:auto;padding-right:2px}
}

/* ===== Redesign-Umbau 1 (der Nutzer): ruhiger + Live-Ops schmaler ===== */
/* Neon-Glow zuruecknehmen — sachlicher, weniger HUD-Effekt. */
.panel-h{text-shadow:none}
.panel::before,.panel::after{opacity:.32;filter:none}
.card h3{text-shadow:none}
.ticker>span{text-shadow:none}
h2{text-shadow:none}
button{box-shadow:none}
button:hover{box-shadow:none;transform:none;filter:brightness(1.08)}
button.ghost:hover{box-shadow:0 0 0 1px var(--accent);filter:none}
.pill.ok,.pill.on{box-shadow:none}
/* Live-Ops nicht mehr vollbreit — moderat begrenzt, Rest bekommt Luft. */
@media(min-width:1050px){
 #v-home .cmd-main{max-width:760px;flex:0 1 760px}
 #v-home .cmd-side{flex:1 1 340px}
}
/* Inline-Rename: editierbare Beschriftungen erkennbar machen. */
.panel-h[data-lblkey],.card h3[data-lblkey]{cursor:text}
.panel-h[data-lblkey]:hover,.card h3[data-lblkey]:hover{color:var(--accent2)}

/* ===== Kommandobruecke (UI-Umbau): Rail + Chip-Kopf + Fokus-Zeile + Chat-3-Spalten =====
   Bewusst als Override-Block am Ende — die alte Schale bleibt oben unangetastet,
   hier gewinnt die Kaskade. */
/* Rail: schmale Icon-Leiste, Label unterm Icon */
#side{width:76px;padding-top:6px}
#side a{display:flex;flex-direction:column;align-items:center;gap:3px;padding:10px 4px;margin:2px 6px;
        border-radius:11px;border-left:none;font-size:10px;letter-spacing:.04em;text-align:center;
        white-space:nowrap;overflow:hidden}
#side a .ti{width:auto;margin:0;font-size:17px}
#side a:hover{padding-left:4px}
#side a.on{box-shadow:inset 0 0 0 1px var(--accent),inset 0 0 18px color-mix(in srgb,var(--glow) 12%,transparent);
           background:rgba(139,92,246,.14)}
#side .frei-badge{position:absolute;transform:translate(16px,-26px)}
#side a{position:relative}
#side .kill{font-size:9px;text-align:center;padding:6px 2px}
/* Wortmarke wohnt jetzt im Kopf — gleicher Neon-Verlauf, kompakter */
#bar #brand{margin:0 8px 0 0;padding:0;line-height:1}
#bar #brand img{display:none}
#bar #brand .txt{display:block;font-family:'Audiowide',ui-sans-serif,system-ui,sans-serif;font-size:19px;
 letter-spacing:2px;padding:0;line-height:1;
 background:linear-gradient(100deg,#e9d5ff,#c084fc,#b026ff,#d946ef,#9333ea,#c084fc,#e9d5ff);
 background-size:260% 100%;-webkit-background-clip:text;background-clip:text;
 -webkit-text-fill-color:transparent;color:transparent;
 filter:drop-shadow(0 0 3px rgba(176,38,255,.7)) drop-shadow(0 0 12px rgba(176,38,255,.4));
 animation:kiraflow 8s linear infinite}
@media (prefers-reduced-motion: reduce){#bar #brand .txt{animation:none}}
/* Status-Chips: die Zahlen im Kopf */
.chip.st{display:inline-flex;gap:6px;align-items:center;padding:4px 11px;border-radius:999px;
         border:1px solid var(--line);background:var(--panel);font-size:12px;color:var(--muted);
         white-space:nowrap}
.chip.st b{color:var(--ink);font-weight:600}
.chip.st .dot{width:7px;height:7px;border-radius:50%;background:var(--muted)}
.chip.st .dot.ok{background:var(--ok);box-shadow:0 0 6px var(--ok)}
.chip.st.warnc{border-color:color-mix(in srgb,var(--warn) 50%,var(--line))}
.chip.st.warnc b{color:var(--warn)}
@media(max-width:1100px){#chip-termin,#chip-motor{display:none!important}}
/* Fokus-Zeile: der Tages-Hebel */
#fokus-line{display:flex;align-items:center;gap:10px;padding:5px 18px;font-size:12.5px;color:var(--muted);
            border-bottom:1px solid var(--line);
            background:linear-gradient(90deg,rgba(139,92,246,.12),rgba(139,92,246,.04) 55%,transparent)}
#fokus-line .fk{font-size:10.5px;letter-spacing:.16em;color:var(--accent);font-weight:700}
#fokus-line b{color:var(--ink);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#fokus-line #fokus-edit{margin-left:auto;cursor:pointer;color:var(--muted);font-size:11.5px;white-space:nowrap}
#fokus-line #fokus-edit:hover{color:var(--accent)}
/* Chat = 3 Spalten: Sessions fest links, Gespraech, Dein Tag rechts */
#sess-panel{order:0;width:236px;margin-left:0;margin-right:14px;opacity:1;border-color:var(--line)}
#sess-toggle{display:none}
#chat-tag{width:296px;flex-shrink:0;margin-left:14px;display:flex;flex-direction:column;gap:12px;
          overflow-y:auto;min-height:0}
#chat-tag .panel{margin:0}
#chat-tag .panel-b{padding:9px 13px 12px;font-size:13px}
#chat-tag .mehr{cursor:pointer;color:var(--muted);font-size:11px;letter-spacing:0;text-transform:none}
#chat-tag .mehr:hover{color:var(--accent)}
#chat-tag .ct-row{display:flex;gap:9px;padding:4px 0;align-items:baseline}
#chat-tag .ct-zeit{color:var(--accent);font-weight:600;font-size:12px;flex:none;min-width:42px}
#chat-tag .radar{margin-top:7px;padding:7px 10px;border-radius:8px;background:rgba(139,92,246,.14);
                 border:1px solid rgba(139,92,246,.4);font-size:12.5px}
@media(max-width:1250px){#chat-tag{display:none}}
@media(max-width:1000px){#sess-panel{display:none}#sess-toggle{display:inline-block}}
/* Freigabe-Karten im Gespraech */
#chat-frei:empty{display:none}
.frei-karte{border:1px solid rgba(139,92,246,.4);border-radius:11px;background:rgba(139,92,246,.12);
            padding:11px 13px;margin:0 0 10px;font-size:13px}
.frei-karte .fkopf{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);
                   font-weight:700;margin-bottom:5px}
.frei-karte .fwas{color:var(--ink);margin-bottom:9px}
.frei-karte .fwas small{display:block;color:var(--muted);margin-top:2px}
.frei-karte .fbtn{display:flex;gap:8px}
.frei-karte .fgo{padding:5px 15px;border-radius:8px;background:var(--accent);color:#fff;font-weight:600;font-size:12.5px;border:0;cursor:pointer}
.frei-karte .fgo:hover{filter:brightness(1.12)}
.frei-karte .fno{padding:5px 13px;border-radius:8px;border:1px solid var(--line);background:none;color:var(--muted);font-size:12.5px;cursor:pointer}
.frei-karte .fno:hover{border-color:var(--danger);color:var(--danger)}
/* Begruessungs-Briefing (leerer Chat) */
#brief-bubble .karte-mini{border:1px solid var(--line);border-radius:10px;background:var(--panel);
                          padding:9px 12px;margin:7px 0;font-size:13px}
#brief-bubble .kk{display:flex;justify-content:space-between;gap:10px;padding:2px 0;color:var(--muted)}
#brief-bubble .kk b{color:var(--ink)}
/* Strg+K Palette */
#pal-wrap{position:fixed;inset:0;background:rgba(5,4,10,.6);backdrop-filter:blur(3px);z-index:2000;
          display:flex;align-items:flex-start;justify-content:center;padding-top:14vh}
#pal{width:min(560px,92vw);background:var(--panel);border:1px solid var(--accent);border-radius:13px;
     box-shadow:0 18px 60px rgba(0,0,0,.55),0 0 30px rgba(139,92,246,.25);overflow:hidden}
#pal-q{width:100%;padding:13px 16px;background:none;border:0;outline:none;color:var(--ink);font-size:15px;
       border-bottom:1px solid var(--line)}
#pal-list{max-height:46vh;overflow-y:auto;padding:6px}
.pal-row{display:flex;gap:10px;align-items:center;padding:8px 11px;border-radius:8px;cursor:pointer;
         font-size:13.5px;color:var(--ink)}
.pal-row .pk{font-size:10px;letter-spacing:.08em;color:var(--muted);text-transform:uppercase;min-width:64px}
.pal-row:hover,.pal-row.on{background:rgba(139,92,246,.16)}
</style>"""

# Wordmark-Schrift (Audiowide, subsettet, base64) direkt in den <style> injizieren — laedt
# offline, kein CDN. Nur der Titel oben links (#side h1) nutzt sie; der Body bleibt System-Font.
_FONT_FACE = ("@font-face{font-family:'Audiowide';font-display:swap;"
              f"src:url(data:font/woff2;base64,{AUDIOWIDE_WOFF2_B64}) format('woff2');}}\n")
HEAD_AND_CSS = HEAD_AND_CSS.replace("<style>\n", "<style>\n" + _FONT_FACE, 1)
