# HANDBUCH — Kira bedienen (für den Nutzer)

> Das Gesetzbuch des Königs. Hier steht alles, was DU über das System wissen musst:
> was Kira kann, wie du sie steuerst, welche Prompts funktionieren, was du in Obsidian
> gefahrlos ändern darfst. Technik-Tiefe steht im [[docs/KIRA-IST|Dossier]] — das hier
> ist dein Bedienbuch. Frei editierbar, nie im Prompt.

---

## §1 Die Rollen

- **Du = König.** Gibst Richtung, segnest ab, änderst Struktur. Ohne dich läuft nichts Großes.
- **Kira = General.** Plant, orchestriert die Armee, meldet ehrlich, lernt aus Ergebnissen.
- **Unteragenten = Armee.** Frische Arbeiter ohne Gedächtnis, nach Rang besetzt, liefern und verschwinden.
- **Der Cloud-Loop = Waffenschmied.** Härtet den Harness alle 4 h auf Branch `kira/loop` (Sammel-PR).

## §2 Was Kira kann (Kurzinventar)

- **Ränge / 5 Stufen** (Modell je Aufgabe, Config `models.routing`): Lokal (Qwen 9B, 0 €, Alltag/Reflexe) ·
  Chat (Flash) · Arbeiter (Flash, Schwarm/Masse) · Denker (GLM 5.2, Coding/harte Tasks) ·
  Richter (Fable — Langzeitplaner, Urteile, Council; feuert nur bei Eskalation).
- **Delegation:** `delegate` (1 Unteragent nach Rang) · `schwarm` (Liste abarbeiten, {item}-Platzhalter).
  Unteragenten können NICHT weiterdelegieren (Tiefen-Sperre). Kosten je Unteragent im Harness-Report.
- **DEIN Steuerpult** (Cockpit → Config → 🎛 Steuerpult): Rang-Tafel (welches Modell auf welchem
  Rang, gesetzt vs. real), Schwarm-Regler (Schritte je Rang, Breite, Kosten-Deckel — live) und die
  Kommandobrücke (Auftrag + Rang wählen → Befehl landet im Chat, DU drückst Senden). Im Chat direkt:
  `/delegiere` und `/schwarm` (§5) — deterministisch, funktioniert mit jedem Modell.
- **Coding (Code-Modus 2.0):** lesen → chirurgisch editieren → Tests automatisch (rot = Datei kommt
  zurück) → **Diff-Review** (frischer Denker prüft den Diff gegen den Auftrag, bessert einmal nach).
  **Read-before-Edit:** ungelesene Dateien kann KEIN Modell editieren (Guard). Läuft auf dem
  Denker-Rang (GLM) mit mittlerer Arbeitsfläche; 🧠 Reasoning/`reason:` schaltet auf Fable.
- **Arbeitsdisziplin:** klare Aufträge werden automatisch geplant (Auto-Plan) und nach Rängen
  verteilt; behauptete Dateien werden geprüft (Beweispflicht, Zwangs-Retry).
- **Gedächtnis:** siehe §4. **Playbooks:** feste Abläufe mit Reifegraden (§7).

## §3 Deine Sicherungen (unantastbar)

