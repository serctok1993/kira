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
_AUTO_PLAN = bool(_AG.get("auto_plan", True))              # Arbeitsauftraege im Plain-Chat automatisch planen
_CLAIM_CHECK = bool(_AG.get("claim_check", True))          # Datei-Behauptungen in Antworten nachpruefen

# --- Modellstarke Arbeitsflaeche ----------------------------------------------
# Die Decken oben sind fuer schwache/lokale Modelle kalibriert. Laeuft die Runde
# REAL auf einem starken Cloud-Modell (Fable & Co.), gelten grosszuegigere Budgets
# aus config agency.strong — folgt automatisch dem Modell-Switch, kein Extra-Schalter.
# Im Fallback (Key fehlt -> lokal) gelten IMMER die engen Basis-Decken.
_STRONG_CFG = _AG.get("strong") if isinstance(_AG.get("strong"), dict) else {}
_STRONG_MARKERS = [str(m).lower() for m in (_AG.get("strong_markers") or ["anthropic/", "claude"])]
# Mittlere Stufe (B-030): starke OFFENE Modelle (GLM & Co.) bekommen mehr Raum als die
# Schwach-Modell-Basis, aber weniger als Fable. Gleiche Mechanik, eigene Marker.
_MEDIUM_CFG = _AG.get("medium") if isinstance(_AG.get("medium"), dict) else {}
_MEDIUM_MARKERS = [str(m).lower() for m in (_AG.get("medium_markers") or ["z-ai/", "glm"])]


def _strong_model(task_type: str = "chat", escalate: bool = False) -> bool:
    """True, wenn diese Runde real auf einem starken Cloud-Modell laeuft (kein Fallback)."""
    try:
        mid, fell_back = llm_router.resolve_model(task_type, escalate)
        return (not fell_back) and any(m in mid.lower() for m in _STRONG_MARKERS)
    except Exception:  # noqa: BLE001 — im Zweifel enge Decken (sicher)
        return False


def _tier_cfg(task_type: str = "chat", escalate: bool = False) -> dict:
    """Budget-Stufe der Runde: strong > medium > Basis ({}). Fallback -> IMMER Basis."""
    try:
        mid, fell_back = llm_router.resolve_model(task_type, escalate)
        if fell_back:
            return {}
        low = mid.lower()
        if _STRONG_CFG and any(m in low for m in _STRONG_MARKERS):
            return _STRONG_CFG
        if _MEDIUM_CFG and any(m in low for m in _MEDIUM_MARKERS):
            return _MEDIUM_CFG
    except Exception:  # noqa: BLE001 — im Zweifel enge Decken (sicher)
        pass
    return {}


def _budget(name: str, base: int, task_type: str = "chat", escalate: bool = False) -> int:
    """Budget fuer diese Runde: Stufen-Wert (strong/medium) je realem Modell, sonst Basis."""
    cfg = _tier_cfg(task_type, escalate)
    try:
        return int(cfg.get(name, base)) if cfg else base
    except Exception:  # noqa: BLE001
        return base

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
    r"schau(e)?\s+(mal|kurz)|sehe (mal )?nach|melde mich gleich|"
    # Rueckfrage-Muster (Bestaetigungsschleife): zurueckfragen statt handeln ist bei
    # klarem Auftrag genauso wertlos wie ankuendigen -> derselbe Nudge greift.
    r"soll ich|moechtest du|möchtest du|willst du,? dass|bestaetige|bestätige|"
    r"darf ich|gib (mir )?gruenes licht|wenn du einverstanden)", re.IGNORECASE)


def _looks_like_promise(text: str) -> bool:
    """Erkennt eine 'ich tu gleich was'- ODER 'soll ich?'-Antwort ohne Handlung (Heuristik)."""
    t = (text or "").strip()
    if not t:
        return True
    return len(t) <= 400 and (t.endswith(":") or bool(_PROMISE_RE.search(t)))


# --- Arbeitsauftrag-Erkennung (Auto-Plan) --------------------------------------------
# Ein klarer Arbeitsauftrag im Plain-Chat soll geplant und abgearbeitet werden statt im
# 8-Runden-Chat zerredet. Bewusst konservativ: False-Positive = unnoetiger Plan-Overhead,
# False-Negative = heutiges Verhalten.
_WORK_VERBS = (r"erstell|schreib|bau|generier|recherchier|analysier|entwickl|entwirf|"
               r"implementier|korrigier|fixe?|sammel|organisier|erarbeit|verfass|bereite|"
               r"ueberarbeit|überarbeit|raussuch|heraussuch|zusammenstell|hinterleg|anleg|such")
