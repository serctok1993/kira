"""Handlungs-Schleife (ReAct-lite): Kira loest eine Aufgabe mit Werkzeugen.

Modellunabhaengiges Textprotokoll (robuster als natives Function-Calling bei
lokalen GGUF-Modellen): Kira antwortet entweder mit

    ACT <tool_name> {json-argumente}

oder, wenn er fertig ist, mit normalem Text (= Endergebnis). Jeder Werkzeug-
Aufruf laeuft durch den Executor (Kill-Switch, Retry, Circuit-Breaker, Log).
"""
from __future__ import annotations

import json
import re

from core.kernel import events, executor, llm_router
from core.agency.tools import builtin  # noqa: F401  -> registriert die eingebauten Tools
from core.agency.tools import registry, synthesize
from core.mind.agent import _read, PERSONA_DIRECTIVE, build_system_prompt
from core.mind.memory import store as memory

# Frueher von Kira selbst gebaute Werkzeuge wieder verfuegbar machen.
synthesize.load_synthesized()

_ACT_RE = re.compile(r"^\s*ACT\s+(\w+)\s+(\{.*\})\s*$", re.MULTILINE | re.DOTALL)


def _identity() -> str:
    return (
        f"# DEINE VERFASSUNG\n{_read('constitution.md')}\n\n"
        f"# DEINE SEELE\n{_read('SOUL.md')}\n\n"
        f"# DEIN ZIEL\n{_read('GOAL.md')}\n\n"
        f"{PERSONA_DIRECTIVE}"
    )


def _parse_act(text: str):
    m = _ACT_RE.search(text)
    if not m:
        return None
    try:
        args = json.loads(m.group(2))
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict):
        return None
    return m.group(1), args


def act(task: str, session_id: str | None = None, max_steps: int = 8, escalate: bool = False) -> dict:
    system = _identity() + f"""

# WERKZEUGE
Du kannst Werkzeuge benutzen, um Aufgaben in der echten Welt zu erledigen:
{registry.manifest()}

So benutzt du ein Werkzeug — antworte mit GENAU einer Zeile, sonst nichts:
ACT <werkzeug_name> {{"argument": "wert"}}
Beispiel: ACT web_fetch {{"url": "https://example.com"}}

Du bekommst danach das ERGEBNIS und kannst ein weiteres Werkzeug nutzen oder,
wenn du genug weisst, normal antworten (ohne ACT) — das ist dann dein Endergebnis
fuer Sergen. Nutze Werkzeuge nur, wenn noetig.

Denke vor jedem Schritt gruendlich Schritt fuer Schritt nach, was der beste
naechste Zug ist, bevor du handelst.

WICHTIG: Gib nicht auf und sage nicht "keine Treffer". Wenn dir Informationen
fehlen, BENUTZE web_search (Stichworte) und danach web_fetch auf die besten Links,
um die Inhalte wirklich zu lesen. Liefere am Ende eine konkrete, belegte Antwort."""

    messages: list[dict] = [{"role": "user", "content": task}]
    events.emit("act_start", {"task": task}, session_id=session_id)

    for step in range(max_steps):
        res = llm_router.complete(
            messages, system=system, task_type="reason", session_id=session_id, escalate=escalate
        )
        text = res["text"].strip()
        call = _parse_act(text)

        if not call:
            events.emit("act_done", {"steps": step}, session_id=session_id)
            return {"text": text, "steps": step}

        name, args = call
        tool = registry.get(name)
        if tool is None:
            obs = f"Fehler: Werkzeug '{name}' existiert nicht. Verfuegbar: {[t.name for t in registry.all_tools()]}"
        else:
            try:
                obs = str(executor.run_tool(name, tool.func, **args))
            except Exception as e:  # noqa: BLE001
                obs = f"Fehler bei '{name}': {e}"

        events.emit(
            "act_step",
            {"step": step, "tool": name, "args": args, "obs_preview": obs[:200]},
            session_id=session_id,
        )
        messages.append({"role": "assistant", "content": text})
        messages.append(
            {"role": "user", "content": f"ERGEBNIS von {name}:\n{obs}\n\nMach weiter oder gib die finale Antwort."}
        )

    # Schrittlimit erreicht -> erzwinge eine finale Zusammenfassung aus dem Recherchierten.
    messages.append({
        "role": "user",
        "content": "Du hast genug recherchiert. Fasse JETZT deine Erkenntnisse als finale, "
                   "konkrete Antwort fuer Sergen zusammen — ohne weitere Werkzeuge (kein ACT).",
    })
    res = llm_router.complete(messages, system=system, task_type="reason", session_id=session_id, escalate=escalate)
    events.emit("act_truncated_summary", {"steps": max_steps}, session_id=session_id)
    return {"text": res["text"].strip(), "steps": max_steps}


