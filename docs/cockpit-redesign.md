# Cockpit-Redesign — Konzept (Sergens Vision)

> Arbeitsauftrag fuer die Desktop-Session: Das Cockpit lebt als reine Python-Strings
> in `core/api/ui/` (`css.py`, `views.py`, `script.py`) + Endpunkte in `core/api/server.py`.
> Kein Build-Schritt. Umbau live am PC (uvicorn --reload), Abnahme im Browser.
> Dieses Dokument ist die verbindliche Richtung — Punkt fuer Punkt umsetzbar.

## Leitprinzipien (gelten ueberall)

1. **Universelle, neutrale Wortwahl.** Kein Geld-/Business-Bias. Projekte sind nicht
   nur zum Geldverdienen — manche sind privat (Social Media, Luvex, Lernen). Begriffe
   generell halten, damit alles nutzbar bleibt, egal ob Einkommen oder nicht.
2. **Config bleibt duenn.** Das Meiste gehoert zu **Kira**, **Projekte** oder in die
   **Zentrale**. Die Zentrale ist die *Zusammenfassung*, nicht eine weitere Ablage.
3. **Selbst editierbar.** Sergen will Beschriftungen im Dashboard per Klick aendern
   koennen (Inline-Rename), ohne Code anzufassen.
4. **Ruhiger, neutraler Look.** Weniger breit, weniger Neon, mehr Luft — sachlich.

---

## 1. Zentrale (Uebersicht)

- **Live-Ops schmaler.** Aktuell viel zu breit. Nicht winzig, aber deutlich schlanker —
  z.B. feste, moderate Spaltenbreite statt Vollbreite; der Rest bekommt Platz.
- **Neutralere Optik** fuer „Letzte Aktionen", „Intel · KI-News" & Co: ruhiger, weniger
  HUD-Effekt, sachlicher (keine Laufschrift/kein Dauer-Glow).
