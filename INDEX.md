# INDEX — der Vault (die Karte)

> Einstiegspunkt für jedes Modell im Harness und für den Nutzer in Obsidian.
> **So schaut der Agent effizient nach:** erst hier die Adresse finden (Malen nach Zahlen),
> dann NUR die eine Zieldatei öffnen — nie den ganzen Vault durchsuchen.

## 1 · Identität & Regeln — *frisch pro Turn injiziert*
- **1a** [[core/mind/constitution|Verfassung]] — unveränderlich, höchste Priorität
- **1b** [[core/mind/SOUL|Seele]] — wer ich bin *(entsteht beim Onboarding aus `core/mind/templates/`)*
- **1c** [[core/mind/GOAL|Ziel]] — wofür ich da bin
- **1d** [[core/mind/USER|Partner]] — mein Mensch (kompaktes Digest; Tiefe → 5)
- **1e** [[core/mind/BODY|Körper]] — meine Anatomie & Werkzeuge

## 2 · Prozeduren — Playbooks *(feste Abläufe, Tabelle unten)*
- **2a** [[playbooks/_VORLAGE|Vorlage]] · erst prüfen, ob ein Rezept passt, DANN handeln

## 3 · Laufende Arbeit
- **3a** `data/workspace/` — Objectives + Arbeits-Briefings (wechseln ständig)

## 4 · Wissen & Referenz
- **4b** [[docs/HANDBUCH|HANDBUCH]] — Gesetzbuch für den Nutzer
- **4c** [[docs/CODING|Coding-Disziplin]] — wie ich mich selbst SICHER verbessere (Modell-Switch beim Coden)

## 5 · Gedächtnis — der Stammbaum *(Tiefenlager über den Nutzer & die Projekte)*
- **5.0** Wurzel & Regeln → die Wurzel-Datei trägt den Namen des Nutzers (legt der /setup-Wizard aus [[gedaechtnis/stammbaum/_WURZEL_VORLAGE|_WURZEL_VORLAGE]] an) · [[gedaechtnis/LIES-MICH|Ordner-Regeln]]
- **5.1** Leben — Blätter wachsen pro Instanz (Daten, Vorlieben, Gesundheit …)
  - **5.1a** `leben/daten` — Geburtstag, E-Mail, Adresse …
  - **5.1b** `leben/vorlieben`
  - **5.1c** `leben/gesundheit`
  - **5.1d** `leben/menschen/` — pro Person ein Blatt aus [[gedaechtnis/stammbaum/leben/menschen/_VORLAGE|_VORLAGE]]
- **5.2** Business/Projekte — pro Projekt ein Blatt aus [[gedaechtnis/stammbaum/business/_VORLAGE|_VORLAGE]]
  - **5.2a** `business/<projekt>.md`
- **5.3** [[gedaechtnis/journal/LIES-MICH|Journal]] — Tag → Woche → Monat, was geschah

> **Fehlt ein Pflichtfeld (`???`)?** Nicht raten — einmal beiläufig den Nutzer fragen und nachtragen.

**Spielregeln:** Ein Playbook = ein Ablauf. Passt eines zur Aufgabe, wird es GENAU befolgt
und das Ergebnis mit `playbook_result` zurückgemeldet — daraus lernt es. Reifegrade:
`entwurf` (nur Vorschläge in die Freigabe-Inbox) → `begleitet` (handeln + melden) →
`autonom` (handeln, Ergebnis melden). Beförderung nur über die Freigabe des Nutzers; ein
Fehlschlag stuft automatisch zurück. Neues Playbook: `playbooks/_VORLAGE.md` kopieren.

<!-- AUTO:START -->
Stand: 13.08.2026 10:53 (automatisch generiert — nicht von Hand editieren)

## Playbooks (13)

| Playbook | Reifegrad | Wann | Erfolge | Fehlschlaege | Lektionen | Letzte |
|---|---|---|---|---|---|---|
| [[playbooks/akquise-email\|akquise-email]] | entwurf | Eine Kaltakquise-Mail an einen Lead schreiben (Beispiel-Projekt/KI-Cha | 0 | 0 | 1 | — |
| [[playbooks/brief-antwort\|brief-antwort]] | entwurf | der Nutzer schickt ein Foto von einem Brief/Dokument (Telegram oder Ch | 0 | 0 | 0 | — |
| [[playbooks/dienst-andocken\|dienst-andocken]] | entwurf | der Nutzer will einen Dienst nutzen, den Kira noch nicht kann (z.B. bu | 0 | 0 | 0 | — |
| [[playbooks/dossier-recherche\|dossier-recherche]] | entwurf | Ein Thema selbststaendig recherchieren und als Dossier in des Nutzers  | 0 | 0 | 0 | — |
| [[playbooks/leads-recherche\|leads-recherche]] | entwurf | der Nutzer will Leads/Kontakte/Firmen einer Branche+Region gesammelt h | 0 | 0 | 0 | — |
| [[playbooks/linkedin-post\|linkedin-post]] | entwurf | der Nutzer will etwas auf LinkedIn posten — Kira entwirft, der Nutzer  | 0 | 0 | 0 | — |
| [[playbooks/logbuch-pflege\|logbuch-pflege]] | entwurf | der Nutzer beantwortet eine Logbuch-Frage oder nennt beilaeufig ein ne | 0 | 0 | 0 | — |
| [[playbooks/monats-verdichtung\|monats-verdichtung]] | entwurf | Am 1. des Monats (Cron) die Wochenseiten zu EINER Monatsseite verdicht | 0 | 0 | 0 | — |
| [[playbooks/projekt-onboarding\|projekt-onboarding]] | entwurf | der Nutzer sagt "neues Projekt", "lass uns X starten" oder will ein Vo | 0 | 0 | 0 | — |
| [[playbooks/tages-einstieg\|tages-einstieg]] | entwurf | der Nutzer beginnt den Tag ("Hallo", "Guten Morgen", "was liegt an?")  | 0 | 0 | 0 | — |
| [[playbooks/tages-journal\|tages-journal]] | entwurf | Abends (Cron ~21:30) eine kurze Journal-Seite ueber den Tag schreiben. | 0 | 0 | 0 | — |
| [[playbooks/wochen-review\|wochen-review]] | entwurf | Einmal pro Woche Bilanz ziehen — was lief, was hakt, was sind die naec | 0 | 0 | 0 | — |
| [[playbooks/wochen-verdichtung\|wochen-verdichtung]] | entwurf | Sonntagabend (Cron) die 7 Tagesseiten zu EINER Wochenseite verdichten. | 0 | 0 | 0 | — |
<!-- AUTO:END -->
