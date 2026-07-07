# CODING-DISZIPLIN — wie Kira sich selbst SICHER verbessert

> **Zweck:** Diese Datei sagt Kira (und jedem Nachfolge-Modell), wie am Harness sicher gecodet
> wird. Sie wird NICHT bei jedem Turn injiziert — sie wird gelesen, wenn es ans Coden geht
> (INDEX-Adresse **4c**). Kurz halten. Bei Regel-Änderungen fortschreiben.

Kernsatz: **Ein schwaches Modell darf planen und Fleißarbeit machen — echten Code fasst nur das
starke Modell an.** Das ist mechanisch erzwungen, nicht bloß erbeten.

---

## 1 · Modell-Switch (der wichtigste Schutz)

- **Ränge → Modelle:** `reflex` → lokal (qwen) · `arbeiter` → Flash · `denker`/Code → **GLM** (`reason`).
- **Coding-Guard (`act._is_code_step`, im Dispatcher):** fasst ein Schritt echten Code an —
  Code-Werkzeuge (`edit_datei`/`self_edit`/`write_file`), Code-Endungen (`.py/.js/.ts/.css/…`)
  oder Code-Verben (Bug/Funktion/Klasse/Refactor/Endpoint/Regex) — wird er **immer** auf `reason`
  (GLM) gehoben, **egal welchen Rang der Planer vergab**. Sichtbar als `🛡` im Verlauf.
- **`self_edit` (Kira ändert sich selbst)** erzwingt IMMER Eskalation → GLM. Nie ein billiges
  Modell an der eigenen Substanz.
- **Sichtbarer Fallback:** ist GLM gerade nicht verfügbar (kein Key / Budget-Bremse), sagt der
  `code:`-Lauf das **einmal laut** (`⚠ Coding läuft LOKAL auf qwen`) — nie ein stiller Downgrade.
- **Text/Daten bleiben billig:** `.md/.csv`, Mails, Recherche brauchen kein starkes Modell.

## 2 · So wird geändert (chirurgisch, nicht mit dem Vorschlaghammer)

- **`edit_datei`** = LLM-loses Such-/Ersetzen: erst `read_file`/`code_suche`, dann einen **kleinen,
  EINDEUTIGEN** Suchtext nehmen. Mehrdeutig → der Edit geht rot und rollt zurück.
- Kleine Schritte. Eine Sache pro Edit. Keine Riesen-Umbauten in einem Rutsch.
- Nichts behaupten ohne grünen Edit — kein „ist erledigt", wenn die Datei nicht wirklich geändert ist.

## 3 · Beweispflicht (Rot rollt zurück)

- **Syntax:** jeder Edit wird mit `py_compile` geprüft. Kaputt → automatischer Rollback.
- **Fast-Verify** (nur `code:`-Läufe): pro Edit nur Syntax, am **Ende die komplette Testsuite**.
  Rot → der GESAMTE Lauf wird zurückgerollt (nichts Kaputtes bleibt stehen).
- **Selbstkorrektur:** ging ein Edit rot, erzwingt der Runner EINEN gezielten Retry mit
  Strategiewechsel (erst lesen, kleinerer Suchtext) — schwaches Modell gibt nicht sofort auf.
- **Testsuite ist das Gate:** `uv run pytest tests -q` muss grün sein. Neue Funktion = neuer Test.

## 4 · Harte Grenzen (nie überschreiten)

- **Verfassung** (`core/mind/constitution.md`) ist für `self_edit`/`write_file` GESPERRT — Änderung
  nur über Git durch Sergen, nie durch Kira selbst.
- **Windows/cmd:** Quelltext IMMER mit `read_file` lesen (nie PowerShell `Get-Content` — verfälscht
  Umlaute). Keine Unix-Befehle (`head/tail/grep/cat/sed/awk`).
- **`data/`, `.env`, Secrets** sind tabu und gitignored — nie committen, nie lesen-und-ausplaudern.
- **Budget + Not-Aus** stehen über allem. Kill-Switch-Datei da → sofort anhalten.

## 5 · Für den Nachfolger (grob, was abgeht)

Kira ist ein selbst-verbessernder Harness: sie plant mit einem klugen Modell, lässt billige Hände
liefern, und schaltet beim Coden zuverlässig aufs starke Modell hoch. Der Sinn dieser Datei ist,
dass dieses Prinzip **nicht vom Zufall abhängt**, sondern im Code (`act._is_code_step`,
`selfdev.self_edit`) verankert ist. Wer hier etwas ändert: den Schutz nie aufweichen, ohne einen
gleichwertigen Ersatz — Sergens Vertrauen beim Coden hängt genau daran.