- **Inline-Rename:** Panel-Titel und Labels per Klick umbenennbar (siehe §7).
- Zentrale zeigt weiterhin die *Zusammenfassung* (Status, Befehl an Kira, Live-Ops,
  „Kira braucht dich", Heute, News).

## 2. Chat

- **Reasoning waehlbar machen.** Nicht nur an/aus — Sergen will *auswaehlen koennen,
  welches* Reasoning (welches Modell / welche Stufe) benutzt wird.
- **Kompakter Modell-Picker.** Ueber OpenRouter sind alle Modelle nutzbar (z.B. Fable
  soll direkt im Chat waehlbar sein). ABER: nicht durch 100 Modelle scrollen —
  ein **komprimierter Picker** mit Favoriten/Kurzliste + Suche. Vorschlag:
  - kleine Favoritenleiste (z.B. flash · pro · fable · sonnet) direkt sichtbar,
  - dahinter Suchfeld „andere…" (tippen filtert den vollen OpenRouter-Katalog).

## 3. Projekte (frueher „Standbeine")

- **Umbenennen:** „Standbeine" -> **„Projekte"**. Es sind Projekte, keine Einkommens-
  Standbeine.
- **Als Projekt-Dashboard denken:** je Projekt eine eigene Mini-Uebersicht
  (z.B. „Social Media", „Luvex", „Lernen"), unter *Projekte* einsehbar. Nicht
  geld-zentriert — Kasse/Kosten sind optional, nicht der Kern.
- Projekt-eigene Routinen/Crons erscheinen hier (Cron-`scope: projekt:<id>`), siehe §6.

## 4. Me / Ich

- **„Von Kira braucht dich":** zeigt die Freigaben. **BUG:** dort wartet eine
  „verpackte E-Mail" — siehe §8 (muss weg).
- **Deine Routinen — selbst erstellen.** Die feste „08:00-Routine" wirkt fremd.
  Stattdessen: **eigene Routine per Knopfdruck** anlegen (dein eigener Cron —
  z.B. „taegliche Erinnerung 18:00: Wasser trinken"). Einfaches Formular:
  Name · was · wann (Uhrzeit oder Intervall). Diese Crons laufen unter `scope: me`.
- Deine Aufgaben, deine Werte (Metriken) bleiben hier.

## 5. Kira

- Reiter schlank (Ziel ~4-5): Identitaet · Gedaechtnis · Wissen & Playbooks · Evolution.
- **Kiras Routinen** hierher: ihre *eigenen* wiederkehrenden Aufgaben (`scope: system`),
  getrennt von deinen (die unter Me). Gleiche Engine, andere Ansicht (siehe §6).
- **„Gewissen" hierher** (aus Config raus): Budget · Autonomie · Audit gehoeren zu
  „wer Kira ist / ihre Grenzen", nicht in einen Technik-Tab. (Budget-Kurzstand darf
  zusaetzlich in der Zentrale-Zusammenfassung auftauchen.)

## 6. Crons — eine Engine, drei Ansichten

Kernidee (nutzt das **bestehende `scope`-Feld** in `core/agency/missions/cron.py`,
Werte `me` | `projekt:<vid>` | `system`): Crons NICHT dreimal bauen, sondern EINE
Verwaltung, gefiltert nach Scope:

| Ansicht    | zeigt Crons mit Scope | Beispiel                              |
|------------|-----------------------|---------------------------------------|
| **Me**     | `me`                  | „Erinnerung 18:00: Wasser trinken"    |
| **Projekte** (je Projekt) | `projekt:<id>` | „Social-Media: taeglich posten pruefen" |
| **Kira**   | `system`              | Wartung, Briefings, Monitor-Check     |

- **Config · Cron raus.** Die Cron-Verwaltung wandert in diese drei kontextnahen Orte.
- „+ Routine anlegen" jeweils vor Ort, Scope wird aus dem Kontext gesetzt.

## 7. Inline-Rename (Labels im Dashboard editieren)

- Panel-Titel / Section-Labels per Klick umbenennbar. Analog zur schon existierenden
  **Tab-Icon-Anpassung** (im Browser gespeichert): eine `labels`-Map in `localStorage`,
  beim Rendern ueberschreibt sie die Default-Texte.
- Umsetzung leichtgewichtig: `contenteditable` auf den Label-Elementen ODER ein kleines
  ✎ beim Hover -> Prompt -> speichern. Reset-Knopf im Cockpit-Tab (wie bei den Icons).
- Kein Backend noetig (rein clientseitig), damit es billig bleibt.

## 8. Config — auf das Noetigste trimmen

**Bleibt in Config:** Modelle · Protokoll · Cockpit.
**Raus aus Config** (nach hier verschieben):
- **Gewissen** (Budget/Autonomie/Audit) -> **Kira** (§5).
- **Cron** -> **Me / Projekte / Kira** je nach Scope (§6).
- **Monitor** (News-Quellen) -> **Zentrale** (dort, wo die News auch angezeigt werden) —
  Quellen verwalten direkt neben dem News-Panel.

## BUG — Phantom-E-Mail in „Von Kira braucht dich"

- **Symptom:** Ein Freigabe-Item „E-Mail" wartet, obwohl gar keine echte Mail existiert
  bzw. gewollt ist. Herkunft: das **Abend-Briefing** hat versucht, sich *zusaetzlich als
  E-Mail an eine unbekannte Adresse* zu schicken; das `email_stranger`-Gate
  (`core/agency/approvals.py`, KINDS Zeile 21) hat das korrekt gestoppt und als
  Freigabe geparkt. Das Briefing soll aber NUR News per Telegram liefern.
- **Fix (Desktop, `data/` ist lokal):**
  1. Das haengende Freigabe-Item wegraeumen.
  2. Abend-Briefing-Cron-Prompt in `data/cron.json` haerten: **ausschliesslich Telegram,
     nie E-Mail** (Commit c20ef00 hat das begonnen — pruefen, ob der Prompt noch Richtung
     Mail zieht, und ggf. nachscherfen).
  3. Sicherstellen, dass kein Code-Pfad aus einem Briefing automatisch eine Mail-Freigabe
     erzeugt.

---

## Offene Punkte (mit Sergen klaeren, bevor umgesetzt)

- **Monitor-Ort:** Vorschlag Zentrale (neben den News). Alternativ Kira. → bestaetigen.
- **Gewissen-Ort:** Vorschlag Kira. → bestaetigen.
- **Modell-Favoriten:** welche 3-5 Modelle als Chat-Schnellwahl? (z.B. flash · pro ·
  fable · sonnet · lokal).
