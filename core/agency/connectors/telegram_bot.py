"""Telegram-Connector: der Draht des Agenten zu seinem Menschen (Text + Sprachmemo), 24/7 erreichbar.

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

from core import identity as _identity
from core.config import CONFIG, DATA_DIR
from core.kernel import events, instance_lock
from core.kernel.phrases import next_phrase
from core.kernel.scheduler import kill_switch_active, kill_switch_path
from core.mind.agent import Agent

# W2: sichtbarer Agenten-Name (Werksname 'Kira', beim Onboarding umbenennbar).
_AGENT = _identity.agent_name()

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
    """Leichtes Markdown -> Telegram-HTML (fett/Code), Rest wird escaped (handy-tauglich).
    Einfache, bewusst gesetzte Tags (b/i/u/s/code) bleiben erhalten — vorher wurden sie
    mit-escaped und standen woertlich im Chat (<b>…</b> statt fett)."""
    import html as _h

    t = _h.escape(text or "", quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.DOTALL)
    t = re.sub(r"(?<![\w`])`([^`\n]+?)`(?![\w`])", r"<code>\1</code>", t)
    t = re.sub(r"&lt;(/?)(b|i|u|s|code)&gt;", r"<\1\2>", t)  # Whitelist wieder freischalten
    return t


def _send(client: httpx.Client, chat_id: int, text: str, html: bool = True,
          effect_id: str | None = None) -> None:
    # Telegram-Limit ~4096 Zeichen -> stueckeln; HTML-Format mit Plain-Fallback.
    client = _ctrl()  # Steuer-Plane immer ueber den dedizierten Kurz-Timeout-Client
    text = text or "…"
    for i in range(0, len(text), 3800):
        chunk = text[i : i + 3800]
        payload = {"chat_id": chat_id, "text": _tg_html(chunk) if html else chunk}
        if html:
            payload["parse_mode"] = "HTML"
        if effect_id and i == 0:   # animierter Premium-Effekt nur auf dem ersten Stueck
            payload["message_effect_id"] = effect_id
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

    # /emoji lernt animierte Custom-Emoji aus DIESER Nachricht (braucht die Entities -> hier, mit msg).
    if text.lstrip().lower().startswith("/emoji"):
        ids = [e.get("custom_emoji_id") for e in (msg.get("entities") or [])
               if e.get("type") == "custom_emoji" and e.get("custom_emoji_id")]
        if ids:
            n = _emoji_learn(ids)
            _send(client, chat_id, f"✨ <b>{n} animierte Emoji gelernt</b> — sie leuchten ab jetzt "
                  "als Neon-Glow im Denk-Status. (Nochmal /emoji mit anderen ersetzt sie.)")
        else:
            _send(client, chat_id, "So geht's: schreib <code>/emoji</code> und häng in DIESELBE Nachricht "
                  "deine <b>animierten</b> (Premium-)Emoji dran. Ich lese ihre IDs aus und nutze sie als "
                  f"Neon-Glow im Denk-Status. (aktuell gelernt: {len(_emoji_ids())})")
        return

    if text.startswith("/"):
        _handle_command(client, chat_id, text)
        return

    # 'todo:'-Fast-Path: blitzschnell erfassen, deterministisch (kein LLM, keine Wartezeit)
    if text.lower().startswith("todo:"):
        from core.agency.tools import life_tools

        body_text = text.split(":", 1)[1].strip()
        if body_text:
            _send(client, chat_id, "📝 " + life_tools.todo_add(body_text))
            events.emit("telegram_in", {"chat_id": chat_id, "text": text[:120]},
                        session_id=f"telegram-{chat_id}")
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
    # /denken an -> diese Session denkt sichtbar: auf den Denker (GLM) heben + Reasoning anfordern.
    if _denken_on(chat_id) and not text.lstrip().lower().startswith(
            ("reason:", "work:", "code:", "plan:", "denk:", "/")):
        text = "reason: denk:hoch " + text
    _agentic_reply(client, chat_id, f"telegram-{chat_id}", text, voice_text=voice_text,
                   user_msg_id=msg.get("message_id"))


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


# Ruhiger Takt fuer die Denk-/Arbeits-Anzeige: EIN bewegtes Element je Pump-Takt -> pulsiert, flackert nicht.
_PULSE_INTERVAL = 1.8  # Sekunden zwischen Edits: gemaechlich = kein Flackern, kein 429
_SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧"       # ruhiger Braille-Spinner (ein Frame je Takt); kein 🧠 mehr


def _esc(s: str) -> str:
    """HTML-sicher fuer parse_mode=HTML — sonst bricht Telegram bei < & > im Denk-/Pfad-Text."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_trace(voice_text: str | None, think: str, lines: list[str],
                  phrase: str, spin: str, running: bool, lead: str = "") -> str:
    """Reiner Renderer der Live-Trace-Nachricht (pur -> testbar), HTML fuer Telegram.

    Hermes-Stil in drei Zonen: DENKEN oben (aufklappbares Zitat, clean Prosa — kein
    Code) · SCHRITTE (Werkzeuge mit passendem Icon) · STATUS unten (Phase fett +
    Spinner). Telegram kann Text NICHT faerben -> bewusst einfarbig; den Neon-/Rainbow-
    Farbwechsel gibt es in der Web-App. Bei Abschluss (running=False) faellt der Status weg."""
    parts: list[str] = []
    if voice_text:
        parts.append("🎙️ <i>«" + _esc(voice_text[:160]) + "»</i>")
    if think:
        # Aufklappbares Zitat = Telegram-natives Ein-/Ausklappen (wie in der Web-App).
        parts.append("<blockquote expandable>💭 " + _esc(think.strip()[-1500:]) + "</blockquote>")
    if lines:
        parts.append("──────────")
        parts += [_esc(l) for l in lines[-12:]]
    if running:
        head = (lead + " ") if lead else ""   # animiertes Neon-Custom-Emoji (falls gelernt)
        parts.append(head + "<b>" + _esc(phrase) + "</b> <code>" + spin + "</code>")
    return ("\n".join(parts))[:3900] or "💭 …"


