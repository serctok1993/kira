"""Rollen-Toolsets (P5, Working-Modus): Rolle = Toolset = Modell.

DIE eine, ABFRAGBARE Quelle der Pyramiden-Etagen (Werkstatt-Vertrag): pro Rang
steht hier, welches Modell-Routing er faehrt, wie viele Schritte er bekommt und
welche Werkzeuge er sieht. Der Prompt eines Unteragenten nennt NUR die eigenen
Werkzeuge (kleines Manifest = kleiner Kontext = treffsichere kleine Modelle),
und die LLM-Werkstatt erzeugt ihre Trainingsdatensaetze pro Etage DIREKT aus
uebersicht() / GET /api/rollen — kein Nachbau, kein Drift.

Die vier ETAGEN (reflex/arbeiter/denker/richter) gelten fuer Unteragenten
(delegate/schwarm). Dazu kommt die Rolle "haupt" (unteragent=False): das
kuratierte Manifest fuer Kiras LOKALEN Haupt-Chat — kleine Modelle sehen die
Speisekarte des Alltags (~halber Prompt statt ~8k Token Voll-Manifest), die
Kueche bleibt voll (KEIN Ausfuehrungs-Gate; jedes registrierte Werkzeug ist
weiter aufrufbar, Coding laeuft eh ueber code:/plan mit voller Flotte).
Cloud-Chat (natives Function-Calling) faehrt unveraendert die volle Flotte.
"""
from __future__ import annotations

# Rang -> Etage. "tools" sind NAMENSLISTEN (Wache: test_rollen prueft jede gegen
# die Registry). task_type/escalate speisen resolve_model (Modellwechsel = config),
# "schritte" ist der Default-Deckel (config agency.delegate.schritte uebersteuert).
# unteragent=False (haupt) nimmt die Rolle aus delegate/schwarm heraus.
ROLLEN: dict[str, dict] = {
    "reflex": {
        "beschreibung": "1B-Etage: triviale Zuarbeit — lesen, suchen, nachschlagen. Kein Schreiben.",
        "task_type": "classify", "escalate": False, "schritte": 6,
        "tools": [
            "jetzt", "read_file", "list_dir",
            "code_suche", "datei_finden", "web_search", "web_fetch",
        ],
    },
    "arbeiter": {
        "beschreibung": "4B-Etage: delegierte Teilaufgaben in Masse — Recherche, Ablage im Workspace/Wissen.",
        "task_type": "worker", "escalate": False, "schritte": 12,
        "tools": [
            "jetzt", "read_file", "list_dir",
            "code_suche", "datei_finden", "web_search", "web_fetch",
            "browse", "screenshot_url", "db_query",
            "knowledge_search", "knowledge_list", "knowledge_note",
            "write_file", "make_dir", "playbook_list", "playbook_read",
        ],
    },
    "denker": {
        "beschreibung": "9B-Etage: Reasoning + Coding — navigieren, chirurgisch editieren, pruefen.",
        "task_type": "reason", "escalate": False, "schritte": 20,
        "tools": [
            "jetzt", "read_file", "list_dir",
            "code_suche", "datei_finden", "web_search", "web_fetch",
            "browse", "screenshot_url", "db_query",
            "knowledge_search", "knowledge_list", "knowledge_note",
            "write_file", "make_dir", "playbook_list", "playbook_read",
            "code_symbol", "code_umriss", "edit_datei", "self_edit",
            "run_command", "read_logs", "health",
        ],
    },
    "richter": {
        "beschreibung": "Frontier-Etage: seltene, finale Urteile — READONLY plus Tests, kein Schreibzugriff.",
        "task_type": "reason", "escalate": True, "schritte": 12,
        "tools": [
            "jetzt", "read_file", "list_dir",
            "code_suche", "datei_finden", "code_symbol", "code_umriss",
            "read_logs", "health", "run_command", "db_query",
            "knowledge_search", "metric_list", "objective_list",
        ],
    },
    "haupt": {
        "beschreibung": ("Kiras lokaler Haupt-Chat: die kuratierte Alltags-Speisekarte "
                         "(Assistenz, Wissen, Zeit, Delegation) — kleines Manifest fuer "
                         "kleine Modelle; Coding/Systemtiefe laeuft ueber code:/plan (volle Flotte)."),
        "task_type": "chat", "escalate": False, "unteragent": False,
        "tools": [
            "jetzt", "health", "web_search", "web_fetch", "browse", "screenshot_url",
            # Datei-Familie KOMPLETT (Live-Fund 22.07.): make_dir fehlte — Kira konnte im
            # Chat gar keinen Ordner anlegen und griff zu write_file ("Ordner Test" wurde
            # eine DATEI). Halbe Familien verwirren (todo_list-Lehre): anlegen, schreiben,
            # lesen, listen, finden, umbenennen, wegraeumen gehoeren zusammen.
            "read_file", "list_dir", "write_file", "make_dir", "datei_finden",
            "move_file", "delete_file",
            "remember_fact", "erinnerung", "termin_add", "termin_list",
            "termin_update", "termin_remove",   # Nacht-Fund 22.07.: ohne sie -> Doppel-Termine
            "cron_add", "cron_list", "cron_remove",   # Familie komplett (todo_list-Lehre)
            "watch_add", "watch_list",
            "todo_add", "todo_done", "todo_list",
            "todo_plan", "todo_update", "todo_stand",
            "knowledge_search", "knowledge_note",
            "delegate", "schwarm",
            "email_check", "email_send", "email_reply",
            "playbook_list", "playbook_read", "vault_note", "person_fakt",
            "request_approval", "switch_model", "read_logs",
        ],
    },
}