_WORK_VERB_RE = re.compile(r"^(" + _WORK_VERBS + r")", re.IGNORECASE)
_WORK_VERB_ANY_RE = re.compile(r"\b(" + _WORK_VERBS + r")\w*\b", re.IGNORECASE)
# Deutsche Hoeflichkeitsform: "Kannst du mir ... raussuchen" — das Verb steht am ENDE.
# Menschen formulieren hoeflich; der Harness muss das als Auftrag erkennen.
_POLITE_RE = re.compile(
    r"^(kannst|koenntest|könntest|wuerdest|würdest|magst|willst)\s+du\s+(mir\s+|bitte\s+|mal\s+)*",
    re.IGNORECASE)
_WORK_HINT_RE = re.compile(
    r"(\d+\s+\w+|desktop|datei|dateien|ordner|projekt|liste|e-?mails?|bericht|dossier)",
    re.IGNORECASE)


def _looks_like_work_order(text: str) -> bool:
    """True bei einem klaren, mehrteiligen Arbeitsauftrag (Imperativ ODER Hoeflichkeitsform
    mit Arbeitsverb + Substanz). Bewusst konservativ."""
    t = (text or "").strip()
    if len(t) < 25:
        return False
    imperativ = bool(_WORK_VERB_RE.match(t.split(maxsplit=1)[0]))
    # Hoeflichkeitsform zaehlt NUR mit Arbeitsverb irgendwo UND Substanz-Hinweis —
    # "Kannst du mir sagen, wie spaet es ist?" bleibt eine Frage.
    hoeflich = bool(_POLITE_RE.match(t)) and bool(_WORK_VERB_ANY_RE.search(t)) \
        and bool(_WORK_HINT_RE.search(t))
    if not (imperativ or hoeflich):
        return False
    if imperativ and t.endswith("?") and not _WORK_HINT_RE.search(t):
        return False  # echte Frage, kein Auftrag
    return hoeflich or len(t) > 120 or bool(_WORK_HINT_RE.search(t))


# --- Beweispflicht: Datei-Behauptungen nachpruefen ------------------------------------
# Gegen halluzinierte Ergebnisse ('10 fertige E-Mails liegen auf dem Desktop'): behauptet
# die Antwort erzeugte Dateien, prueft der Harness deren Existenz — read-only, deterministisch.
_CLAIM_VERB_RE = re.compile(
    r"(erstellt|geschrieben|gespeichert|angelegt|abgelegt|hinterlegt|liegt|liegen)", re.IGNORECASE)
_PATH_RE = re.compile(r"`([^`\n]{3,180})`|((?:~[\\/]|[A-Za-z]:\\)[\w .\-\\/]{2,180})")


def _missing_claims(text: str) -> list[str]:
    """Behauptete-aber-fehlende Dateien im Text (read-only, deterministisch, raist nie).

    Relative Pfade werden gegen Arbeitsverzeichnis, Projekt-ROOT und ~/Desktop geprueft,
    damit der Check nicht faelschlich anschlaegt. Leer = alles belegt oder nichts behauptet."""
    if not _CLAIM_CHECK or not text or not _CLAIM_VERB_RE.search(text):
        return []
    try:
        from pathlib import Path

        from core.config import ROOT

        fehlend: list[str] = []
        gesehen: set[str] = set()
        for m in _PATH_RE.finditer(text):
            tok = (m.group(1) or m.group(2) or "").strip().rstrip(".,;:)“”")
            if not tok or tok in gesehen or len(gesehen) >= 8:
                continue
            if "/" not in tok and "\\" not in tok:
                continue  # kein Pfad (z.B. Werkzeugname in Backticks)
            p = Path(tok.replace("\\", "/")).expanduser()
            if not p.suffix or len(p.suffix) > 9:
                continue  # nur dateiartige Tokens mit Endung
            gesehen.add(tok)
            kandidaten = [p] if p.is_absolute() else [p, ROOT / p, Path.home() / "Desktop" / p]
            if not any(k.is_file() for k in kandidaten):
                fehlend.append(tok)
        return fehlend
    except Exception:  # noqa: BLE001 — der Check darf nie stoeren
        return []


def _claim_stamp(text: str, session_id: str | None = None) -> str:
    """Haengt eine sichtbare Warnung an, wenn behauptete Dateien NICHT existieren."""
    fehlend = _missing_claims(text)
    if fehlend:
        events.emit("claim_check_failed", {"missing": fehlend[:8]}, session_id=session_id)
        text += ("\n\n⚠ BEWEISPFLICHT: Diese behaupteten Dateien existieren NICHT: "
                 + ", ".join(fehlend[:8])
                 + " — erledige es wirklich oder sag ehrlich, dass es fehlt.")
    return text


def _cloud(escalate: bool, task_type: str = "reason") -> bool:
    """True, wenn das aufzurufende Modell ein Cloud-/Provider-Modell ist (nicht lokal Ollama)."""
    model, _ = llm_router.resolve_model(task_type, escalate=escalate)
    real, _ab, _ke = llm_router._provider_config(model)
    return not real.startswith("ollama")


