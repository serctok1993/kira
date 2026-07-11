---
titel: Neuen Dienst selbst andocken
wann: Sergen will einen Dienst nutzen, den Kira noch nicht kann (z.B. bundle.social, Notion, ein neues Social-Netzwerk) — oder Kira fehlt fuer eine Aufgabe eine Faehigkeit und sie schlaegt das Andocken selbst vor.
reifegrad: entwurf
erfolge: 0
fehlschlaege: 0
serie: 0
letzte:
---

# Neuen Dienst selbst andocken

> Sergens Zielbild (11.07.): Kira waechst durch SELBST-Erweiterung, nicht durch
> Vorverdrahtung. Kein Dienst wird "auf Vorrat" gebaut — wenn einer gebraucht wird,
> holt Kira ihn sich: recherchieren, vorschlagen, Freigabe, Key anfragen, anbinden,
> testen. Alle Gates gelten unveraendert.

## Schritte

1. Bedarf benennen: WAS soll der Dienst koennen (z.B. "auf LinkedIn+X posten via
   bundle.social")? Ein Satz. Bei eigener Initiative: Sergen erst fragen, ob er das will.
2. Weg finden (Reihenfolge = Aufwand):
   a) Gibt es einen MCP-Server dafuer? (Registry/Web durchsuchen: web_search
      "<dienst> MCP server"). MCP ist der Koenigsweg — anbinden statt bauen.
   b) Gibt es eine einfache HTTP-API? (Doku mit web_fetch lesen: Auth, Endpoints,
      Limits, Preis.)
   c) Nur wenn a+b ausfallen: eigenes Werkzeug bauen (synthesize/self_edit) —
      auf der Denker-Stufe (reason:), mit Tests.
3. Vorschlag an Sergen via request_approval: was gefunden wurde, welcher Weg, was es
   kostet (Abo/API-Preise ehrlich nennen), welcher Key gebraucht wird. NICHTS anbinden
   ohne Freigabe.
4. Nach Freigabe: Zugangsdaten via request_secret anfragen (Sergen traegt den Key im
   Cockpit ein — Kira sieht Keys nie im Klartext im Chat).
5. Anbinden: MCP-Server in die Bridge-Config eintragen bzw. Werkzeug bauen. Danach
   SMOKE-TEST mit einer harmlosen Lese-Operation (nie als Erstes posten/senden).
6. Ergebnis melden (Klartext): was jetzt geht, wie man es benutzt, was es kostet.
   Erkenntnisse als vault_note (ordner dienste) ablegen; playbook_result eintragen.

## Grenzen (bindend)

- Aussenwirkung des neuen Dienstes (posten, senden, zahlen) laeuft durch dieselben
  Gates wie alles andere — ein frisch angedockter Dienst ist KEIN Freifahrtschein.
- Keine Anmeldedaten/Passwoerter im Chat-Klartext; immer request_secret.
- Scheitert der Smoke-Test: ehrlich melden, Anbindung zurueckbauen, Lektion notieren.
