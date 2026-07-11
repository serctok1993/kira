---
titel: LinkedIn-Post entwerfen
wann: Sergen will etwas auf LinkedIn posten — Kira entwirft, Sergen kopiert (keine LinkedIn-API; features.linkedin bleibt aus, bis Sergen mehr will).
reifegrad: entwurf
erfolge: 0
fehlschlaege: 0
serie: 0
letzte:
---

# LinkedIn-Post entwerfen

> Bewusst OHNE API (OAuth-App waere unverhaeltnismaessig): Kira liefert den fertigen
> Text als Freigabe-Eintrag, Sergen kopiert ihn mit einem Klick in LinkedIn.

## Schritte

1. Thema + Ziel klaeren: worum geht es, was soll der Post bewirken (Reichweite,
   Kunden, Recruiting)? Zielgruppe = deutschsprachige KMU/Business-Kontakte.
2. Entwurf schreiben: Hook in Zeile 1 (ohne Clickbait), 3-6 kurze Absaetze,
   konkrete Zahlen/Beispiele statt Buzzwords, 1 Frage oder CTA am Ende,
   3-5 passende Hashtags. Laenge 500-1200 Zeichen.
3. ACT request_approval mit kind publish: Titel "LinkedIn-Post: <Thema>", der
   Volltext im Detail. (LinkedIn wird NICHT automatisch bepostet — die Freigabe
   ist Sergens Copy-Paste-Vorlage.)
4. Nach seiner Entscheidung playbook_result melden; Feedback als Lektion notieren
   (was er umformuliert hat = Lernmaterial fuer den naechsten Post).

## Akzeptanzkriterien

- Erster Satz funktioniert ohne den Rest (Feed-Abriss-Test).
- Keine erfundenen Zahlen/Referenzen; Sergens Ton (direkt, bodenstaendig, kein Guru-Sprech).
- Entwurf liegt in der Freigabe-Inbox, nichts wurde irgendwo gepostet.