# --- Read-before-Edit-Guard (B-028, Claude-Code-Prinzip, deterministisch) ---------------
# Editieren darf nur, wer die Datei in DIESER Session vorher angefasst hat (read_file,
# code_suche-/datei_finden-Treffer). Harness-Mechanik statt LLM-Disziplin: kein Modell
# kann blind drauflos schreiben. Neue (nicht existierende) Dateien sind frei.
_RBE_ON = bool(_AG.get("read_before_edit", True))
_EDIT_TOOLS = {"edit_datei": "pfad", "self_edit": "path"}
_SEEN_FILES: dict[str, set] = {}
_SEEN_SESSIONS_CAP = 32
_OBS_PATH_RE = re.compile(r"^([\w][\w .\-/\\]{2,180}\.\w{1,9})(?=:|\s*$)", re.MULTILINE)


def _rbe_norm(p: str) -> str:
    """Pfad-Token auf ROOT-relatives Posix-Format bringen (best effort, raist nie)."""
    try:
        from pathlib import Path

        from core.config import ROOT

        pp = Path(str(p).strip().replace("\\", "/")).expanduser()
        if pp.is_absolute():
            try:
                return pp.resolve().relative_to(Path(ROOT).resolve()).as_posix()
            except Exception:  # noqa: BLE001 — ausserhalb des Projekts -> absolut
                return pp.as_posix()
        return pp.as_posix()
    except Exception:  # noqa: BLE001
        return str(p)


def _rbe_seen(session_id: str | None) -> set:
    key = session_id or "solo"
    if key not in _SEEN_FILES and len(_SEEN_FILES) >= _SEEN_SESSIONS_CAP:
        _SEEN_FILES.pop(next(iter(_SEEN_FILES)), None)  # aelteste Session raus
    return _SEEN_FILES.setdefault(key, set())


def _rbe_record(session_id: str | None, name: str, args: dict, obs: str) -> None:
    """Nach jedem Werkzeug-Lauf: gelesene/gefundene Dateien der Session gutschreiben."""
    try:
        seen = _rbe_seen(session_id)
        if name in ("read_file",) and args.get("path"):
            seen.add(_rbe_norm(args["path"]))
        elif name in ("code_suche", "datei_finden"):
            for m in _OBS_PATH_RE.finditer(obs or ""):
                seen.add(_rbe_norm(m.group(1)))
                if len(seen) > 400:
                    break
        elif name in _EDIT_TOOLS and args.get(_EDIT_TOOLS[name]):
            seen.add(_rbe_norm(args[_EDIT_TOOLS[name]]))  # einmal editiert = bekannt
    except Exception:  # noqa: BLE001 — Buchhaltung darf nie stoeren
        pass


def _rbe_block(session_id: str | None, name: str, args: dict) -> str | None:
    """Blockier-Text, wenn ein Edit-Werkzeug eine UNGELESENE bestehende Datei anfasst."""
    if not _RBE_ON or name not in _EDIT_TOOLS:
        return None
    try:
        from pathlib import Path

        from core.config import ROOT

        raw = args.get(_EDIT_TOOLS[name]) or ""
        if not str(raw).strip():
            return None
        rel = _rbe_norm(raw)
        ziel = Path(rel) if Path(rel).is_absolute() else Path(ROOT) / rel
        if not ziel.is_file():
            return None  # neue Datei -> frei
        if rel in _rbe_seen(session_id):
            return None
        events.emit("edit_blocked_unread", {"tool": name, "file": rel}, session_id=session_id)
        return (f"GESPERRT (Read-before-Edit): Du hast '{rel}' in dieser Session noch nicht "
                f"gelesen. Lies die relevante Stelle ZUERST (read_file oder code_suche auf die "
                f"Datei) und rufe {name} danach erneut auf.")
    except Exception:  # noqa: BLE001 — im Zweifel nicht blockieren
        return None


