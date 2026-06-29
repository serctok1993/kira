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
import time

import httpx

from core.config import CONFIG, DATA_DIR
from core.kernel import events
from core.kernel.scheduler import kill_switch_active, kill_switch_path
from core.mind.agent import Agent

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"

_agents: dict[int, Agent] = {}


def _cfg() -> dict:
    return CONFIG.get("channels", {}).get("telegram", {})


def _agent_for(chat_id: int) -> Agent:
    if chat_id not in _agents:
        _agents[chat_id] = Agent(session_id=f"telegram-{chat_id}")
    return _agents[chat_id]


def _send(client: httpx.Client, chat_id: int, text: str) -> None:
    # Telegram-Limit: 4096 Zeichen pro Nachricht -> bei Bedarf stueckeln.
    for i in range(0, len(text) or 1, 4000):
        client.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text[i : i + 4000] or "…"})


def _typing(client: httpx.Client, chat_id: int) -> None:
    try:
        client.post(f"{API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
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


def _agentic_reply(client: httpx.Client, chat_id: int, session_id: str, text: str,
                   voice_text: str | None = None) -> None:
    """Agentischer Chat mit Live-Trace (Denken + Werkzeug-Schritte). Ein Sprachmemo wird NUR
    live im Arbeits-Trace gezeigt (kein separates 'Verstanden'); am Ende faellt der Trace zu
    einer kompakten Taetigkeits-Zeile zusammen, die Antwort kommt als neue Nachricht."""
    _typing(client, chat_id)
    head = ("🎙️ «" + voice_text[:200] + "»\n") if voice_text else ""
    init = client.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": head + "💭 …"}).json()
    mid = init.get("result", {}).get("message_id")
    state = {"think": "", "lines": [], "tools": [], "last": 0.0}

    def render() -> str:
        parts = []
        if voice_text:
            parts.append("🎙️ «" + voice_text[:200] + "»")
        if state["think"]:
            parts.append("💭 " + state["think"][-300:])
        parts += state["lines"][-8:]
        return ("\n".join(parts))[:4000] or "💭 …"

    def push(force: bool = False) -> None:
        now = time.time()
        if mid and (force or now - state["last"] > 1.3):
            try:
                client.post(f"{API}/editMessageText", json={"chat_id": chat_id, "message_id": mid, "text": render()})
            except Exception:
                pass
            state["last"] = now
            _typing(client, chat_id)

    def on_event(ev: dict) -> None:
        k = ev["kind"]
        if k == "think":
            state["think"] += ev["text"]
            push()
        elif k == "tool":
            state["tools"].append(ev["name"])
            state["lines"].append(f"🔧 {ev['name']} {_short(ev['args'])}")
            push(force=True)
        elif k == "obs":
            state["lines"].append(f"   ✓ {ev['text'][:70]}")
            push(force=True)

    from core.agency.act import act_chat

    answer = _clean(act_chat(text, session_id=session_id, on_event=on_event))

    # Arbeits-Trace abschliessen: bei Werkzeug-Nutzung eine kompakte Taetigkeits-Zeile,
    # sonst die Trace-Nachricht entfernen (sauberer Chat, kein Transkript-Berg).
    if mid:
        try:
            if state["tools"]:
                uniq = list(dict.fromkeys(state["tools"]))
                client.post(f"{API}/editMessageText",
                            json={"chat_id": chat_id, "message_id": mid, "text": "🔧 erledigt: " + ", ".join(uniq)})
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
        if not args:
            s = models.status()
            _send(client, chat_id,
                  f"Aktiv: {s['default']}\nEskalation: {s['escalation_model']}\n"
                  f"Eigene Provider: {s['providers'] or '(keine)'}\n"
                  f"Lokal: {', '.join(s['ollama_local']) or '(keine)'}")
        elif args[0] == "use" and len(args) >= 2:
            _send(client, chat_id, f"Aktives Modell -> {models.set_model(args[1])}")
        elif args[0] == "openrouter" and len(args) >= 2:
            _send(client, chat_id, f"Aktiv ueber OpenRouter -> {models.add_openrouter(args[1])}")
        elif args[0] == "add" and len(args) >= 5:
            models.add_provider(args[1], args[2], args[3], args[4])
            _send(client, chat_id, f"Provider '{args[1]}' angelegt. Nutzen: /model use {args[1]}")
        else:
            _send(client, chat_id, "Nutzung: /model | /model use <id> | /model openrouter <modell> | /model add <alias> <modell> <api_base> <ENV>")
        return
    _send(client, chat_id, "Unbekannter Befehl. /help zeigt, was ich kann.")


def run() -> None:
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN fehlt in .env — Bot via @BotFather anlegen und Token eintragen.")
        return
    events.init_db()
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
                    try:
                        _handle(client, update)
                    except Exception as e:  # eine kaputte Nachricht darf den Loop nicht killen
                        events.emit("telegram_handle_error", {"error": str(e)})
            except httpx.ReadTimeout:
                continue
            except KeyboardInterrupt:
                print("\nBot gestoppt.")
                break
            except Exception as e:
                events.emit("telegram_loop_error", {"error": str(e)})


if __name__ == "__main__":
    run()
