"""Planner: zerlegt die Mission in die naechsten konkreten Aufgaben."""
from __future__ import annotations

import re

from core.kernel import llm_router
from core.mind.agent import _read


def generate_tasks(goal: str, context: str, n: int = 3, escalate: bool = False) -> list[str]:
    system = (
        _read("constitution.md")
        + "\n\nDu bist der Planer. Du zerlegst ein Ziel in kleine, eigenstaendig "
        "ausfuehrbare Schritte. Nur lesende Recherche/Reflexion, keine Aussen-Aktionen "
        "(kein Geld, keine Mails, keine Posts)."
    )
    user = (
        f"ZIEL DER MISSION:\n{goal}\n\n"
        f"BISHERIGER FORTSCHRITT:\n{context}\n\n"
        f"Nenne die naechsten {n} Aufgaben, die dem Ziel dienen und NICHT wiederholen, "
        f"was schon erledigt ist. WICHTIG: jede Aufgabe ist KLEIN und ATOMAR — genau EIN "
        f"konkreter Rechercheschritt (z.B. 'Suche und lies 3 Quellen zur Nachfrage nach "
        f"Micro-SaaS X'), NICHT mehrere Themen in einer Aufgabe. Jede als eine Zeile mit '- '. "
        f"Nur Recherche/Analyse/Reflexion."
    )
    # Grind-Sparsamkeit: Task-Zerlegung braucht nicht die teure 'reason'-Stufe (pro),
    # 'bulk' (flash/lokal) genuegt fuer atomare Rechercheschritte. escalate=True hebt weiter an.
    res = llm_router.complete([{"role": "user", "content": user}], system=system, task_type="bulk", escalate=escalate)
    tasks = []
    for line in res["text"].splitlines():
        s = line.strip()
        m = re.match(r"^(?:[-*•]|\d+[.)])\s*(.+)$", s)
        if m:
            item = re.sub(r"\*+", "", m.group(1)).strip()
            if len(item) > 5:
                tasks.append(item)
    return tasks[:n]