def _run_tool_guarded(name: str, tool, args: dict, session_id: str | None) -> str:
    """Zentraler Werkzeug-Runner aller Loops: Guard davor, Buchhaltung danach."""
    block = _rbe_block(session_id, name, args)
    if block:
        return block
    obs = str(executor.run_tool(name, tool.func, **args))
    _rbe_record(session_id, name, args, obs)
    return obs


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
    obs_cap = _budget("obs_max_chars", _OBS_MAX, task_type, escalate)  # starkes Modell -> sieht mehr
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
                messages.append({"role": "user", "content": "Der Auftrag liegt bereits vor — tu es "
                                 "JETZT in diesem Zug: nutze die passenden Werkzeuge und antworte erst "
                                 "mit dem Ergebnis. Nicht ankuendigen, nicht zurueckfragen."})
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
                    obs = _run_tool_guarded(name, tool, args, session_id)
                except Exception as e:  # noqa: BLE001
                    obs = f"Fehler bei '{name}': {e}"
            emit({"kind": "obs", "name": name, "text": obs[:200]})
            events.emit("act_step", {"step": step, "tool": name, "args": args, "obs_preview": obs[:160]}, session_id=session_id)
            messages.append({"role": "tool", "tool_call_id": cid, "content": obs[:obs_cap]})
    try:
        res = _complete_resilient(
            messages + [{"role": "user", "content": "Fasse jetzt final fuer Sergen zusammen — ohne weitere Werkzeuge."}],
            system=system, task_type=task_type, session_id=session_id, escalate=escalate)
    except Exception as e:  # noqa: BLE001
        events.emit("act_degraded", {"step": "final", "error": str(e)[:300]}, session_id=session_id)
        return _degrade_text(messages, e)
    return (res["text"].strip()
            or "Ich habe die Werkzeuge genutzt, aber keine saubere Schluss-Antwort hinbekommen — frag mich gern konkret nach, dann liefere ich dir das Ergebnis.")


def act(task: str, session_id: str | None = None, max_steps: int | None = None, escalate: bool = False, task_type: str = "reason") -> dict:
    if max_steps is None:  # kein expliziter Deckel -> Budget passend zum realen Modell
        max_steps = _budget("max_steps", _MAX_STEPS, task_type, escalate)
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
                obs = _run_tool_guarded(name, tool, args, session_id)
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


# Dispatcher: der Planer (Denker) vergibt pro Schritt ein Rang-Etikett, die Ausfuehrung
# routet danach — kluges Hirn plant, billige Haende liefern. Rang -> (task_type, Modellroute
# via config models.routing). 'richter' vergibt der Planer NICHT (Eskalation nur explizit).
_PLAN_RANG = {"reflex": "classify", "arbeiter": "worker", "denker": "reason"}


def _make_plan(task: str, session_id: str | None, escalate: bool = True) -> list[dict]:
    """Zerlegt eine Aufgabe in 3-7 Schritte MIT Rang-Etikett: [{"schritt":..., "rang":...}].

    Tolerant: liefert der Planer nur Strings (schwaches Modell), wird Rang 'denker'
    angenommen — nie schlechter als das alte Verhalten."""
    system = _identity() + (
        "\n\nDu bist im PLANUNGS-Modus. Zerlege die Aufgabe in 3 bis 7 konkrete, ausfuehrbare "
        "Schritte und vergib pro Schritt einen RANG: 'reflex' (trivial: lesen, sortieren), "
        "'arbeiter' (mechanische Arbeit: recherchieren, Dateien schreiben, Massenaufgaben), "
        "'denker' (Urteil/Analyse noetig). Nenne im Schritt konkrete Dateipfade, wenn etwas "
        "erzeugt werden soll. Antworte AUSSCHLIESSLICH mit einem JSON-Array, sonst nichts. "
        'Beispiel: [{"schritt": "Lies leads.csv", "rang": "reflex"}, '
        '{"schritt": "Schreibe die Mail nach ~/Desktop/luvex/mail1.md", "rang": "arbeiter"}]'
    )
    res = llm_router.complete([{"role": "user", "content": task}], system=system,
                              task_type="reason", session_id=session_id, escalate=escalate)
    m = re.search(r"\[.*\]", res["text"], re.DOTALL)
    if m:
        try:
            steps: list[dict] = []
            for s in json.loads(m.group(0)):
                if isinstance(s, dict) and str(s.get("schritt", "")).strip():
                    rang = str(s.get("rang", "")).strip().lower()
                    steps.append({"schritt": str(s["schritt"]).strip(),
                                  "rang": rang if rang in _PLAN_RANG else "denker"})
                elif str(s).strip():  # schwacher Planer liefert Strings -> denker
                    steps.append({"schritt": str(s).strip(), "rang": "denker"})
            if steps:
                return steps[:8]
        except Exception:  # noqa: BLE001
            pass
    return [{"schritt": task, "rang": "denker"}]