_DENKEN_FILE = DATA_DIR / "telegram_denken.json"

# getUpdates-Offset dauerhaft merken -> ueberlebt Neustart/Absturz. Ohne das startet der
# Bot mit offset=None, Telegram liefert die letzte(n) unbestaetigte(n) Update(s) erneut aus
# und Kira beantwortet dieselbe Nachricht nach jedem Restart nochmal (wirkt wie eine Schleife).
_OFFSET_FILE = DATA_DIR / "telegram_offset.json"


def _load_offset() -> int | None:
    try:
        import json
        v = int(json.loads(_OFFSET_FILE.read_text(encoding="utf-8"))["offset"])
        return v if v > 0 else None
    except Exception:  # noqa: BLE001 — fehlende/kaputte Datei -> frisch anfangen
        return None


def _save_offset(offset: int) -> None:
    try:
        import json
        _OFFSET_FILE.write_text(json.dumps({"offset": int(offset)}), encoding="utf-8")
    except Exception:  # noqa: BLE001 — Persistenz ist best-effort, darf den Poll nie brechen
        pass


def _denken_on(chat_id: int) -> bool:
    """Zeigt Kira in DIESEM Telegram-Chat ihren Denkstrom? (dann laeuft's auf dem Denker GLM)."""
    try:
        import json
        return int(chat_id) in set(json.loads(_DENKEN_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return False


def _denken_set(chat_id: int, on: bool) -> None:
    import json
    try:
        s = set(json.loads(_DENKEN_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        s = set()
    s.add(int(chat_id)) if on else s.discard(int(chat_id))
    try:
        _DENKEN_FILE.write_text(json.dumps(sorted(s)), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


# ---- Premium-Extras (Bot-Owner hat Premium): Reaktionen · Effekte · Custom-Emoji-Glow ----
_EFFECTS = {   # bekannte message_effect_id (Premium) fuer die finale Antwort
    "feuer": "5104841245755180586", "party": "5046509860389126442",
    "herz": "5044134455711629726", "daumen": "5107584321108051014",
}
_EFFEKT_STD = "feuer"                                   # dezenter Standard-Effekt bei erledigten Aufgaben
_EFFEKT_FILE = DATA_DIR / "telegram_effekt_aus.json"    # Chats mit Effekt AUS (Default = an)
_EMOJI_FILE = DATA_DIR / "telegram_emoji.json"          # gelernte animierte Custom-Emoji-IDs


def _react(client: httpx.Client, chat_id: int, message_id: int, emoji: str) -> None:
    """Kira reagiert auf DEINE Nachricht (👀 Start, 🔥 fertig) — best effort, nie kritisch."""
    try:
        client.post(f"{API}/setMessageReaction",
                    json={"chat_id": chat_id, "message_id": message_id,
                          "reaction": [{"type": "emoji", "emoji": emoji}]})
    except Exception:  # noqa: BLE001
        pass


def _effekt_on(chat_id: int) -> bool:
    try:
        import json
        return int(chat_id) not in set(json.loads(_EFFEKT_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return True   # Default: Effekt an (Premium-Flair)


def _effekt_set(chat_id: int, on: bool) -> None:
    import json
    try:
        s = set(json.loads(_EFFEKT_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        s = set()
    s.discard(int(chat_id)) if on else s.add(int(chat_id))
    try:
        _EFFEKT_FILE.write_text(json.dumps(sorted(s)), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _emoji_ids() -> list[str]:
    try:
        import json
        return [str(x) for x in json.loads(_EMOJI_FILE.read_text(encoding="utf-8"))][:8]
    except Exception:  # noqa: BLE001
        return []


def _emoji_learn(ids: list[str]) -> int:
    import json
    clean = [str(x) for x in ids if x][:8]
    try:
        _EMOJI_FILE.write_text(json.dumps(clean), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return len(clean)


def _lead_emoji(tick: int) -> str:
    """Fuehrendes Neon-Glow im Status: ein gelerntes animiertes Custom-Emoji (rotiert je Takt).
    Ohne gelernte Emoji leer -> sauberer Status. tg-emoji umschliesst EIN Fallback-Emoji (Pflicht)."""
    ids = _emoji_ids()
    if not ids:
        return ""
    return '<tg-emoji emoji-id="' + ids[tick % len(ids)] + '">✨</tg-emoji>'


def _agentic_reply(client: httpx.Client, chat_id: int, session_id: str, text: str,
                   voice_text: str | None = None, user_msg_id: int | None = None) -> None:
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

    if user_msg_id:
        _react(client, chat_id, user_msg_id, "👀")   # "ich hab's gesehen und lege los"
    _typing(client, chat_id)
    phrase0 = next_phrase()
    init_txt = _render_trace(voice_text, "", [], phrase0, _SPIN[0], True, _lead_emoji(0))
    init = client.post(f"{API}/sendMessage",
                       json={"chat_id": chat_id, "text": init_txt, "parse_mode": "HTML"}).json()
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
        spin = _SPIN[state["tick"] % len(_SPIN)]
        lead = _lead_emoji(state["tick"])   # animiertes Neon-Glow (falls gelernt)
        txt = _render_trace(voice_text, state["think"], state["lines"], state["phrase"], spin, running, lead)
        if txt == state["last_render"]:
            return
        # Reine Puls-Bewegung (kein neuer Inhalt) nur gedrosselt senden -> waehrend Kira
        # still nachdenkt flackert der Chat nicht bei jedem Takt (des Nutzers Kernschmerz).
        if not force and content_sig() == state.get("last_sig") and (state["tick"] % 2 != 0):
            return
        state["last_render"] = txt
        state["last_sig"] = content_sig()
        try:
            client.post(f"{API}/editMessageText",
                        json={"chat_id": chat_id, "message_id": mid, "text": txt, "parse_mode": "HTML"})
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
                done = "\n".join(_esc(l) for l in state["lines"][-6:]) + f"\n✅ <b>erledigt</b> ({len(state['tools'])} Schritte)"
                client.post(f"{API}/editMessageText",
                            json={"chat_id": chat_id, "message_id": mid, "text": done[:3900], "parse_mode": "HTML"})
            else:
                # Transkript-/Trace-Nachricht restlos entfernen. Wichtig: Ergebnis PRUEFEN —
                # ein still scheiterndes Loeschen laesst das Sprachmemo-Transkript stehen
                # und sprengt den Chat (des Nutzers Kernschmerz). Fallback: kollabieren.
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

    # Finale Antwort als NEUE Nachricht. Bei einer erledigten Aufgabe (Werkzeuge genutzt)
    # ein dezenter animierter Premium-Effekt; danach die Abschluss-Reaktion auf DEINE Nachricht.
    eff = _EFFECTS.get(_EFFEKT_STD) if (state["tools"] and _effekt_on(chat_id)) else None
    _send(client, chat_id, answer or "(keine Antwort)", effect_id=eff)
    if user_msg_id:
        _react(client, chat_id, user_msg_id, "🔥" if state["tools"] else "👍")


def _status_text() -> str:
    """Kurzer Status (Heartbeat, Modell, Budget, Offenes, Not-Aus). Jeder Teil best effort."""
    lines = [f"📊 <b>{_AGENT}-Status</b>"]
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
        dl, ml = b.get("day_limit"), b.get("month_limit")
        lines.append(f"💶 Heute: {b.get('day_spent', 0)} €" + (f" / {dl} €" if dl is not None else ""))
        lines.append(f"🗓 Monat: {b.get('month_spent', 0)} €" + (f" / {ml} €" if ml is not None else ""))
    except Exception:  # noqa: BLE001
        pass
    try:
        from core.agency import approvals
        n = len(approvals.pending())
        if n:
            lines.append(f"🔔 Freigaben offen: {n} (/freigaben)")
    except Exception:  # noqa: BLE001
        pass
    try:
        from core.agency.missions import queue
        n = len(queue.pending(limit=99))
        if n:
            lines.append(f"📋 Aufgaben offen: {n}")
    except Exception:  # noqa: BLE001
        pass
    lines.append("🛑 Not-Aus: " + ("AKTIV" if kill_switch_active() else "aus"))
    return "\n".join(lines)


def _tagewerk_text() -> str:
    """Tagewerk als Telegram-Nachricht (dieselben Zahlen wie Cockpit-Zentrale)."""
    try:
        from core.agency import tagewerk
        d = tagewerk.heute()
    except Exception:  # noqa: BLE001
        return "Tagewerk gerade nicht abrufbar."
    t = d.get("tasks", {})
    lines = [f"📅 **Tagewerk — {time.strftime('%d.%m.%Y')}**"]
    lines.append(f"✅ {t.get('done', 0)} Tasks erledigt"
                 + (f" (Ø {t['avg_score']})" if t.get("avg_score") is not None else "")
                 + (f" · ❌ {t['failed']} gescheitert" if t.get("failed") else ""))
    m = d.get("mails", {})
    if m.get("anzahl"):
        lines.append(f"✉️ {m['anzahl']} Mails: " + ", ".join(m.get("an", [])[:3]))
    s = d.get("skills", {})
    if s.get("anzahl"):
        lines.append(f"🧠 {s['anzahl']} Skills: " + ", ".join(s.get("namen", [])[:3]))
    c = d.get("crons", {})
    if c.get("anzahl"):
        lines.append(f"⏰ {c['anzahl']} Cron-Laeufe: " + ", ".join(c.get("labels", [])[:3]))
    sv = d.get("selbstverbesserung", {})
    if sv.get("ticks") or sv.get("code_edits"):
        lines.append(f"🔧 {sv.get('ticks', 0)} Selbst-Ticks"
                     + (f" · Code: {', '.join(sv['code_edits'][:2])}" if sv.get("code_edits") else ""))
    if d.get("lektionen"):
        lines.append(f"💡 {d['lektionen']} Lektionen gelernt")
    dg = d.get("diagnose")
    if dg:
        lines.append("🩺 Diagnose: " + ("ok" if dg.get("ok") else f"{dg.get('probleme', '?')} Problem(e)"))
    if d.get("freigaben_offen"):
        lines.append(f"🔔 {d['freigaben_offen']} Freigaben warten (/freigaben)")
    lines.append(f"💰 {d.get('kosten_heute_usd', 0)} $ heute")
    return "\n".join(lines)


def _kalibrierung_text() -> str:
    """Selbstkalibrierung (7 Tage) als Telegram-Nachricht — wie im Cockpit (Checkliste)."""
    try:
        from core.agency import calibration
        return "🧭 **Selbstkalibrierung**\n" + calibration.render(7)
    except Exception:  # noqa: BLE001
        return "Kalibrierung gerade nicht abrufbar."


def _todo_overview() -> tuple[str, dict | None]:
    """Offene Todos als eine Nachricht + Abhak-Knoepfe (ein Tipp = erledigt)."""
    try:
        from core.agency.missions import queue
        queue.init_queue()
        board = queue.board("leben")
    except Exception:  # noqa: BLE001
        return "Todos gerade nicht abrufbar.", None
    lines = ["📝 <b>Deine Todos</b>"]
    buttons: list[list[dict]] = []
    n = 0
    for key, label in (("today", "HEUTE"), ("week", "WOCHE"), ("later", "SPAETER")):
        items = board.get(key, [])
        if not items:
            continue
        lines.append(f"\n<b>{label}</b>")
        for t in items:
            if n >= 8:  # Knopf-Limit: uebersichtlich bleiben
                break
            n += 1
            due = f" [{t['due_date']}]" if t.get("due_date") else ""
            desc = str(t.get("description") or "?")
            lines.append(f"{n}. {_tg_html(desc[:80])}{due}")
            buttons.append([{"text": f"✔ {n}. {desc[:28]}",
                             "callback_data": f"todo:done:{t['id'][:8]}"}])
    if n == 0:
        return "📝 Keine offenen Todos — freies Feld. 🙂", None
    lines.append("\n<i>Tipp: „todo: Reifen wechseln“ legt sofort eins an.</i>")
    return "\n".join(lines), {"inline_keyboard": buttons}


def _send_todos(chat_id: int) -> None:
    text, kb = _todo_overview()
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = kb
    try:
        _ctrl().post(f"{API}/sendMessage", json=payload)
    except Exception:  # noqa: BLE001
        pass


# --- Abend-Resuemee: das Tagewerk kommt von selbst (deterministisch, 0 Token) ---
_RESUEMEE_FILE = DATA_DIR / "telegram_resuemee.json"


def _resuemee_zeit() -> str:
    """HH:MM aus config (channels.telegram.tagewerk_zeit); '' = aus. Default 21:30."""
    v = _cfg().get("tagewerk_zeit", "21:30")
    v = str(v or "").strip()
    return v if re.fullmatch(r"\d{1,2}:\d{2}", v) else ("" if not v else "21:30")


def _resuemee_due(now_struct: time.struct_time | None = None) -> bool:
    """Faellig, wenn die konfigurierte Zeit heute erreicht und heute noch nicht gesendet."""
    zeit = _resuemee_zeit()
    if not zeit:
        return False
    lt = now_struct or time.localtime()
    hh, mm = (int(x) for x in zeit.split(":"))
    if (lt.tm_hour, lt.tm_min) < (hh, mm):
        return False
    heute = time.strftime("%Y-%m-%d", lt)
    try:
        import json
        return json.loads(_RESUEMEE_FILE.read_text(encoding="utf-8")).get("date") != heute
    except Exception:  # noqa: BLE001
        return True


def _maybe_melde_buendel(client: httpx.Client) -> None:
    """Missions-Buendel (des Nutzers Fix): alle N Stunden EIN Sammel-Post mit Einzeilern
    statt 10 Einzelmeldungen. Details stehen im Cockpit (Log) und im Tagewerk."""
    chat = _cfg().get("allowed_chat_id")
    if not chat:
        return
    try:
        from core.config import CONFIG as _C
        stunden = float((_C.get("mission", {}) or {}).get("buendel_stunden", 3) or 3)
        from core.agency.missions import melde

        if not melde.faellig(stunden):
            return
        zeilen = melde.leeren()
        if not zeilen:
            return
        _send(client, chat, "🧺 **Missions-Bündel** (" + str(len(zeilen)) + " Schritte):\n"
              + "\n".join("• " + z for z in zeilen[-15:])
              + "\n\nDetails: /tagewerk oder Cockpit → Puls.")
        events.emit("melde_buendel", {"zeilen": len(zeilen)})
    except Exception:  # noqa: BLE001
        pass


def _maybe_erinnerungen(client: httpx.Client) -> None:
    """Faellige Einmal-Wecker (erinnerung-Tool) per Telegram zustellen. Raist nie.
    Der Bot ist DER Zusteller, sobald Telegram konfiguriert ist — der Runner stellt
    nur ohne Telegram zu (Cockpit-Event), damit kein Prozess-Rennen entsteht."""
    chat = _cfg().get("allowed_chat_id")
    if not chat:
        return
    try:
        from core.agency import erinnerungen

        erinnerungen.zustellen(lambda t: _send(client, chat, t))
    except Exception:  # noqa: BLE001
        pass


def _maybe_evening_resuemee(client: httpx.Client) -> None:
    """Einmal am Abend das Tagewerk pushen — Feierabend-Blick ohne Nachfragen. Raist nie."""
    chat = _cfg().get("allowed_chat_id")
    if not chat or not _resuemee_due():
        return
    try:
        import json
        _RESUEMEE_FILE.write_text(json.dumps({"date": time.strftime("%Y-%m-%d")}),
                                  encoding="utf-8")
        _send(client, chat, "🌙 **Feierabend-Blick** — das war mein Tag:\n\n" + _tagewerk_text())
        events.emit("telegram_resuemee", {"zeit": _resuemee_zeit()})
    except Exception:  # noqa: BLE001
        pass


def _tasks_text() -> str:
    """Kompakte Liste der naechsten offenen Aufgaben (fuer den Aufgaben-Knopf)."""
    try:
        from core.agency.missions import queue
        items = queue.pending(limit=8)
    except Exception:  # noqa: BLE001
        return "Aufgaben gerade nicht abrufbar."
    if not items:
        return "📋 Keine offenen Aufgaben."
    lines = ["📋 <b>Offene Aufgaben</b>"]
    for t in items:
        lines.append("• " + _tg_html(str(t.get("description") or "?")[:90]))
    return "\n".join(lines)


def _panel_markup() -> dict:
    """Knopfleiste des Steuerpults — spiegelt den aktuellen Zustand (Heartbeat an/aus)."""
    hb = False
    try:
        from core.kernel.scheduler import heartbeat_on
        hb = heartbeat_on()
    except Exception:  # noqa: BLE001
        pass
    return {"inline_keyboard": [
        [{"text": "💤 Heartbeat AUS" if hb else "💓 Heartbeat AN",
          "callback_data": "ctl:hb:" + ("off" if hb else "on")}],
        [{"text": "🔄 Aktualisieren", "callback_data": "ctl:refresh"},
         {"text": "📋 Aufgaben", "callback_data": "ctl:tasks"}],
        [{"text": "🔔 Freigaben", "callback_data": "ctl:freigaben"},
         {"text": "📅 Tagewerk", "callback_data": "ctl:tagewerk"}],
    ]}


def _send_panel(chat_id: int) -> None:
    """Steuerpult senden: Status-Text + Knopfleiste."""
    try:
        _ctrl().post(f"{API}/sendMessage",
                     json={"chat_id": chat_id, "text": "🎛 <b>Steuerpult</b>\n" + _status_text(),
                           "parse_mode": "HTML", "reply_markup": _panel_markup()})
    except Exception:  # noqa: BLE001
        pass


def _handle_command(client: httpx.Client, chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("start", "help"):
        _send(client, chat_id,
              f"Ich bin {_AGENT}. Schreib oder sprich mir einfach — oder tippe „/“ fuer das Menue.\n"
              "Befehle:\n"
              "/status – Heartbeat, Budget & Modell auf einen Blick\n"
              "/tagewerk – was ich HEUTE geschafft habe (Tasks, Mails, Skills, Kosten)\n"
              "/todo – deine Todos mit Abhak-Knoepfen · „todo: Reifen wechseln“ legt sofort eins an\n"
              "/fokus <richtung> – Tagesfokus setzen (/fokus - loescht) — ich plane darum herum\n"
              "/kalibrierung – wie meine Modelle laufen (Fehler/Kosten/Empfehlungen)\n"
              "/steuer – Steuerpult mit Knoepfen (Heartbeat, Aufgaben, Freigaben, Tagewerk)\n"
              "/freigaben – offene Eintraege entscheiden (🔔 Aktion · 💶 Anfrage · 📋 Info)\n"
              "/plan <große aufgabe> – ich erstelle einen Plan und arbeite ihn Schritt fuer Schritt ab\n"
              f"/code <coding-auftrag> – Coding-Modus (an {_AGENT} selbst schrauben; erbt den Chat davor)\n"
              "/work <auftrag> – voller Werkzeug-Modus fuer laengere Aufgaben\n"
              "/denken an|aus – Gedankenstrom sichtbar machen (laeuft dann auf dem Denker GLM)\n"
              "/emoji – deine animierten Emoji als Neon-Glow im Denk-Status lernen\n"
              "/effekt an|aus – animierter Effekt auf erledigten Antworten\n"
              "/act <aufgabe>  – ich nutze Werkzeuge (z.B. Web), um etwas zu erledigen\n"
              "/build <idee>   – ich baue mir ein neues Werkzeug\n"
              "/model – Modelle anzeigen/wechseln\n"
              "/stop  – Not-Aus (ich halte sofort an)\n"
              "/go    – Not-Aus aufheben")
        return
    if cmd == "status":
        _send(client, chat_id, _status_text())
        return
    if cmd == "tagewerk":
        _send(client, chat_id, _tagewerk_text())
        return
    if cmd in ("kalibrierung", "kalib"):
        _send(client, chat_id, _kalibrierung_text())
        return
    if cmd == "todo":
        if rest:  # /todo <text> = anlegen (wie 'todo: <text>')
            from core.agency.tools import life_tools
            _send(client, chat_id, "📝 " + life_tools.todo_add(rest))
        else:
            _send_todos(chat_id)
        return
    if cmd == "fokus":
        from core.agency import fokus
        arg = rest.strip()
        if not arg:
            cur = fokus.get().get("focus") or ""
            _send(client, chat_id, ("🧭 Aktueller Fokus:\n<i>" + cur + "</i>\n\n" if cur
                   else "🧭 Kein Fokus gesetzt.\n\n")
                  + "Setzen: <code>/fokus Steuerunterlagen vorbereiten</code> · "
                    "Loeschen: <code>/fokus -</code>")
        elif arg in ("-", "aus", "loeschen", "löschen", "clear"):
            fokus.set_focus("", via="telegram")
            _send(client, chat_id, "🧭 **Fokus geloescht** — ich plane wieder frei.")
        else:
            fokus.set_focus(arg, via="telegram")
            _send(client, chat_id, "🧭 **Fokus gesetzt:** " + arg + "\n"
                  "Ich plane meine naechsten Schritte darum herum (offene Queue geleert).")
        return
    if cmd in ("steuer", "panel"):
        _send_panel(chat_id)
        return
    if cmd in ("freigaben", "freigabe", "inbox"):
        from core.agency import approvals
        pend = approvals.pending()
        if not pend:
            _send(client, chat_id, "✅ Keine offenen Freigaben.")
            return
        _send(client, chat_id, f"🔔 <b>{len(pend)} offene Freigabe(n)</b> — tippe ✅ oder ❌:")
        for appr in pend[:10]:
            _send_approval_card(client, chat_id, appr)
        if len(pend) > 10:
            _send(client, chat_id, f"… und {len(pend) - 10} weitere. (/freigaben erneut fuer den Rest)")
        return
    if cmd == "plan":
        if not rest:
            _send(client, chat_id, "Nutzung: /plan <große, mehrstufige Aufgabe>")
            return
        _agentic_reply(client, chat_id, f"telegram-{chat_id}", "plan: " + rest)
        return
    if cmd == "code":
        if not rest:
            _send(client, chat_id, f"Nutzung: /code <coding-auftrag an {_AGENT}, z.B. einen Bug fixen>")
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
    if cmd == "denken":
        arg = rest.lower().strip()
        if arg in ("an", "on", "ein", "1"):
            _denken_set(chat_id, True)
            _send(client, chat_id, "💜 <b>Denken an</b> — ich zeige dir jetzt meinen Gedankenstrom "
                  "(laeuft auf dem Denker GLM, etwas teurer). <code>/denken aus</code> schaltet zurueck.")
        elif arg in ("aus", "off", "0"):
            _denken_set(chat_id, False)
            _send(client, chat_id, "💤 <b>Denken aus</b> — zurueck auf schnelle, guenstige Antworten.")
        else:
            _send(client, chat_id, "Denken ist gerade <b>" + ("an" if _denken_on(chat_id) else "aus")
                  + "</b>. Nutzung: <code>/denken an</code> · <code>/denken aus</code>")
        return
    if cmd == "emoji":
        # Der echte Lern-Weg laeuft in _handle (braucht die Entities); hier nur die Erklaerung,
        # falls /emoji ohne Emoji ueber das Menue kommt.
        _send(client, chat_id, "So geht's: schreib <code>/emoji</code> und häng in DIESELBE Nachricht "
              "deine <b>animierten</b> (Premium-)Emoji dran — dann lerne ich sie als Neon-Glow. "
              f"(aktuell gelernt: {len(_emoji_ids())})")
        return
    if cmd == "effekt":
        arg = rest.lower().strip()
        if arg in ("an", "on", "ein", "1"):
            _effekt_set(chat_id, True)
            _send(client, chat_id, "🔥 <b>Effekt an</b> — erledigte Aufgaben kriegen einen animierten Effekt.")
        elif arg in ("aus", "off", "0"):
            _effekt_set(chat_id, False)
            _send(client, chat_id, "🔕 <b>Effekt aus</b> — schlichte Antworten ohne Animation.")
        else:
            _send(client, chat_id, "Effekt ist gerade <b>" + ("an" if _effekt_on(chat_id) else "aus")
                  + "</b>. Nutzung: <code>/effekt an</code> · <code>/effekt aus</code>")
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

    runstate.enter_turn(f"telegram-{chat_id}")  # aktiver Zug -> Neustart wartet; Watchdog misst DIESE Session
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
        runstate.exit_turn(f"telegram-{chat_id}")  # idle -> ein aufgeschobener Neustart wird jetzt ausgeloest


# --- Inline-Buttons: Freigaben per Knopfdruck (✅/❌) direkt in der Nachricht ---
def _answer_cb(cq_id: str, text: str = "") -> None:
    """Bestaetigt Telegram den Button-Klick (sonst dreht sich beim Nutzer ewig das Raedchen)."""
    try:
        _ctrl().post(f"{API}/answerCallbackQuery", json={"callback_query_id": cq_id, "text": text})
    except Exception:  # noqa: BLE001
        pass


# Praxis-Fund (08.07.): "Freigabe noetig" stand auf ALLEM — auch auf reinen Infos.
# Jede Karte sagt jetzt ehrlich, was der Knopf WIRKLICH tut. Drei Klassen:
#   AKTION (🔔): dein GO fuehrt sofort etwas aus (Mail senden, posten, anwenden).
#   ANFRAGE (💶/🌐): dein GO erlaubt nur — Kira muss die Aktion danach selbst anstossen.
#   INFO (📋, alles andere/generic): Knopf raeumt nur die Inbox auf, nichts passiert.
_KIND_CARDS = {
    "email_stranger": ("🔔 Freigabe noetig", "✅ sendet die E-Mail SOFORT.",
                       "✅ Senden", "❌ Nicht senden"),
    "publish": ("🔔 Freigabe noetig", "✅ postet SOFORT (Aussenwirkung).",
                "✅ Posten", "❌ Nicht posten"),
    "email": ("🔔 Freigabe noetig", "✅ sendet die E-Mail SOFORT.",
              "✅ Senden", "❌ Nicht senden"),
    "evolution": ("🔔 Freigabe noetig", "✅ wendet den Vorschlag an (Backup automatisch).",
                  "✅ Anwenden", "❌ Verwerfen"),
    "playbook": ("🔔 Freigabe noetig", "✅ befoerdert das Playbook eine Stufe.",
                 "✅ Befoerdern", "❌ Ablehnen"),
    "money": ("💶 Geld-Anfrage", "Nur eine Erlaubnis — durch den Klick fliesst KEIN Geld; "
              "Der Agent muss die Aktion danach selbst anstossen.",
              "✅ Erlauben", "❌ Ablehnen"),
    "external": ("🌐 Anfrage", "Nur eine Erlaubnis — der Agent muss die Aktion danach selbst anstossen.",
                 "✅ Erlauben", "❌ Ablehnen"),
}
_INFO_CARD = ("📋 Zur Kenntnis / Entscheidung", "Info-Eintrag: der Knopf aendert nichts "
              "automatisch, er raeumt nur die Inbox auf.", "✔ Gelesen", "🗑 Verwerfen")


def _approval_card(appr: dict) -> tuple[str, dict]:
    """Pure Karten-Renderer (testbar): (HTML-Text, Inline-Keyboard) fuer eine Freigabe."""
    aid = appr.get("id") or ""
    kind = (appr.get("kind") or "").strip()
    head, folge, ok_label, no_label = _KIND_CARDS.get(kind, _INFO_CARD)
    title = _tg_html((appr.get("title") or "Freigabe"))
    detail = _tg_html((appr.get("detail") or "").strip()[:600])
    text = f"<b>{head}</b>\n{title}" + (("\n" + detail) if detail else "") \
        + f"\n\n<i>{_tg_html(folge)}</i>"
    kb = {"inline_keyboard": [[
        {"text": ok_label, "callback_data": f"appr:ok:{aid}"},
        {"text": no_label, "callback_data": f"appr:no:{aid}"},
    ]]}
    return text, kb


def _send_approval_card(client: httpx.Client, chat_id: int, appr: dict) -> None:
    """Eine Freigabe als Nachricht mit Entscheidungs-Knoepfen (Beschriftung je nach Art)."""
    if not appr.get("id"):
        return
    text, kb = _approval_card(appr)
    try:
        _ctrl().post(f"{API}/sendMessage",
                     json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": kb})
    except Exception:  # noqa: BLE001
        pass


# Push: neue Freigaben proaktiv an den Nutzer schicken (statt dass er /freigaben tippt).
# Beim Start werden bestehende Pendings als "bekannt" markiert -> kein Spam alter Eintraege.
_pushed_approvals: set = set()


def _seed_pushed_approvals() -> None:
    try:
        from core.agency import approvals
        approvals.init_approvals()
        _pushed_approvals.update(a["id"] for a in approvals.pending())
    except Exception:  # noqa: BLE001
        pass


def _push_new_approvals(client: httpx.Client) -> None:
    """Neue offene Freigaben als ✅/❌-Karte an den erlaubten Chat schicken (max 5/Runde ->
    kein Flut-Risiko; der Rest kommt in den naechsten Runden). Raist nie."""
    chat = _cfg().get("allowed_chat_id")
    if not chat:
        return
    try:
        from core.agency import approvals
        pend = approvals.pending()
    except Exception:  # noqa: BLE001
        return
    new = [a for a in pend if a.get("id") and a["id"] not in _pushed_approvals]
    for a in new[:5]:
        _pushed_approvals.add(a["id"])
        _send_approval_card(client, chat, a)


def _handle_ctl(client: httpx.Client, cq: dict, data: str) -> None:
    """Steuerpult-Knoepfe (ctl:*): Heartbeat schalten, aktualisieren, Aufgaben/Freigaben zeigen.
    Danach das Panel neu rendern, damit die Knoepfe den neuen Zustand spiegeln."""
    cq_id = cq.get("id")
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    mid = msg.get("message_id")
    toast = "aktualisiert"
    if data in ("ctl:hb:on", "ctl:hb:off"):
        on = data.endswith(":on")
        try:
            from core.kernel.scheduler import set_heartbeat
            set_heartbeat(on)
            events.emit("heartbeat_toggle", {"on": on, "via": "telegram-button"})
        except Exception:  # noqa: BLE001
            pass
        toast = "💓 Heartbeat an" if on else "💤 Heartbeat aus"
    elif data == "ctl:tasks":
        _answer_cb(cq_id, "Aufgaben")
        if chat_id:
            _send(client, chat_id, _tasks_text())
        return
    elif data == "ctl:tagewerk":
        _answer_cb(cq_id, "Tagewerk")
        if chat_id:
            _send(client, chat_id, _tagewerk_text())
        return
    elif data == "ctl:freigaben":
        _answer_cb(cq_id, "Freigaben")
        if chat_id:
            _handle_command(client, chat_id, "/freigaben")
        return
    _answer_cb(cq_id, toast)
    if chat_id and mid:  # Panel an Ort und Stelle aktualisieren (Text + Knoepfe)
        try:
            _ctrl().post(f"{API}/editMessageText",
                         json={"chat_id": chat_id, "message_id": mid,
                               "text": "🎛 <b>Steuerpult</b>\n" + _status_text(),
                               "parse_mode": "HTML", "reply_markup": _panel_markup()})
        except Exception:  # noqa: BLE001
            pass


def _handle_callback(client: httpx.Client, cq: dict) -> None:
    """Button-Klick: Freigabe-Karte (appr:*) entscheiden ODER Steuerpult (ctl:*) bedienen.
    Fremde callback_data wird nur bestaetigt (Raedchen stoppen). Raist nie."""
    data = cq.get("data") or ""
    cq_id = cq.get("id")
    if data.startswith("ctl:"):
        _handle_ctl(client, cq, data)
        return
    m_todo = re.match(r"todo:done:([0-9a-f]{4,})$", data)
    if m_todo:
        from core.agency.tools import life_tools
        res = life_tools.todo_done(m_todo.group(1))
        _answer_cb(cq_id, res[:180])
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        mid = msg.get("message_id")
        if chat_id and mid:  # Liste an Ort und Stelle aktualisieren
            text, kb = _todo_overview()
            payload = {"chat_id": chat_id, "message_id": mid, "text": text, "parse_mode": "HTML"}
            if kb:
                payload["reply_markup"] = kb
            try:
                _ctrl().post(f"{API}/editMessageText", json=payload)
            except Exception:  # noqa: BLE001
                pass
        return
    m = re.match(r"appr:(ok|no):([0-9a-f]+)$", data)
    if not m:
        _answer_cb(cq_id, "")
        return
    approved = m.group(1) == "ok"
    aid = m.group(2)
    from core.agency import approvals
    res = approvals.decide(aid, approved, note="via Telegram-Button")
    if res.get("ok"):
        toast = "✅ Freigegeben" if approved else "❌ Abgelehnt"
    elif res.get("error") == "already decided":
        toast = "Schon entschieden"
    else:
        toast = "Nicht gefunden"
    _answer_cb(cq_id, toast)
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    mid = msg.get("message_id")
    if chat_id and mid:
        appr = approvals.get(aid) or {}
        kind = (appr.get("kind") or "").strip()
        icon = _KIND_CARDS.get(kind, _INFO_CARD)[0].split(" ", 1)[0]
        head = icon + " " + _tg_html(appr.get("title") or "Freigabe")
        if res.get("ok") and kind in _KIND_CARDS:
            state = "✅ <b>Freigegeben</b>" if approved else "❌ <b>Abgelehnt</b>"
        elif res.get("ok"):  # Info-Eintrag: ehrliche Wortwahl statt "Freigegeben"
            state = "✔ <b>Gelesen</b>" if approved else "🗑 <b>Verworfen</b>"
        else:
            state = "• " + toast
        events.emit("approval_decided_telegram", {"id": aid, "approved": approved, "ok": res.get("ok")})
        try:  # editMessageText ohne reply_markup entfernt die Knoepfe automatisch
            _ctrl().post(f"{API}/editMessageText",
                         json={"chat_id": chat_id, "message_id": mid,
                               "text": head + "\n" + state, "parse_mode": "HTML"})
        except Exception:  # noqa: BLE001
            pass


def _dispatch(client: httpx.Client, update: dict) -> None:
    """Eine Aufgabe pro Chat gleichzeitig; weitere Nachrichten kommen kurz in die Queue
    (max 3) und werden danach der Reihe nach abgearbeitet -> keine Thread-Flut, keine
    verlorenen Antworten durch Telegram-Rate-Limit."""
    cq = update.get("callback_query")
    if cq:  # Button-Klicks sind schnell -> inline, nicht ueber die Chat-Warteschlange
        _handle_callback(client, cq)
        return
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
# klickt der Nutzer ins Leere. Reihenfolge = Anzeige-Reihenfolge im Menue.
_BOT_COMMANDS = [
    ("status", "Heartbeat, Budget & Modell auf einen Blick"),
    ("tagewerk", "Was HEUTE geschafft wurde (Tasks, Mails, Kosten)"),
    ("todo", "Todos: Liste mit Abhak-Knöpfen · /todo <text> legt an"),
    ("fokus", "Tagesfokus setzen/löschen – der Plan richtet sich danach"),
    ("steuer", "Steuerpult – Heartbeat, Aufgaben, Freigaben per Knopf"),
    ("freigaben", "Offene Einträge entscheiden (Aktion/Anfrage/Info)"),
    ("kalibrierung", "Modell-Report: Fehler, Kosten, Empfehlungen (7 Tage)"),
    ("code", "Coding-Modus: am Agenten selbst schrauben"),
    ("plan", "Große Aufgabe planen und Schritt für Schritt abarbeiten"),
    ("work", "Längerer Auftrag mit vollem Werkzeug-Budget"),
    ("denken", "Gedankenstrom an/aus – zeigt, wie ich denke (läuft auf GLM)"),
    ("emoji", "Animierte Emoji als Neon-Glow im Denk-Status lernen"),
    ("effekt", "Animierter Effekt auf erledigten Antworten an/aus"),
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
    # Instanz-Lock ZUERST (noch vor dem Token-Check): der Bot ist der schlimmste
    # Doppelgaenger — zwei getUpdates-Poller klauen sich gegenseitig die Nachrichten
    # (Telegram-409). Ein zweiter Start (Autostart + manuell + Dev-Preview) beendet
    # sich hier sofort und sauber. Das Objekt lebt bis zum Prozessende (haelt den Lock).
    lock = instance_lock.acquire("telegram_bot")  # noqa: F841 — Besitz = Lock
    if lock is None:
        print(instance_lock.blocked_msg("telegram_bot", "Ein Telegram-Bot"))
        return
    if not TOKEN:
        # W3: SCHLAFEN statt beenden — sonst startet der Supervisor den Bot alle paar
        # Sekunden neu und flutet einen frischen Klon mit service_crash-Events. Nach dem
        # /setup-Wizard bounct der Supervisor den Bot (restart.flag) -> frischer Prozess
        # laedt den Token aus dem Tresor.
        print("TELEGRAM_BOT_TOKEN fehlt — Bot schlaeft (Token via /setup oder .env; danach Neustart).")
        import time as _t
        while True:
            _t.sleep(3600)
    events.init_db()
    _register_commands(_ctrl())  # '/'-Menue bei Telegram anmelden (einmalig beim Start)
    _seed_pushed_approvals()     # bestehende Freigaben als bekannt markieren (kein Alt-Spam)
    try:  # MCP-Bruecke im Hintergrund anschliessen (Ausfall darf den Boot nie bricken)
        from core.agency.mcp import registry_bridge as _mcp_bridge
        _mcp_bridge.init_background()
    except Exception:  # noqa: BLE001
        pass
    from core.kernel import runstate
    runstate.start_watchdog()  # festgefahrene Chat-Zuege erkennen -> Force-Restart (kein wedged Bot)
    offset: int | None = _load_offset()   # ueberlebt Neustart/Absturz -> kein Doppel-Beantworten
    backoff = 2.0      # S8.0: exponentiell bei Stoerungen (2s -> 60s), Reset bei Erfolg
    err_state: dict = {}
    print("Telegram-Bot laeuft (Long-Polling). Strg+C zum Stoppen.")
    with httpx.Client(timeout=75) as client:
        while True:
            if kill_switch_active():
                print("KILL-SWITCH aktiv — Bot haelt an.")
                break
            _push_new_approvals(client)  # jede Runde (~60s): neue Freigaben proaktiv schicken
            _maybe_evening_resuemee(client)  # einmal am Abend: Tagewerk von selbst
            _maybe_melde_buendel(client)     # Missions-Meldungen gebuendelt statt Flut
            _maybe_erinnerungen(client)      # faellige Einmal-Wecker aktiv zustellen
            try:
                resp = client.get(f"{API}/getUpdates", params={"timeout": 60, "offset": offset})
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    _save_offset(offset)   # VOR dem Dispatch persistieren: ein Absturz/Abbruch
                    _dispatch(client, update)   # mitten im Handling beantwortet die Nachricht NICHT erneut
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