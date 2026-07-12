"""Trigger-Werkzeuge: Kira verdrahtet sich eigene Wenn-Dann-Reflexe (S4).

Beispiele: 'wenn task_failed_final ->
plane einen anderen Ansatz', 'wenn mcp_server_died -> diagnostiziere'.
"""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("trigger_add",
      "Legt einen proaktiven Trigger an: WENN ein Event dieses Typs auftritt, DANN wird die "
      "Aufgabe in die Missions-Queue gelegt (laeuft durch die normale Ergebnis-Pruefung). "
      "Event-Typen siehe db_query auf events (z.B. task_failed_final, mcp_server_died).",
      {"label": "kurzer Name des Reflexes",
       "event_type": "exakter Event-Typ, der ausloest",
       "task": "die Aufgabe, die dann in die Queue soll",
       "contains": "optional: nur ausloesen, wenn dieser Text im Event-Inhalt vorkommt",
       "cooldown_minutes": "Mindestabstand zwischen Ausloesungen (Standard 60)"})
def trigger_add(label: str, event_type: str, task: str, contains: str = "",
                cooldown_minutes: str = "60") -> str:
    from core.agency.missions import triggers

    try:
        cd = max(1, int(float(cooldown_minutes))) * 60
    except ValueError:
        cd = 3600
    tid = triggers.add(label, event_type, task, contains=contains, cooldown_s=cd)
    return (f"Trigger angelegt (id {tid[:8]}): WENN '{event_type}'"
            + (f" mit '{contains}'" if contains else "")
            + f" DANN '{task[:80]}' (Cooldown {cd // 60} min)")


@tool("trigger_list", "Zeigt alle proaktiven Trigger (Wenn-Dann-Reflexe).", {})
def trigger_list() -> str:
    from core.agency.missions import triggers

    trigs = triggers.list_all()
    if not trigs:
        return "Keine Trigger angelegt. Mit trigger_add verdrahtest du Wenn-Dann-Reflexe."
    lines = []
    for t in trigs:
        status = "an" if t.get("enabled", True) else "AUS"
        lines.append(f"- [{status}] {t['label']} (id {t['id'][:8]}): "
                     f"WENN {t['event_type']}"
                     + (f" ~'{t['contains']}'" if t.get("contains") else "")
                     + f" DANN {t['task'][:80]} (Cooldown {int(t.get('cooldown_s', 3600)) // 60} min)")
    return "\n".join(lines)


@tool("trigger_remove", "Entfernt einen Trigger (id oder 8-Zeichen-Kurzform).",
      {"trigger_id": "die Trigger-Id"})
def trigger_remove(trigger_id: str) -> str:
    from core.agency.missions import triggers

    return "Trigger entfernt." if triggers.remove(trigger_id.strip()) \
        else f"Kein Trigger mit id {trigger_id} gefunden (trigger_list zeigt alle)."
