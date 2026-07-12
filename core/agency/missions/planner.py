"""Planner: zerlegt die Mission in die naechsten konkreten Aufgaben.

S6.3 zusaetzlich: propose_weekly_objectives() zerlegt grosse/monatliche Ziele in
Wochen-Ziele (Meilensteine) — die Bruecke von Langfrist-Zielen zur Task-Queue."""
from __future__ import annotations

import datetime
import re

from core import identity as _id
from core.kernel import llm_router
from core.mind.agent import _read


def generate_tasks(goal: str, context: str, n: int = 3, escalate: bool = False,
                   budget: dict | None = None, insights: str | None = None) -> list[str]:
    system = (
        _read("constitution.md")
        + "\n\nDu bist der Planer. Du zerlegst ein Ziel in kleine, eigenstaendig "
        "ausfuehrbare Schritte. Nur lesende Recherche/Reflexion, keine Aussen-Aktionen "
        "(kein Geld, keine Mails, keine Posts)."
    )
    user = (
        f"ZIEL DER MISSION:\n{goal}\n\n"
        f"BISHERIGER FORTSCHRITT:\n{context}\n\n"
    )
    if insights:  # S6.2: Outcome-Muster fliessen in die Planung zurueck
        user += insights + "\n\n"
    if budget:  # S8.1: KEINE Budget-Kalkulation mehr (das macht der Nutzer) — nur die
        dl, dr = budget.get("day_limit"), budget.get("day_remaining")  # Schutz-Warnung bei knapp.
        if dl and dr is not None and dr < 0.2 * float(dl):
            user += ("HINWEIS: Tagesbudget fast erschoepft — plane NUR billige lokale "
                     "Analyse-/Aufraeumschritte, keine teuren Recherche-Ketten.\n\n")
    user += (
        f"Nenne die naechsten {n} Aufgaben, die dem Ziel dienen und NICHT wiederholen, "
        f"was schon erledigt ist. WICHTIG: jede Aufgabe ist KLEIN und ATOMAR — genau EIN "
        f"konkreter Rechercheschritt (z.B. 'Suche und lies 3 Quellen zur Nachfrage nach "
        f"Micro-SaaS X'), NICHT mehrere Themen in einer Aufgabe. Jede als eine Zeile mit '- '. "
        f"Nur Recherche/Analyse/Reflexion.\n"
        f"RECHERCHE-DISZIPLIN (bindend): Fallstudien/Markt-Analysen nur, wenn sie "
        f"VIELVERSPRECHEND sind und eine konkrete Entscheidung vorbereiten — Klasse statt "
        f"Masse, maximal EINE Fallstudie pro Planung. Jede Analyse-Aufgabe muss mit einer "
        f"direkten Empfehlung enden, wie {_id.user_name()} das konkret nutzen/umsetzen kann."
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


def propose_weekly_objectives(parent: dict, context: str, n: int = 3,
                              escalate: bool = False) -> list[dict]:
    """Zerlegt ein grosses/monatliches Ziel in Wochen-Ziele (S6.3).

    Ausgabe-Vertrag des Modells: genau eine Zeile pro Ziel im Format
    '- <Titel> | <YYYY-MM-DD>'. Zeilen ohne gueltiges ISO-Datum oder mit Datum
    NACH dem Eltern-Zieldatum werden verworfen (robustes Parsen statt Vertrauen)."""
    system = (
        _read("constitution.md")
        + "\n\nDu bist der Stratege. Du zerlegst ein grosses Ziel in konkrete "
        "Wochen-Ziele (Meilensteine). Jedes Wochen-Ziel ist in EINER Woche schaffbar, "
        "messbar formuliert und baut auf den vorherigen auf."
    )
    tail = ""
    parent_due = None
    if parent.get("target_date"):
        try:
            parent_due = datetime.date.fromisoformat(str(parent["target_date"])[:10])
            tail = f" Das Eltern-Ziel hat Zieldatum {parent_due.isoformat()} — alle Wochen-Ziele liegen davor."
        except ValueError:
            parent_due = None
    user = (
        f"GROSSES ZIEL [{parent.get('kind', 'big')}]: {parent['title']}\n"
        + (f"NOTIZEN: {parent['notes']}\n" if parent.get("notes") else "")
        + f"\nKONTEXT:\n{context}\n\n"
        f"Schlage die naechsten {n} WOCHEN-Ziele vor (heute ist {datetime.date.today().isoformat()}).{tail}\n"
        f"FORMAT: genau eine Zeile pro Ziel, sonst nichts: - <Titel> | <YYYY-MM-DD>"
    )
    res = llm_router.complete([{"role": "user", "content": user}], system=system,
                              task_type="reason", escalate=escalate)
    out: list[dict] = []
    for line in res["text"].splitlines():
        m = re.match(r"^(?:[-*•]|\d+[.)])?\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*$", line.strip())
        if not m:
            continue
        title = re.sub(r"\*+", "", m.group(1)).strip("- ").strip()
        try:
            due = datetime.date.fromisoformat(m.group(2))
        except ValueError:
            continue
        if len(title) < 5 or (parent_due and due > parent_due):
            continue
        out.append({"title": title, "target_date": due.isoformat()})
    return out[:n]
