"""Skill-Automatik (der Hermes-Lernkreis): nach einem erfolgreich VERIFIZIERTEN schweren
Task destilliert Kira automatisch eine wiederverwendbare Faehigkeit — und ein SKEPTIKER
prueft sie, bevor sie ins Gedaechtnis darf. Ohne Gate wuerde sich die Skill-Bibliothek
mit Selbstlob und Einmal-Notizen fuellen und recall_skills() vergiften.

Bewusst gedrosselt und billig:
- nur SCHWERE Tasks (>= 2 Versuche ODER lange Laufzeit ODER >= 3 Akzeptanzkriterien)
- nur bei gutem Score (>= 75)
- max. MAX_NEW_PER_DAY Neuzugaenge pro Tag (persistenter Tageszaehler)
- Destillat auf der bulk-Route (flash), Skeptiker auf reason (der Denker richtet)
- Firewall-/Testmodus-sicher: ohne Netz oder im Test passiert schlicht nichts.

Der Kurator (curate_skills, taeglich) bleibt die zweite Verteidigungslinie gegen Duplikate.
"""
from __future__ import annotations

import datetime
import re

from core.kernel import events

HEAVY_MIN_DURATION_S = 120.0   # ab dieser Laufzeit gilt ein Task als "schwer"
MIN_SCORE = 75                 # nur aus wirklich gelungenen Ergebnissen lernen
MAX_NEW_PER_DAY = 5            # Kosten-/Qualitaetsbremse fuer den 24/7-Betrieb

_DISTILL = (
    "Ein Task wurde erfolgreich abgeschlossen und vom Pruefer abgenommen.\n\n"
    "TASK: {task}\n\nERGEBNIS (Auszug):\n{result}\n\n"
    "Frage: Steckt darin EINE wiederverwendbare FAEHIGKEIT — ein Vorgehen, das bei "
    "KUENFTIGEN, ANDEREN Aufgaben derselben Art hilft (Schritte, Befehle, Stolperfallen)?\n"
    "Wenn ja, antworte EXAKT in diesem Format (knapp, max 5 Zeilen Schritte):\n"
    "NAME: <kurzer Skill-Name>\nSCHRITTE: <die Anleitung>\n"
    "Wenn nichts echt Wiederverwendbares drinsteckt (Einmal-Aufgabe, Trivialitaet), "
    "antworte NUR mit: NONE"
)

_SKEPTIC = (
    "Du bist ein strenger SKEPTIKER. Kira will sich folgende Faehigkeit merken:\n\n"
    "NAME: {name}\nSCHRITTE: {steps}\n\n(Gelernt aus Task: {task})\n\n"
    "Pruefe hart: (a) Ist das ueber DIESEN einen Task hinaus wiederverwendbar? "
    "(b) Ist das Vorgehen fachlich plausibel? (c) Ist es mehr als eine Trivialitaet, "
    "die jedes Modell ohnehin weiss?\n"
    "Antworte NUR mit 'JA' wenn ALLE drei Punkte erfuellt sind, sonst mit "
    "'NEIN: <kurzer Grund>'. Im Zweifel NEIN."
)


def _is_heavy(attempt: int, duration_s: float, criteria: list | None) -> bool:
    """Schwer = mehrere Versuche noetig ODER lange gelaufen ODER viele Kriterien."""
    return (int(attempt or 0) >= 2 or float(duration_s or 0) >= HEAVY_MIN_DURATION_S
            or len(criteria or []) >= 3)


def _day_count_ok() -> bool:
    """Persistenter Tageszaehler (ueberlebt Neustarts): hoechstens N neue Skills am Tag."""
    from core.agency.missions import maintenance

    key = "skillloop_" + datetime.date.today().isoformat()
    return maintenance.bump_counter(key) <= MAX_NEW_PER_DAY


def maybe_learn(task_desc: str, result_text: str, attempt: int, duration_s: float,
                criteria: list | None, score: int | None) -> dict | None:
    """Der komplette Kreis: schwer genug? -> destillieren -> Skeptiker -> speichern.

    Gibt {"name": ..., "steps": ...} zurueck, wenn ein Skill gespeichert wurde, sonst None.
    Raist NIE — ein Fehler hier darf den Mission-Loop nicht mitreissen."""
    try:
        from core import config

        if config.test_mode() or config.outbound_blocked():
            return None
        if score is None or int(score) < MIN_SCORE:
            return None
        if not _is_heavy(attempt, duration_s, criteria):
            return None
        if not _day_count_ok():
            events.emit("skill_throttled", {"task": (task_desc or "")[:120]})
            return None

        from core.kernel import llm_router

        # 1) Destillat — billig (bulk/flash reicht fuer die Zusammenfassung)
        r = llm_router.complete(
            [{"role": "user", "content": _DISTILL.format(task=(task_desc or "")[:400],
                                                         result=(result_text or "")[:1500])}],
            task_type="bulk", session_id="skill-loop")
        draft = (r.get("text") or "").strip()
        if not draft or draft.upper().startswith("NONE"):
            return None
        m_name = re.search(r"NAME:\s*(.+)", draft)
        m_steps = re.search(r"SCHRITTE:\s*(.+)", draft, re.DOTALL)
        if not m_name or not m_steps:
            return None
        name = m_name.group(1).strip()[:80]
        steps = m_steps.group(1).strip()[:800]

        # 2) Skeptiker-Gate — der Denker richtet (verhindert Selbstlob & Einmal-Notizen)
        v = llm_router.complete(
            [{"role": "user", "content": _SKEPTIC.format(name=name, steps=steps,
                                                         task=(task_desc or "")[:300])}],
            task_type="reason", session_id="skill-loop")
        urteil = (v.get("text") or "").strip()
        if not urteil.upper().startswith("JA"):
            events.emit("skill_rejected", {"name": name, "grund": urteil[:200]})
            return None

        # 3) Speichern — gleicher Weg wie das learn_skill-Werkzeug
        from core.mind.memory import store as memory

        memory.init_memory()
        memory.remember(f"SKILL [{name}]: {steps}", role="self", kind="skill")
        events.emit("skill_learned", {"name": name, "task": (task_desc or "")[:120]})
        return {"name": name, "steps": steps}
    except Exception as e:  # noqa: BLE001 — Lernen ist Bonus, nie Blocker
        try:
            events.emit("skill_loop_error", {"error": str(e)[:200]})
        except Exception:  # noqa: BLE001
            pass
        return None
