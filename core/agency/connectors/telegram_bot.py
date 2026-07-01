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

    events.emit("telegram_in", {"chat_id": chat_id, "text": text}, session_id=f"telegram-{chat_id}")
    _agentic_reply(client, chat_id, f"telegram-{chat_id}", text, voice_text=voice_text)


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
        "switch_model": ("🔀", "wechsle mein Hirn zu", pick("model")),
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
    init = client.post(f"{API}/sendMessage",
                       json={"chat_id": chat_id, "text": head + "💭 Kira denkt ·"}).json()
    mid = init.get("result", {}).get("message_id")

    state = {"think": "", "lines": [], "tools": [], "tick": 0, "last_render": ""}
    lock = threading.Lock()
    stop = threading.Event()

    def render() -> str:
        parts = []
        if voice_text:
            parts.append("🎙️ «" + voice_text[:160] + "»")
        running = not stop.is_set()
        pulse = _PULSE[state["tick"] % len(_PULSE)]
        if state["think"]:
            # Ganzen Denk-Strom als geglaetteten Tail zeigen -> waechst ruhig im Takt,
            # kein zitternder Zeichen-Cursor. Ein einziges Puls-Element am Ende.
            tail = re.sub(r"\s+", " ", state["think"]).strip()[-240:]
            parts.append("💭 " + tail + (" " + pulse if running else ""))
        elif running:
            parts.append("💭 Kira denkt " + pulse)
        if state["lines"]:
            parts.append("─" * 18)
            parts += state["lines"][-8:]
        return ("\n".join(parts))[:4000] or "💭 …"

    def edit() -> None:
        if not mid:
            return
        txt = render()
        if txt == state["last_render"]:
            return
        state["last_render"] = txt
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
                edit()
            if state["tick"] % 3 == 0:  # nativen „tippt…"-Indikator am Leben halten
                _typing(client, chat_id)

    anim = threading.Thread(target=pump, daemon=True)
    anim.start()

    def on_event(ev: dict) -> None:
        # Nur Zustand mutieren; das Rendern macht ausschliesslich der Pump.
        with lock:
            k = ev["kind"]
            if k == "think":
                state["think"] += ev["text"]
            elif k == "tool":
                state["tools"].append(ev["name"])
                state["lines"].append(_action_label(ev["name"], ev.get("args")))
            elif k == "obs":
                if "Fehler" in (ev.get("text") or ""):  # Ergebnis nur bei Fehlern zeigen
                    state["lines"].append("   ⚠️ " + ev["text"][:60])

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
                client.post(f"{API}/deleteMessage", json={"chat_id": chat_id, "message_id": mid})
        except Exception:
            pass

    # Finale Antwort als NEUE Nachricht
    _send(client, chat_id, answer or "(keine Antwort)")


def _handle_command(client: httpx.Client, chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("start", "help"):
        _send(client, chat_id,
              "Ich bin Kira. Schreib oder sprich mir einfach.\n"
              "Befehle:\n"
              "/plan <große aufgabe> – ich erstelle einen Plan und arbeite ihn Schritt fuer Schritt ab\n"
              "/act <aufgabe>  – ich nutze Werkzeuge (z.B. Web), um etwas zu erledigen\n"
              "/build <idee>   – ich baue mir ein neues Werkzeug\n"
              "/stop  – Not-Aus (ich halte sofort an)\n"
              "/go    – Not-Aus aufheben")
        return
    if cmd == "plan":
        if not rest:
            _send(client, chat_id, "Nutzung: /plan <große, mehrstufige Aufgabe>")
            return
        _agentic_reply(client, chat_id, f"telegram-{chat_id}", "plan: " + rest)
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


def run() -> None:
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN fehlt in .env — Bot via @BotFather anlegen und Token eintragen.")
        return
    events.init_db()
    from core.kernel import runstate
    runstate.start_watchdog()  # festgefahrene Chat-Zuege erkennen -> Force-Restart (kein wedged Bot)
    offset: int | None = None
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
            except httpx.ReadTimeout:
                continue
            except KeyboardInterrupt:
                print("\nBot gestoppt.")
                break
            except Exception as e:
                events.emit("telegram_loop_error", {"error": str(e)})


if __name__ == "__main__":
    run()