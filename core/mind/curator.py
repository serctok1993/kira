"""Curator: pflegt Kiras Skill-Bibliothek — konsolidiert Aehnliches, mistet Veraltetes
aus (inspiriert vom Hermes-Curator, aber souveraen/lokal). Per Cron oder Tool ausloesbar.
"""
from __future__ import annotations

from core.kernel import events, llm_router
from core.mind.memory import store as memory


def curate_skills(escalate: bool = False) -> dict:
    memory.init_memory()
    skills = memory.all_skills()
    if len(skills) < 3:
        return {"note": "zu wenige Skills zum Aufraeumen", "count": len(skills)}

    listing = "\n".join(f"- {s['text'][:240]}" for s in skills)
    prompt = (
        "Hier ist Kiras Skill-Bibliothek (wiederverwendbare Faehigkeiten):\n\n"
        f"{listing}\n\n"
        "Raeume sie auf: fasse Duplikate/sehr Aehnliches zusammen, entferne Triviales oder "
        "Veraltetes. Gib NUR die bereinigte Liste aus — je Zeile genau ein Skill im Format:\n"
        "SKILL [Name]: knappe, konkrete Anleitung\n"
        "Nichts anderes."
    )
    res = llm_router.complete([{"role": "user", "content": prompt}], task_type="reason", escalate=escalate)
    new_skills = [ln.strip() for ln in res["text"].splitlines()
                  if ln.strip().upper().startswith("SKILL")]
    if not new_skills:
        return {"note": "keine bereinigte Liste erhalten", "count": len(skills)}

    for s in skills:
        try:
            memory.delete(s["id"])
        except Exception:  # noqa: BLE001
            pass
    for ns in new_skills[:30]:
        memory.remember(ns, role="self", kind="skill")
    events.emit("skills_curated", {"before": len(skills), "after": len(new_skills)})
    return {"before": len(skills), "after": len(new_skills)}


if __name__ == "__main__":
    print(curate_skills())
