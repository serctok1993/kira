"""Widget-Werkzeuge (Werkbank PR 8): Kira blendet Cockpit-Kacheln ein — per CONFIG.

Sergens Wunsch aus dem Redesign: "modular — Kira kann Add-ons einblenden,
z.B. Follower-Statistik". Diese Werkzeuge schreiben NUR validierte JSON-Configs
nach data/widgets/ — gerendert wird mit drei festen, sicheren Bausteinen
(metric/chart/list). Kira liefert nie Code, nur Config.
"""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("widget_add",
      "Blendet eine Zusatz-Kachel im Cockpit ein (Zentrale, Projekt-Tab oder Serc-Tab). "
      "Typen: metric (aktueller Wert + Sparkline einer Kennzahl), chart (Balkenverlauf), "
      "list (Liste aus digest/tagewerk/status/evolution). "
      "Beispiel: widget_add('follower', 'Follower', 'metric', 'zentrale', metric='follower').",
      {"id": "kurzer Kachel-Name, nur a-z 0-9 und Bindestrich",
       "titel": "Ueberschrift der Kachel (max 60 Zeichen)",
       "typ": "metric | chart | list",
       "slot": "zentrale | projekt | serc",
       "metric": "bei metric/chart: Name der Kennzahl (wie bei metric_log)",
       "endpoint": "bei list: /api/digest | /api/tagewerk | /api/status | /api/evolution",
       "key": "bei list: Feldname im Endpunkt, z.B. tasks_done"})
def widget_add(id: str, titel: str, typ: str, slot: str,
               metric: str = "", endpoint: str = "", key: str = "") -> str:
    from core.agency import widgets
    from core.kernel import events

    cfg = {"id": (id or "").strip().lower(), "title": titel, "type": (typ or "").strip().lower(),
           "slot": (slot or "").strip().lower()}
    if metric:
        cfg["metric"] = metric
    if endpoint:
        cfg["endpoint"] = endpoint
    if key:
        cfg["key"] = key
    res = widgets.save(cfg)
    if not res.get("ok"):
        return f"Widget abgelehnt: {res.get('error')}"
    events.emit("widget_saved", {"id": res["id"], "slot": cfg["slot"], "via": "tool"})
    return (f"Widget '{res['id']}' eingeblendet ({cfg['type']}, Slot {cfg['slot']}). "
            "Sergen sieht es beim naechsten Laden des Cockpits.")


@tool("widget_weg",
      "Entfernt eine Cockpit-Kachel wieder. Beispiel: widget_weg('follower').",
      {"id": "Kachel-Name aus widget_add"})
def widget_weg(id: str) -> str:
    from core.agency import widgets
    from core.kernel import events

    ok = widgets.delete((id or "").strip().lower())
    if ok:
        events.emit("widget_deleted", {"id": (id or "").strip().lower(), "via": "tool"})
        return f"Widget '{id}' entfernt."
    aktive = ", ".join(w["id"] for w in widgets.list_all()) or "keine"
    return f"Kein Widget '{id}' gefunden. Aktive Widgets: {aktive}."
