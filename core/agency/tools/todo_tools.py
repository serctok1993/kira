"""P1 (Working-Modus): der Plan als Werkzeug — todo_plan / todo_update / todo_stand.

Das Modell fuehrt seine eigene Schritt-Liste (Store: core/agency/auftrag.py);
der Harness legt sie bei jedem Zug ans Prompt-ENDE. Drei SCHLANKE Werkzeuge
statt eines komplexen: nummerierte Einzel-Updates sind fuer kleine Modelle
(4B) deutlich robuster als Array-Argumente. Fehlertexte LEHREN den naechsten
korrekten Aufruf (Trainings-Kategorie "Schritt-Disziplin").

Die Plan-Ansicht heisst todo_stand, NICHT todo_list: todo_list gehoert dem
Lebens-Board (persoenliche Todos, life_tools.py) — die P1-Erstfassung hatte
den Namen ueberschrieben (Registry: letzte Registrierung gewinnt).
"""
from __future__ import annotations

from core.agency import auftrag
from core.agency.tools.registry import tool


@tool("todo_plan",
      "Legt den Arbeitsplan fuer einen laengeren Auftrag an: ein Ziel + nummerierte "
      "Schritte (eine Zeile pro Schritt). Der Plan erscheint ab dann automatisch in "
      "deinem Prompt — erledige immer NUR den naechsten offenen Schritt.",
      {"ziel": "Was am Ende fertig sein soll (ein Satz)",
       "schritte": "Ein Schritt pro Zeile, in Reihenfolge (2-20 Zeilen)",
       "ersetzen": "optional 'ja': bestehenden Auftrag bewusst ueberschreiben"})
def todo_plan(ziel: str, schritte: str, ersetzen: str = "nein") -> str:
    zeilen = [z.strip() for z in (schritte or "").split("\n") if z.strip()]
    if not (ziel or "").strip():
        return ("Fehlgeschlagen: ziel fehlt. Beispiel: todo_plan(\"Report fertigstellen\", "
                "\"Daten sammeln\\nEntwurf schreiben\\nKorrektur lesen\").")
    if len(zeilen) < 2:
        return ("Fehlgeschlagen: mindestens 2 Schritte, EINE Zeile pro Schritt. "
                "Beispiel: schritte=\"Daten sammeln\\nEntwurf schreiben\".")
    alt = auftrag.get()
    offen = [s for s in alt.get("schritte", []) if s["status"] in ("offen", "laeuft")]
    if offen and (ersetzen or "").strip().lower() != "ja":
        return ("Fehlgeschlagen: es laeuft schon ein Auftrag mit offenen Schritten "
                f"(Nr. {', '.join(str(s['nr']) for s in offen)}). Entweder abarbeiten "
                "(todo_update(nr, \"fertig\"/\"verworfen\")) oder bewusst neu starten: "
                "todo_plan(..., ersetzen=\"ja\").")
    d = auftrag.set_plan(ziel, zeilen)
    return f"Plan steht ({len(d['schritte'])} Schritte).\n{auftrag.klartext()}"


@tool("todo_update",
      "Hakt einen Schritt deines Auftrags ab oder meldet eine Huerde. status: "
      "'laeuft' (beginne ich jetzt), 'fertig', 'verworfen' oder 'huerde' (mit notiz, "
      "was blockiert).",
      {"nr": "Schrittnummer aus dem Plan (Zahl)",
       "status": "laeuft | fertig | verworfen | huerde",
       "notiz": "optional; bei 'huerde' Pflicht: was blockiert konkret?"})
def todo_update(nr, status: str = "", notiz: str = "") -> str:
    try:
        nr = int(str(nr).strip().replace("Schritt", "").strip())
    except (TypeError, ValueError):
        return ("Fehlgeschlagen: nr muss die Schrittnummer als Zahl sein. "
                "Beispiel: todo_update(2, \"fertig\").")
    d, fehler = auftrag.update(nr, (status or "").strip().lower(), notiz or "")
    if fehler:
        return "Fehlgeschlagen: " + fehler
    return auftrag.klartext()


@tool("todo_stand",
      "Zeigt deinen aktuellen Arbeitsplan (Ziel, Schritte mit Status, naechster "
      "Schritt). Fuer persoenliche Todos vom Lebens-Board stattdessen todo_list nutzen.",
      {})
def todo_stand() -> str:
    return auftrag.klartext()
