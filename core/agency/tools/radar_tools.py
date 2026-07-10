"""Radar-Werkzeuge: Kiras Chancen-Pipeline im Griff (S5)."""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("radar_scan_now",
      "Startet sofort einen Business-Radar-Scan (Web-Signale -> konkrete Einkommens-Chancen "
      "mit Hypothese + Score). Laeuft sonst automatisch woechentlich.",
      {}, feature="radar")
def radar_scan_now() -> str:
    from core.agency import radar

    res = radar.scan(notify=False)
    if res.get("error"):
        return f"Scan fehlgeschlagen: {res['error']}"
    if not res.get("found"):
        return f"Scan fertig — nichts Neues ({res.get('note') or 'alles schon bekannt'})."
    return f"Scan fertig: {res['found']} neue Chance(n) in der Pipeline (opportunity_list zeigt sie)."


@tool("radar_fokus",
      "Legt fest, WONACH das Ideen-Radar sucht (persistent). Sergen sagt es dir, du "
      "traegst es hier ein — mehrere Themen mit ';' trennen. Ohne Argument zeigst du den "
      "aktuellen Fokus. Beispiel: radar_fokus('KI-Tools fuer Handwerker; Social-Media-"
      "Automatisierung fuer lokale Laeden').",
      {"themen": "die Suchthemen, ';'-getrennt — leer lassen zeigt den aktuellen Fokus"},
      feature="radar")
def radar_fokus(themen: str = "") -> str:
    from core.agency import radar

    if not (themen or "").strip():
        cur = radar.get_focus()
        if cur:
            return "Aktueller Radar-Fokus:\n" + "\n".join(f"- {t}" for t in cur)
        return "Noch kein eigener Fokus gesetzt — das Radar sucht nach breiten Standardthemen."
    parts = radar.set_focus(themen)
    return "Radar-Fokus gesetzt — ab jetzt suche ich nach:\n" + "\n".join(f"- {t}" for t in parts)


@tool("opportunity_list",
      "Zeigt die Business-Chancen-Pipeline (new/shortlist/rejected/converted) mit Scores.",
      {"status": "optional: nur diesen Status zeigen"}, feature="radar")
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
       "note": "optional: warum"},
      feature="radar")
def opportunity_decide(opp_id: str, status: str, note: str = "") -> str:
    from core.agency import radar

    ok = radar.decide(opp_id.strip(), status.strip().lower(), note=note)
    return "Status gesetzt." if ok else f"Konnte {opp_id!r} nicht auf {status!r} setzen (opportunity_list zeigt Ids)."


@tool("opportunity_convert",
      "Macht aus einer Chance ein echtes Venture (Status idea) + Validierungs-Ziel — "
      "ab da arbeitet der 24/7-Heartbeat daran.",
      {"opp_id": "die Id (Kurzform reicht)"}, feature="radar")
def opportunity_convert(opp_id: str) -> str:
    from core.agency import radar

    res = radar.convert(opp_id.strip())
    if not res.get("ok"):
        return f"Konnte nicht konvertieren: {res.get('error')}"
    return (f"Venture angelegt (id {res['venture_id'][:8]}) mit Validierungs-Ziel — "
            f"der Heartbeat nimmt es in die Planung auf.")
