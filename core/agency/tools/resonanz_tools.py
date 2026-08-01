"""Resonanz-Werkzeug: was zu einem Thema wirklich ankommt.

Ergaenzt web_search um die andere Frage. Die Suche liefert, WAS es gibt; Resonanz
liefert, WORUEBER geredet wird und was davon traegt — gemessen an Upvotes und
Kommentaren auf Reddit und Hacker News. Beide Quellen ohne Schluessel, ohne Login.
"""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("resonanz",
      "Zeigt, was zu einem Thema WIRKLICH ankommt — die meistdiskutierten Beitraege "
      "der letzten Wochen auf Hacker News (und Reddit, falls Zugangsdaten "
      "hinterlegt sind), sortiert nach Zustimmung und "
      "Diskussion (nicht nach Suchmaschinen-Rang). Nimm es, wenn es um Resonanz geht: "
      "'was kommt gerade an', 'worueber wird geredet', vor Content-Ideen, "
      "Produktentscheidungen oder Erstansprachen. Fuer reine Faktenfragen web_search.",
      {"thema": "wonach gesucht wird, z.B. 'Kaltakquise Handwerk'",
       "tage": "optional: Zeitfenster in Tagen (Standard 30)",
       "limit": "optional: wie viele Treffer (Standard 10, max 25)"})
def resonanz(thema: str = "", tage: int = 30, limit: int = 10, **falsche_args) -> str:
    from core.agency import resonanz as _r
    from core.agency.tools.builtin import _lehr_fehler

    if falsche_args or not str(thema).strip():
        return _lehr_fehler("resonanz", falsche_args, "'thema'",
                            'resonanz(thema="Kaltakquise Handwerk", tage=30)')
    try:
        tage = max(1, min(365, int(tage)))
        limit = max(1, min(25, int(limit)))
    except (TypeError, ValueError):
        return ("Fehler: tage und limit muessen Zahlen sein. "
                'Beispiel: resonanz(thema="Kaltakquise", tage=30, limit=10)')
    return _r.bericht(thema, tage=tage, limit=limit)
