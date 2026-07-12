"""Playbook-Werkzeuge (S11): feste Prozeduren nachschlagen, befolgen, verbessern.

Der Router-Block im System-Prompt zeigt nur die Kopfzeilen — diese Werkzeuge
sind der Rest der Progressive Disclosure: erst bei Treffer wird gelesen.
Werkzeuge liefern Strings und raisen nie (Haus-Regel).
"""
from __future__ import annotations

from core import identity as _id
from core.agency.tools.registry import tool
from core.mind import playbooks


@tool(
    "playbook_list",
    "Alle Playbooks mit Reifegrad und Einsatz-Zweck auflisten (Uebersicht, keine Details).",
)
def playbook_list() -> str:
    try:
        pbs = playbooks.list_playbooks()
        if not pbs:
            return "Keine Playbooks vorhanden. Neue anlegen: playbooks/_VORLAGE.md kopieren."
        lines = [f"- {m['name']} [{m['reifegrad']}] ({m['erfolge']}✓/{m['fehlschlaege']}✗): "
                 f"{(m.get('wann') or '')[:110]}" for m in pbs]
        return "Playbooks (Details: playbook_read):\n" + "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"Fehler beim Auflisten: {e}"


@tool(
    "playbook_read",
    "Ein Playbook komplett lesen. Die Schritte danach GENAU befolgen; bei Reifegrad "
    "'entwurf' Ergebnisse NUR als Vorschlag in die Freigabe-Inbox legen.",
    {"name": "Name des Playbooks, z.B. akquise-email"},
)
def playbook_read(name: str) -> str:
    try:
        text = playbooks.read_full(str(name))
        if text is None:
            pbs = ", ".join(m["name"] for m in playbooks.list_playbooks()) or "(keine)"
            return f"Playbook '{name}' nicht gefunden. Vorhanden: {pbs}"
        return text
    except Exception as e:  # noqa: BLE001
        return f"Fehler beim Lesen: {e}"


@tool(
    "playbook_result",
    "Nach JEDER Playbook-Ausfuehrung das Ergebnis melden — daraus lernt das Playbook "
    "(Zaehler, Reifegrad, Befoerderungs-Vorschlag). Bei Fehlschlag Lektion mitgeben.",
    {"name": "Name des Playbooks",
     "erfolg": "ja oder nein",
     "lektion": "optional: was beim naechsten Mal anders laufen soll (ein Satz)"},
)
def playbook_result(name: str, erfolg: str, lektion: str = "") -> str:
    try:
        ok = str(erfolg).strip().lower() in ("ja", "true", "1", "yes", "erfolg")
        res = playbooks.record_result(str(name), ok, notiz=str(lektion or ""))
        if not res.get("ok"):
            return f"Fehler: {res.get('error')}"
        msg = (f"Verbucht: {res['name']} -> {'Erfolg' if ok else 'Fehlschlag'} "
               f"({res['erfolge']}✓/{res['fehlschlaege']}✗, Serie {res['serie']}, "
               f"Reifegrad {res['reifegrad']}).")
        if res.get("demoted"):
            msg += f" Zurueckgestuft auf '{res['demoted']}'."
        if res.get("proposal"):
            msg += f" Befoerderungs-Vorschlag liegt in {_id.user_name()}s Freigabe-Inbox."
        return msg
    except Exception as e:  # noqa: BLE001
        return f"Fehler beim Verbuchen: {e}"


@tool(
    "playbook_lesson",
    "Eine Lektion in ein Playbook schreiben (z.B. aus {{USER_NAME_S}} Korrektur), ohne ein "
    "Ergebnis zu verbuchen.",
    {"name": "Name des Playbooks", "text": "die Lektion, ein praegnanter Satz"},
)
def playbook_lesson(name: str, text: str) -> str:
    try:
        res = playbooks.add_lesson(str(name), str(text))
        return (f"Lektion in '{res['name']}' festgehalten." if res.get("ok")
                else f"Fehler: {res.get('error')}")
    except Exception as e:  # noqa: BLE001
        return f"Fehler bei der Lektion: {e}"
