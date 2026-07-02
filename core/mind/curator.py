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


def curate_lessons(escalate: bool = False) -> dict:
    """Konsolidiert Kiras Lektionen: Duplikate zusammenfassen, Triviales raus (max 10).

    Lektionen fliessen in JEDEN System-Prompt (recall_lessons) — ohne Pflege wachsen
    sie unbegrenzt und verwaessern sich gegenseitig. Loescht NIE blind: ohne saubere
    bereinigte Liste vom LLM bleibt alles unangetastet."""
    memory.init_memory()
    lessons = memory.all_lessons()
    if len(lessons) < 6:
        return {"note": "zu wenige Lektionen zum Aufraeumen", "count": len(lessons)}

    listing = "\n".join(f"- {l['text'][:240]}" for l in lessons)
    prompt = (
        "Hier sind Kiras gelernte Lektionen (fliessen in jeden System-Prompt):\n\n"
        f"{listing}\n\n"
        "Raeume sie auf: fasse Duplikate/sehr Aehnliches zusammen, entferne Triviales, "
        "Veraltetes und Floskeln. Behalte nur konkret UMSETZBARE Lektionen. Gib NUR die "
        "bereinigte Liste aus — hoechstens 10 Zeilen, je Zeile genau:\n"
        "LEKTION: <konkrete, umsetzbare Lehre>\n"
        "Nichts anderes."
    )
    res = llm_router.complete([{"role": "user", "content": prompt}], task_type="reason", escalate=escalate)
    new_lessons = [ln.strip() for ln in res["text"].splitlines()
                   if ln.strip().upper().startswith("LEKTION")]
    if not new_lessons:
        return {"note": "keine bereinigte Liste erhalten", "count": len(lessons)}

    for l in lessons:
        try:
            memory.delete(l["id"])
        except Exception:  # noqa: BLE001
            pass
    for nl in new_lessons[:10]:
        text = nl.split(":", 1)[1].strip() if ":" in nl else nl
        if text:
            memory.remember(text, role="self", kind="lesson")
    events.emit("lessons_curated", {"before": len(lessons), "after": min(len(new_lessons), 10)})
    return {"before": len(lessons), "after": min(len(new_lessons), 10)}


if __name__ == "__main__":
    print(curate_skills())
