"""Radar-Werkzeuge: Kiras Chancen-Pipeline im Griff (S5)."""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("radar_scan_now",
      "Startet sofort einen Business-Radar-Scan (Web-Signale -> konkrete Einkommens-Chancen "
      "mit Hypothese + Score). Laeuft sonst automatisch woechentlich.",
      {})
def radar_scan_now() -> str:
    from core.agency import radar

    res = radar.scan(notify=False)
    if res.get("error"):
        return f"Scan fehlgeschlagen: {res['error']}"
    if not res.get("found"):
        return f"Scan fertig — nichts Neues ({res.get('note') or 'alles schon bekannt'})."
    return f"Scan fertig: {res['found']} neue Chance(n) in der Pipeline (opportunity_list zeigt sie)."


@tool("opportunity_list",
      "Zeigt die Business-Chancen-Pipeline (new/shortlist/rejected/converted) mit Scores.",
      {"status": "optional: nur diesen Status zeigen"})
def opportunity_list(status: str = "") -> str:
    from core.agency import radar

    opps = radar.list_all(status.strip().lower())
    if not opps:
        return "Pipeline ist leer — radar_scan_now fuellt sie."
    lines = []
    for o in opps[:20]:
        lines.append(f"- ({o['id'][:8]}) [{o['score']}] {o['status'].upper()}: {o['title'][:80]}"
                     + (f"\n  {o['hypothesis'][:120]}" if o.get("hypothesis") else ""))
    return "\n".join(lines)


@tool("opportunity_decide",
      "Setzt den Status einer Chance: shortlist (weiter beobachten) | rejected (verwerfen).",
      {"opp_id": "die Id (8-Zeichen-Kurzform reicht)", "status": "shortlist | rejected",
       "note": "optional: warum"})
def opportunity_decide(opp_id: str, status: str, note: str = "") -> str:
    from core.agency import radar

    ok = radar.decide(opp_id.strip(), status.strip().lower(), note=note)
    return "Status gesetzt." if ok else f"Konnte {opp_id!r} nicht auf {status!r} setzen (opportunity_list zeigt Ids)."


@tool("opportunity_convert",
      "Macht aus einer Chance ein echtes Venture (Status idea) + Validierungs-Ziel — "
      "ab da arbeitet der 24/7-Heartbeat daran.",
      {"opp_id": "die Id (Kurzform reicht)"})
def opportunity_convert(opp_id: str) -> str:
    from core.agency import radar

    res = radar.convert(opp_id.strip())
    if not res.get("ok"):
        return f"Konnte nicht konvertieren: {res.get('error')}"
    return (f"Venture angelegt (id {res['venture_id'][:8]}) mit Validierungs-Ziel — "
            f"der Heartbeat nimmt es in die Planung auf.")
