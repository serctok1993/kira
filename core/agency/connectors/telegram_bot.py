"""Telegram-Connector: Kiras Draht zu Sergen (Text + Sprachmemo), 24/7 erreichbar.

- Long-Polling (kein oeffentlicher Webhook noetig) ueber die Telegram-Bot-API.
- Sprachmemos werden lokal transkribiert (siehe transcribe.py).
- Allowlist: reagiert nur auf die konfigurierte Chat-ID (Sicherheits-Gate).
- Eigene Session pro Chat -> der Telegram-Verlauf fliesst ins selbe Gedaechtnis.
- Respektiert den Kill-Switch.

Start:  uv run python -m core.agency.connectors.telegram_bot
Vorher: TELEGRAM_BOT_TOKEN in .env setzen (Bot via @BotFather anlegen).
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque

import httpx

from core.config import CONFIG, DATA_DIR
from core.kernel import events
from core.kernel.phrases import next_phrase
from core.kernel.scheduler import kill_switch_active, kill_switch_path
from core.mind.agent import Agent

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"

_agents: dict[int, Agent] = {}

# Dedizierter Kurz-Timeout-Client fuer ALLE ausgehenden Steuer-Nachrichten
# (send/edit/delete/typing). Strikt getrennt vom Long-Polling-Client (getUpdates,
# 75 s) -> keine Pool-Konkurrenz, keine verhakte Zustellung, jeder Call hart begrenzt.
# Das war die Wurzel des 20-Min-Wedge: Dauer-Edits der Live-Animation kollidierten
# mit dem laufenden 60-s-getUpdates auf demselben Verbindungspool.
_ctrl_client: httpx.Client | None = None
_ctrl_lock = threading.Lock()


def _ctrl() -> httpx.Client:
    global _ctrl_client
    c = _ctrl_client
    if c is None:
        with _ctrl_lock:
            if _ctrl_client is None:
                _ctrl_client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
            c = _ctrl_client
    return c


def _cfg() -> dict:
    return CONFIG.get("channels", {}).get("telegram", {})


def _agent_for(chat_id: int) -> Agent:
    if chat_id not in _agents:
        _agents[chat_id] = Agent(session_id=f"telegram-{chat_id}")
    return _agents[chat_id]


def _tg_html(text: str) -> str:
    """Leichtes Markdown -> Telegram-HTML (fett/Code), Rest wird escaped (handy-tauglich)."""
    import html as _h

    t = _h.escape(text or "", quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.DOTALL)
    t = re.sub(r"(?<![\w`])`([^`\n]+?)`(?![\w`])", r"<code>\1</code>", t)
    return t


def _send(client: httpx.Client, chat_id: int, text: str, html: bool = True) -> None:
    # Telegram-Limit ~4096 Zeichen -> stueckeln; HTML-Format mit Plain-Fallback.
    client = _ctrl()  # Steuer-Plane immer ueber den dedizierten Kurz-Timeout-Client
    text = text or "…"
    for i in range(0, len(text), 3800):
        chunk = text[i : i + 3800]
        payload = {"chat_id": chat_id, "text": _tg_html(chunk) if html else chunk}
        if html:
            payload["parse_mode"] = "HTML"
        try:
            j = client.post(f"{API}/sendMessage", json=payload).json()
            if not j.get("ok") and j.get("error_code") == 429:  # Rate-Limit -> kurz warten + 1x erneut
                time.sleep(min(6, ((j.get("parameters") or {}).get("retry_after") or 2)))
                j = client.post(f"{API}/sendMessage", json=payload).json()
            if not j.get("ok") and html:  # HTML-Parsing gescheitert -> als Plain nachsenden
                client.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": chunk})
        except Exception:
            pass


def _typing(client: httpx.Client, chat_id: int) -> None:
    try:
        _ctrl().post(f"{API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass


def _transcribe_voice(client: httpx.Client, msg: dict) -> str | None:
    file_id = msg["voice"]["file_id"]
    meta = client.get(f"{API}/getFile", params={"file_id": file_id}).json()
    file_path = meta["result"]["file_path"]
    data = client.get(f"{FILE_API}/{file_path}").content
    voice_dir = DATA_DIR / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    local = voice_dir / f"{file_id}.oga"
    local.write_bytes(data)
    try:
        from core.agency.connectors.transcribe import transcribe

        return transcribe(str(local))
    except ImportError:
        events.emit("telegram_voice_error", {"reason": "faster-whisper fehlt (uv sync)"})
        return None


def _handle_photo(client: httpx.Client, chat_id: int, msg: dict) -> None:
    _typing(client, chat_id)
    try:
        import base64

        file_id = msg["photo"][-1]["file_id"]  # groesste Aufloesung
        meta = client.get(f"{API}/getFile", params={"file_id": file_id}).json()
        data = client.get(f"{FILE_API}/{meta['result']['file_path']}").content
        dataurl = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        from core.agency.vision import describe

        answer = _clean(describe(dataurl, msg.get("caption", "") or ""))
        events.emit("telegram_photo", {"chat_id": chat_id, "caption": msg.get("caption", "")})
    except Exception as e:  # noqa: BLE001
        answer = f"Konnte das Bild nicht analysieren: {e}"
    _send(client, chat_id, answer)


def _handle(client: httpx.Client, update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    allowed = _cfg().get("allowed_chat_id")

    # Sicherheits-Gate
    if allowed is None:
        _send(client, chat_id,
              f"Hallo. Deine Chat-ID ist {chat_id}. Trage sie in config.yaml unter "
              f"channels.telegram.allowed_chat_id ein, dann antworte ich dir.")
        events.emit("telegram_unauthorized", {"chat_id": chat_id})
        return
    if str(chat_id) != str(allowed):
        events.emit("telegram_blocked", {"chat_id": chat_id})
        return

    # Foto -> Kira "sieht" es (Vision)
    if "photo" in msg and _cfg().get("vision", True):
        _handle_photo(client, chat_id, msg)
        return

    # Dokument -> Wissens-Archiv (S5: der 'fertige Schreibtisch')
    if "document" in msg:
        _handle_document(client, chat_id, msg)
        return

    text = msg.get("text")
    voice_text = None
    if not text and "voice" in msg and _cfg().get("voice", True):
        _typing(client, chat_id)
        text = _transcribe_voice(client, msg)
        if not text:
            _send(client, chat_id, "Konnte das Memo nicht verstehen (Whisper installiert? 'uv sync').")
            return
        voice_text = text  # nur live im Arbeits-Trace zeigen, kein separates "Verstanden"
    if not text:
        return

    if text.startswith("/"):
        _handle_command(client, chat_id, text)
        return

    # 'merke:'-Fast-Path: lange Texte deterministisch ins Archiv (kein LLM noetig)
    if text.lower().startswith("merke:") and len(text) > 400:
        try:
            from core.mind import knowledge

            body_text = text.split(":", 1)[1].strip()
            title = body_text.splitlines()[0][:80] or "Telegram-Notiz"
            res = knowledge.ingest_text(title, body_text, source="telegram")
            if res.get("ok"):
                _send(client, chat_id, ("Kenne ich schon (Duplikat)." if res.get("duplicate")
                                        else f"Im Archiv abgelegt: {title} ({res.get('chunks', '?')} Abschnitte) 📚"))
                return
        except Exception as e:  # noqa: BLE001
            events.emit("knowledge_error", {"error": str(e)[:200]})

    events.emit("telegram_in", {"chat_id": chat_id, "text": text}, session_id=f"telegram-{chat_id}")
    _agentic_reply(client, chat_id, f"telegram-{chat_id}", text, voice_text=voice_text)


def _handle_document(client: httpx.Client, chat_id: int, msg: dict) -> None:
    """Telegram-Anhang -> Wissens-Archiv (txt/md/html/pdf, max 15 MB)."""
    doc = msg.get("document") or {}
    fname = doc.get("file_name") or "anhang.txt"
    if (doc.get("file_size") or 0) > 15 * 1024 * 1024:
        _send(client, chat_id, "Zu gross (max 15 MB) — schick mir eine kleinere Datei.")
        return
    try:
        info = client.get(f"{API}/getFile", params={"file_id": doc.get("file_id")}).json()
        fpath = info.get("result", {}).get("file_path")
        if not fpath:
            _send(client, chat_id, "Konnte die Datei nicht abrufen.")
            return
        data = client.get(f"https://api.telegram.org/file/bot{TOKEN}/{fpath}").content
        from core.mind import knowledge

        res = knowledge.ingest_file(data, fname, source="telegram")
        if res.get("ok"):
            _send(client, chat_id, ("Kenne ich schon (Duplikat). 📚" if res.get("duplicate")
                                    else f"📚 Im Archiv: {fname} ({res.get('chunks', '?')} Abschnitte). "
                                         f"Frag mich einfach danach."))
        else:
            _send(client, chat_id, f"Konnte {fname} nicht ablegen: {res.get('error')}")
    except Exception as e:  # noqa: BLE001
        events.emit("knowledge_error", {"error": str(e)[:200]})
        _send(client, chat_id, f"Fehler beim Ablegen: {str(e)[:150]}")


def _clean(t: str) -> str:
    """Markdown-Sternchen raus (Telegram zeigt sie sonst als Zeichen)."""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t, flags=re.DOTALL)
    return t.replace("**", "").replace("__", "").strip()


def _short(args: dict) -> str:
    s = str(args)
    return s if len(s) <= 60 else s[:57] + "…"


def _action_label(name: str, args: dict | None) -> str:
    """Warmes, persoenliches Aktions-Label in Ich-Form (sie erzaehlt, was sie tut)."""
    a = args or {}

    def pick(*keys: str) -> str:
        for k in keys:
            if a.get(k):
                return str(a[k])
        return ""

    table = {
        "read_file": ("📖", "lese", pick("path")),
        "write_file": ("✍️", "schreibe", pick("path")),
        "append_file": ("✍️", "ergänze", pick("path")),
        "list_dir": ("📂", "schaue in", pick("path")),
        "make_dir": ("📁", "lege einen Ordner an", pick("path")),
        "run_command": ("⚡", "führe aus", pick("command")),
        "web_search": ("🌐", "suche", pick("query")),
        "web_fetch": ("🌐", "lese die Seite", pick("url")),
        "self_edit": ("🔧", "baue an mir selbst", pick("path")),
        "remember_fact": ("🧠", "merke mir das", ""),
        "learn_skill": ("🎓", "lerne einen Skill", pick("name")),
        "list_skills": ("🎓", "gehe meine Skills durch", ""),
        "curate_skills": ("🧹", "räume meine Skills auf", ""),
        "read_logs": ("📋", "lese mein Log", ""),
        "watch_add": ("📡", "beobachte", pick("value", "label")),
        "watch_list": ("📡", "schaue in meinen Monitor", ""),
        "cron_add": ("⏰", "plane eine Aufgabe", pick("label", "prompt")),
        "cron_list": ("⏰", "schaue meine Termine an", ""),
        "switch_model": ("🔀", "wechsle mein Modell zu", pick("model")),
        "list_models": ("🧠", "prüfe meine Modelle", ""),
        "set_context": ("🧩", "stelle mein Kontextfenster ein", ""),
        "plan_and_execute": ("🧭", "plane & arbeite ab", pick("task")),
        "request_secret": ("🔑", "frage einen Zugang an", pick("name")),
        "jetzt": ("🕐", "schaue auf die Uhr", ""),
    }
    emoji, verb, arg = table.get(name, ("✨", name, _short(a)))
    arg = arg.replace("\n", " ").strip()
    if len(arg) > 56:
        arg = arg[:55] + "…"
    return f"{emoji} {verb}" + (f": {arg}" if arg else "")


# Ruhiger „Atem"-Puls fuer die Denk-/Arbeits-Anzeige: EIN einziges bewegtes Element,
# das im gemaechlichen Pump-Takt atmet (waechst/schrumpft) -> pulsiert, flackert nicht.
_PULSE = ["·", "··", "···", "··"]
_PULSE_INTERVAL = 1.8  # Sekunden zwischen Edits: gemaechlich = kein Flackern, kein 429


def _render_trace(voice_text: str | None, think: str, lines: list[str],
                  phrase: str, pulse: str, running: bool) -> str:
    """Reiner Renderer der Live-Trace-Nachricht (pur -> testbar).

    Struktur: Transkript-Kopf (falls Sprachmemo) · voller Denk-Strom · Trenner +
    Werkzeug-Schritte · EINE bewegte Puls-Zeile unten. Bei Abschluss (running=False)
    faellt die Puls-Zeile weg -> ruhige Finalisierung."""
    parts: list[str] = []
    if voice_text:
        parts.append("🎙️ «" + voice_text[:160] + "»")
    if think:
        parts.append("💭 " + think.strip()[-1400:])
    if lines:
        parts.append("─" * 18)
        parts += lines[-12:]
    if running:
        parts.append("🧠 " + phrase + " " + pulse)
    return ("\n".join(parts))[:4000] or "💭 …"


def _agentic_reply(client: httpx.Client, chat_id: int, session_id: str, text: str,
                   voice_text: str | None = None) -> None:
    """Agentischer Chat mit RUHIGER Live-Trace (Denken + Werkzeug-Schritte).

    Architektur bewusst deterministisch:
    - EIN Render-Pump editiert die Trace-Nachricht in gemaechlichem Fixtakt
      (Puls statt Flackern); eingehende Events mutieren NUR den Zustand, nie das UI.
    - Alle Telegram-Calls laufen ueber den dedizierten Kurz-Timeout-Client (_ctrl),
      strikt getrennt vom Long-Polling -> keine verhakte Zustellung (Wedge-Fix).
    - Ein Sprachmemo ist live oben sichtbar und verschwindet bei Abschluss aus dem
      Verlauf (kein Transkript-Berg). Die Antwort kommt als neue Nachricht.
    """
    client = _ctrl()  # dedizierter Sende-/Edit-Client (nicht der getUpdates-Long-Poll)

    _typing(client, chat_id)
    head = ("🎙️ «" + voice_text[:200] + "»\n") if voice_text else ""
    phrase0 = next_phrase()
    init = client.post(f"{API}/sendMessage",
                       json={"chat_id": chat_id, "text": head + "🧠 " + phrase0 + " ·"}).json()
    mid = init.get("result", {}).get("message_id")

    state = {"think": "", "lines": [], "tools": [], "tick": 0, "last_render": "", "phrase": phrase0}
    lock = threading.Lock()
    stop = threading.Event()

    def content_sig() -> str:
        """Signatur des INHALTS (Denk-Strom + Schritte) — ohne Puls/Spruch. So laesst
        sich 'nur der Puls hat sich bewegt' von 'echte neue Info' unterscheiden."""
        return state["think"].strip()[-1400:] + "" + "\n".join(state["lines"][-12:])

    def edit(force: bool = False) -> None:
        if not mid:
            return
        running = not stop.is_set()
        pulse = _PULSE[state["tick"] % len(_PULSE)]
        txt = _render_trace(voice_text, state["think"], state["lines"], state["phrase"], pulse, running)
        if txt == state["last_render"]:
            return
        # Reine Puls-Bewegung (kein neuer Inhalt) nur gedrosselt senden -> waehrend Kira
        # still nachdenkt flackert der Chat nicht bei jedem Takt (Sergens Kernschmerz).
        if not force and content_sig() == state.get("last_sig") and (state["tick"] % 2 != 0):
            return
        state["last_render"] = txt
        state["last_sig"] = content_sig()
        try:
            client.post(f"{API}/editMessageText",
                        json={"chat_id": chat_id, "message_id": mid, "text": txt})
        except Exception:
            pass

    def pump() -> None:
        # Einziger Editor: ruhiger Fixtakt -> kein Sub-Edit-Flackern, kein 429.
        # stop.wait() weckt bei Abschluss SOFORT -> snappy Finalisierung.
        while not stop.wait(_PULSE_INTERVAL):
            with lock:
                state["tick"] += 1
                if state["tick"] % 4 == 0:  # Spruch alle ~7 s wechseln (ruhig, nicht hektisch)
                    state["phrase"] = next_phrase(state["phrase"])
                edit()
            if state["tick"] % 3 == 0:  # nativen „tippt…"-Indikator am Leben halten
                _typing(client, chat_id)

    anim = threading.Thread(target=pump, daemon=True)
    anim.start()

    def on_event(ev: dict) -> None:
        # Zustand mutieren; Denk-Strom rendert der ruhige Pump-Takt, ein NEUER
        # Werkzeug-Schritt aber sofort (echte Info -> snappy, kein 1,8s-Verzug).
        with lock:
            k = ev["kind"]
            if k == "think":
                state["think"] += ev["text"]
            elif k == "tool":
                state["tools"].append(ev["name"])
                state["lines"].append(_action_label(ev["name"], ev.get("args")))
                edit(force=True)
            elif k == "obs":
                if "Fehler" in (ev.get("text") or ""):  # Ergebnis nur bei Fehlern zeigen
                    state["lines"].append("   ⚠️ " + ev["text"][:60])
                    edit(force=True)

    from core.agency.act import act_chat

    try:
        answer = act_chat(text, session_id=session_id, on_event=on_event).strip()
    except Exception as e:  # noqa: BLE001  -> niemals stilles Verschlucken
        events.emit("agentic_reply_error", {"error": str(e)})
        answer = f"⚠️ Ich bin auf einen Fehler gestossen: {str(e)[:300]}"

    # Pump deterministisch stoppen (weckt sofort) und einholen -> kein Thread laeuft weiter.
    stop.set()
    anim.join(timeout=3)

    # Genau EINE finale Aktion: Transkript + Denk-Trace verschwinden aus dem Verlauf.
    if mid:
        try:
            if state["tools"]:
                done = "\n".join(state["lines"][-6:]) + f"\n✅ erledigt ({len(state['tools'])} Schritte)"
                client.post(f"{API}/editMessageText",
                            json={"chat_id": chat_id, "message_id": mid, "text": done[:4000]})
            else:
                # Transkript-/Trace-Nachricht restlos entfernen. Wichtig: Ergebnis PRUEFEN —
                # ein still scheiterndes Loeschen laesst das Sprachmemo-Transkript stehen
                # und sprengt den Chat (Sergens Kernschmerz). Fallback: kollabieren.
                r = client.post(f"{API}/deleteMessage",
                                json={"chat_id": chat_id, "message_id": mid})
                ok = False
                try:
                    ok = bool(r.json().get("ok"))
                except Exception:  # noqa: BLE001
                    pass
                if not ok:
                    events.emit("telegram_cleanup_failed", {"message_id": mid})
                    client.post(f"{API}/editMessageText",
                                json={"chat_id": chat_id, "message_id": mid, "text": "🎙️ ✓"})
        except Exception:
            pass

    # Finale Antwort als NEUE Nachricht. Auf Telegram bewusst NUR Text — die Stimme lebt
    # im Cockpit-Assistenzmodus (auf Telegram liest Sergen lieber, das ist schneller).
    _send(client, chat_id, answer or "(keine Antwort)")


def _handle_command(client: httpx.Client, chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("start", "help"):
        _send(client, chat_id,
              "Ich bin Kira. Schreib oder sprich mir einfach — oder tippe „/“ fuer das Menue.\n"
              "Befehle:\n"
              "/status – Heartbeat, Budget & Modell auf einen Blick\n"
              "/plan <große aufgabe> – ich erstelle einen Plan und arbeite ihn Schritt fuer Schritt ab\n"
              "/code <coding-auftrag> – Coding-Modus (an Kira selbst schrauben; erbt den Chat davor)\n"
              "/work <auftrag> – voller Werkzeug-Modus fuer laengere Aufgaben\n"
              "/act <aufgabe>  – ich nutze Werkzeuge (z.B. Web), um etwas zu erledigen\n"
              "/build <idee>   – ich baue mir ein neues Werkzeug\n"
              "/model – Modelle anzeigen/wechseln\n"
              "/stop  – Not-Aus (ich halte sofort an)\n"
              "/go    – Not-Aus aufheben")
        return
    if cmd == "status":
        lines = ["📊 <b>Kira-Status</b>"]
        try:
            from core.kernel.scheduler import heartbeat_on
            lines.append("💓 Heartbeat: " + ("laeuft" if heartbeat_on() else "aus"))
        except Exception:  # noqa: BLE001
            pass
        try:
            from core.kernel import models
            lines.append("🧩 Modell (Chat): " + str(models.roles().get("chat", "?")).split("/")[-1])
        except Exception:  # noqa: BLE001
            pass
        try:
            from core.governance import treasury
            b = treasury.status()
            dl = b.get("day_limit")
            ml = b.get("month_limit")
            lines.append(f"💶 Heute: {b.get('day_spent', 0)} €" + (f" / {dl} €" if dl is not None else ""))
            lines.append(f"🗓 Monat: {b.get('month_spent', 0)} €" + (f" / {ml} €" if ml is not None else ""))
        except Exception:  # noqa: BLE001
            pass
        lines.append("🛑 Not-Aus: " + ("AKTIV" if kill_switch_active() else "aus"))
        _send(client, chat_id, "\n".join(lines))
        return
    if cmd == "plan":
        if not rest:
            _send(client, chat_id, "Nutzung: /plan <große, mehrstufige Aufgabe>")
            return
        _agentic_reply(client, chat_id, f"telegram-{chat_id}", "plan: " + rest)
        return
    if cmd == "code":
        if not rest:
            _send(client, chat_id, "Nutzung: /code <coding-auftrag an Kira, z.B. einen Bug fixen>")
            return
        # Coding-Modus wie im Cockpit — erbt den Verlauf DIESER Telegram-Session (geteiltes Gedaechtnis).
        _agentic_reply(client, chat_id, f"telegram-{chat_id}", "code: " + rest)
        return
    if cmd == "work":
        if not rest:
            _send(client, chat_id, "Nutzung: /work <langer Auftrag mit vollem Werkzeug-Budget>")
            return
        _agentic_reply(client, chat_id, f"telegram-{chat_id}", "/work " + rest)
        return
    if cmd == "stop":
        kill_switch_path().write_text("stop", encoding="utf-8")
        events.emit("kill_switch_set", {"via": "telegram"})
        _send(client, chat_id, "🛑 Not-Aus aktiv. Ich halte alle Aktionen an. Mit /go wieder frei.")
        return
    if cmd == "go":
        p = kill_switch_path()
        if p.exists():
            p.unlink()
        events.emit("kill_switch_clear", {"via": "telegram"})
        _send(client, chat_id, "✅ Not-Aus aufgehoben. Ich bin wieder einsatzbereit.")
        return
    if cmd == "act":
        if not rest:
            _send(client, chat_id, "Nutzung: /act <aufgabe>")
            return
        _typing(client, chat_id)
        from core.agency.act import act

        result = act(rest, session_id=f"telegram-{chat_id}")
        _send(client, chat_id, result["text"])
        return
    if cmd == "build":
        if not rest:
            _send(client, chat_id, "Nutzung: /build <was das Werkzeug koennen soll>")
            return
        _typing(client, chat_id)
        from core.agency.tools import synthesize

        r = synthesize.synthesize(rest)
        if r["ok"]:
            _send(client, chat_id, f"✅ Werkzeug '{r['name']}' gebaut & registriert.\nTest: {r.get('test_output','')[:200]}")
        else:
            _send(client, chat_id, f"❌ Nicht registriert: {r.get('reason')}\n{r.get('test_output','')[:200]}")
        return
    if cmd == "model":
        from core.kernel import models

        args = rest.split()
        _ROLES = ("chat", "reason", "bulk", "escalation", "default")
        if not args:
            r = models.roles()
            _send(client, chat_id,
                  "🧠 Modell-Rollen:\n"
                  f"💬 chat: {r['chat']}\n🧠 reason: {r['reason']}\n⏰ bulk: {r['bulk']}\n"
                  f"⚡ escalation: {r['escalation']}\n★ default: {r['default']}\n\n"
                  "Wechseln: /model <rolle> <modell-id>\n"
                  "z.B. /model chat deepseek/deepseek-v4-flash")
        elif args[0] in _ROLES and len(args) >= 2:
            mid = args[1]
            if not (mid.startswith("openrouter/") or mid.startswith("ollama")):
                mid = "openrouter/" + mid
            _send(client, chat_id, f"✅ {args[0]} → {models.set_role(args[0], mid)}")
        elif args[0] == "use" and len(args) >= 2:
            _send(client, chat_id, f"Default-Modell → {models.set_model(args[1])}")
        elif args[0] == "add" and len(args) >= 5:
            models.add_provider(args[1], args[2], args[3], args[4])
            _send(client, chat_id, f"Provider '{args[1]}' angelegt. Nutzen: /model use {args[1]}")
        else:
            _send(client, chat_id, "Nutzung: /model  ·  /model <rolle> <id> (rolle: chat/reason/bulk/escalation/default)  ·  /model use <id>")
        return
    _send(client, chat_id, "Unbekannter Befehl. /help zeigt, was ich kann.")


# --- Nebenlaeufigkeit: pro Chat genau EINE aktive Aufgabe + kurze Warteschlange (kein Thread-Stau) ---
_chat_busy: dict[int, bool] = {}
_chat_queue: dict[int, deque] = {}
_chat_lock = threading.Lock()


def _worker(client: httpx.Client, chat_id: int, update: dict) -> None:
    from core.kernel import runstate

    runstate.enter_turn()  # aktiver Zug -> ein Neustart (restart_self/self_edit) wartet bis danach
    try:
        cur = update
        while cur is not None:
            try:
                _handle(client, cur)
            except Exception as e:  # eine kaputte Nachricht darf den Worker nicht killen
                events.emit("telegram_handle_error", {"error": str(e)})
            with _chat_lock:
                q = _chat_queue.get(chat_id)
                cur = q.popleft() if (q and len(q)) else None
                if cur is None:
                    _chat_busy[chat_id] = False
    finally:
        runstate.exit_turn()  # idle -> ein aufgeschobener Neustart wird jetzt ausgeloest


def _dispatch(client: httpx.Client, update: dict) -> None:
    """Eine Aufgabe pro Chat gleichzeitig; weitere Nachrichten kommen kurz in die Queue
    (max 3) und werden danach der Reihe nach abgearbeitet -> keine Thread-Flut, keine
    verlorenen Antworten durch Telegram-Rate-Limit."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    with _chat_lock:
        if _chat_busy.get(chat_id):
            _chat_queue.setdefault(chat_id, deque(maxlen=3)).append(update)
            busy = True
        else:
            _chat_busy[chat_id] = True
            busy = False
    if busy:
        try:
            client.post(f"{API}/sendMessage",
                        json={"chat_id": chat_id, "text": "⏳ Bin noch an der vorigen Aufgabe — ich nehm das gleich mit. 💜"})
        except Exception:
            pass
        return
    threading.Thread(target=_worker, args=(client, chat_id, update), daemon=True).start()


