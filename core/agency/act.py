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
from core.config import CONFIG

# Frueher von Kira selbst gebaute Werkzeuge wieder verfuegbar machen.
synthesize.load_synthesized()

# --- Agentische Ausdauer (Claude-Code-artig) ---------------------------------
# Hohe Decken, damit ein langer Task DURCHLAEUFT statt nach wenigen Runden zwangs-
# weise abzubrechen. Die Schleife endet ohnehin frueh, sobald Kira fertig ist (keine
# tool_calls mehr) -- diese Decken sind nur das Sicherheitsnetz gegen Endlosschleifen,
# NICHT der Normal-Ausstieg. Alle drei ueber config.yaml (Sektion 'agency') justierbar.
_AG = CONFIG.get("agency", {}) if isinstance(CONFIG.get("agency"), dict) else {}
_MAX_STEPS = int(_AG.get("max_steps", 40))                 # Werkzeug-Runden pro TASK (vorher hart 8)
_MAX_STEPS_PLAN = int(_AG.get("max_steps_plan_step", 12))  # Runden pro Plan-Teilschritt (vorher hart 6)
_OBS_MAX = int(_AG.get("obs_max_chars", 16000))            # wie viel Werkzeug-Ergebnis das Modell sieht (vorher 6000)
_MAX_STEPS_CHAT = int(_AG.get("max_steps_chat", 8))        # knapper Deckel fuer NORMALEN Chat -> kein 80er-Sturm bei Small-Talk (voller Task-Deckel via /work oder /plan)

_ACT_RE = re.compile(r"ACT\s+([a-zA-Z_]\w*)\s*\{")


def _identity() -> str:
    return (
        f"# DEINE VERFASSUNG\n{_read('constitution.md')}\n\n"
        f"# DEINE SEELE\n{_read('SOUL.md')}\n\n"
        f"# DEIN ZIEL\n{_read('GOAL.md')}\n\n"
        f"{PERSONA_DIRECTIVE}"
    )


def _parse_act(text: str):
    """Findet 'ACT <tool> {json}' robust — auch mit Prosa oder Code-Fences drumherum,
    damit Tool-Aufrufe nie als Antwort durchsickern. JSON wird ab der '{'-Position
    dekodiert (raw_decode ignoriert nachfolgenden Text)."""
    t = text.replace("`", " ").replace("*", " ")  # Fences/Deko entschaerfen, Laenge bleibt 1:1
    m = _ACT_RE.search(t)
    if not m:
        return None
    name = m.group(1)
    brace = m.end() - 1  # Index des '{'
    try:
        args, _ = json.JSONDecoder().raw_decode(text[brace:])
    except json.JSONDecodeError:
        return None
    return (name, args) if isinstance(args, dict) else None


_NATIVE_TOOLS_HINT = """

# WERKZEUGE
Du hast Werkzeuge (Web suchen/lesen, Dateien lesen/schreiben, Befehle ausfuehren, dich selbst
bearbeiten, Gedaechtnis, Monitor/Cron ...). Nutze sie bei Bedarf ueber die bereitgestellten
Funktionen. Du laeufst auf WINDOWS (PowerShell/cmd) — zum Erkunden/Lesen von Dateien nutze
list_dir/read_file (NICHT shell-Befehle wie find/grep/ls) und KEINE Linux-Pfade wie /workspace
oder $HOME. Wenn du etwas Aktuelles nicht sicher weisst (Wetter/News/Preise/Webinhalte) oder
Dateiinhalte brauchst: RATE NICHT — hol es dir mit dem passenden Werkzeug. Wenn du genug weisst,
antworte normal, natuerlich und vollstaendig fuer Sergen (ohne weiteren Werkzeug-Aufruf).
WICHTIG: Kuendige Aktionen NICHT nur an, um dann aufzuhoeren. Wenn du etwas nachsehen oder tun
willst, RUF die Werkzeuge SOFORT in DIESEM Zug auf und antworte erst mit dem Ergebnis. Eine
Antwort wie "lass mich kurz schauen ..." OHNE einen Werkzeug-Aufruf ist verboten."""


_PROMISE_RE = re.compile(
    r"(lass mich|ich schau|ich sehe nach|ich pruef|ich check|moment\b|kurz schauen|"
    r"schau(e)?\s+(mal|kurz)|sehe (mal )?nach|melde mich gleich)", re.IGNORECASE)


