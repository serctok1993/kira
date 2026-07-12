"""Council: mehrere Perspektiven debattieren eine Frage, ein Judge entscheidet.

Genau das vom Nutzer gewuenschte Primitiv ('Council von Subagenten mit Judge').
Jede Stimme und das Urteil werden als Event protokolliert.
"""
from __future__ import annotations

import sys

from core import identity as _id
from core.kernel import events, llm_router
from core.mind.agent import _read

DEFAULT_PERSONAS = [
    ("Visionaer", "Du denkst gross, chancenorientiert, mutig. Du siehst das groesste Potenzial und den staerksten Hebel."),
    ("Skeptiker", "Du bist der Risikomanager. Du suchst Schwachstellen, Kosten und Gefahren — was schiefgehen kann."),
    ("Macher", "Du bist radikal pragmatisch. Du fragst: Was ist der konkrete naechste Schritt, der schon heute umsetzbar ist?"),
]


def deliberate(
    question: str,
    personas: list[tuple[str, str]] | None = None,
    context: str | None = None,
    escalate: bool = False,
) -> dict:
    events.init_db()
    personas = personas or DEFAULT_PERSONAS
    constitution = _read("constitution.md")
    goal = _read("GOAL.md")
    base = f"Verfassung (bindend):\n{constitution}\n\nZiel:\n{goal}\n"
    if context:
        base += f"\nKontext:\n{context}\n"

    events.emit("council_opening", {"question": question, "personas": [p[0] for p in personas]})

    positions: list[tuple[str, str]] = []
    for name, persona in personas:
        sys_prompt = (
            f"{base}\nDu bist '{name}' in einem Beraterrat fuer {_id.user_name()} und seinen Agenten. "
            f"{persona}\nAntworte in hoechstens 6 Saetzen, klar und begruendet."
        )
        res = llm_router.complete(
            [{"role": "user", "content": f"Frage: {question}"}],
            system=sys_prompt,
            task_type="reason",
            escalate=escalate,
        )
        text = res["text"].strip()
        positions.append((name, text))
        events.emit("council_argument", {"persona": name, "text": text})

    debate = "\n\n".join(f"## {n}\n{t}" for n, t in positions)
    judge_sys = (
        f"{base}\nDu bist der JUDGE des Rates. Waege die Positionen ehrlich ab und triff eine "
        f"klare Entscheidung im Sinne der Mission und der Verfassung."
    )
    judge_prompt = (
        f"Frage: {question}\n\nDie Positionen des Rates:\n\n{debate}\n\n"
        f"Antworte genau so:\nENTSCHEIDUNG: <ein klarer Satz>\n"
        f"BEGRUENDUNG: <2-4 Saetze>\nWICHTIGSTER EINWAND: <1 Satz>"
    )
    verdict = llm_router.complete(
        [{"role": "user", "content": judge_prompt}],
        system=judge_sys,
        task_type="reason",
        escalate=escalate,
    )
    decision = verdict["text"].strip()
    events.emit("council_verdict", {"question": question, "decision": decision})
    return {"question": question, "positions": positions, "verdict": decision}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Was ist der beste naechste Schritt Richtung Freiheit?"
    r = deliberate(q)
    for n, t in r["positions"]:
        print(f"\n[{n}]\n{t}")
    print(f"\n=== URTEIL ===\n{r['verdict']}")
