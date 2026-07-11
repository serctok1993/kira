---
titel: Brief-Foto beantworten
wann: Sergen schickt ein Foto von einem Brief/Dokument (Telegram oder Chat) und will eine Antwort — z.B. "sag denen ab", "beantworte mir das formell".
reifegrad: entwurf
erfolge: 0
fehlschlaege: 0
serie: 0
letzte:
---

# Brief-Foto beantworten

> Phase 3 (Alltagshilfe): Foto rein, fertiger formeller Entwurf raus. Der Versand
> laeuft IMMER ueber email_send/email_reply — an Fremde greift das Freigabe-Gate,
> nichts geht ohne Sergens OK raus.

## Schritte

1. Das Foto ist beim Eintreffen schon per Vision beschrieben worden. Extrahiere daraus:
   Absender (Behoerde/Firma), Betreff/Aktenzeichen, Kernaussage, Frist, gefordertes Handeln.
   Ist etwas Entscheidendes unleserlich: EINE gezielte Rueckfrage an Sergen, nicht raten.
2. Sergens Anweisung verstehen ("sag denen ab", "frag nach Aufschub", "bestaetigen") —
   sie bestimmt Ton und Inhalt. Ohne Anweisung: kurz fragen, was er will.
3. Formellen Antwort-Entwurf schreiben: deutsches Geschaeftsdeutsch, hoeflich und knapp;
   Bezug (Aktenzeichen/Datum des Schreibens) in der ersten Zeile; Absender Sergen Tok.
   Keine Behauptungen erfinden (Termine, Gruende) — was Sergen nicht gesagt hat, bleibt draussen.
4. Entwurf sichern: ACT vault_note {"titel": "<Absender> <Datum>", "text": "<Entwurf>", "ordner": "briefe"}
   — so hat Sergen jeden Briefwechsel dauerhaft in Obsidian.
5. Entwurf Sergen im Chat zeigen (Volltext). Erst nach seinem OK:
   email_send bzw. email_reply an die im Brief genannte Adresse — an Fremde stoppt
   automatisch die Freigabe-Inbox (email_stranger), das ist gewollt.
6. Gibt es eine Frist: ACT termin_add mit Fristdatum ("Antwort an <Absender> faellig").

## Akzeptanzkriterien

- Kernaussage + Frist des Briefes korrekt wiedergegeben (gegen die Vision-Beschreibung pruefbar).
- Entwurf formell, fehlerfrei, mit Bezugzeile; nichts dazugedichtet.
- Kopie liegt als vault_note im Ordner briefe.
- Versand NUR ueber die Gates; nie direkt behaupten "ist raus" ohne Beleg.