- **Not-Aus:** Cockpit unten links ODER Datei `data/STOP` anlegen → alles hält sofort.
- **Budget:** 20 €/Tag, 150 €/Monat (Config `governance.budget`) — danach automatisch lokal/0 €.
- **Gates:** Geld + Mails an Fremde landen IMMER in deiner Freigabe-Inbox („Von Kira braucht dich").
- **Verfassung:** `core/mind/constitution.md` kann NIEMAND ändern außer dir via Git.
- **Jeder Selbst-Edit** = Git-Commit → mit `git revert` rückgängig machbar.

## §4 Das Gedächtnis-System (5 Ebenen)

```
Ebene 0  Rohlog (state.db)          alles, unendlich, nie im Prompt
Ebene 1  Tages-Journal (21:30)      gedaechtnis/journal/JJJJ-MM-TT.md
Ebene 2  Wochenseite (So)           gedaechtnis/journal/wochen/
Ebene 3  Monatsseite (1.)           gedaechtnis/journal/monate/
Ebene 4  Destillat                  gedaechtnis/stammbaum/ + Lektionen/Playbooks
```

- **Stammbaum** = wer/was (du, Menschen, Projekte). Obsidian-Graph zeigt den Baum.
- **`???`-Felder** = Lücken, die Kira füllen will — das Briefing stellt dir EINE Frage pro Tag.
- **Rückruf** läuft über Suche („Rosen vor zwei Jahren" = Treffer im Journal-Archiv +
  Destillat im Stammbaum), nicht über Vollgedächtnis im Prompt.
- Nichts davon bläht die Prompts auf — Kira liest hier nur gezielt nach.

## §5 Deine Befehle (funktionieren IMMER, egal wie dumm das Modell ist)

| Befehl | Wirkung |
|---|---|
| `/model` | zeigt: gesetztes Modell, REAL laufendes Modell, Key-Status |
| `/model fable` · `glm` · `pro` · `deepseek` · `local` | Modell schalten (`glm` = Denker-Rang, `local` = Notbremse qwen3.5:9b) |
| `/model 9b` · `/model 35b` | lokal klein (schnell) bzw. lokaler Denker qwen3.6:35b (braucht RAM) |
| `/model <rolle> <id>` | Rolle gezielt besetzen (chat/reason/worker/escalation…) |
| `reason:` vor der Nachricht | diese eine Anfrage aufs starke Modell |
| `/delegiere <rang> <auftrag>` | DEIN Draht zur Armee: EIN Unteragent im gewaehlten Rang (reflex/arbeiter/denker/richter) |
| `/schwarm <rang> <vorlage mit {item}> \| a \| b` | mehrere Unteragenten parallel ueber eine Liste |
| `/work <auftrag>` | volles Arbeitsbudget (langer Task) |
| `/code <auftrag>` (Chat & Telegram) | Coding-Modus — **erbt den Chat davor** (erst brainstormen, dann `/code`) |
| `plan:` / Coding-Modus | erst Plan, dann Schritte (Coding erzwingt zusätzlich Regeln) |
| `@ziel:<name>` | Arbeit auf ein Ziel buchen — **wirkt nur zusammen mit `/work`** (`/work @ziel:beispiel-projekt …`) |
| `denk:aus` · `niedrig` · `mittel` · `hoch` | Reasoning-Tiefe des Modells regeln (mehr Denken = besser + teurer) |
| Fokus (Zentrale) | Daueranweisung für den Motor |
| JETZT-Eimer (`loop/BACKLOG.md`) | Befehl an den Cloud-Loop — die Datei liegt **im `kira/loop`-Checkout**, nicht in diesem Repo |

## §6 Prompt-Guide — was funktioniert, was nicht

**Funktioniert gut ✅**
- **Imperativ ODER höflich, aber mit Substanz:** „Erstelle mir…" und „Kannst du mir … raussuchen"
  werden beide als Auftrag erkannt — wenn Stückzahl/Datei/Projekt drinsteht.
- **Zahlen + Zielort nennen:** „20 Leads", „als Datei nach ~/Desktop/leads/". Was messbar ist,
  kann die Beweispflicht prüfen.
- **Etappen bei Masse:** „…in Etappen von 5." (Ein Arbeiter-Schritt hat ~12 Werkzeug-Runden.)
- **Eine Sache pro Auftrag.** Zwei Aufträge = zwei Nachrichten.
- **Für Urteile das starke Modell:** `reason:` davor — Kleinkram läuft billig von selbst.

**Funktioniert schlecht ❌**
- Vage Sammelaufträge („mach mal was mit den Leads und guck auch noch X und Y").
- Riesen-Einzelschritte („schreib 50 Mails auf einmal") — Budgets reißen, Qualität sinkt.
- Kurskorrektur MITTEN im Lauf — lieber Lauf fertig, dann neuer Auftrag.
- Fähigkeitsfragen, wenn du einen Auftrag meinst: „Kannst du eigentlich X?" = Frage;
  „Kannst du mir X als Datei erstellen" = Auftrag.
- Erwartung ohne Quelle: Sie darf nichts erfinden — gib ihr die Fakten oder sag, wo sie liegen.

## §7 Obsidian-Regeln — was du ändern darfst

| Ampel | Bereich | Regel |
|---|---|---|
| 🟢 FREI | `gedaechtnis/**`, `docs/**`, `loop/BACKLOG.md` (JETZT) | Ändere alles, jederzeit — nie im Prompt |
| 🟢 FREI | Playbook-**Text** (Schritte, Kriterien, Vorlagen) | Wird respektiert und bleibt erhalten |
| 🟡 VORSICHT | Playbook-**Frontmatter** (zwischen den `---`) | NUR die 7 Standard-Zeilen nutzen — eigene Zusatz-Zeilen dort werden beim nächsten Zurückschreiben GELÖSCHT. Zähler (erfolge/serie) nicht von Hand ändern |
| 🟡 VORSICHT | `core/mind/SOUL/GOAL/USER.md` | Landen in JEDEM Prompt — kurz halten! Jede Zeile kostet bei jedem Gespräch Geld |
| 🔴 NIE | `core/mind/constitution.md` | Nur via Git (bewusst so) |
| 🔴 NIE | `INDEX.md` zwischen `<!-- AUTO:START -->` und `AUTO:END` | Wird täglich überschrieben — darüber/darunter ist frei |

## §8 Einmalige Desktop-Einrichtung (wörtlich an Kira im Chat schicken)

1. `Lege einen Cron an: label "Tages-Journal", schedule "21:30", scope "me", prompt: Fuehre das Playbook tages-journal aus: schreibe die heutige Journal-Seite nach gedaechtnis/journal/. Nutze playbook_read fuer die Schritte.`
2. `Lege einen Cron an: label "Wochen-Verdichtung", schedule "20:30", scope "me", prompt: NUR wenn heute Sonntag ist: fuehre das Playbook wochen-verdichtung aus (playbook_read fuer die Schritte), sonst antworte nur "kein Sonntag" und tue nichts.`
   *(Achtung: KEIN Wochentag im schedule-Feld — "So 20:30" versteht der Planer nicht und macht daraus einen STUNDEN-Takt. Der Sonntags-Filter lebt im Prompt.)*
3. `Lege einen Cron an: label "Monats-Verdichtung", schedule "21:00", scope "me", prompt: NUR am 1. des Monats: fuehre das Playbook monats-verdichtung aus, sonst nichts tun.`

4. `Lege einen Cron an: label "Morgen-Briefing", schedule "08:00", scope "me", prompt: {{standup}} Fasse mir den Tag zusammen: Termine, offene Tasks, Fehler, 3 wichtigste Punkte.`
   *(Ohne diesen Briefing-Cron gibt es KEINE Logbuch-Frage — sie reist im `{{standup}}`-Platzhalter mit. Alternativ: Cockpit → Me → Chip „☀ Morgen-Briefing".)*

Danach: ab morgen enthält dein Briefing automatisch eine **LOGBUCH-FRAGE** (eine pro Tag),
bis der Stammbaum gefüllt ist.

## §9 Der Fable-Rüstungscheck (wenn das Fundament ein paar Tage lief)

Erst `/model fable`, dann wörtlich:

```
reason: /work RÜSTUNGSCHECK. Du prüfst dich selbst wie ein Elitesoldat seine Rüstung —
Organ für Organ, gegen docs/HANDBUCH.md als Prüfliste. Für jeden Paragraphen: prüfe mit
Werkzeugen (nicht raten), ob das Beschriebene WIRKLICH funktioniert:
§2 Ränge/delegate (delegiere testweise einen Reflex-Auftrag), §3 Gates/Budget-Stand,
§4 Gedächtnis (existieren Journal-Seiten? wie viele ???-Lücken offen? Stichprobe:
finde ein Destillat im Stammbaum), §5 Befehle (/model-Status), Playbook-Reifegrade,
Motor-Outcomes seit Aktivierung (Anzahl, Pass-Quote, Kosten je Modell aus dem
Harness-Report). Dann: die 5 wichtigsten Verbesserungen, priorisiert nach
Wirkung/Aufwand, mit konkretem erstem Schritt. EHRLICH — Lücken sind der Zweck
dieses Checks, nicht Peinlichkeiten. Delegiere Zuarbeit an Arbeiter, urteile selbst.
```

## §10 Wenn etwas klemmt

- Modell reagiert komisch → `/model` (läuft real, was du denkst?) → `/model local` als Notbremse.
- Sie behauptet Dinge → Beweispflicht-Stempel in der Antwort ernst nehmen (⚠ = nicht geliefert).
- Nichts geht mehr → Not-Aus, dann `kira-update.bat` (holt Stand + sauberer Neustart).
- Loop pausieren → Routine in der Claude-App deaktivieren. Cloud-Fragen → Claude-Session.
