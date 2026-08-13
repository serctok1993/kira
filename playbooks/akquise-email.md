---
titel: Akquise-Vorlage aus einem Website-Link
wann: {{USER_NAME}} schickt einen Website-Link und will eine individuelle Akquise-Mail-Vorlage — oder bittet um einen "Lead-Check" fuer eine Firma.
reifegrad: entwurf
erfolge: 0
fehlschlaege: 1
serie: 0
letzte: 2026-08-13 16:30
---

# Akquise-Vorlage aus einem Website-Link

> Die Hauptnutzung: Link rein -> individuelle Vorlage raus. Es wird NIE versendet —
> das Ergebnis ist immer eine DATEI, die {{USER_NAME}} liest und selbst verschickt.
> Umgeschrieben 13.08.2026 (alte Version zeigte auf das ausgebaute Venture-System).
> Angebots-/Firmenspezifika stehen bewusst im Vault, nicht hier.

## Schritte

1. Startseite laden: `web_fetch(url)`. Kommt ein Block-/Fehlerhinweis zurueck:
   sofort `browse(url)` — nicht erneut web_fetch versuchen.
2. Impressum/Kontakt finden: web_fetch haengt "Gefundene Kontakt-/Impressum-Links" an —
   diesen Link fetchen. Fehlt er: `<url>/impressum`, `<url>/kontakt`, `<url>/imprint`
   probieren (je EIN Versuch). Die E-Mail-Adresse steht meist im Anhang
   "Gefundene E-Mail-Adressen" — auch obfuskierte Formen zaehlen (name [at] domain).
3. Mankos sammeln (2-4 Stueck, KONKRET und belegbar — nur was du wirklich gesehen hast):
   - veraltetes Copyright-Jahr / tote Plattformen (Google+, Gaestebuch)
   - "optimiert fuer Internet Explorer" / nicht mobiltauglich / marquee & Co.
   - widerspruechliche Oeffnungszeiten, fehlende Preise, kein Online-Termin, kein Chat
   - Textwueste ohne Struktur, kein Call-to-Action
   Abgleich mit dem eigenen Angebot: Was davon loest ihr konkret? (Nutzenargumente und
   Branchen-Vorlagen liegen im Vault unter Business/Akquise/.)
4. Vorlage verfassen: maximal 120 Woerter, Sie-Form, erster Satz nimmt KONKRET Bezug
   auf den Betrieb (kein Baustein-Satz), 2-3 Mankos als Beobachtung (respektvoll,
   nie herablassend), EIN Nutzen, EIN Call-to-Action (10-15-Minuten-Telefonat),
   Signatur aus den Vault-Vorlagen uebernehmen (Business/Akquise/Vorlagen/).
5. Als Datei ablegen (write_file), Sandy-Konvention:
   `<Vault>/Business/Akquise/Entwuerfe/JJJJ-MM-TT_<Firma>_<Branche>.md`
   Kopf: `An:` / `Betreff:` / `Quelle: <url>` / `Status: Entwurf` — dann der Mailtext,
   darunter "## Beobachtete Mankos" als Stichpunkte mit Fundstelle.
6. {{USER_NAME}} kurz melden: Pfad der Datei + die 2-3 Mankos in einem Satz. KEIN request_approval
   noetig — es wurde nichts versendet, die Datei IST das Ergebnis.
7. `playbook_result` melden: Datei sauber angelegt = Erfolg. Stolperstein entdeckt
   (Block-Seite, fehlendes Impressum, Obfuskation) = als `playbook_lesson` festhalten.

## Akzeptanzkriterien (Selbst-Check vor Schritt 5)

- [ ] E-Mail-Adresse stammt AUS DER WEBSITE (Impressum/Kontakt), nicht geraten
- [ ] Jedes genannte Manko ist auf der Seite wirklich belegbar (Fakten-Treue!)
- [ ] Max. 120 Woerter Mailtext, Sie-Form, konkreter erster Satz
- [ ] Datei liegt unter Business/Akquise/Entwuerfe/ mit korrektem Namensschema
- [ ] Nichts versendet, nichts in fremde Postfaecher

## Lektionen

- (04.08., uebernommen) Fakten-Treue schlaegt Eloquenz: eine erfundene "Beobachtung"
  ruiniert die ganze Mail — lieber ein Manko weniger nennen.
