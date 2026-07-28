# Werkstatt-Meldung — Harness-Stand nach der Nacht vom 28.07.2026

Bitte an die LLM-Werkstatt weiterleiten. **Keine Werkzeug-Vertragsänderung**:
`tests/golden_werkzeug_vertrag.json` ist unberührt, Namen und Argumente aller
Werkzeuge sind unverändert. Was sich ändert, betrifft den *Umgang* mit dem Protokoll
und zwei Fehler im Generator selbst.

## 1. Der Parser ist an zwei Stellen toleranter geworden

Beides darf in c7-Beispielen vorkommen, ohne als Fehler zu gelten:

* **Argumentlose Aufrufe** werden jetzt geparst: `ACT jetzt`, `ACT health`,
  `ACT health()`. Zwölf Werkzeuge stehen im Manifest als „Argumente: keine" —
  ausgerechnet der einfachste Fall fiel vorher durch, weil der Parser eine `{`
  verlangte.

  **Wichtige Einschränkung:** diese Form gilt nur, wenn drumherum nichts
  Nennenswertes steht (< 40 Zeichen). Grund: eine nackte Zeile `ACT restart_self`
  ist von Prosa nicht zu unterscheiden — ungefiltert wurde aus einer *Rückfrage*
  („Wenn du willst, mache ich einen Neustart … soll ich?") ein echter Neustart.
  Für Trainingsbeispiele heißt das: argumentlose Aufrufe **allein** in den Zug
  stellen, nicht in Prosa einbetten. Die Argument-Form (`ACT tool {…}`) bleibt
  überall tolerant.

* **Echte Zeilenumbrüche in JSON-Strings** werden akzeptiert (`strict=False`).
  Kleine Modelle escapen sie fast nie korrekt, und es traf ausgerechnet die
  Werkzeuge, die Arbeit erzeugen: `write_file`, `vault_note`, `knowledge_note`.

## 2. Drei modellgerichtete Wortlaute sind jetzt festgezurrt

Alle drei kommen aus Konstanten in `core/agency/act.py` und werden von
`tests/test_trainingsvertrag.py` exakt gezählt (vorher nur `>= 2`, deshalb lief die
Produktion unbemerkt auseinander).

**Stups, ACT-Pfad** (Chat *und* Missionen — wortgleich):

> Der Auftrag liegt bereits vor — tu es JETZT mit einem Werkzeug (ACT ...) und
> antworte erst mit dem Ergebnis. Nicht ankuendigen, nicht zurueckfragen.

**Stups, nativer Pfad** (Cloud-Function-Calling; einziger zulässiger Unterschied,
dort gibt es kein ACT):

> Der Auftrag liegt bereits vor — tu es JETZT in diesem Zug: nutze die passenden
> Werkzeuge und antworte erst mit dem Ergebnis. Nicht ankuendigen, nicht zurueckfragen.

**Beweispflicht** (`beweis_nachfrage(wort, nativ=False)`):

> Halt — du schreibst "{wort}", aber in diesem Zug lief KEIN Werkzeug. Damit hat sich
> nichts geaendert. Entweder du tust es JETZT wirklich (ACT <werkzeug> {...}), oder du
> sagst ehrlich, dass es noch offen ist und was du dafuer brauchst. Nichts behaupten,
> was nicht passiert ist.

Auf dem nativen Pfad entfällt `(ACT <werkzeug> {...})`, sonst identisch.

**Neu:** beide feuern ab jetzt auch auf dem **Missionspfad** (`act()` — Crons,
Missionen, Planschritte). Vorher gab es sie dort gar nicht.

## 3. Ausgangswache: zwei neue Wortlaute

Aufforderung an das Modell, wenn eine Antwort unbrauchbar war:

> Deine letzte Antwort war unbrauchbar ({leer|roher Werkzeugaufruf}). Schreib JETZT
> die fertige Antwort fuer {Nutzer} — in normalen Saetzen, ohne Werkzeug-Zeile. Wenn
> du etwas herausgefunden hast, sag es; wenn nicht, sag ehrlich, was fehlt.

Und der Satz, den Kira sagt, wenn auch das nicht half (`act.KAPITULATION`):

> Ich habe es versucht, aber keine brauchbare Antwort zustande gebracht. Frag mich
> nochmal — am besten etwas konkreter, dann komme ich weiter.

**Für die Werkstatt wichtig:** dieser Satz wird von `tuning.record_chat()`
ausdrücklich **nicht** mitgeschrieben. Er entsteht genau dann, wenn das Modell zweimal
nichts lieferte — als Trainingspaar würde er beibringen, bei schweren Fragen
aufzugeben. Falls ältere `episodes.jsonl` ihn enthalten: vor dem nächsten Export
herausfiltern.

## 4. Zwei Fehler im Generator selbst — Exporte prüfen

Beide sind behoben, aber **bereits exportierte Datensätze tragen sie noch**:

* `_tool_examples()` baute den Beispielaufruf aus dem **ersten** Parameter statt aus
  allen Pflichtargumenten. 13 der 81 Beispiele waren unvollständig, darunter
  `email_send`, `learn_skill`, `self_edit`, `metric_log`, `trigger_add`, `watch_add`.
  Seit der Argument-Wache beantwortet der Harness genau diese Aufrufe deterministisch
  mit einem Fehler.
* `_SEED_CODING` benutzte falsche Argumentnamen: `code_suche {"query"}` statt
  `{"muster"}`, `edit_datei {"path","suchen","ersetzen"}` statt `{"pfad","suche","ersetze"}`.

Zusammen 15 Beispiele, die dem Modell Aufrufe beibrachten, die die Produktion ablehnt.
Dieselbe Fehlerklasse wie der 187-Fälle-Fund des `vertrag_pruefer.py`, nur in Kiras
eigenem Generator. **Bitte `vertrag_pruefer.py` über die bestehenden Exporte laufen
lassen und betroffene Datensätze neu generieren.**

## 5. Beispielwerte und Identität

* Beispielwerte kommen jetzt aus der Parameter-Beschreibung selbst, wenn dort eine
  steht: `ACT termin_add {"datum": "15.08.2026"}` statt `{"datum": "beispiel"}`,
  `ACT set_context {"num_ctx": "16384"}` statt eines ganzen Satzes (ein
  Zahlenparameter bekam Prosa, weil „text" als Teilstring in „Kontext" steckt).
* `_example_arg` schrieb den **echten Nutzernamen** in 8 von 77 Beispiele und umging
  damit `system_stub(agent, user)` — den Haken, über den die Identitäts-Variation des
  kommerziellen Datensatzes läuft. Jetzt 0. **Bestehende Exporte auf den echten Namen
  prüfen.**
