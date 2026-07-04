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
    try:
        from core.mind.agent import _body_compact, _playbooks_block

        koerper = _body_compact()
        pb = _playbooks_block()
    except Exception:  # noqa: BLE001
        koerper = ""
        pb = ""
    return (
        f"# DEINE VERFASSUNG\n{_read('constitution.md')}\n\n"
        f"# DEINE SEELE\n{_read('SOUL.md')}\n\n"
        f"# DEIN ZIEL\n{_read('GOAL.md')}\n\n"
        + (f"# DEIN KOERPER (Details: read_file(\"core/mind/BODY.md\"))\n{koerper}\n\n" if koerper else "")
        + (f"{pb}\n\n" if pb else "")
        + f"{PERSONA_DIRECTIVE}"
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


# Manche guenstige Modelle (z.B. DeepSeek V4 Flash) liefern Tool-Calls unzuverlaessig: mal als
# strukturierte tool_calls, mal als TEXT im XML-/DSML-Format (mit fullwidth-Pipe ｜). Dann saehe der
# Loop keine tool_calls und wuerde das Markup als "Antwort" ausgeben. Diese Helfer holen die Calls
# aus dem Text -> billige Modelle bleiben nutzbar, der Loop wird robust gegen den Leak.
_LEAK_INVOKE_RE = re.compile(r"invoke\s+name=\"([^\"]+)\"[^>]*>(.*?)</[^>]*invoke\s*>", re.DOTALL)
_LEAK_PARAM_RE = re.compile(r"parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)</[^>]*parameter\s*>", re.DOTALL)


def _parse_leaked_tool_calls(text: str) -> list[dict]:
    """Holt als TEXT geleakte Tool-Calls (DeepSeek-DSML / Claude-XML-Stil) heraus."""
    if not text or "invoke" not in text:
        return []
    out: list[dict] = []
    for m in _LEAK_INVOKE_RE.finditer(text):
        args: dict = {}
        for pm in _LEAK_PARAM_RE.finditer(m.group(2)):
            raw = pm.group(2).strip()
            try:
                val = json.loads(raw)      # Zahlen/Bools/JSON sauber typisieren ...
            except Exception:  # noqa: BLE001
                val = raw                  # ... sonst als String (z.B. SQL/Pfad)
            args[pm.group(1)] = val
        out.append({"id": None, "name": m.group(1), "args": args})
    return out


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
        recovered = False
        if not calls:  # kein strukturierter Call -> evtl. als Text geleakt (DeepSeek)? rausparsen
            leaked = _parse_leaked_tool_calls(res.get("text") or "")
            if leaked:
                calls, recovered = leaked, True
                events.emit("tool_calls_recovered",
                            {"count": len(leaked), "names": [c["name"] for c in leaked][:8]},
                            session_id=session_id)
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
            "content": None if recovered else (res["text"] or None),
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


def _resolve_objective_token(text: str) -> tuple[str, str | None]:
    """Erkennt '@ziel:<id-praefix-oder-titel-teil>' im /work-Text (S6.3) und loest es
    gegen die aktiven Ziele auf: erst id-Praefix, dann Titel-Teiltreffer (case-insensitiv).
    Mehrdeutig oder kein Treffer -> keine Verknuepfung. Liefert (Text ohne Token, oid|None)."""
    m = re.search(r"@ziel:(\S+)", text, flags=re.IGNORECASE)
    if not m:
        return text, None
    token = m.group(1).strip().rstrip(",.;:")
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    try:
        from core.agency.missions import objectives

        actives = objectives.list_active()
    except Exception:  # noqa: BLE001
        return cleaned, None
    hits = [o for o in actives if o["id"].startswith(token)]
    if not hits:
        low = token.lower()
        hits = [o for o in actives if low in (o.get("title") or "").lower()]
    return cleaned, (hits[0]["id"] if len(hits) == 1 else None)


def _book_work_result(oid: str | None, desc: str, result: str) -> None:
    """/work-Ergebnis als erledigten Task aufs Ziel buchen (S6.3): Chat-Arbeit zaehlt
    damit im Ziel-Fortschritt und landet im Arbeitsstand (workingset)."""
    if not oid or not result:
        return
    try:
        from core.agency.missions import queue, workingset
        from core.config import CONFIG

        queue.init_queue()
        tid = queue.add(f"[chat/work] {desc[:180]}",
                        mission=CONFIG.get("mission", {}).get("name", "default"),
                        objective_id=oid, kind="produce")
        queue.complete(tid, result[:4000])
        first = (result.strip().splitlines() or [""])[0]
        workingset.append(oid, f"[chat] {desc[:80]} -> {first[:120]}")
        events.emit("work_booked", {"objective_id": oid, "task_id": tid})
    except Exception as e:  # noqa: BLE001
        events.emit("work_book_error", {"error": str(e)[:200]})


# Kurzbefehle als Daten (nicht als if-Kette): Kurzname -> (Rolle, Modell-ID).
# 'local' ist die NOTBREMSE — schaltet immer, egal wie schwach das aktuelle Modell ist.
# Der Fable-Slug ist gegen den Live-OpenRouter-Katalog zu verifizieren.
_MODEL_SHORTCUTS = {
    "local": ("default", "ollama_chat/qwythos"),
    "lokal": ("default", "ollama_chat/qwythos"),
    "deepseek": ("default", "openrouter/deepseek/deepseek-v4-flash"),
    "flash": ("default", "openrouter/deepseek/deepseek-v4-flash"),
    "pro": ("default", "openrouter/deepseek/deepseek-v4-pro"),
    "fable": ("escalation", "openrouter/anthropic/claude-fable-5"),
}
_MODEL_ROLES = ("chat", "reason", "bulk", "escalation", "default", "classify")


def _handle_model_command(text: str) -> str:
    """Deterministischer Modell-Wechsel OHNE LLM (fuer /model bzw. /switch im Web-Chat).

    Spiegelt den Telegram-Handler + Kurzbefehle. Liefert IMMER einen String, raist nie —
    so kann auch ein schwaches lokales Modell (oder Sergen) jederzeit umschalten, ohne dass
    ein Tool-Call gelingen muss. Nutzt die bestehenden Setter aus core.kernel.models."""
    try:
        from core.kernel import llm_router, models

        args = text.strip().split()[1:]  # [0] ist /model bzw. /switch

        def keywarn(mid: str) -> str:
            return "" if llm_router.has_key(mid) else \
                f"  ⚠ Kein Key fuer {mid.split('/', 1)[0]} — laeuft bis dahin lokal."

        if not args:
            st = models.status()
            rd, fbd = llm_router.resolve_model("default")
            rc, fbc = llm_router.resolve_model("chat")
            re_, fbe = llm_router.resolve_model("default", escalate=True)
            routing = st.get("routing", {})
            lines = ["Modelle (gespeichert  ->  laeuft real):",
                     f"- default:    {st.get('default')}  ->  {rd}" + ("  [FALLBACK]" if fbd else ""),
                     f"- chat:       {routing.get('chat', st.get('default'))}  ->  {rc}" + ("  [FALLBACK]" if fbc else ""),
                     f"- escalation: {st.get('escalation_model')}  ->  {re_}" + ("  [FALLBACK]" if fbe else "")]
            have = [k for k, v in (st.get("api_keys") or {}).items() if v]
            lines.append("Keys vorhanden: " + (", ".join(have) if have else "keine (nur lokal moeglich)"))
            lines.append("Umschalten: /model <kurz> (local, deepseek, pro, fable) | /model use <id> | /model <rolle> <id>")
            return "\n".join(lines)

        sub = args[0].lower()
        if sub in _MODEL_SHORTCUTS and len(args) == 1:
            role, mid = _MODEL_SHORTCUTS[sub]
            models.set_model(mid) if role == "default" else models.set_role(role, mid)
            return f"Umgeschaltet: {role} -> {mid}." + keywarn(mid)
        if sub == "use" and len(args) >= 2:
            mid = args[1].strip()
            models.set_model(mid)
            return f"Aktives Modell: {mid}." + keywarn(mid)
        if sub == "add" and len(args) >= 5:
            models.add_provider(args[1], args[2], args[3], args[4])
            return f"Provider '{args[1]}' registriert. Nutzen: /model use {args[1]}"
        if sub in _MODEL_ROLES and len(args) >= 2:
            mid = args[1].strip()
            if not (mid.startswith("openrouter/") or mid.startswith("ollama")):
                mid = "openrouter/" + mid  # blanke id -> openrouter (Parity mit switch_model)
            models.set_role(sub, mid)
            return f"'{sub}' laeuft jetzt auf: {mid}." + keywarn(mid)
        return ("Unbekannter Modell-Befehl. Beispiele:\n"
                "  /model              (Status: was ist gesetzt vs. was laeuft real)\n"
                "  /model local        (Notbremse: lokales Modell)\n"
                "  /model deepseek     (zurueck auf DeepSeek Flash)\n"
                "  /model fable        (Eskalation auf Fable)\n"
                "  /model use <modell-id>\n"
                "  /model <rolle> <modell-id>")
    except Exception as e:  # noqa: BLE001 — Werkzeuge/Befehle liefern Strings, raisen nie
        return f"Modell-Befehl fehlgeschlagen: {str(e)[:200]}"


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

    # S9.2: Reasoning-Regler — Prefix "reason:" hebt auf das staerkere Modell (escalate),
    # komponierbar mit den Modi (z.B. "reason: plan: ..."). Wird hier abgestreift.
    if user_message.lstrip().lower().startswith("reason:"):
        escalate = True
        user_message = re.sub(r"^\s*reason:\s*", "", user_message, flags=re.IGNORECASE)

    # Deterministischer Modell-Wechsel: /model bzw. /switch umgeht die LLM komplett.
    # So kann auch ein schwaches lokales Modell (oder Sergen) IMMER umschalten — der
    # Wechsel haengt NIE davon ab, dass das aktuelle Modell einen Tool-Call absetzt.
    # Vor memory.remember/user_message, damit Steuerbefehle den Dialog nicht verschmutzen.
    _mc = user_message.strip()
    _mc_first = _mc.split(maxsplit=1)[0].lower() if _mc else ""
    if _mc_first in ("/model", "/switch"):
        reply = _handle_model_command(_mc)
        events.emit("model_command", {"reply": reply[:400]}, session_id=session_id)
        emit({"kind": "final", "text": reply})
        return reply

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
    work_objective = None
    if work_mode:
        user_message = re.sub(r"^(/work|work:)\s*", "", _s, flags=re.IGNORECASE).strip() or _s
        # S6.3: '@ziel:<praefix|titel-teil>' verknuepft die Arbeit mit einem Ziel.
        user_message, work_objective = _resolve_objective_token(user_message)
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
        _book_work_result(work_objective, user_message, text)
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
            _book_work_result(work_objective, user_message, text)
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
    _book_work_result(work_objective, user_message, text)
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