# --- Diff-Review (B-029): der Skeptiker fuer Code ---------------------------------------
def _git_out(*args: str) -> str:
    """git im Projekt-ROOT, best effort ('' bei Fehler/ohne Repo) — raist nie."""
    try:
        import subprocess

        from core.config import ROOT

        r = subprocess.run(["git", "-C", str(ROOT), *args],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


_REVIEW_DIFF_CAP = 12000


def _code_review_run(task: str, head0: str, session_id, escalate: bool, emit) -> str:
    """Liest den git-Diff des Laufs gegen den Auftrag (frischer Denker-Blick).

    OK -> kurzer Vermerk. MAENGEL -> genau EIN Fix-Schritt, danach ehrlicher Vermerk.
    Raist nie; ohne Diff (reine Lese-Schritte) still ueberspringen."""
    try:
        diff = _git_out("diff", f"{head0}..HEAD") if head0 else ""
        dirty = _git_out("diff")  # unversionierte Reste (sollten leer sein)
        full = (diff + "\n" + dirty).strip()
        if not full:
            return ""
        full = full[:_REVIEW_DIFF_CAP]
        emit({"kind": "tool", "name": "Code-Review 🔎", "args": {"diff_chars": len(full)}})
        res = llm_router.complete(
            [{"role": "user", "content":
              f"AUFTRAG war:\n{task[:2000]}\n\nDIESER DIFF ist dabei entstanden:\n```diff\n{full}\n```\n\n"
              "Pruefe als strenger Reviewer: 1) Erfuellt der Diff den Auftrag vollstaendig? "
              "2) Nebenwirkungen/kaputte Stellen? 3) Vergessene Stellen (gleiche Aenderung woanders noetig)? "
              "Antworte in GENAU diesem Format:\nURTEIL: OK oder URTEIL: MAENGEL\n- <Befund 1>\n- <Befund 2>"}],
            system="Du bist ein strenger, knapper Code-Reviewer. Nur echte Maengel zaehlen — Stil-Noergelei ist keiner.",
            task_type="reason", session_id=session_id, escalate=escalate)
        urteil = (res.get("text") or "").strip()
        kopf = urteil.splitlines()[0].upper() if urteil else ""
        if "MAENGEL" not in kopf and "MÄNGEL" not in kopf:
            events.emit("code_review_pass", {"chars": len(full)}, session_id=session_id)
            emit({"kind": "obs", "name": "Code-Review", "text": "bestanden ✓"})
            return "\n\n🔎 Code-Review: bestanden."
        events.emit("code_review_fail", {"befund": urteil[:400]}, session_id=session_id)
        emit({"kind": "obs", "name": "Code-Review ⚠", "text": urteil[:200]})
        fix = act(f"Auftrag war: {task[:1500]}\n\nEin Code-Review deines Diffs fand diese Maengel:\n"
                  f"{urteil[:1500]}\n\nBehebe GENAU diese Punkte jetzt (edit_datei/self_edit; "
                  "Tests laufen automatisch). Nichts anderes anfassen.",
                  session_id=session_id,
                  max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, "reason", escalate),
                  escalate=escalate, task_type="reason")["text"].strip()
        events.emit("code_review_fixed", {"fix": fix[:300]}, session_id=session_id)
        return ("\n\n🔎 Code-Review fand Maengel und hat nachgebessert:\n"
                + urteil[:600] + "\nNachbesserung: " + fix[:400])
    except Exception as e:  # noqa: BLE001 — Review darf den Lauf nie abreissen
        events.emit("code_review_error", {"error": str(e)[:200]}, session_id=session_id)
        return ""


