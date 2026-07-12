"""Reflexion: der Agent kritisiert sein eigenes juengstes Handeln und zieht Lektionen.

Die Lektionen werden als Erinnerungen (kind='lesson') gespeichert und fliessen
ab dann in jeden System-Prompt ein (siehe agent.build_system_prompt).
Das ist Meta-Kognition: aus 'self-modify' wird ein strukturierter Lernzyklus.
"""
from __future__ import annotations

import re

from core import identity as _id
from core.kernel import events, llm_router
from core.mind.agent import _read
from core.mind.memory import store as memory

REFLECT_SYSTEM = (
    "Du bist der reflektierende, kritische Teil eines autonomen Partner-Agenten. "
    "Du bewertest das eigene juengste Handeln ehrlich und schonungslos. "
    "Du beschoenigst nichts und suchst echte, umsetzbare Lektionen statt Floskeln."
)


def _recent_context(limit: int = 40) -> str:
    evs = events.recent(limit)
    lines: list[str] = []
    for e in reversed(evs):
        t, p = e["type"], e["payload"]
        if t == "user_message":
            lines.append(f"{_id.user_name()}: {p.get('text', '')[:300]}")
        elif t == "partner_message":
            lines.append(f"Ich: {p.get('text', '')[:300]}")
        elif t == "council_verdict":
            lines.append(f"[Rats-Urteil] {p.get('decision', '')[:200]}")
        elif t == "self_update_applied":
            lines.append(f"[Selbst-Update] {p.get('doc')}: {p.get('reason', '')[:150]}")
    return "\n".join(lines) if lines else "(noch nichts Nennenswertes geschehen)"


def _extract_lessons(text: str) -> list[str]:
    """Robuste Erfassung der Lektionen.

    Erkennt die Ueberschrift auch mit Markdown-Deko (**LEKTIONEN:**, ## ...) und
    erfasst sowohl Aufzaehlungen ('-', '*', '•') als auch nummerierte Listen ('1.', '2)').
    LEKTIONEN steht im vorgegebenen Format als letzter Abschnitt -> wir lesen bis zum Ende.
    """
    lessons: list[str] = []
    capture = False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        clean = s.strip("#*_ ").strip()
        if clean.upper().startswith("LEKTION"):
            capture = True
            continue
        if not capture:
            continue
        m = re.match(r"^(?:[-*•]|\d+[.)])\s*(.+)$", s)
        if m:
            item = re.sub(r"\*+", "", m.group(1)).strip()
            if item:
                lessons.append(item)
    return lessons[:5]


def reflect(lookback: int = 40, escalate: bool = False) -> dict:
    events.init_db()
    memory.init_memory()
    goal = _read("GOAL.md")
    context = _recent_context(lookback)

    prompt = f"""Hier ist mein juengstes Handeln (chronologisch, alt -> neu):

{context}

Mein Ziel (GOAL):
{goal}

Reflektiere als mein innerer kritischer Beobachter. Halte dich genau an dieses Format:

WAS LIEF GUT:
- ...
WAS LIEF SCHLECHT:
- ...
LEKTIONEN (hoechstens 3): je EIN vollstaendiger Satz Klartext, den {_id.user_name()} ohne Kontext
versteht — WAS gelernt wurde und WIE es kuenftig angewendet wird. Keine Stichworte,
keine Insider-Abkuerzungen, nicht mitten im Satz enden:
- ...
"""
    res = llm_router.complete(
        [{"role": "user", "content": prompt}], system=REFLECT_SYSTEM, task_type="bulk", escalate=escalate
    )
    text = res["text"].strip()
    lessons = _extract_lessons(text)
    for lesson in lessons:
        memory.remember(lesson, role="self", kind="lesson")
    events.emit("reflection", {"summary": text, "lessons": lessons, "model": res["model"]})
    return {"text": text, "lessons": lessons}


def reflect_on(task: str, work: str, escalate: bool = False) -> dict:
    """Fokussierte Reflexion ueber EINE gerade erledigte Aufgabe -> konkrete Lektionen.

    Wird automatisch am Ende von plan_and_execute aufgerufen, damit Kira mit jeder
    groesseren Aufgabe dazulernt (Lektionen fliessen kuenftig in jeden System-Prompt)."""
    events.init_db()
    memory.init_memory()
    prompt = f"""Ich habe gerade diese Aufgabe bearbeitet:
{task}

Was ich getan habe (Schritte und Ergebnisse):
{work[:2500]}

Reflektiere kurz und ehrlich als mein innerer kritischer Beobachter. Halte dich an dieses Format:

LEKTIONEN (hoechstens 3): je EIN vollstaendiger Satz Klartext, den {_id.user_name()} ohne Kontext
versteht — WAS gelernt wurde und WIE es bei kuenftigen aehnlichen Aufgaben angewendet wird.
Keine Stichworte, nicht mitten im Satz enden:
- ..."""
    res = llm_router.complete(
        [{"role": "user", "content": prompt}], system=REFLECT_SYSTEM, task_type="bulk", escalate=escalate
    )
    lessons = _extract_lessons(res["text"])
    for lesson in lessons:
        memory.remember(lesson, role="self", kind="lesson")
    events.emit("reflection", {"summary": res["text"][:400], "lessons": lessons, "scope": "task"})
    return {"text": res["text"], "lessons": lessons}


if __name__ == "__main__":
    r = reflect()
    print(r["text"])
    print("\nGespeicherte Lektionen:", r["lessons"])
