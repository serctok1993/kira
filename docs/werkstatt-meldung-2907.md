# Werkstatt-Meldung — Harness-Stand 29.07.2026 (c10-relevant)

Bitte an die LLM-Werkstatt weiterleiten. Betrifft zwei Runden: die Harness-Hälfte der
Katalog-Analyse (PR #214) und ein neues Werkzeug (PR folgt).

**Training nötig?** Ja — ein Werkzeug kommt dazu. Nach der Faustregel in
`tests/test_werkzeug_vertrag_golden.py` ist das der klare Fall.

---

## 1. NEU: das Werkzeug `resonanz`

```
resonanz(thema, tage=30, limit=10)
  thema  — Pflicht. Wonach gesucht wird, z.B. "Kaltakquise Handwerk"
  tage   — optional, Zeitfenster in Tagen (Standard 30, eingefangen auf 1–365)
  limit  — optional, Anzahl Treffer (Standard 10, eingefangen auf 1–25)
```

Werkzeug-Zahl: **77 → 78.** Der Golden-Vertrag ist entsprechend aktualisiert.

**Wozu es da ist — und das ist der Drill-Punkt:** `web_search` beantwortet *„was gibt es
dazu"*, `resonanz` *„worüber wird geredet und was davon trägt"*. Ein kleines Modell
greift hier zuverlässig daneben; die Abgrenzung gehört geübt.

- „Was kommt gerade an zu X?" / „Worüber wird geredet?" / vor Content-Ideen,
  Produktentscheidungen, Erstansprachen → **resonanz**
- „Wann wurde X gegründet?" / „Was kostet Y?" / Fakten, Definitionen → **web_search**

Die Antwort ist eine sortierte Liste mit sichtbaren Rohzahlen (Punkte, Kommentare,
Alter, URL). Sortiert wird nach *Punkte + 2× Kommentare* — Diskussion wiegt schwerer als
ein Klick.

**Zwei Fälle, in denen das Werkzeug etwas sagt statt zu schweigen** — bitte so trainieren,
dass das Modell die Aussage übernimmt statt sie zu füllen:

- Firewall aktiv (Benchmark/Sandbox): *„Resonanz ist in diesem Lauf abgeschaltet …
  erfinde keine."*
- Null Treffer: *„… dazu wird gerade wenig geschrieben — sag das ruhig so, statt etwas
  zu erfinden."*

Das zielt auf dieselbe Schwäche wie Beweispflicht III (siehe unten): eine leere Antwort
füllt ein kleines Modell sonst aus dem eigenen Kopf.

---

## 2. GEÄNDERT: das Datumsfeld nimmt jetzt Wochentage

Betrifft **`termin_add`**, **`erinnerung`**, **`termin_update`**. Der Vertragstext für
`datum` lautet jetzt:

> TT.MM.JJJJ (z.B. 15.08.2026) ODER direkt heute/morgen/uebermorgen oder ein Wochentag
> (Donnerstag, am Montag, naechsten Freitag) — rechne NICHT selbst

Argumentnamen unverändert, nur die Beschreibung. Nach der Faustregel allein also kein
Trainingsgrund — **aber der Drill lohnt sich trotzdem**, denn genau hier lag der Fehler:

Katalog-Aufgabe 001, *„Trag mir Donnerstag 14 Uhr ein"* → das Modell antwortete, es gebe
„zwei Donnerstage im Juli (30. und 6. August)", und fragte zurück statt einzutragen. Der
Harness löst `heute/morgen` seit PR #190 auf — er hat es dem Modell nur nie gesagt.
Jetzt löst er auch Wochentage auf (Montag–Sonntag, Kurzformen Mo/Di/Do, „am Montag",
„nächsten Freitag", „Sonnabend").

**Regel:** die nächste Gelegenheit, heute eingeschlossen. „nächsten Donnerstag" schiebt
einen Treffer auf heute um eine Woche; sonst sind beide Formen gleich.

**Drill:** relative Angaben **durchreichen**, nicht selbst rechnen.

---

## 3. NEUE WORTLAUTE (drei Stück)

**Datumshilfe im Fehlertext** — ersetzt „Heute ist der …, morgen der …":

> Heute ist Mittwoch, der 29.07.2026 — siehe auch deine JETZT-Zeile. Du darfst auch
> direkt heute/morgen/uebermorgen oder einen Wochentag schicken — ich rechne das um.
> Die naechsten: Donnerstag=30.07.2026, Freitag=31.07.2026, …

Der Anker „siehe auch deine JETZT-Zeile" bleibt bewusst erhalten.

**Namensvorschlag bei unbekanntem Werkzeug** — hängt an „existiert nicht":

> Fehler: Werkzeug 'find_files' existiert nicht. Meintest du datei_finden? Verfuegbar: […]

Anlass: Katalog-Aufgabe 082. Der Lehrfehler griff, aber das Modell stellte nicht um —
die Liste aller 78 Werkzeuge ist zu lang, um daraus den einen zu finden.

**Beweispflicht III — erfundene Außen-Fakten:**

> Halt — du schreibst "{stelle}", aber in diesem Zug lief KEINE Recherche. Das kannst du
> nicht wissen, ohne nachzusehen. Entweder du siehst JETZT nach (nutze
> web_search/web_fetch), oder du sagst ehrlich, dass du es nicht weisst. Erfundene
> Zahlen sind schlimmer als keine Antwort.

Auf dem nativen Pfad steht „nutze die Suche" statt der Werkzeugnamen.

Ausgelöst wird **eng**: nur bei Behauptungen über die Außenwelt mit Zeitbezug (Wetter,
Preise/Kurse „gerade/aktuell/heute/morgen") in einem Zug ohne Werkzeug. Gemessen: 2 von
412 Live-Antworten. Der naheliegende Auslöser „Zahlen und Messwerte" hätte bei **44 %**
aller Antworten gefeuert.

---

## 4. ZUM ZWEITEN FABRIKATIONS-FALL: kein Harness-Fix, sondern ein c10-Drill

Fall [074] — *„In meiner SOUL.md steht …"* ohne die Datei zu lesen — ist **kein**
fehlendes Werkzeug. SOUL, GOAL und PERSONA stehen **vollständig im System-Prompt**
(nachgemessen: 20.383 Zeichen, Abschnitt `# DEINE SEELE` mit dem echten Text). Daraus
zu zitieren braucht keinen Dateizugriff.

Was schiefging, war ein **Fehlzitat**: im echten SOUL steht „nicht Assistentin, nicht
Boss", die Antwort machte daraus eine dienende Rolle — inhaltlich das Gegenteil. Das
ist ein Drill („zitiere deine eigene Seele korrekt oder gar nicht"), keine
Harness-Lücke — ein Wächter hätte hier ein sinnloses Dateilesen erzwungen.
