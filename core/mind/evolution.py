"""Selbst-Evolution: der Agent darf SOUL.md und GOAL.md umschreiben.

Drei Sicherungen aus der Verfassung sind fest verdrahtet:
1. constitution.md ist NICHT veraenderbar (nur SOUL/GOAL).
2. Ein Verfassungs-Waechter prueft jeden Vorschlag (fail-safe: im Zweifel ablehnen).
3. Jede Anwendung legt vorher ein Backup an (Undo-Spur) und wird protokolliert.

Ablauf: propose_update() erzeugt einen Vorschlag (schreibt ihn nach data/proposals/),
apply_update() uebernimmt ihn nach Backup. So bleibt ein Mensch (vorerst) in der Schleife.
"""
from __future__ import annotations

import sys
import time

from core.config import DATA_DIR, MIND_DIR
from core.kernel import events, llm_router
from core.mind.agent import _read

MUTABLE = {"SOUL.md", "GOAL.md", "BODY.md"}  # BODY: Erzaehl-Teile via Freigabe; den AUTO-Block schreibt body.refresh()
HISTORY_DIR = MIND_DIR / "history"
PROPOSAL_DIR = DATA_DIR / "proposals"


def _strip_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _guardian_check(doc: str, new_content: str, constitution: str, escalate: bool = False) -> dict:
    sys_prompt = (
        "Du bist der Verfassungs-Waechter eines autonomen Agenten. Pruefe, ob ein "
        "vorgeschlagenes Dokument der Verfassung widerspricht. Erste Zeile NUR das Wort "
        "COMPLIANT oder VIOLATION, danach ein Satz Begruendung."
    )
    user = (
        f"VERFASSUNG:\n{constitution}\n\nVORGESCHLAGENES '{doc}':\n{new_content}\n\n"
        f"Widerspricht der Vorschlag der Verfassung?"
    )
    res = llm_router.complete(
        [{"role": "user", "content": user}], system=sys_prompt, task_type="reason", escalate=escalate
    )
    text = res["text"].strip()
    first = text.splitlines()[0].upper() if text else ""
    compliant = ("COMPLIANT" in first) and ("VIOLATION" not in first)
    return {"compliant": compliant, "reason": text}


def propose_update(doc: str, instruction: str | None = None, escalate: bool = False) -> dict:
    if doc not in MUTABLE:
        raise ValueError(f"'{doc}' ist unveraenderlich. Nur {sorted(MUTABLE)} duerfen sich entwickeln.")
    events.init_db()
    constitution = _read("constitution.md")
    current = _read(doc)

    sys_prompt = (
        f"Du ueberarbeitest dein eigenes Dokument '{doc}'. Deine VERFASSUNG ist bindend und "
        f"darf durch die Ueberarbeitung NIEMALS verletzt werden:\n---\n{constitution}\n---\n"
        f"Gib NUR den vollstaendigen neuen Inhalt von '{doc}' als Markdown zurueck, sonst nichts."
    )
    user = f"Aktueller Inhalt von {doc}:\n---\n{current}\n---\n"
    if instruction:
        user += f"\nAenderungswunsch: {instruction}\n"
    user += "\nSchreibe eine verbesserte Version. Bleibe du selbst, aber wachse."

    res = llm_router.complete(
        [{"role": "user", "content": user}], system=sys_prompt, task_type="reason", escalate=escalate
    )
    new_content = _strip_fence(res["text"].strip())

    verdict = _guardian_check(doc, new_content, constitution, escalate=escalate)

    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
    (PROPOSAL_DIR / doc).write_text(new_content, encoding="utf-8")
    events.emit(
        "self_update_proposed",
        {"doc": doc, "compliant": verdict["compliant"], "verdict": verdict["reason"]},
    )
    return {"doc": doc, "new": new_content, "verdict": verdict}


def apply_update(doc: str, reason: str = "(kein Grund angegeben)") -> dict:
    if doc not in MUTABLE:
        raise ValueError("Die Verfassung ist unantastbar.")
    proposal = PROPOSAL_DIR / doc
    if not proposal.exists():
        raise FileNotFoundError("Kein Vorschlag vorhanden — erst propose_update() aufrufen.")
    new_content = proposal.read_text(encoding="utf-8")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{doc}.{ts}.bak"
    (HISTORY_DIR / backup).write_text(_read(doc), encoding="utf-8")

    (MIND_DIR / doc).write_text(new_content, encoding="utf-8")
    events.emit("self_update_applied", {"doc": doc, "reason": reason, "backup": backup})
    return {"doc": doc, "backup": backup}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "GOAL.md"
    p = propose_update(target, " ".join(sys.argv[2:]) or None)
    print("Compliant:", p["verdict"]["compliant"], "|", p["verdict"]["reason"])
    print("\n--- Vorschlag ---\n", p["new"][:1000])