def _backoff_next(cur: float) -> float:
    """S8.0: exponentielles Backoff fuer den Poll-Loop (2s -> 60s Cap)."""
    return min(max(cur, 2.0) * 2, 60.0)


def _bundle(state: dict, error: str | None) -> dict | None:
    """Stoerungs-Buendelung (S8.0): gleichartige Loop-Fehler werden gesammelt.

    Liefert hoechstens EIN Event-Payload (mit 'type'-Schluessel): beim ERSTEN
    Fehler einer Serie und bei der Erholung eine Zusammenfassung ('12x in 600s').
    Dazwischen: None — kein Event-Spam mehr im Live-Ops-Feed."""
    if error is not None:
        state["count"] = state.get("count", 0) + 1
        state.setdefault("first", time.time())
        state["last_error"] = error[:200]
        if state["count"] == 1:
            return {"type": "telegram_loop_error", "error": error[:200],
                    "note": "weitere gleichartige Fehler werden gebuendelt"}
        return None
    if state.get("count"):
        out = {"type": "telegram_loop_recovered", "count": state["count"],
               "seconds": round(time.time() - state.get("first", time.time())),
               "last_error": state.get("last_error", "")}
        state.clear()
        return out
    return None


# Das '/'-Befehlsmenue in Telegram (setMyCommands). Nur wirklich vorhandene Befehle — sonst
# klickt Sergen ins Leere. Reihenfolge = Anzeige-Reihenfolge im Menue.
_BOT_COMMANDS = [
    ("status", "Heartbeat, Budget & Modell auf einen Blick"),
    ("code", "Coding-Modus: an Kira selbst schrauben"),
    ("plan", "Große Aufgabe planen und Schritt für Schritt abarbeiten"),
    ("work", "Längerer Auftrag mit vollem Werkzeug-Budget"),
    ("act", "Etwas mit Werkzeugen erledigen (z. B. Web)"),
    ("build", "Ein neues Werkzeug für mich bauen"),
    ("model", "Modelle anzeigen oder wechseln"),
    ("stop", "Not-Aus: sofort alles anhalten"),
    ("go", "Not-Aus wieder aufheben"),
    ("help", "Was ich kann – Kurzhilfe"),
]


