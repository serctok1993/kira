---
titel: Projekt-Onboarding (neues Projekt anlegen)
wann: Sergen sagt "neues Projekt", "lass uns X starten" oder will ein Vorhaben in die App bringen.
reifegrad: entwurf
erfolge: 0
fehlschlaege: 0
serie: 0
letzte:
---

# Projekt-Onboarding

> Du fuehrst Sergen durch das Anlegen — er beantwortet Fragen, DU fuellst die App.
> Ein Projekt ist erst fertig angelegt, wenn ALLE 6 Stationen stehen. Frag nach, was fehlt —
> aber gebuendelt (max. 2 Fragen pro Nachricht), kein Verhoer.

## Schritte

1. FRAGEN (Runde 1): Wie heisst das Projekt? Was ist die Hypothese in einem Satz
   (wer zahlt wofuer / was soll entstehen)? Gibt es ein Geld- oder Zahlen-Ziel (EUR, Follower, Kunden)?
2. ANLEGEN: venture_add mit Name, Hypothese, Meilenstein. (Der Stammbaum-Ast
   gedaechtnis/stammbaum/business/<name>.md entsteht automatisch mit ???-Feldern.)
3. FRAGEN (Runde 2): Zielkunden/Zielgruppe? Ton/Stil? Absolute No-Gos? Daraus das
   Briefing bauen und mit project_note als Daueranweisung ablegen. Kurz zeigen, was du abgelegt hast.
4. ZIEL: objective_add — messbar formuliert, Art big oder monthly, Domain business
   (sonst grindet der Motor es NICHT). Sergen im Cockpit ans Venture koppeln lassen
   (Projekte -> Ziel -> Venture) oder selbst per API, wenn moeglich.
5. ROUTINE: EINEN sinnvollen Cron vorschlagen (cron_add mit project=<Name>!) — z.B. taegliche
   Recherche oder Redaktion. Erst vorschlagen, dann anlegen, wenn Sergen ja sagt.
6. LUECKEN: Den neuen Stammbaum-Ast oeffnen (read_file) und die 2 wichtigsten ???-Felder
   direkt erfragen; Antworten mit edit_datei eintragen. Rest holt die taegliche Logbuch-Frage.
7. ABSCHLUSS: Kurze Zusammenfassung — was angelegt wurde (Venture, Briefing, Ziel, Cron,
   Stammbaum) + der EINE naechste Schritt. playbook_result melden.

## Akzeptanzkriterien

- Venture existiert mit Hypothese + Meilenstein; Stammbaum-Ast vorhanden.
- Briefing als project_note abgelegt (Zielgruppe, Ton, No-Gos).
- Messbares Ziel mit Domain business angelegt und ans Venture gekoppelt.
- Hoechstens 2 Fragen pro Nachricht; nichts erfunden — fehlende Antworten bleiben ??? oder offen.

## Lektionen