def plan_and_execute(task: str, session_id: str | None = None, on_event=None, escalate: bool = True,
                     code_review: bool = False) -> str:
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
    head0 = _git_out("rev-parse", "HEAD") if code_review else ""
    steps = _make_plan(task, session_id, escalate)
    emit({"kind": "think", "text": "📋 Plan:\n" + "\n".join(
        f"{i}. [{s['rang']}] {s['schritt']}" for i, s in enumerate(steps, 1)) + "\n"})
    events.emit("plan_made", {"steps": [s["schritt"] for s in steps],
                              "raenge": [s["rang"] for s in steps]}, session_id=session_id)

    done: list[str] = []
    for i, sp in enumerate(steps, 1):
        step, rang = sp["schritt"], sp["rang"]
        # Dispatcher: Rang -> Modellroute. Eskalation (starkes Modell) nur fuer Denker-Schritte
        # und nur, wenn der Aufrufer sie wollte — Arbeiter-/Reflex-Schritte bleiben billig.
        task_type = _PLAN_RANG.get(rang, "reason")
        step_escalate = escalate and rang == "denker"
        emit({"kind": "tool", "name": f"Schritt {i}/{len(steps)} [{rang}]", "args": {"ziel": step[:80]}})
        ctx = ("Bisher erledigt:\n" + "\n".join(f"- {d}" for d in done) + "\n\n") if done else ""
        step_task = f"{ctx}Gesamtziel: {task}\n\nFuehre jetzt NUR diesen Schritt aus: {step}"
        try:
            out = act(step_task, session_id=session_id,
                      max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, task_type, step_escalate),
                      escalate=step_escalate, task_type=task_type)["text"].strip()
        except Exception as e:  # noqa: BLE001
            out = f"Fehler: {e}"

        # Liefernachweis: behauptet der Schritt Dateien, muessen sie EXISTIEREN — sonst genau
        # EIN Zwangs-Retry. Danach steht der Fehlschlag ehrlich im Ergebnis (kein stilles Weiter).
        fehlend = _missing_claims(out)
        if fehlend:
            events.emit("plan_step_retry", {"n": i, "missing": fehlend[:5]}, session_id=session_id)
            emit({"kind": "obs", "name": f"Schritt {i} ⚠", "text": "Artefakt fehlt -> Zwangs-Retry: "
                  + ", ".join(fehlend[:3])})
            retry_task = (f"{step_task}\n\nDEIN VORHERIGER VERSUCH HAT NICHT GELIEFERT: die Datei(en) "
                          f"{', '.join(fehlend[:5])} existieren NICHT. Erzeuge sie JETZT wirklich "
                          "(write_file/edit_datei) und antworte erst DANACH mit dem Ergebnis.")
            try:
                out = act(retry_task, session_id=session_id,
                          max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, task_type, step_escalate),
                          escalate=step_escalate, task_type=task_type)["text"].strip()
            except Exception as e:  # noqa: BLE001
                out = f"Fehler: {e}"
            fehlend = _missing_claims(out)
            if fehlend:
                out += " ⚠ NICHT BELEGT: " + ", ".join(fehlend[:5]) + " existieren nicht."
                events.emit("plan_step_unproven", {"n": i, "missing": fehlend[:5]}, session_id=session_id)

        done.append(f"{step} -> {out[:160]}")
        emit({"kind": "obs", "name": f"Schritt {i}", "text": out[:200]})
        events.emit("plan_step", {"n": i, "step": step, "rang": rang, "result": out[:300]}, session_id=session_id)

    # Diff-Review (nur code:-Laeufe): ein frischer Denker liest den entstandenen Diff
    # gegen den Auftrag — Maengel -> EIN Fix-Schritt, danach ehrlicher Vermerk.
    review_note = _code_review_run(task, head0, session_id, escalate, emit) if code_review else ""

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
    final += review_note
    events.emit("plan_done", {"task": task, "steps": len(steps)}, session_id=session_id)

    # Auto-Reflexion: aus jeder groesseren Aufgabe Lektionen ziehen (lokal, 0 EUR).
    try:
        from core.mind.reflection import reflect_on

        refl = reflect_on(task, "\n".join(done), escalate=False)
        if refl.get("lessons"):
            emit({"kind": "think", "text": "🧠 Gelernt: " + "; ".join(refl["lessons"][:2]) + "\n"})
    except Exception:  # noqa: BLE001
        pass

    # Beweispflicht auch fuer Plan-Ergebnisse: behauptete Dateien werden nachgeprueft.
    final = _claim_stamp(final, session_id=session_id)
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
    "local": ("default", "ollama_chat/qwen3.5:9b"),
    "lokal": ("default", "ollama_chat/qwen3.5:9b"),
    "9b": ("default", "ollama_chat/qwen3.5:9b"),
    "qwen": ("default", "ollama_chat/qwen3.5:9b"),
    "35b": ("default", "ollama_chat/qwen3.6:35b"),
    "deepseek": ("default", "openrouter/deepseek/deepseek-v4-flash"),
    "flash": ("default", "openrouter/deepseek/deepseek-v4-flash"),
    "pro": ("default", "openrouter/deepseek/deepseek-v4-pro"),
    "glm": ("reason", "openrouter/z-ai/glm-5.2"),
    "fable": ("escalation", "openrouter/anthropic/claude-fable-5"),
}
_MODEL_ROLES = ("chat", "reason", "bulk", "escalation", "default", "classify", "worker")

# Verify-Reflex fuer den Coding-Chat ("code:"): kompakte, bindende Arbeitsregeln.
# Bewusst klein (~600 Zeichen) — sie fliessen in den Plan UND in jeden Teilschritt.
_CODING_REGELN = (
    "CODING-REGELN (bindend):\n"
    "1. ERST suchen, dann aendern: code_suche/datei_finden statt raten oder ganze Dateien lesen.\n"
    "2. Aenderungen an BESTEHENDEN Dateien NUR mit edit_datei (exakter, eindeutiger Suchtext) "
    "oder self_edit — NIE write_file (blindes Ueberschreiben).\n"
    "3. Jeder Edit laeuft automatisch durch Syntax-Check + Testsuite; ROT heisst: Datei kam "
    "zurueck, dein Ansatz war falsch — aendere die STRATEGIE, nicht die Behauptung.\n"
    "4. Melde Testergebnisse EHRLICH und woertlich. NIE Erfolg behaupten ohne gruenen Verify.\n"
    "5. Kleine, gezielte Edits; ein Schritt = eine abgeschlossene, geprueft funktionierende Aenderung."
)


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
            lines.append("Umschalten: /model <kurz> (local, 9b, 35b, deepseek, pro, fable) | /model use <id> | /model <rolle> <id>")
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
                "  /model local        (Notbremse: lokal qwen3.5:9b)\n"
                "  /model 35b          (lokaler Denker qwen3.6:35b)\n"
                "  /model deepseek     (zurueck auf DeepSeek Flash)\n"
                "  /model fable        (Eskalation auf Fable)\n"
                "  /model use <modell-id>\n"
                "  /model <rolle> <modell-id>")
    except Exception as e:  # noqa: BLE001 — Werkzeuge/Befehle liefern Strings, raisen nie
        return f"Modell-Befehl fehlgeschlagen: {str(e)[:200]}"