def _register_commands(client: httpx.Client) -> None:
    """Registriert das '/'-Befehlsmenue bei Telegram. Best effort — ein Fehler hier darf den
    Bot-Start nie bremsen (das Menue ist Komfort, kein kritischer Pfad)."""
    try:
        cmds = [{"command": c, "description": d} for c, d in _BOT_COMMANDS]
        r = client.post(f"{API}/setMyCommands", json={"commands": cmds}, timeout=15)
        ok = bool((r.json() or {}).get("ok"))
        events.emit("telegram_commands_set", {"ok": ok, "n": len(cmds)})
    except Exception as e:  # noqa: BLE001
        events.emit("telegram_commands_error", {"error": str(e)[:200]})


def run() -> None:
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN fehlt in .env — Bot via @BotFather anlegen und Token eintragen.")
        return
    events.init_db()
    _register_commands(_ctrl())  # '/'-Menue bei Telegram anmelden (einmalig beim Start)
    try:  # MCP-Bruecke im Hintergrund anschliessen (Ausfall darf den Boot nie bricken)
        from core.agency.mcp import registry_bridge as _mcp_bridge
        _mcp_bridge.init_background()
    except Exception:  # noqa: BLE001
        pass
    from core.kernel import runstate
    runstate.start_watchdog()  # festgefahrene Chat-Zuege erkennen -> Force-Restart (kein wedged Bot)
    offset: int | None = None
    backoff = 2.0      # S8.0: exponentiell bei Stoerungen (2s -> 60s), Reset bei Erfolg
    err_state: dict = {}
    print("Telegram-Bot laeuft (Long-Polling). Strg+C zum Stoppen.")
    with httpx.Client(timeout=75) as client:
        while True:
            if kill_switch_active():
                print("KILL-SWITCH aktiv — Bot haelt an.")
                break
            try:
                resp = client.get(f"{API}/getUpdates", params={"timeout": 60, "offset": offset})
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    _dispatch(client, update)
                ev = _bundle(err_state, None)  # Erholung -> EIN Sammel-Event statt Spam
                if ev:
                    events.emit(ev.pop("type"), ev)
                backoff = 2.0
            except httpx.ReadTimeout:
                continue  # normales Long-Polling-Ende, kein Fehler
            except KeyboardInterrupt:
                print("\nBot gestoppt.")
                break
            except Exception as e:
                ev = _bundle(err_state, str(e))
                if ev:
                    events.emit(ev.pop("type"), ev)
                time.sleep(backoff)  # S8.0: vorher Hammer-Loop ohne Pause
                backoff = _backoff_next(backoff)


if __name__ == "__main__":
    run()