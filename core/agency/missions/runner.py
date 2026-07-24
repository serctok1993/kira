"""Mission-Heartbeat: der 24/7-Antrieb.

Ein Tick (run_once):
1. Kill-Switch pruefen (Verfassung #4).
2. Queue leer? -> Planner erzeugt die naechsten Aufgaben.
3. Naechste Aufgabe ziehen und mit der Handlungs-Schleife (act) bearbeiten
   (Werkzeuge: Web etc.) -> Ergebnis protokollieren.
4. Optional den Nutzer per Telegram benachrichtigen.

Sicher als erster Dauerlauf: nur lesende Recherche/Reflexion, keine Aussen-Aktionen.
Start:  uv run python -m core.agency.missions.runner            (ein Tick zum Testen: --once)
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time

from core.agency import outcomes, verifier
from core.agency.act import act
from core.agency.missions import planner, queue, workingset
from core import identity as _id
from core.config import CONFIG, feature_on
from core.kernel import events
from core.kernel.scheduler import heartbeat_on, kill_switch_active
from core.mind.agent import _read


def _mission() -> dict:
    return CONFIG.get("mission", {})


def _focus() -> str:
    """Aktueller Fokus des Nutzers (Direktive) — live pro Tick gelesen, wirkt ohne Neustart."""
    try:
        import json

        from core.config import ROOT

        d = json.loads((ROOT / "data" / "focus.json").read_text(encoding="utf-8"))
        return (d.get("focus") or "").strip()
    except Exception:
        return ""


def _context(limit: int = 12) -> str:
    lines: list[str] = []
    for e in reversed(events.recent(80)):
        if e["type"] == "mission_task_done":
            lines.append("Erledigt: " + str(e["payload"].get("summary", ""))[:160])
        elif e["type"] == "mission_planned":
            lines.append("Geplant: " + ", ".join(e["payload"].get("tasks", []))[:160])
        elif e["type"] == "task_failed_final":
            # Der Planner soll denselben todgeweihten Task nicht sofort neu planen.
            lines.append("Endgueltig gescheitert (NICHT wiederholen): "
                         + str(e["payload"].get("desc", ""))[:160])
    return "\n".join(lines[-limit:]) or "(noch kein Fortschritt)"


def _notify(text: str, wichtig: bool = False, kurz: str | None = None) -> None:
    """Missions-Meldung. Fix vom 09.07.: Standard ist BUENDELN (mission.notify_mode
    'gebuendelt') — der Einzeiler `kurz` wandert in den Melde-Puffer, der Bot schickt alle
    N Stunden EIN Buendel. wichtig=True (Gescheitertes, Freigabe-Bedarf) geht sofort raus;
    notify_mode 'sofort' = Alt-Verhalten, 'aus' = still."""
    from core import config as _cfg
    if _cfg.outbound_blocked():  # Firewall (Benchmark/Sandbox): kein Telegram
        return
    if not _mission().get("notify_telegram"):
        return
    mode = str(_mission().get("notify_mode") or "gebuendelt").lower()
    if not wichtig:
        if mode == "aus":
            return
        if mode != "sofort":
            from core.agency.missions import melde

            melde.merken(kurz or text.splitlines()[0])
            return
    try:
        import httpx

        # Token-Hygiene-Nachzug: gleiche Aufloesung wie der Bot (token_env) — sonst
        # gingen Missions-Meldungen nach dem .env-Aufraeumen still verloren.
        from core.config import telegram_token

        token = telegram_token()
        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        if token and chat:
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:4000]},
                timeout=15,
            )
    except Exception as e:  # noqa: BLE001
        events.emit("notify_error", {"error": str(e)})


def _self_improve_tick(mission: str, escalate: bool) -> dict:
    """S8.1: Selbstoptimierungs-Tick — Kira arbeitet an SICH statt an Projekten.

    Kontext = Doctor-Report + Erkenntnisse (insights) + letzte Fehler-Signale.
    Bewusst schlank: EIN konkreter, abgeschlossener Verbesserungs-Schritt, gemeldet."""
    sid = f"mission-{mission}"
    parts = ["SELBST-OPTIMIERUNG (dieser Tick gehoert DIR, nicht den Projekten). "
             "Waehle EINE konkrete, abgeschlossene Verbesserung an dir selbst: einen Bug beheben, "
             "eine Schwaeche schliessen, ein fehlendes Werkzeug bauen oder einen Skill lernen. "
             "Klein und fertig, kein Marathon. Melde am Ende knapp, was du verbessert hast."]
    try:
        from core.kernel import doctor

        rep = doctor.check()
        if rep.get("problems"):
            parts.append("DOCTOR meldet:\n- " + "\n- ".join(map(str, rep["problems"][:6])))
    except Exception:  # noqa: BLE001
        pass
    try:
        from core.agency import insights

        brief = insights.render_brief(days=14, max_chars=500)
        if brief:
            parts.append(brief)
    except Exception:  # noqa: BLE001
        pass
    errs = [e for e in events.recent(120) if (e.get("sev") == "error"
            or e["type"] in ("act_degraded", "task_failed_final", "self_tick_error",
                              "mcp_bridge_error", "heartbeat_error"))]
    if errs:
        parts.append("LETZTE FEHLER-SIGNALE:\n" + "\n".join(
            f"- {e['type']}: {str(e.get('payload') or '')[:120]}" for e in errs[:5]))
    prompt = "\n\n".join(parts)
    events.emit("self_tick", {"problems": len((locals().get("rep") or {}).get("problems", []))},
                session_id=sid)
    result = act(prompt, session_id=sid, escalate=escalate, task_type="reason")
    text = result["text"]
    events.emit("mission_task_done", {"id": "self", "summary": text[:300], "self": True},
                session_id=sid)
    _notify(f"🔧 Selbst-Optimierung:\n{text[:1000]}",
            kurz=f"🔧 Selbst-Optimierung: {text[:110]}")
    return {"self_tick": True, "result": text[:400]}


def _outcomes_enabled() -> bool:
    o = CONFIG.get("outcomes") or {}
    return bool(o.get("enabled", True)) if isinstance(o, dict) else True


def _attempt_prompt(task: dict, criteria: list[dict], attempt: int) -> str:
    """Task-Beschreibung + Akzeptanzkriterien; ab Versuch 2 Pruefer-Feedback + Strategiewechsel.

    Die description in der DB bleibt UNVERAENDERT (Board + stabile Kriterien) —
    nur der Arbeits-Prompt des Versuchs traegt die Zusaetze."""
    parts = []
    if task.get("objective_id"):
        ws = workingset.render(task["objective_id"])
        if ws:
            parts.append("ARBEITSSTAND ZUM ZIEL (darauf aufbauen, nichts wiederholen):\n" + ws + "\n---")
    parts.append(task["description"])
    if criteria:
        parts.append("\nAKZEPTANZKRITERIEN (dein Ergebnis wird unabhaengig dagegen geprueft):\n"
                     + "\n".join(f"- {c['text']}" for c in criteria))
    if attempt >= 2:
        fb = (task.get("feedback") or "").strip()
        if fb:
            parts.append("\nDEIN VORHERIGER VERSUCH WURDE ABGELEHNT. Pruefer-Feedback:\n" + fb)
        if attempt >= 3:
            parts.append("\nWICHTIG: Wechsle die STRATEGIE grundlegend — anderer Ansatz, andere "
                         "Quellen/Werkzeuge als zuvor. Benenne deine neue Strategie im ersten Satz.")
        else:
            parts.append("\nBehebe die Kritikpunkte gezielt.")
    # Melde-Regel (08.07.): die Telegram-Meldung zeigt NUR diesen Block —
    # er muss allein verstaendlich sein. Der Volltext bleibt im Cockpit.
    parts.append(f"\nBeende dein Ergebnis IMMER mit dem Block 'KURZ FUER {_id.user_name().upper()}:' — 3-5 Saetze "
                 "in einfacher Sprache (kurze Saetze, Fachbegriffe in Klammern erklaert): "
                 "was rausgekommen ist, was es fuer das Projekt bedeutet, was der naechste "
                 "Schritt ist. Kein Behoerdendeutsch.")
    return "\n".join(parts)


def _kurz_re() -> re.Pattern:
    """'KURZ FUER <Nutzer>'-Marker — der Name kommt live aus identity (W3),
    fuer den Werksnutzer byte-identisch zu vorher."""
    return re.compile(rf"KURZ\s+F(?:UE|Ü)R\s+{re.escape(_id.user_name().upper())}\s*:?",
                      re.IGNORECASE)


def _report(desc: str, text: str, label: str = "") -> str:
    """Telegram-Meldung fuer einen erledigten Task: Klartext-Block statt Roh-Dump.

    Der alte Schmerz: 1200 rohe Zeichen, mitten im Satz abgerissen, Hochdeutsch ohne
    Einordnung. Jetzt: NUR der 'KURZ FUER <Nutzer>'-Block (das Modell schreibt ihn per
    Melde-Regel); fehlt er, ein Anriss mit sauberem Satzende. Volltext -> Cockpit."""
    head = f"🤖 Mission-Schritt erledigt{label}:\n{desc[:180]}"
    m = _kurz_re().search(text or "")
    kurz = (text or "")[m.end():].strip().lstrip("*# \n") if m else ""
    if kurz:
        body = kurz[:900]
    else:
        body = (text or "").strip()[:700]
        if len((text or "").strip()) > 700:  # an der Satzgrenze kappen statt mitten im Wort
            body = (body.rsplit(". ", 1)[0] + ". […]") if ". " in body else body + " […]"
    return f"{head}\n\n{body}\n\n📄 Volltext im Cockpit (Kira → Log)."


def _book_playbook_results(sid: str, since_ts: float, erfolg: bool, score) -> None:
    """Audit-Fund: die Playbook-Reifung hing daran, dass das MODELL brav playbook_result
    ruft — tat es das nicht, blieb jedes Playbook ewig 'entwurf'. Jetzt deterministisch:
    hat der Lauf ein Playbook GELESEN (playbook_read im Event-Log dieser Session), wird
    das Richter-Urteil automatisch verbucht. Hat das Modell selbst schon gebucht
    (playbook_result im selben Fenster), buchen wir nicht doppelt. Raist nie."""
    try:
        import sqlite3

        from core.config import DB_PATH

        gelesen: set[str] = set()
        selbst_gebucht: set[str] = set()
        con = sqlite3.connect(DB_PATH)
        try:
            con.execute("PRAGMA busy_timeout=5000")
            rows = con.execute(
                "SELECT payload FROM events WHERE session_id=? AND ts>=? AND type='act_step'",
                (sid, since_ts)).fetchall()
        finally:
            con.close()
        for (p,) in rows:
            try:
                d = json.loads(p or "{}")
            except Exception:  # noqa: BLE001
                continue
            n = str((d.get("args") or {}).get("name") or "")
            if not n:
                continue
            if d.get("tool") == "playbook_read":
                gelesen.add(n)
            elif d.get("tool") == "playbook_result":
                selbst_gebucht.add(n)
        offen = gelesen - selbst_gebucht
        if not offen:
            return
        from core.mind import playbooks as _pb

        for n in offen:
            r = _pb.record_result(n, erfolg,
                                  notiz=f"auto: Richter-{'pass' if erfolg else 'fail'}"
                                        + (f" (Score {score})" if score is not None else ""))
            events.emit("playbook_auto_result", {"name": n, "erfolg": erfolg,
                                                 "ok": bool(r.get("ok"))}, session_id=sid)
    except Exception as e:  # noqa: BLE001 — Buchhaltung darf den Task nie mitreissen
        events.emit("playbook_book_error", {"error": str(e)[:200]})


def _execute_scored(task: dict, mission: str, escalate: bool) -> dict:
    """Ein Task-Versuch MIT Ergebnis-Rueckkopplung (S2): act -> pruefen -> pass/retry/fail.

    Retry = Requeue auf 'pending' fuer den NAECHSTEN Tick (crash-durabel, budget-glatt),
    nicht In-Tick-Schleife. Qualitaets-Retries (quality_retries) sind strikt getrennt
    von Absturz-Retries (retry_count, gehoert reset_stuck)."""
    sid = f"mission-{mission}"
    full = queue.get_task(task["id"]) or task

    if not _outcomes_enabled():  # Alt-Pfad: blind 'done' wie vor S2
        result = act(full["description"], session_id=sid, escalate=escalate, task_type="bulk")
        text = result["text"]
        queue.complete(full["id"], text)
        events.emit("mission_task_done", {"id": full["id"], "summary": text[:300]}, session_id=sid)
        _notify(_report(full["description"], text), kurz=f"✅ {full['description'][:120]}")
        return {"task": full["description"], "result": text}

    criteria = verifier.ensure_criteria(full)
    attempt = int(full.get("quality_retries") or 0) + 1
    strategy = ("standard", "eskaliert", "strategiewechsel")[min(attempt, 3) - 1]
    t0 = time.time()
    # Versuch 1 auf der billigen bulk-Route (wie bisher); ab Versuch 2 hebt 'reason' an.
    # AUSNAHME (Audit-Fund): CODE-Tasks nie auf bulk — derselbe Guard wie im
    # interaktiven code:-Pfad (docs/CODING.md §1), sonst schreibt der 24/7-Motor
    # Produktionscode mit dem Massen-Modell.
    code_task = False
    try:
        from core.agency.act import _is_code_step
        code_task = _is_code_step(full["description"])
    except Exception:  # noqa: BLE001
        pass
    result = act(_attempt_prompt(full, criteria, attempt), session_id=sid,
                 escalate=escalate,
                 task_type=("reason" if (attempt >= 2 or code_task) else "bulk"))
    text = result["text"]
    out = verifier.verify(full, criteria, text)
    outcomes.record(full["id"], attempt, criteria, out["checks"], out["score"], out["verdict"],
                    feedback=out["feedback"], strategy=strategy,
                    cost_usd=out["cost_usd"], duration_s=time.time() - t0)
    events.emit("task_scored", {"id": full["id"], "attempt": attempt, "score": out["score"],
                                "verdict": out["verdict"], "strategy": strategy}, session_id=sid)
    if full.get("objective_id"):
        try:
            takeaway = (out["feedback"] or "").strip() if out["verdict"] != "pass" \
                else (text.strip().splitlines() or [""])[0]
            workingset.append(full["objective_id"],
                              f"[{out['score']}/{out['verdict']}] {full['description'][:80]} -> {takeaway[:120]}")
        except Exception as e:  # noqa: BLE001
            events.emit("workingset_error", {"error": str(e)[:200]})

    if out["verdict"] == "pass":
        queue.complete(full["id"], text)
        queue.update_task(full["id"], score=out["score"])
        events.emit("mission_task_done", {"id": full["id"], "summary": text[:300],
                                          "score": out["score"]}, session_id=sid)
        try:
            # Hermes-Lernkreis: aus schweren, abgenommenen Tasks automatisch eine
            # wiederverwendbare Faehigkeit destillieren (Skeptiker-geprueft, gedrosselt).
            from core.mind import skillloop

            skillloop.maybe_learn(full["description"], text, attempt,
                                  time.time() - t0, criteria, out["score"])
        except Exception as e:  # noqa: BLE001
            events.emit("skill_loop_error", {"error": str(e)[:200]})
        _book_playbook_results(sid, t0, erfolg=True, score=out["score"])
        label = f" (Score {out['score']})" if out["score"] is not None else ""
        _notify(_report(full["description"], text, label),
                kurz=f"✅ ({out['score'] if out['score'] is not None else '–'}) {full['description'][:110]}")
        return {"task": full["description"], "result": text, "score": out["score"]}

    if attempt <= verifier.max_quality_retries():
        # Naechster Tick versucht es erneut: pop_next sortiert nach (priority, ts ASC),
        # der alte ts bringt den Task als erstes wieder dran.
        queue.update_task(full["id"], status="pending", quality_retries=attempt,
                          feedback=out["feedback"], score=out["score"])
        events.emit("task_retry", {"id": full["id"], "attempt": attempt, "score": out["score"],
                                   "feedback": (out["feedback"] or "")[:300]}, session_id=sid)
        return {"task": full["description"], "retry": attempt, "score": out["score"]}

    queue.complete(full["id"], text, status="failed")
    queue.update_task(full["id"], score=out["score"])
    _book_playbook_results(sid, t0, erfolg=False, score=out["score"])
    events.emit("task_failed_final", {"id": full["id"], "attempts": attempt, "score": out["score"],
                                      "desc": full["description"][:200]}, session_id=sid)
    try:
        from core.mind import reflection

        reflection.reflect_on(
            full["description"],
            f"Nach {attempt} Versuchen an den Akzeptanzkriterien gescheitert. "
            f"Letztes Pruefer-Feedback: {out['feedback']}\n\nLetztes Ergebnis:\n{text[:1500]}")
    except Exception as e:  # noqa: BLE001
        events.emit("reflect_error", {"error": str(e)[:200]})
    try:
        from core.agency import approvals

        approvals.create(
            f"Task {attempt}x an Qualitaet gescheitert: {full['description'][:80]}",
            kind="generic", source="task",
            detail=(f"Aufgabe: {full['description']}\n\nKriterien:\n"
                    + "\n".join(f"- {c['text']}" for c in criteria)
                    + f"\n\nLetzter Score: {out['score']}\nLetztes Feedback: {out['feedback']}"))
    except Exception as e:  # noqa: BLE001
        events.emit("approval_error", {"error": str(e)[:200]})
    _notify(f"⚠️ Task endgueltig gescheitert ({attempt} Versuche, Score {out['score']}):\n"
            f"{full['description']}\n\nPruefer: {(out['feedback'] or '')[:600]}", wichtig=True)
    return {"task": full["description"], "failed": True, "score": out["score"]}


def _werktakt() -> int:
    """Tagespensum pro Ziel (mission.steps_per_objective_daily, 0 = unbegrenzt).
    Regel vom 08.07.: lieber 2-3 dosierte, vielversprechende Schritte als
    4-6 Fallstudien am Tag durch den 30-Minuten-Takt."""
    try:
        return max(0, int(_mission().get("steps_per_objective_daily", 3)))
    except Exception:  # noqa: BLE001
        return 3


def _pop_paced(mission: str) -> dict | None:
    """Naechsten Task ziehen, Werktakt beachten: ist das Tagespensum eines Ziels voll,
    werden dessen Tasks auf morgen verschoben und der naechste (anderes Ziel) kommt dran."""
    import datetime as _dt

    cap = _werktakt()
    for _ in range(12):  # Sicherheitsdeckel gegen Endlos-Verschieben
        task = queue.pop_next(mission)
        if not task or not cap:
            return task
        full = queue.get_task(task["id"]) or {}
        oid = full.get("objective_id")
        if not oid or queue.done_today(oid) < cap:
            return task
        morgen = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
        queue.update_task(task["id"], status="pending", deferred_until=morgen)
        events.emit("objective_paced", {"objective_id": oid, "cap": cap,
                                        "task": str(full.get("description") or "")[:120]})
    return None


def run_once(escalate: bool = False) -> dict:
    events.init_db()
    if kill_switch_active():
        events.emit("heartbeat_halted", {"reason": "kill_switch"})
        return {"halted": True}

    m = _mission()
    mission = m.get("name", "default")
    goal = m.get("goal") or _read("GOAL.md")
    focus = _focus()
    if focus:
        goal = f"AKTUELLER FOKUS von {_id.user_name()} (hat Vorrang vor dem Dauer-Ziel): {focus}\n\n{goal}"
    queue.init_queue()

    # S8.1: jeder N-te Tick (mission.self_every) gehoert der Selbstoptimierung —
    # NUR wenn keine offene Arbeit wartet und der Nutzer keinen Fokus gesetzt hat.
    self_every = int(m.get("self_every") or 0)
    if self_every > 1 and not focus and not queue.pending(mission):
        try:
            from core.agency.missions import maintenance as _maint

            if _maint.bump_counter("mission_tick") % self_every == 0:
                return _self_improve_tick(mission, escalate)
        except Exception as e:  # noqa: BLE001
            events.emit("self_tick_error", {"error": str(e)[:200]})

    if not queue.pending(mission):
        # W1: der Business-Objectives-Grind ist ausgebaut. Der Heartbeat plant direkt
        # auf die Dienst-Mission; Lebens-Ziele (domain='leben') laufen weiter ueber
        # Coach/Briefings, nie automatisch.
        plan_goal, oid = goal, None
        # S6.2: Erkenntnisse aus dem Outcome-Ledger + Restbudget fliessen in die Planung.
        try:
            from core.agency import insights as _insights
            from core.governance import treasury as _treasury

            brief = _insights.render_brief()
            budget = _treasury.status()
        except Exception as e:  # noqa: BLE001
            events.emit("insights_error", {"error": str(e)[:200]})
            brief, budget = "", None
        tasks = planner.generate_tasks(plan_goal, _context(), escalate=escalate,
                                       budget=budget, insights=brief or None)
        for t in tasks:
            queue.add(t, mission=mission, objective_id=oid)
        events.emit("mission_planned", {"mission": mission, "tasks": tasks})

    task = _pop_paced(mission)
    if not task:
        events.emit("heartbeat_idle", {"mission": mission})
        return {"idle": True}

    events.emit("mission_task_start", {"id": task["id"], "desc": task["description"]}, session_id=f"mission-{mission}")
    try:
        # 24/7-Grind guenstig: Versuch 1 laeuft auf der 'bulk'-Stufe (flash) statt 'reason'
        # (pro) -> ~5-8x billiger pro Tick; erst Qualitaets-Retries eskalieren die Route.
        # Ergebnis-Rueckkopplung (S2): pruefen statt blind 'done' melden.
        return _execute_scored(task, mission, escalate)
    except Exception as e:  # noqa: BLE001
        queue.complete(task["id"], str(e), status="failed")
        events.emit("mission_task_failed", {"id": task["id"], "error": str(e)})
        return {"task": task["description"], "error": str(e)}


def _tick_timeout() -> int:
    """Wall-Clock-Deckel fuer EINEN Missions-Tick (act kann extern haengen). Aus config,
    Default 1200s. 0/negativ schaltet den Watchdog ab (Alt-Verhalten: blockierend warten)."""
    try:
        return int(CONFIG.get("heartbeat", {}).get("tick_timeout_seconds", 1200))
    except Exception:  # noqa: BLE001
        return 1200


# Ein laufender Tick wird in einem Daemon-Thread ausgefuehrt und mit Deadline beobachtet.
# Haengt er (act blockiert extern), laeuft der Haupt-Loop weiter — Cron/Monitor/Trigger
# frieren NICHT mit ein. Der verwaiste Tick-Thread darf im Hintergrund auslaufen (Python
# kann Threads nicht sicher toeten); ein neuer Tick startet erst, wenn der alte fertig ist.
_tick_thread: threading.Thread | None = None
_tick_result: dict = {}


def _run_tick_timeboxed() -> dict | None:
    """Startet run_once in einem Daemon-Thread und wartet bis zur Deadline.

    Rueckgabe: das Tick-Ergebnis, oder None wenn (a) ein frueherer Tick noch haengt oder
    (b) dieser Tick die Deadline riss (dann laeuft er im Hintergrund weiter). In beiden
    Faellen bleibt der Loop lebendig und macht Cron/Monitor/Pflege weiter."""
    global _tick_thread, _tick_result
    if _tick_thread is not None and _tick_thread.is_alive():
        events.emit("heartbeat_tick_still_running", {})  # Vor-Tick haengt -> Loop trotzdem weiter
        return None

    timeout = _tick_timeout()
    if timeout <= 0:  # Watchdog aus: blockierend wie frueher
        return run_once()

    _tick_result = {}

    def _worker() -> None:
        global _tick_result
        try:
            _tick_result = run_once() or {}
        except Exception as e:  # noqa: BLE001 — Tick-Absturz darf den Loop nie reissen
            _tick_result = {"error": str(e)}
            events.emit("heartbeat_error", {"error": str(e)[:200]})

    _tick_thread = threading.Thread(target=_worker, name="mission-tick", daemon=True)
    _tick_thread.start()
    _tick_thread.join(timeout)
    if _tick_thread.is_alive():
        events.emit("heartbeat_tick_timeout", {"timeout_s": timeout})
        _notify(wichtig=True, text=f"⏱ Ein Missions-Tick haengt seit >{timeout}s — der Loop laeuft weiter "
                "(Cron/Monitor aktiv), der Tick werkelt im Hintergrund.")
        return None
    return _tick_result


# Die Cron-Strecke bekommt denselben Waechter: run_due arbeitet alle faelligen Jobs
# sequenziell ab, jeder Job ruft act() — gegen ein langsames lokales Modell oder einen
# toten Endpunkt kann EIN Durchlauf viele Minuten haengen und hielt frueher die ganze
# naechste Runde auf (Nachtdenker/Erinnerungen/Monitor standen still). Ein Ueberzieher
# laeuft jetzt im Hintergrund aus; solange er lebt, startet kein zweiter Durchlauf
# (kein Doppel-Lauf derselben Jobs).
_cron_thread: threading.Thread | None = None


def _run_cron_timeboxed() -> None:
    """Startet cron.run_due in einem Daemon-Thread und wartet bis zur Deadline.

    Reisst der Durchlauf die Deadline, macht der Loop weiter und die faelligen Jobs
    werkeln im Hintergrund zu Ende — gleiche Mechanik wie beim Missions-Tick."""
    global _cron_thread
    if _cron_thread is not None and _cron_thread.is_alive():
        events.emit("cron_tick_still_running", {})  # Vor-Durchlauf haengt -> Loop trotzdem weiter
        return

    def _worker() -> None:
        try:
            from core.agency.missions import cron

            cron.run_due()
        except Exception as e:  # noqa: BLE001 — Cron-Absturz darf den Loop nie reissen
            events.emit("cron_error", {"error": str(e)})

    timeout = _tick_timeout()
    if timeout <= 0:  # Watchdog aus: blockierend wie frueher
        _worker()
        return

    _cron_thread = threading.Thread(target=_worker, name="cron-tick", daemon=True)
    _cron_thread.start()
    _cron_thread.join(timeout)
    if _cron_thread.is_alive():
        events.emit("cron_tick_timeout", {"timeout_s": timeout})
        _notify(wichtig=True, text=f"⏱ Die Cron-Strecke haengt seit >{timeout}s — der Loop laeuft "
                "weiter, die faelligen Jobs werkeln im Hintergrund zu Ende.")


def run_forever(interval: int | None = None) -> None:
    interval = interval or CONFIG.get("heartbeat", {}).get("interval_seconds", 1800)
    events.init_db()
    try:  # MCP-Bruecke im Hintergrund anschliessen (Ausfall darf den Boot nie bricken)
        from core.agency.mcp import registry_bridge as _mcp_bridge

        _mcp_bridge.init_background()
    except Exception as e:  # noqa: BLE001
        events.emit("mcp_bridge_error", {"error": str(e)[:200]})
    last_stuck_check = 0.0
    print(f"Mission-Runner laeuft. Cron+Monitor laufen immer; 24/7-Missionen nur wenn eingeschaltet. Takt {interval}s.")
    while True:
        try:
            if kill_switch_active():
                time.sleep(15)  # Not-Aus: pausieren, nach /go weiter
                continue

            # Durable Execution: haengengebliebene Tasks periodisch wiederbeleben.
            try:
                if time.time() - last_stuck_check >= 600:
                    reset_result = queue.reset_stuck(timeout_seconds=1800, max_retries=3)
                    last_stuck_check = time.time()
                    if reset_result.get("requeued", 0) > 0 or reset_result.get("failed", 0) > 0:
                        events.emit("mission_stuck_reset", reset_result)
            except Exception as e:  # noqa: BLE001
                events.emit("stuck_reset_error", {"error": str(e)})

            # Immer (unabhaengig vom Missions-Toggle): Monitor + geplante Aufgaben.
            # Der Monitor MERKT sich Neues nur (Puffer) und pingt NICHT mehr spontan;
            # die News liefert das Briefing (08:00/20:00) in Kiras Stimme. Spontanes
            # Melden nur, wenn der Nutzer es ueber config monitor.spontaneous_notify anschaltet.
            try:
                from core.agency.connectors import news_monitor

                spontan = bool(CONFIG.get("monitor", {}).get("spontaneous_notify", False))
                news_monitor.run_all(force=False, notify=spontan)
            except Exception as e:  # noqa: BLE001
                events.emit("monitor_error", {"error": str(e)})
            try:
                # Dashboard-Aenderungen (Modellwechsel/set_override) auch hier live
                # nachladen — der Runner ist wie der Bot ein Langlaeufer-Prozess.
                from core import config as _cfg_mod

                if _cfg_mod.refresh_overrides():
                    events.emit("config_refreshed", {"prozess": "runner"})
            except Exception as e:  # noqa: BLE001
                events.emit("config_refresh_error", {"error": str(e)})
            try:
                # Nachtdenker (GPU-Zeitteilung): Fenster-Automat tickt 24/7 mit —
                # NACH refresh_overrides, damit Cockpit-Aenderungen sofort greifen.
                from core.kernel import nachtdenker

                nachtdenker.tick()
            except Exception as e:  # noqa: BLE001
                events.emit("nachtdenker_fehler", {"error": str(e)[:200]})
            try:
                _run_cron_timeboxed()
            except Exception as e:  # noqa: BLE001
                events.emit("cron_error", {"error": str(e)})
            try:
                # Einmal-Wecker OHNE Telegram: Cockpit-Zustellung als Fallback (mit
                # Telegram stellt der Bot zu — genau EIN Zusteller, kein Datei-Rennen).
                from core.agency import erinnerungen

                if not erinnerungen.telegram_konfiguriert():
                    erinnerungen.zustellen(None)
            except Exception as e:  # noqa: BLE001
                events.emit("erinnerung_error", {"error": str(e)})
            try:
                # Proaktive Trigger (S4): neue Events gegen Wenn-Dann-Reflexe matchen.
                from core.agency.missions import triggers as _triggers

                _triggers.check()
            except Exception as e:  # noqa: BLE001
                events.emit("trigger_error", {"error": str(e)})
            try:
                # Taegliche Pflege: Skill-Bibliothek entduplizieren (gebaut, jetzt verdrahtet).
                from core.agency.missions import maintenance

                if maintenance.maybe_run("curate_skills"):
                    from core.mind import curator

                    curator.curate_skills()
                if maintenance.maybe_run("curate_lessons"):
                    from core.mind import curator

                    curator.curate_lessons()
                if maintenance.maybe_run("embed_backfill", interval_s=7 * 86400):
                    from core.mind.memory import store as _mem

                    n = _mem.backfill_embeddings()
                    if n:
                        events.emit("embed_backfill", {"count": n})
                # P7 dream: alte Sessions -> wenige Kern-Erinnerungen (cheapest gate
                # first: enabled/Reife/Lock prueft dream selbst, das Zeit-Gate haelt
                # maybe_run — enabled() davor, damit AUS gar nicht erst stempelt).
                from core.mind import dream as _dream

                if _dream.enabled() and maintenance.maybe_run("dream", interval_s=_dream.intervall_s()):
                    _dream.dream()
                if maintenance.maybe_run("body_refresh"):
                    from core.mind import body

                    res = body.refresh()  # Anatomie-Fakten frisch abschreiben (S5)
                    events.emit("body_refreshed", res)
                if maintenance.maybe_run("playbook_index"):
                    from core.mind import playbooks as _pb

                    res = _pb.refresh_index()  # Vault-INDEX frisch abschreiben (S11)
                    events.emit("playbook_index_refreshed", res)
                if maintenance.maybe_run("insights_weekly", interval_s=7 * 86400):
                    from core.agency import insights as _ins

                    lessons = _ins.weekly_lessons()  # Outcome-Muster -> Lektionen (S6.2)
                    if lessons:
                        events.emit("insights_lessons", {"count": len(lessons)})
                if maintenance.maybe_run("report_rollup", interval_s=6 * 3600):
                    # Phase 2: Wochen-/Monatsreport in den Vault (deterministisch, 0 Token);
                    # die Funktionen pruefen Faelligkeit selbst (Montag / Monatserster).
                    from core.agency import reports as _reports

                    for _r in _reports.rollup():
                        _notify(f"📒 {_r['art']} {_r['label']} liegt im Vault (reports/).",
                                kurz=f"{_r['art']} {_r['label']} geschrieben")
                if maintenance.maybe_run("bluesky_stats", interval_s=86400):
                    # Phase 3: Follower-Zeitreihe (0 Token, oeffentliche API, kein Login) —
                    # sichtbar als metric-Widget/Ziele-Dashboard ("bluesky_follower").
                    from core.agency.connectors import bluesky as _bsky
                    from core.agency.missions import metrics as _metrics

                    stats = _bsky.profile_stats()
                    if stats:
                        _metrics.log("bluesky_follower", stats["followers"])
                        events.emit("bluesky_stats", stats)
                if maintenance.maybe_run("calibration_report", interval_s=7 * 86400):
                    # B-025: Nudge-/Fehler-/Fallback-Raten pro Modell -> Vorschlag in die
                    # Inbox (nur bei genug Daten), damit der Nutzer Rollen datenbasiert nachzieht.
                    from core.agency import calibration as _cal

                    _cal.propose()
                if maintenance.maybe_run("selfmetric_snapshot", interval_s=7 * 86400):
                    # Selbstmessung (0 Token): Wochen-Messpunkt in die Zeitreihe -> Drift sichtbar.
                    from core.agency import selfmetrics as _sm

                    pt = _sm.snapshot()
                    events.emit("selfmetric_snapshot", pt)
                if maintenance.maybe_run("db_backup", interval_s=7 * 86400):
                    # Wochen-Backup der state.db (Gedaechtnis/Ziele/Ledger) — Audit-Fund:
                    # ohne Backup waere ein Platten-Crash der einzige Totalverlust-Pfad.
                    from core.kernel import backup as _bk

                    events.emit("db_backup", _bk.backup_state_db())
                if maintenance.maybe_run("doctor_check", interval_s=7 * 86400):
                    from core.kernel import doctor

                    rep = doctor.check()  # 0-Token-Selbst-Check (S5.6)
                    events.emit("doctor_report", {"problems": rep.get("problems", [])[:10],
                                                  "ok": rep.get("ok")})
                    if rep.get("problems"):
                        _notify("🩺 Selbst-Check meldet:\n- " + "\n- ".join(rep["problems"][:5]),
                                wichtig=True)
                if maintenance.maybe_run("desktop_watch", interval_s=86400):
                    # S8.5: Desktop-Pflege — taeglicher lokaler Scan -> Sortiervorschlag (kein Move).
                    from core.agency import desktop_watch

                    res = desktop_watch.propose()
                    if res.get("suggestions"):
                        events.emit("desktop_watch_done", res)
                        _notify(f"🗂 Aufraeum-Vorschlag: {res['suggestions']} Dateien "
                                "warten in der Freigabe-Inbox auf dein OK.")
            except Exception as e:  # noqa: BLE001
                events.emit("maintenance_error", {"error": str(e)})

            if heartbeat_on():
                out = _run_tick_timeboxed()
                if out is not None:  # None = Vor-Tick haengt noch oder Deadline gerissen
                    print("tick:", {k: (str(v)[:80]) for k, v in out.items()})
                # Unterbrechbarer Schlaf: reagiert binnen ~15s auf Abschalten (Dashboard-
                # Toggle) oder Kill-Switch, statt stur bis zu 'interval' Sek. weiterzulaufen.
                slept = 0
                while slept < interval and heartbeat_on() and not kill_switch_active():
                    step = min(15, interval - slept)
                    time.sleep(step)
                    slept += step
            else:
                time.sleep(60)  # aus -> Cron/Monitor ~minuetlich pruefen
        except KeyboardInterrupt:
            print("\nGestoppt.")
            break
        except Exception as e:  # noqa: BLE001
            events.emit("heartbeat_error", {"error": str(e)})
            time.sleep(20)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows-Konsole nicht crashen lassen
    except Exception:
        pass
    if "--once" in sys.argv:
        import json

        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    else:
        run_forever()