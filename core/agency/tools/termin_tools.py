"""Termin-Werkzeuge (Phase 2): der kleinste nuetzliche Kalender.

Bewusst NUR 2 Werkzeuge (Manifest-Diaet fuer kleine Modelle): eintragen + ansehen.
Loeschen macht der Nutzer im Cockpit (Tag -> TERMINE). Fehler lehren mit
Beispiel-ACT-Zeile — die Texte sind Trainingsmaterial fuer die LLM-Werkstatt.
"""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("termin_add",
      "Traegt einen Termin in {{USER_NAME_S}} Kalender ein — er erscheint im TERMIN-RADAR der "
      "Briefings und im Cockpit (Me -> Tag). Faellt im Gespraech ein Datum (Zahnarzt, "
      "Geburtstag, Frist), trag es VON DIR AUS ein. Geburtstage/Jahrestage: jaehrlich=ja.",
      {"datum": "TT.MM.JJJJ, z.B. 15.08.2026",
       "titel": "was ansteht, z.B. Zahnarzt",
       "zeit": "optional HH:MM, z.B. 14:30",
       "jaehrlich": "optional: ja = wiederholt sich jedes Jahr (Geburtstag/Jahrestag)"})
def termin_add(datum: str = "", titel: str = "", zeit: str = "", jaehrlich: str = "",
               **falsche_args) -> str:
    from core.agency import termine

    if falsche_args or not str(datum).strip() or not str(titel).strip():
        return ("Fehler: termin_add braucht 'datum' (TT.MM.JJJJ) und 'titel'. Beispiel: "
                'ACT termin_add {"datum": "15.08.2026", "titel": "Zahnarzt"}')
    res = termine.add(datum, titel, zeit=zeit,
                      jaehrlich=str(jaehrlich).strip().lower() in ("ja", "1", "true", "yes"))
    if not res.get("ok"):
        return (f"Fehler: {res.get('error')}. Beispiel: "
                'ACT termin_add {"datum": "15.08.2026", "titel": "Zahnarzt"}')
    z = f" um {res['zeit']}" if res.get("zeit") else ""
    j = " (jaehrlich)" if res.get("jaehrlich") else ""
    return f"Eingetragen: {res['titel']} am {res['datum']}{z}{j} — id {res['id']}."


@tool("termin_list",
      "Zeigt {{USER_NAME_S}} kommende Kalender-Termine mit id. Geburtstage aus dem Stammbaum "
      "stehen zusaetzlich automatisch im TERMIN-RADAR des Briefings.",
      {"tage": "optional: Vorschau-Fenster in Tagen, Standard 14"})
def termin_list(tage: str = "", **falsche_args) -> str:
    from core.agency import termine

    try:
        fenster = int(str(tage).strip() or 14)
    except ValueError:
        fenster = 14
    items = termine.list_upcoming(fenster)
    if not items:
        return (f"Keine Termine in den naechsten {fenster} Tagen. Neu eintragen: "
                'ACT termin_add {"datum": "15.08.2026", "titel": "Zahnarzt"}')
    lines = [f"Termine der naechsten {fenster} Tage:"]
    for e in items[:20]:
        diff = e["tage_bis"]
        wann = "HEUTE" if diff == 0 else ("morgen" if diff == 1 else f"in {diff} Tagen")
        zeit = f" {e['zeit']}" if e.get("zeit") else ""
        j = " (jaehrlich)" if e.get("jaehrlich") else ""
        lines.append(f"- ({e['id']}) {e['datum']}{zeit}: {e['titel']} — {wann}{j}")
    return "\n".join(lines)