def _handle_swarm_command(text: str, session_id: str | None) -> str:
    """Direkter Draht zur Schwarmintelligenz OHNE LLM (/delegiere, /schwarm).

    Sergens Riegel: ER waehlt den Rang (und damit die Modell-Klasse laut Rang-Tafel),
    der Befehl geht deterministisch an die Delegations-Werkzeuge — kein Modell muss
    mitspielen oder darf umdeuten. Liefert IMMER einen String, raist nie."""
    try:
        from core.agency.tools import delegate_tools

        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if not rest:
            return ("Direktzugriff auf die Schwarmintelligenz:\n"
                    "  /delegiere <rang> <auftrag>\n"
                    "  /schwarm [rang] <vorlage mit {item}> | item1 | item2 | …\n"
                    f"Raenge: {', '.join(delegate_tools._RANG)} (Modell je Rang: Cockpit → Config → Steuerpult).")
        words = rest.split(maxsplit=1)
        rang = "arbeiter"
        if words[0].lower() in delegate_tools._RANG:
            rang = words[0].lower()
            rest = words[1].strip() if len(words) > 1 else ""
        if not rest:
            return "Auftrag fehlt. Beispiel: /delegiere denker Fasse docs/HANDBUCH.md in 10 Zeilen zusammen."
        if cmd in ("/delegiere", "/delegate"):
            return delegate_tools._delegiere(rest, rang, session_id)
        if "|" in rest:  # /schwarm: Items per '|' (eine Zeile) oder als eigene Zeilen
            vorlage, _, items_raw = rest.partition("|")
            items = "\n".join(i.strip() for i in items_raw.split("|") if i.strip())
        else:
            lines = [ln for ln in rest.splitlines() if ln.strip()]
            vorlage, items = lines[0], "\n".join(lines[1:])
        if not items.strip():
            return ("Schwarm braucht Items: /schwarm [rang] <vorlage mit {item}> | item1 | item2 …\n"
                    "(oder die Items in eigenen Zeilen unter der Vorlage)")
        return delegate_tools.schwarm(vorlage.strip(), items, rang=rang, session_id=session_id or "")
    except Exception as e:  # noqa: BLE001 — Steuerbefehle liefern Strings, raisen nie
        return f"Schwarm-Befehl fehlgeschlagen: {str(e)[:200]}"


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
    # Modus-Praefixe (Coding/Research haengen code:/plan://work an) werden fuer die
    # Erkennung abgestreift — ein Steuerbefehl darf in KEINEM Modus verschluckt werden.
    _mc = re.sub(r"^(code:|plan:|/plan|/work|work:)\s*", "", user_message.strip(),
                 flags=re.IGNORECASE)
    _mc_first = _mc.split(maxsplit=1)[0].lower() if _mc else ""
    if _mc_first in ("/model", "/switch"):
        reply = _handle_model_command(_mc)
        events.emit("model_command", {"reply": reply[:400]}, session_id=session_id)
        emit({"kind": "final", "text": reply})
        return reply

    # Sergens Riegel: /delegiere und /schwarm gehen deterministisch an die
    # Schwarmintelligenz — Rang (= Modell-Klasse) waehlt ER, kein LLM deutet um.
    # Ergebnis wandert ins Gedaechtnis, damit der Dialog danach darauf aufbauen kann.
    if _mc_first in ("/delegiere", "/delegate", "/schwarm"):
        reply = _handle_swarm_command(_mc, session_id)
        events.emit("swarm_command", {"cmd": _mc[:160], "reply": reply[:400]}, session_id=session_id)
        memory.remember(_mc, role="user", session_id=session_id)
        memory.remember(reply, role="partner", session_id=session_id)
        emit({"kind": "final", "text": reply})
        return reply

    events.emit("user_message", {"text": user_message}, session_id=session_id)
    history = memory.recent_dialogue(session_id, limit=10)
    memory.remember(user_message, role="user", session_id=session_id)

    # Plan-Modus: "plan:"/"/plan" -> erst Plan, dann Schritt fuer Schritt (wie ein Coding-Agent).
    # "code:" (Coding-Chat im Cockpit) laeuft identisch, haengt aber die CODING-REGELN an —
    # der Verify-Reflex erreicht so JEDEN Teilschritt (via 'Gesamtziel' im Step-Prompt).
    # 5-Stufen-Oekonomie: code: laeuft auf dem DENKER (GLM) — Fable nur, wenn Sergen
    # explizit eskaliert (reason:-Prefix / 🧠-Toggle). plan: bleibt der Langzeitplaner (Fable).
    _s = user_message.strip()
    code_mode = _s.lower().startswith("code:")
    if code_mode or _s.lower().startswith(("plan:", "/plan")):
        ptask = _s[5:].lstrip(": ").strip() or "(keine Aufgabe angegeben)"
        if code_mode:
            ptask += "\n\n" + _CODING_REGELN
        final = plan_and_execute(ptask, session_id=session_id, on_event=on_event,
                                 escalate=(escalate if code_mode else True),
                                 code_review=code_mode)
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
    step_ceiling = (_budget("max_steps", _MAX_STEPS, "chat", escalate) if work_mode
                    else _budget("max_steps_chat", _MAX_STEPS_CHAT, "chat", escalate))

    # Auto-Plan: klarer Arbeitsauftrag im Plain-Chat -> erst Plan, dann Schritt fuer Schritt,
    # statt ihn im knappen Chat-Deckel zu zerreden. escalate=False (Denker-Rang, nicht das
    # teure Eskalations-Modell) — explizites plan:/code: bleibt bewusst escalate=True.
    if _AUTO_PLAN and not work_mode and _looks_like_work_order(user_message):
        emit({"kind": "think", "text": "Arbeitsauftrag erkannt — ich baue erst einen Plan "
                                       "und arbeite ihn Schritt fuer Schritt ab."})
        events.emit("auto_plan", {"task": user_message[:200]}, session_id=session_id)
        final = plan_and_execute(user_message, session_id=session_id,
                                 on_event=on_event, escalate=False)
        memory.remember(final, role="partner", session_id=session_id)
        events.emit("partner_message", {"text": final, "plan": True, "auto": True}, session_id=session_id)
        return final

    def _finalize(text: str) -> str:
        """Gemeinsamer Abschluss aller Chat-Ausgaenge: Beweispflicht-Stempel, Gedaechtnis,
        Events, final-Emit. Genau EIN Ort, an dem Antworten das Haus verlassen."""
        text = _claim_stamp(text, session_id=session_id)
        memory.remember(text, role="partner", session_id=session_id)
        events.emit("partner_message", {"text": text, "agentic": True}, session_id=session_id)
        _book_work_result(work_objective, user_message, text)
        emit({"kind": "final", "text": text})
        return text

    messages = [
        {"role": "assistant" if h["role"] == "partner" else "user", "content": h["text"]}
        for h in history
    ]
    messages.append({"role": "user", "content": user_message})

    # Cloud-Modelle: natives Function-Calling (robust, kein ACT-Text-Leak)
    if _cloud(escalate, "chat"):
        system = build_system_prompt(user_message, session_id=session_id) + _NATIVE_TOOLS_HINT
        text = _native_loop(messages, system, session_id, escalate, emit, max_steps=step_ceiling, task_type="chat")
        return _finalize(text)

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

    used_tools = False
    nudged = False
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
            # Lokale Modelle sind die schlimmsten Ankuendiger/Rueckfrager: einmal pro Turn
            # deterministisch nachstupsen statt das Pingpong an Sergen weiterzureichen.
            if not used_tools and not nudged and _looks_like_promise(text):
                nudged = True
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": "Der Auftrag liegt bereits vor — "
                                 "tu es JETZT mit einem Werkzeug (ACT ...) und antworte erst "
                                 "mit dem Ergebnis. Nicht ankuendigen, nicht zurueckfragen."})
                continue
            return _finalize(text)
        name, args = call
        used_tools = True
        emit({"kind": "tool", "name": name, "args": args})
        tool = registry.get(name)
        if tool is None:
            obs = f"Fehler: Werkzeug '{name}' existiert nicht."
        else:
            try:
                obs = _run_tool_guarded(name, tool, args, session_id)
            except Exception as e:  # noqa: BLE001
                obs = f"Fehler bei '{name}': {e}"
        emit({"kind": "obs", "name": name, "text": obs[:200]})
        events.emit("act_step", {"step": step, "tool": name, "args": args, "obs_preview": obs[:160]}, session_id=session_id)
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": f"ERGEBNIS von {name}:\n{obs}\n\nMach weiter oder gib die finale Antwort."})

    messages.append({"role": "user", "content": "Fasse jetzt final fuer Sergen zusammen — ohne weiteres ACT."})
    res = llm_router.complete(messages, system=system, task_type="chat", session_id=session_id, escalate=escalate)
    return _finalize(res["text"].strip())


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