def _looks_like_promise(text: str) -> bool:
    """Erkennt eine 'ich tu gleich was'-Antwort ohne tatsaechliche Handlung (Heuristik)."""
    t = (text or "").strip()
    if not t:
        return True
    return len(t) <= 400 and (t.endswith(":") or bool(_PROMISE_RE.search(t)))


def _cloud(escalate: bool, task_type: str = "reason") -> bool:
    """True, wenn das aufzurufende Modell ein Cloud-/Provider-Modell ist (nicht lokal Ollama)."""
    model, _ = llm_router.resolve_model(task_type, escalate=escalate)
    real, _ab, _ke = llm_router._provider_config(model)
    return not real.startswith("ollama")


def _complete_resilient(*args, **kwargs):
    """Ein LLM-Call, der einen transienten Fehler (Provider/Netz/Ratelimit/402) EINMAL
    kurz abfedert, statt sofort den ganzen Task abzureissen. Wirft erst, wenn auch der
    zweite Versuch scheitert -> der Aufrufer degradiert dann sauber (kein Voll-Abbruch)."""
    import time as _t
    try:
        return llm_router.complete(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        events.emit("llm_call_error", {"error": str(e)[:300], "retry": True},
                    session_id=kwargs.get("session_id"))
        _t.sleep(2)
        return llm_router.complete(*args, **kwargs)  # zweiter Versuch; scheitert der -> raise


def _degrade_text(messages: list[dict], err: Exception) -> str:
    """Graceful Degrade OHNE weiteren LLM-Call: kurzer Bericht ueber die bisher gemachten
    Werkzeug-Schritte + der Fehler. So verwirft ein transienter Modellausfall nicht den
    ganzen Task (und Kiras Arbeit) — Sergen kann mit 'weiter' den Faden aufnehmen."""
    used: list[str] = []
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            fn = (tc.get("function") or {}).get("name")
            if fn:
                used.append(fn)
    steps = ", ".join(used[-8:]) if used else "keine abgeschlossenen Schritte"
    return ("⚠️ Ich bin bei einem Modell-/Netzwerk-Schritt auf einen Fehler gestossen und breche "
            "diesen Task SAUBER ab, statt ihn halb kaputt fortzusetzen.\n"
            f"Bisher gemacht: {steps}.\n"
            f"Fehler: {str(err)[:200]}\n"
            "Sag 'weiter', dann nehme ich den Faden wieder auf.")


def _native_loop(messages: list[dict], system: str, session_id, escalate: bool, emit, max_steps: int = _MAX_STEPS, task_type: str = "reason") -> str:
    """Nativer Function-Calling-Loop fuer Cloud-Modelle: strukturierte tool_calls statt
    ACT-Text — robust, kein Leak. Streamt Schritte ueber emit({'kind':'tool'|'obs'|...})."""
    schemas = registry.tool_schemas()
    used_tools = False
    nudged = False
    for step in range(max_steps):
        try:
            res = _complete_resilient(messages, system=system, task_type=task_type,
                                      session_id=session_id, escalate=escalate, tools=schemas)
        except Exception as e:  # noqa: BLE001 -> Teilstand liefern statt ganzen Task abreissen
            events.emit("act_degraded", {"step": step, "error": str(e)[:300]}, session_id=session_id)
            return _degrade_text(messages, e)
        calls = res.get("tool_calls") or []
        if not calls:
            text = res["text"].strip()
            # "Promise statt Action": etwas angekuendigt, aber kein Werkzeug genutzt -> einmal anschubsen
            if not used_tools and not nudged and _looks_like_promise(text):
                nudged = True
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": "Tu es JETZT in diesem Zug: nutze die "
                                 "passenden Werkzeuge und antworte erst mit dem Ergebnis — nicht nur ankuendigen."})
                continue
            return text
        used_tools = True
        messages.append({
            "role": "assistant",
            "content": res["text"] or None,
            "tool_calls": [
                {"id": c["id"] or f"call_{step}_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                for i, c in enumerate(calls)
            ],
        })
        for i, c in enumerate(calls):
            name, args, cid = c["name"], c["args"], (c["id"] or f"call_{step}_{i}")
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
            messages.append({"role": "tool", "tool_call_id": cid, "content": obs[:_OBS_MAX]})
    try:
        res = _complete_resilient(
            messages + [{"role": "user", "content": "Fasse jetzt final fuer Sergen zusammen — ohne weitere Werkzeuge."}],
            system=system, task_type=task_type, session_id=session_id, escalate=escalate)
    except Exception as e:  # noqa: BLE001
        events.emit("act_degraded", {"step": "final", "error": str(e)[:300]}, session_id=session_id)
        return _degrade_text(messages, e)
    return (res["text"].strip()
            or "Ich habe die Werkzeuge genutzt, aber keine saubere Schluss-Antwort hinbekommen — frag mich gern konkret nach, dann liefere ich dir das Ergebnis.")


def act(task: str, session_id: str | None = None, max_steps: int = _MAX_STEPS, escalate: bool = False, task_type: str = "reason") -> dict:
    events.emit("act_start", {"task": task}, session_id=session_id)

    # Cloud-Modelle: natives Function-Calling (robust, kein ACT-Text-Leak)
    if _cloud(escalate, task_type):
        text = _native_loop([{"role": "user", "content": task}], _identity() + _NATIVE_TOOLS_HINT,
                            session_id, escalate, emit=lambda ev: None, max_steps=max_steps, task_type=task_type)
        events.emit("act_done", {"native": True}, session_id=session_id)
        return {"text": text, "steps": max_steps}

    # Lokale Modelle: bewaehrtes Text-Protokoll (ACT <tool> {json})
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

    for step in range(max_steps):
        res = llm_router.complete(
            messages, system=system, task_type=task_type, session_id=session_id, escalate=escalate
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


def _make_plan(task: str, session_id: str | None, escalate: bool = True) -> list[str]:
    """Zerlegt eine groessere Aufgabe in 3-7 konkrete, ausfuehrbare Schritte (JSON-Array)."""
    system = _identity() + (
        "\n\nDu bist im PLANUNGS-Modus. Zerlege die Aufgabe in 3 bis 7 konkrete, ausfuehrbare "
        "Schritte. Antworte AUSSCHLIESSLICH mit einem JSON-Array kurzer Schritt-Strings, sonst "
        'nichts. Beispiel: ["Recherchiere X", "Erstelle Datei Y", "Teste Y"].'
    )
    res = llm_router.complete([{"role": "user", "content": task}], system=system,
                              task_type="reason", session_id=session_id, escalate=escalate)
    m = re.search(r"\[.*\]", res["text"], re.DOTALL)
    if m:
        try:
            steps = [str(s).strip() for s in json.loads(m.group(0)) if str(s).strip()]
            if steps:
                return steps[:8]
        except Exception:  # noqa: BLE001
            pass
    return [task]


def plan_and_execute(task: str, session_id: str | None = None, on_event=None, escalate: bool = True) -> str:
    """Plan-&-Execute-Agent: erst einen Plan erstellen, dann Schritt fuer Schritt mit Werkzeugen
    abarbeiten (inkl. self_edit), am Ende eine Zusammenfassung. Streamt ueber on_event mit denselben
    Ereignissen wie act_chat (think=Plan, tool/obs=Schritte, final=Ergebnis)."""
    def emit(ev):
        if on_event:
            try:
                on_event(ev)
            except Exception:  # noqa: BLE001
                pass

    events.emit("plan_start", {"task": task}, session_id=session_id)
    steps = _make_plan(task, session_id, escalate)
    emit({"kind": "think", "text": "📋 Plan:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) + "\n"})
    events.emit("plan_made", {"steps": steps}, session_id=session_id)

    done: list[str] = []
    for i, step in enumerate(steps, 1):
        emit({"kind": "tool", "name": f"Schritt {i}/{len(steps)}", "args": {"ziel": step[:80]}})
        ctx = ("Bisher erledigt:\n" + "\n".join(f"- {d}" for d in done) + "\n\n") if done else ""
        step_task = f"{ctx}Gesamtziel: {task}\n\nFuehre jetzt NUR diesen Schritt aus: {step}"
        try:
            out = act(step_task, session_id=session_id, max_steps=_MAX_STEPS_PLAN, escalate=escalate)["text"].strip()
        except Exception as e:  # noqa: BLE001
            out = f"Fehler: {e}"
        done.append(f"{step} -> {out[:160]}")
        emit({"kind": "obs", "name": f"Schritt {i}", "text": out[:200]})
        events.emit("plan_step", {"n": i, "step": step, "result": out[:300]}, session_id=session_id)

    synth = llm_router.complete(
        [{"role": "user", "content":
          f"Aufgabe war: {task}\n\nDu hast diese Schritte ausgefuehrt:\n"
          + "\n".join(f"{i}. {d}" for i, d in enumerate(done, 1))
          + "\n\nFasse fuer Sergen knapp und konkret zusammen, was du erreicht hast (Ergebnis, nicht der Prozess)."}],
        system=_identity(), task_type="reason", session_id=session_id, escalate=escalate,
    )
    final = synth["text"].strip()
    if not final:  # Synthese leer (Modell-Haenger/Timeout) -> NIE leer: aus den Schritten zusammenbauen
        final = ("Ich habe die Aufgabe abgearbeitet — die Abschluss-Zusammenfassung kam leer zurueck, "
                 "darum hier die Ergebnisse der Schritte direkt:\n" + "\n".join(f"• {d}" for d in done))
    events.emit("plan_done", {"task": task, "steps": len(steps)}, session_id=session_id)

    # Auto-Reflexion: aus jeder groesseren Aufgabe Lektionen ziehen (lokal, 0 EUR).
    try:
        from core.mind.reflection import reflect_on

        refl = reflect_on(task, "\n".join(done), escalate=False)
        if refl.get("lessons"):
            emit({"kind": "think", "text": "🧠 Gelernt: " + "; ".join(refl["lessons"][:2]) + "\n"})
    except Exception:  # noqa: BLE001
        pass

    emit({"kind": "final", "text": final})
    return final


def act_chat(user_message: str, session_id: str, max_steps: int = _MAX_STEPS, escalate: bool = False, on_event=None) -> str:
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

    # Plan-Modus: "plan: ..." oder "/plan ..." -> erst Plan, dann Schritt fuer Schritt (wie ein Coding-Agent)
    _s = user_message.strip()
    if _s.lower().startswith(("plan:", "/plan")):
        ptask = _s[5:].lstrip(": ").strip() or "(keine Aufgabe angegeben)"
        final = plan_and_execute(ptask, session_id=session_id, on_event=on_event, escalate=True)
        memory.remember(final, role="partner", session_id=session_id)
        events.emit("partner_message", {"text": final, "plan": True}, session_id=session_id)
        return final

    # Arbeits-Modus: /work bzw. work: -> volles Task-Budget (viele Schritte, Claude-Code-Stil).
    # Sonst knapper Chat-Deckel -> normaler Dialog laeuft nicht in einen langen Tool-Sturm.
    work_mode = _s.lower().startswith(("/work", "work:"))
    if work_mode:
        user_message = re.sub(r"^(/work|work:)\s*", "", _s, flags=re.IGNORECASE).strip() or _s
    step_ceiling = _MAX_STEPS if work_mode else _MAX_STEPS_CHAT

    messages = [
        {"role": "assistant" if h["role"] == "partner" else "user", "content": h["text"]}
        for h in history
    ]
    messages.append({"role": "user", "content": user_message})

    # Cloud-Modelle: natives Function-Calling (robust, kein ACT-Text-Leak)
    if _cloud(escalate, "chat"):
        system = build_system_prompt(user_message, session_id=session_id) + _NATIVE_TOOLS_HINT
        text = _native_loop(messages, system, session_id, escalate, emit, max_steps=step_ceiling, task_type="chat")
        memory.remember(text, role="partner", session_id=session_id)
        events.emit("partner_message", {"text": text, "agentic": True}, session_id=session_id)
        emit({"kind": "final", "text": text})
        return text

    # Lokale Modelle: bewaehrtes Text-Protokoll (ACT <tool> {json}) mit Streaming
    system = build_system_prompt(user_message, session_id=session_id) + f"""

# WERKZEUGE (nutze sie, wenn die Aufgabe es braucht)
{registry.manifest()}

Brauchst du ein Werkzeug, antworte mit GENAU einer Zeile (sonst nichts):
ACT <werkzeug_name> {{"argument": "wert"}}
Beispiel: ACT web_search {{"query": "Wetter Koblenz heute"}}
Danach bekommst du das ERGEBNIS und kannst weiter ein Werkzeug nutzen oder normal antworten.
Wenn du etwas Aktuelles nicht sicher weisst (Wetter, Preise, News, Webinhalte): NICHT raten,
sondern web_search/web_fetch nutzen. Sonst antworte direkt, natuerlich und vollstaendig."""

    for step in range(step_ceiling):
        parts = []
        for piece in llm_router.stream_tagged(
            messages, system=system, task_type="chat", session_id=session_id, escalate=escalate
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
    res = llm_router.complete(messages, system=system, task_type="chat", session_id=session_id, escalate=escalate)
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
