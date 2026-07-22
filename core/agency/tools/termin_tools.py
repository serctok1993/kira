"""Termin-Werkzeuge (Phase 2) + Einmal-Wecker (c4-Nachzug) + Aendern/Loeschen (Termin-Runde).

Fehler lehren mit Beispiel-ACT-Zeile — die Texte sind Trainingsmaterial fuer
die LLM-Werkstatt. Abgrenzung (Kern des c4-Vorfalls vom 16.07.):
termin_add = passiver Kalender (Radar/Briefing) · erinnerung = EINMALIGE
aktive Nachricht zur Uhrzeit · cron_add = wiederkehrende Routine.
Nacht-Fund 22.07. (Testbatterien, events-belegt): Die alte Manifest-Diaet
("Loeschen macht der Nutzer im Cockpit") erzeugte bei JEDER Korrektur
Doppel-Termine bzw. geratene Namen (termin_edit/termin_delete) — deshalb
gibt es jetzt termin_update und termin_remove, Familien-konsistent zu cron_*.
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


@tool("termin_update",
      "Aendert einen BESTEHENDEN Termin (Zeit verschieben, Datum aendern, Titel "
      "korrigieren) — NIE einen zweiten Termin fuer dieselbe Sache anlegen. Die id "
      "steht in termin_list. Nur die Felder angeben, die sich aendern.",
      {"id": "die Termin-id aus termin_list, z.B. 7c31a9d2",
       "datum": "optional: neues Datum TT.MM.JJJJ (auch heute/morgen/uebermorgen)",
       "zeit": "optional: neue Uhrzeit HH:MM",
       "titel": "optional: neuer Titel",
       "jaehrlich": "optional: ja/nein"})
def termin_update(id: str = "", datum: str = "", zeit: str = "", titel: str = "",
                  jaehrlich: str = "", **falsche_args) -> str:
    from core.agency import termine

    if falsche_args or not str(id).strip():
        return ("Fehler: termin_update braucht die 'id' aus termin_list plus die zu "
                "aendernden Felder. Beispiel: "
                'ACT termin_update {"id": "7c31a9d2", "zeit": "16:00"}')
    res = termine.update(id, datum=datum, zeit=zeit or None, titel=titel,
                         jaehrlich=jaehrlich or None)
    if not res.get("ok"):
        return (f"Fehler: {res.get('error')}. Beispiel: "
                'ACT termin_update {"id": "7c31a9d2", "zeit": "16:00"}')
    z = f" um {res['zeit']}" if res.get("zeit") else ""
    j = " (jaehrlich)" if res.get("jaehrlich") else ""
    return (f"Geaendert ({', '.join(res['geaendert'])}): {res['titel']} am "
            f"{res['datum']}{z}{j} — id {res['id']}.")


@tool("termin_remove",
      "Loescht einen Termin aus {{USER_NAME_S}} Kalender. Die id steht in termin_list. "
      "Zum Verschieben/Korrigieren stattdessen termin_update nutzen.",
      {"id": "die Termin-id aus termin_list, z.B. 7c31a9d2"})
def termin_remove(id: str = "", **falsche_args) -> str:
    from core.agency import termine

    if falsche_args or not str(id).strip():
        return ("Fehler: termin_remove braucht die 'id' aus termin_list. Beispiel: "
                'ACT termin_remove {"id": "7c31a9d2"}')
    if not termine.remove(id):
        return (f"Fehler: Kein Termin mit id '{str(id).strip()}'. Erst nachschauen: "
                "ACT termin_list {}")
    return f"Termin geloescht (id {str(id).strip()})."


@tool("erinnerung",
      "Stellt einen EINMALIGEN Wecker: {{USER_NAME}} bekommt zur angegebenen Zeit die "
      "Nachricht aktiv per Telegram (und im Cockpit), danach ist der Wecker weg. Das "
      "heutige Datum steht in deiner JETZT-Zeile. Fuer wiederkehrende Routinen cron_add, "
      "fuer Kalender-Eintraege ohne Weckruf termin_add.",
      {"text": "die Weck-Nachricht, z.B. 'Aufstehen — Termin um 16 Uhr'",
       "datum": "TT.MM.JJJJ, z.B. 16.07.2026",
       "zeit": "HH:MM, z.B. 15:00"})
def erinnerung(text: str = "", datum: str = "", zeit: str = "", **falsche_args) -> str:
    from core.agency import erinnerungen

    if falsche_args:
        return ("Fehler: erinnerung kennt nur text, datum, zeit. Beispiel: "
                'ACT erinnerung {"text": "Aufstehen", "datum": "16.07.2026", "zeit": "15:00"}')
    e, fehler = erinnerungen.add(text, datum, zeit)
    if fehler:
        return "Fehler: " + fehler
    kanal = ("per Telegram" if erinnerungen.telegram_konfiguriert()
             else "im Cockpit (Telegram ist nicht eingerichtet)")
    return f"Wecker gestellt: {e['wann']} — „{e['text']}“. Zustellung {kanal}."
