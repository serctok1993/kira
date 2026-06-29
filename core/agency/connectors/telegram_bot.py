"""Telegram-Connector: Kyros' Draht zu Sergen (Text + Sprachmemo), 24/7 erreichbar.

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

    text = msg.get("text")
    if not text and "voice" in msg and _cfg().get("voice", True):
        _typing(client, chat_id)
        text = _transcribe_voice(client, msg)
        if text:
            _send(client, chat_id, f"🎙️ Verstanden: «{text}»")
        else:
            _send(client, chat_id, "Konnte das Memo nicht verstehen (Whisper installiert? 'uv sync').")
            return
    if not text:
        return

    if text.startswith("/"):
        _handle_command(client, chat_id, text)
        return

    events.emit("telegram_in", {"chat_id": chat_id, "text": text}, session_id=f"telegram-{chat_id}")
    _typing(client, chat_id)
    result = _agent_for(chat_id).respond(text)
    _send(client, chat_id, result["text"])


def _handle_command(client: httpx.Client, chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("start", "help"):
        _send(client, chat_id,
              "Ich bin Kyros. Schreib oder sprich mir einfach.\n"
              "Befehle:\n"
              "/act <aufgabe>  – ich nutze Werkzeuge (z.B. Web), um etwas zu erledigen\n"
              "/build <idee>   – ich baue mir ein neues Werkzeug\n"
              "/stop  – Not-Aus (ich halte sofort an)\n"
              "/go    – Not-Aus aufheben")
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
