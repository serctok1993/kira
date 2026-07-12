---
titel: Leads recherchieren und beiseitelegen
wann: der Nutzer will Leads/Kontakte/Firmen einer Branche+Region gesammelt haben ("leg mir N Leads fuer X aus Y beiseite").
reifegrad: entwurf
erfolge: 0
fehlschlaege: 0
serie: 0
letzte:
---

# Leads recherchieren und beiseitelegen

> Aus einem Satz ("20 Leads fuer Friseure aus Berlin") wird eine PRUEFBARE Datei —
> kein Gerede, kein "habe ich erledigt" ohne Artefakt.

## Schritte

1. Auftrag zerlegen: BRANCHE, REGION, ANZAHL (fehlt die Anzahl: 10). Zieldatei festlegen:
   `~/Desktop/leads/<branche>-<region>-<datum>.md` (make_dir fuer den Ordner).
2. Quellen abklappern mit web_search (mehrere Suchanfragen: "<branche> <region>",
   "<branche> <region> impressum", Branchenverzeichnisse). Pro Lead per web_fetch
   verifizieren, dass es die Firma gibt.
3. Pro Lead EINE Zeile in die Zieldatei schreiben (write_file/append_file):
   `| Name | Ort | Web | Kontakt (Mail/Tel falls oeffentlich) | Notiz |` — Markdown-Tabelle.
4. Selbst-Check: Datei existiert, Zeilenzahl == gewuenschte Anzahl, keine Duplikate,
   keine erfundenen Eintraege (jeder Lead hat eine echte Quelle).
5. Ergebnis melden: Pfad + Anzahl + 2-3 Beispiel-Leads. Bei `entwurf`: als Vorschlag
   via request_approval, NICHT eigenmaechtig kontaktieren.
6. `playbook_result("leads-recherche", erfolg)` melden — bei Fehlschlag mit Lektion.

## Akzeptanzkriterien

- Die Zieldatei EXISTIERT und enthaelt exakt N Leads als Tabelle (Beweispflicht!).
- Jeder Lead ist real (Website/Quelle erreichbar), keine Duplikate, keine Fantasie-Firmen.
- Keine Kontaktaufnahme ohne Freigabe — sammeln ja, anschreiben nur ueber die Inbox.

## Lektionen