# spawn-and-retry-once (grok-Muster): scheitert ein Rang HART, darf delegate den
# Auftrag GENAU EINMAL eine Etage hoeher neu starten.
_ESKALATION = {"reflex": "arbeiter", "arbeiter": "denker", "denker": "richter", "richter": None}


def toolset(rang: str) -> frozenset[str] | None:
    """Erlaubte Werkzeug-Namen eines Rangs — None = kein Filter (volle Flotte, Kira)."""
    d = ROLLEN.get((rang or "").strip().lower())
    return frozenset(d["tools"]) if d else None


def eskalation(rang: str) -> str | None:
    return _ESKALATION.get((rang or "").strip().lower())


def verweigert(name: str, rang: str) -> str:
    """Lehrender Fehler, wenn ein Unteragent ausserhalb seines Toolsets greift."""
    eigene = ", ".join(sorted(toolset(rang) or []))
    return (f"Werkzeug '{name}' gehoert nicht zu deinem Rang '{rang}'. "
            f"Deine Werkzeuge: {eigene}. Loese den Auftrag damit — oder melde als "
            "Ergebnis, was dir konkret fehlt (der Orchestrator entscheidet dann).")


def manifest(rang: str) -> str:
    from core.agency.tools import registry

    return registry.manifest(nur=toolset(rang))


def schemas(rang: str) -> list[dict]:
    from core.agency.tools import registry

    return registry.tool_schemas(nur=toolset(rang))


def uebersicht() -> dict:
    """Alles, was die Werkstatt pro Etage braucht — Datensaetze DIREKT hieraus generieren."""
    out: dict[str, dict] = {}
    for rang, d in ROLLEN.items():
        out[rang] = {
            "beschreibung": d["beschreibung"],
            "task_type": d["task_type"],
            "escalate": d["escalate"],
            "schritte": d.get("schritte"),          # haupt: kein Delegations-Deckel -> null
            "unteragent": d.get("unteragent", True),
            "eskalation": _ESKALATION.get(rang),
            "tools": sorted(d["tools"]),
            "manifest": manifest(rang),
            "schemas": schemas(rang),
        }
    return out
