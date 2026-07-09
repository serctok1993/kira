"""Werkszustand / Blanko-Handover (Phase 5): Kira nach vier Tagen Bauphase in einen
sauberen Uebergabe-Zustand bringen — der Dev-/Test-Wildwuchs raus, die echte Substanz
(Verfassung, Persona, USER.md, Zugaenge, Config) bleibt UNANGETASTET.

Vorsatz: NICHTS still loeschen. preview() zeigt exakt, WAS und WIE VIEL fiele; reset()
sichert jede Kategorie vorher (Backups liegen zeilenweise unter data/backups/) und
raeumt nur die ausgewaehlten. Fakten sind bewusst NICHT im Standard — echte Fakten ueber
Sergen sollen einen Neustart ueberleben, ausser er waehlt sie explizit.
"""
from __future__ import annotations

from core.kernel import events


def _cat_defs() -> list[dict]:
    """Kategorie-Register: key, label, Beschreibung, count(), clear()->Anzahl. Lazy-Importe,
    damit ein fehlendes Teilsystem den Rest nicht bricht."""
    from core.mind.memory import store as memory

    def _clear_kind(kinds):
        return lambda: memory.delete_by_kind(kinds, backup=True).get("deleted", 0)

    def _clear_chats():
        return memory.reset_episodic(backup=True).get("deleted", 0)

    def _clear_events():
        return events.clear_all()

    def _clear_wissen():
        from core.mind import knowledge
        return knowledge.clear_all()

    def _cnt_kind(kind):
        return lambda: memory.count_by_kind(kind)

    def _cnt_wissen():
        from core.mind import knowledge
        return knowledge.count_docs()

    return [
        {"key": "chats", "label": "Chat-Verlaeufe", "standard": True,
         "desc": "alle Gespraeche (episodisches Gedaechtnis)",
         "count": _cnt_kind("episodic"), "clear": _clear_chats},
        {"key": "skills", "label": "Skills", "standard": True,
         "desc": "waehrend der Bauphase gelernte Faehigkeiten",
         "count": _cnt_kind("skill"), "clear": _clear_kind(["skill"])},
        {"key": "lektionen", "label": "Lektionen", "standard": True,
         "desc": "gelernte Lektionen (Reflexion)",
         "count": _cnt_kind("lesson"), "clear": _clear_kind(["lesson"])},
        {"key": "events", "label": "Live-Ops-Protokoll", "standard": True,
         "desc": "Ereignis-/Aktionslog der Bauphase",
         "count": events.count_all, "clear": _clear_events},
        {"key": "wissen", "label": "Wissens-Archiv", "standard": False,
         "desc": "hochgeladene Dokumente (nur leeren, wenn Test-Dateien)",
         "count": _cnt_wissen, "clear": _clear_wissen},
        {"key": "fakten", "label": "Gemerkte Fakten", "standard": False,
         "desc": "Dauer-Fakten — VORSICHT: auch echte ueber Sergen!",
         "count": _cnt_kind("fact"), "clear": _clear_kind(["fact"])},
    ]


def preview() -> dict:
    """Was fiele einem Reset zum Opfer? {categories: [{key,label,desc,standard,count}], total}."""
    cats = []
    for c in _cat_defs():
        try:
            n = int(c["count"]())
        except Exception:  # noqa: BLE001
            n = 0
        cats.append({"key": c["key"], "label": c["label"], "desc": c["desc"],
                     "standard": c["standard"], "count": n})
    return {"categories": cats, "total": sum(c["count"] for c in cats)}


def reset(scope: list[str], confirm: str = "") -> dict:
    """Setzt die AUSGEWAEHLTEN Kategorien auf Werkszustand — jede vorher gesichert.

    Schutz: confirm muss exakt 'WERKSZUSTAND' sein (bewusste, nicht versehentliche Aktion).
    Gibt {ok, cleared:{key:anzahl}, error?} zurueck; eine kaputte Kategorie stoppt die
    anderen nicht."""
    if confirm != "WERKSZUSTAND":
        return {"ok": False, "error": "Bestaetigung fehlt (confirm='WERKSZUSTAND')."}
    wanted = set(scope or [])
    if not wanted:
        return {"ok": False, "error": "Keine Kategorie gewaehlt."}
    cleared: dict[str, int] = {}
    for c in _cat_defs():
        if c["key"] not in wanted:
            continue
        try:
            cleared[c["key"]] = int(c["clear"]())
        except Exception as e:  # noqa: BLE001 — eine Kategorie darf den Rest nicht abreissen
            cleared[c["key"]] = -1
            events.emit("factory_reset_error", {"category": c["key"], "error": str(e)[:200]})
    events.emit("factory_reset", {"scope": sorted(wanted),
                                  "cleared": {k: v for k, v in cleared.items() if k != "events"}})
    return {"ok": True, "cleared": cleared}