def act_chat(user_message: str, session_id: str, max_steps: int = 6, escalate: bool = False, on_event=None) -> str:
    """Konversationeller, agentischer Chat: Gedaechtnis + Persona + Werkzeuge.

    Streamt Denken live und meldet Tool-Schritte ueber on_event(dict):
      {"kind":"think","text":...} | {"kind":"tool","name":...,"args":...}
      {"kind":"obs","name":...,"text":...} | {"kind":"final","text":...}
    Gibt die finale Antwort zurueck. Nur die finale Antwort kommt ins Gedaechtnis.
    """
    def emit(ev):
        if on_event:
            try:
                on_event(ev)
            except Exception:
                pass

    events.emit("user_message", {"text": user_message}, session_id=session_id)
    history = memory.recent_dialogue(session_id, limit=10)
    memory.remember(user_message, role="user", session_id=session_id)

    system = build_system_prompt(user_message, session_id=session_id) + f"""

# WERKZEUGE (nutze sie, wenn die Aufgabe es braucht)
{registry.manifest()}

Brauchst du ein Werkzeug, antworte mit GENAU einer Zeile (sonst nichts):
ACT <werkzeug_name> {{"argument": "wert"}}
Beispiel: ACT web_search {{"query": "Wetter Koblenz heute"}}
Danach bekommst du das ERGEBNIS und kannst weiter ein Werkzeug nutzen oder normal antworten.
Wenn du etwas Aktuelles nicht sicher weisst (Wetter, Preise, News, Webinhalte): NICHT raten,
sondern web_search/web_fetch nutzen. Sonst antworte direkt, natuerlich und vollstaendig."""

    messages = [
        {"role": "assistant" if h["role"] == "partner" else "user", "content": h["text"]}
        for h in history
    ]
    messages.append({"role": "user", "content": user_message})

    for step in range(max_steps):
        parts = []
        for piece in llm_router.stream_tagged(
            messages, system=system, task_type="reason", session_id=session_id, escalate=escalate
        ):
            if piece["kind"] == "think":
                emit({"kind": "think", "text": piece["text"]})
            else:
                parts.append(piece["text"])
        text = "".join(parts).strip()
        call = _parse_act(text)
        if not call:
            memory.remember(text, role="partner", session_id=session_id)
            events.emit("partner_message", {"text": text, "agentic": True}, session_id=session_id)
            emit({"kind": "final", "text": text})
            return text
        name, args = call
        emit({"kind": "tool", "name": name, "args": args})
        tool = registry.get(name)
        if tool is None:
            obs = f"Fehler: Werkzeug '{name}' existiert nicht."
        else:
            try:
                obs = str(executor.run_tool(name, tool.func, **args))
            except Exception as e:  # noqa: BLE001
                obs = f"Fehler bei '{name}': {e}"
        emit({"kind": "obs", "name": name, "text": obs[:200]})
        events.emit("act_step", {"step": step, "tool": name, "args": args, "obs_preview": obs[:160]}, session_id=session_id)
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": f"ERGEBNIS von {name}:\n{obs}\n\nMach weiter oder gib die finale Antwort."})

    messages.append({"role": "user", "content": "Fasse jetzt final fuer Sergen zusammen — ohne weiteres ACT."})
    res = llm_router.complete(messages, system=system, task_type="reason", session_id=session_id, escalate=escalate)
    text = res["text"].strip()
    memory.remember(text, role="partner", session_id=session_id)
    events.emit("partner_message", {"text": text, "agentic": True}, session_id=session_id)
    emit({"kind": "final", "text": text})
    return text


def act_chat_stream(user_message: str, session_id: str, escalate: bool = False):
    """Generator-Variante von act_chat fuers WebSocket-Cockpit.

    yields die Events {kind: 'think'|'tool'|'obs'|'final', ...}. act_chat laeuft in
    einem Thread; die Events kommen ueber eine Queue an.
    """
    import queue as _queue
    import threading

    out: "_queue.Queue" = _queue.Queue()
    sentinel = {"kind": "__done__"}

    def run():
        try:
            act_chat(user_message, session_id, escalate=escalate, on_event=out.put)
        except Exception as e:  # noqa: BLE001
            out.put({"kind": "final", "text": f"(Fehler: {e})"})
        finally:
            out.put(sentinel)

    threading.Thread(target=run, daemon=True).start()
    while True:
        ev = out.get()
        if ev is sentinel:
            break
        yield ev


if __name__ == "__main__":
    import sys

    t = " ".join(sys.argv[1:]) or "Lies https://example.com und sage in einem Satz, worum es geht."
    print(act(t)["text"])
