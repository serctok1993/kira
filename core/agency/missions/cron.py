"""Planbare Aufgaben (Cron-lite): wiederkehrende Tasks mit Verlaufs-Tracking.

Jeder Job hat einen Prompt (was Kira tun soll) und einen Zeitplan:
  - Intervall:  "30m", "2h", "90"        -> alle N Minuten
  - taeglich:   "08:00", "daily 08:00"   -> jeden Tag zu der Uhrzeit (lokal)
  - Wochentage: "werktags 08:00", "montags 09:00", "mo,mi,fr 07:30",
                "woechentlich 20:00" (= montags), "wochenende 10:00"

Jobs liegen in data/cron.json. Der Mission-Runner prueft bei jedem Durchlauf faellige
Jobs (run_due) und fuehrt sie mit der Handlungs-Schleife (act) aus; jeder Lauf wird
protokolliert (runs[]) und ist im Dashboard nachverfolgbar.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time

from core import identity as _id
from core.config import ROOT
from core.kernel import events
from core.kernel.fs import atomic_write

JOBS = ROOT / "data" / "cron.json"


_LOAD_ERR_TS = 0.0  # Drossel: kaputtes cron.json nur ~alle 30 min melden, nicht pro Loop-Tick


def _load() -> list[dict]:
    """Jobs laden. NIE still scheitern: ein beschaedigtes cron.json liess frueher ALLE Crons
    lautlos verschwinden (leere Liste, kein Event, keine Nachricht) — jetzt wird es gemeldet,
    und die kaputte Datei bleibt als .broken-Kopie zur Diagnose liegen."""
    global _LOAD_ERR_TS
    if JOBS.exists():
        try:
            return json.loads(JOBS.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            now = time.time()
            if now - _LOAD_ERR_TS > 1800:
                _LOAD_ERR_TS = now
                try:
                    JOBS.with_suffix(".json.broken").write_text(
                        JOBS.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
                events.emit("cron_load_error", {"error": str(e)[:200]})
                _notify("⚠ cron.json ist beschaedigt — alle geplanten Aufgaben pausieren! "
                        "Kopie liegt als cron.json.broken. Bitte im Cockpit unter Kira→Cron neu anlegen.")
            return []
    return []


def _save(jobs: list[dict]) -> None:
    atomic_write(JOBS, json.dumps(jobs, ensure_ascii=False, indent=2))


def _hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8", "replace")).hexdigest()[:8]


# Wochentage (Live-Fund 26.07.): der Planer kannte NUR taeglich+Intervall. Folgen im
# Betrieb: der erste Nutzer-Wunsch ueberhaupt ("werktags 08:00") war unmoeglich, und
# der Job "Wochen-Review" lief noetigerweise TAEGLICH um 20:00 — ein Haupttreiber der
# Melde-Flut. Wochentags-Plaene sind daher kein Komfort, sondern Laerm-Vermeidung.
_TAGE = {"montag": 0, "montags": 0, "mo": 0, "dienstag": 1, "dienstags": 1, "di": 1,
         "mittwoch": 2, "mittwochs": 2, "mi": 2, "donnerstag": 3, "donnerstags": 3, "do": 3,
         "freitag": 4, "freitags": 4, "fr": 4, "samstag": 5, "samstags": 5, "sa": 5,
         "sonnabend": 5, "sonntag": 6, "sonntags": 6, "so": 6}
_GRUPPEN = {"werktags": [0, 1, 2, 3, 4], "wochentags": [0, 1, 2, 3, 4],
            "unter der woche": [0, 1, 2, 3, 4], "wochenende": [5, 6],
            "am wochenende": [5, 6], "woechentlich": [0], "wöchentlich": [0],
            "jede woche": [0]}


def parse_schedule(s: str) -> dict:
    s = (s or "").strip().lower()
    # 1) Wochentags-Plaene: "werktags 08:00", "montags 09:00", "mo,mi,fr 07:30",
    #    "woechentlich 20:00" (= montags). Uhrzeit optional -> 08:00.
    m = re.fullmatch(r"([a-zäöüß, ]+?)\s*(?:um\s*)?(?:(\d{1,2}):(\d{2}))?", s)
    if m and m.group(1):
        wort = m.group(1).strip().rstrip(",")
        tage: list[int] = []
        if wort in _GRUPPEN:
            tage = list(_GRUPPEN[wort])
        else:
            teile = [t.strip() for t in re.split(r"[,+/]| und ", wort) if t.strip()]
            if teile and all(t in _TAGE for t in teile):
                tage = sorted({_TAGE[t] for t in teile})
        if tage:
            zeit = (f"{int(m.group(2)):02d}:{m.group(3)}" if m.group(2) else "08:00")
            return {"type": "weekly", "days": tage, "time": zeit}
    # 2) Taeglich. Das Zeitwort war frueher nur als "daily " mit Leerzeichen erlaubt —
    #    "taeglich 08:00" fiel durch und landete im stummen 60-Minuten-Default weiter
    #    unten. In der Live-DB stehen 15 so angelegte Jobs: gewuenscht war EIN Briefing
    #    pro Tag, angelegt wurden 24 (Befund 27.07., Haupttreiber der Melde-Flut).
    m = re.fullmatch(
        r"(?:taeglich|täglich|daily|jeden\s+tag|jeden\s+morgen|jeden\s+abend|"
        r"morgens|abends|mittags|nachts|um)?\s*(\d{1,2}):(\d{2})\s*(?:uhr)?", s)
    if m:
        return {"type": "daily", "time": f"{int(m.group(1)):02d}:{m.group(2)}"}
    m = re.fullmatch(r"(?:alle\s+)?(\d+)\s*(?:h|std|stunde|stunden)", s)
    if m:
        return {"type": "interval", "minutes": max(5, int(m.group(1)) * 60)}
    if re.fullmatch(r"stuendlich|stündlich", s):
        return {"type": "interval", "minutes": 60}
    m = re.fullmatch(r"(?:alle\s+)?(\d+)\s*(?:m|min|minute|minuten)?", s)
    if m:
        return {"type": "interval", "minutes": max(5, int(m.group(1)))}
    # Unverstanden bleibt unverstanden: der stumme Stundentakt hat wochenlang Jobs
    # angelegt, die niemand so wollte. cron_add lehrt daraus einen Fehler.
    return {"type": "unklar", "roh": s}


def _next_run(sched: dict, ref: float | None = None) -> float:
    now = ref or time.time()
    if sched.get("type") == "weekly":
        tage = sorted(set(sched.get("days") or [0]))
        hh, mm = (int(x) for x in sched.get("time", "08:00").split(":"))
        d = dt.datetime.fromtimestamp(now).replace(hour=hh, minute=mm, second=0, microsecond=0)
        for plus in range(0, 8):          # heute zaehlt mit, sonst der naechste Tag der Liste
            kandidat = d + dt.timedelta(days=plus)
            if kandidat.weekday() in tage and kandidat.timestamp() > now:
                return kandidat.timestamp()
        return (d + dt.timedelta(days=7)).timestamp()
    if sched.get("type") == "daily":
        hh, mm = (int(x) for x in sched.get("time", "08:00").split(":"))
        d = dt.datetime.fromtimestamp(now).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if d.timestamp() <= now:
            d = d + dt.timedelta(days=1)
        return d.timestamp()
    return now + sched.get("minutes", 60) * 60


def _public(j: dict) -> dict:
    out = {k: v for k, v in j.items() if k != "runs"}
    out["recent_runs"] = j.get("runs", [])[-5:]
    return out


def list_jobs(scope: str | None = None) -> list[dict]:
    """Alle Jobs; scope filtert (S8.4): 'me' (Routinen des Nutzers) | 'projekt:<vid>' |
    'system'. Alt-Jobs ohne scope-Feld gelten defensiv als 'system'."""
    out = []
    for j in _load():
        s = j.get("scope") or "system"
        if scope and s != scope:
            continue
        p = _public(j)
        p["scope"] = s
        out.append(p)
    return out


def _stamm(label: str) -> str:
    """Erstes bedeutungstragendes Wort eines Labels, normalisiert.

    'Wetter-Brief', 'Wetter-Briefing', 'Wetter-Fact' und 'Wetter' teilen den Stamm
    'wetter' — 'Morgen-Briefing' und 'Backlog & Selbst-Diagnose' teilen keinen."""
    from core.agency.erinnerungen import normtext

    roh = re.split(r"[^a-zA-Z0-9äöüÄÖÜß]+", label or "")
    return next((normtext(w) for w in roh if len(normtext(w)) >= 4), "")


def aehnlicher_job(label: str, schedule: str) -> dict | None:
    """Ein bestehender Job zur selben Zeit mit gleichem Themen-Stamm — oder None.

    Live-Fund 27.07.: fuenf Wetter-Jobs innerhalb von 19 Stunden, weil beim Anlegen
    nichts prueft, ob es die Routine schon gibt. Bewusst eng: gleiche Zeit UND
    gleicher Stamm, damit legitime Jobs zur selben Uhrzeit (Morgen-Briefing +
    Backlog-Diagnose um 08:00) nicht faelschlich blockiert werden."""
    stamm = _stamm(label)
    if not stamm:
        return None
    try:
        sched = parse_schedule(schedule)
    except Exception:  # noqa: BLE001 — ungueltiger Zeitplan faellt anderswo auf
        return None
    for j in _load():
        if j.get("schedule") == sched and _stamm(j.get("label", "")) == stamm:
            return _public(j)
    return None


def add_job(label: str, prompt: str, schedule: str, escalate: bool = False,
            scope: str = "system", enabled: bool = True) -> dict:
    jobs = _load()
    sched = parse_schedule(schedule)
    job = {
        "id": _hash(label + prompt + str(time.time())),
        "label": (label or prompt[:40]).strip(),
        "prompt": prompt.strip(),
        "schedule": sched,
        "schedule_text": (schedule or "").strip(),
        "enabled": bool(enabled),
        "escalate": bool(escalate),
        "scope": (scope or "system").strip(),  # S8.4: me | projekt:<vid> | system
        "last_run": 0,
        "next_run": _next_run(sched),
        "runs": [],
    }
    jobs.append(job)
    _save(jobs)
    events.emit("cron_added", {"label": job["label"], "schedule": job["schedule_text"],
                               "scope": job["scope"]})
    return _public(job)


def remove_job(jid: str) -> bool:
    jobs = _load()
    n = [j for j in jobs if j.get("id") != jid]
    _save(n)
    return len(n) != len(jobs)


def toggle_job(jid: str, on: bool | None = None) -> bool:
    jobs = _load()
    state = None
    for j in jobs:
        if j.get("id") == jid:
            j["enabled"] = (not j.get("enabled")) if on is None else bool(on)
            if j["enabled"]:
                j["next_run"] = _next_run(j["schedule"])
            state = j["enabled"]
    _save(jobs)
    return bool(state)


def update_job(jid: str, label: str | None = None, prompt: str | None = None, schedule: str | None = None) -> bool:
    """Bestehenden Job bearbeiten (Name/Prompt/Zeitplan). Historie (runs) bleibt erhalten."""
    jobs = _load()
    found = False
    for j in jobs:
        if j.get("id") == jid:
            if label is not None and label.strip():
                j["label"] = label.strip()
            if prompt is not None and prompt.strip():
                j["prompt"] = prompt.strip()
            if schedule is not None and schedule.strip():
                j["schedule"] = parse_schedule(schedule)
                j["schedule_text"] = schedule.strip()
                j["next_run"] = _next_run(j["schedule"])
            found = True
    if found:
        _save(jobs)
        events.emit("cron_updated", {"id": jid, "label": label})
    return found


def _notify(text: str) -> bool:
    """Cron-Meldung zustellen. True = angekommen.

    Ging frueher blind raus: der Rueckgabewert von httpx.post wurde verworfen, ein
    fehlender Token brach still ab, und text[:4000] kappte lange Ergebnisse mitten
    im Satz, obwohl der Aufrufer glaubte, hier werde gestueckelt (Fund 27.07.)."""
    from core.kernel import zustellung

    return zustellung.an_nutzer(text, quelle="cron")


def run_job(job: dict, notify: bool = True, verspaetet_min: int = 0) -> dict:
    from core.agency.act import act

    prompt = job["prompt"]
    if verspaetet_min:
        # Ohne diesen Hinweis gratuliert ein nachgeholtes Morgen-Briefing um 14 Uhr
        # zum guten Morgen. Die JETZT-Zeile allein reicht nicht — im Prompt steht oft
        # eine feste Uhrzeit ("Es ist 08:00 Uhr").
        std = round(verspaetet_min / 60, 1)
        prompt = (f"(NACHGEHOLT: dieser Termin war vor {std} Stunden faellig, der Rechner "
                  f"war aus. Sag am Anfang kurz, dass es nachgereicht ist, und richte dich "
                  f"nach der JETZT-Zeit — nicht nach einer Uhrzeit, die im Auftrag steht.)\n\n"
                  f"{prompt}")
    try:
        # Zeitsinn (Fund): Cron-Prompts behaupten gern feste Uhrzeiten
        # ("Es ist 05:55 Uhr") — die ECHTE Zeit steht ab jetzt immer davor.
        from core.mind.agent import jetzt_zeile

        prompt = f"{jetzt_zeile()}\n\n{prompt}"
    except Exception:  # noqa: BLE001
        pass
    if "{{standup}}" in prompt:
        # S5: Briefings/Coach lesen echte Boards (Leben, Ziele, Metriken)
        # statt zu raten — der Platzhalter wird pro Lauf frisch expandiert.
        try:
            from core.agency.missions import standup

            prompt = prompt.replace("{{standup}}", standup.build_context(scope=job.get("label", "cron")))
        except Exception:  # noqa: BLE001
            prompt = prompt.replace("{{standup}}", "(Lagebericht nicht verfuegbar)")
    # Zustellweg klarstellen (Audit-Fund 26.07.): mehrere Cron-Prompts befahlen ein
    # "telegram_send", das es nie gab — Folge waren Entschuldigungslaeufe ("ich habe
    # kein Telegram-Werkzeug") und ein roher ACT-Leak als Nachricht. Der Kanal ist
    # Harness-Sache, nicht Modell-Sache: die Antwort IST die Meldung.
    prompt = (f"{prompt}\n\n(Zustellung: Deine Antwort wird automatisch an "
              f"{_id.user_name()} zugestellt — schreib sie direkt als fertige Nachricht. "
              "Es gibt KEIN Sende-Werkzeug und du brauchst keins.)")
    grund = ""
    try:
        r = act(prompt, session_id=f"cron-{job['id']}", escalate=job.get("escalate", False),
                task_type="bulk")  # einfache Crons -> lokal (0 EUR); escalate-Crons gehen weiter zu GLM
        volltext = (r.get("text") or "").strip()
        ok, grund = _lauf_bewerten(volltext)
        if not ok and not job.get("escalate"):
            # EIN Versuch auf der starken Stufe, bevor der Termin ersatzlos ausfaellt.
            # Grund (Befund 27.07.): die News-Briefings verlangen zehn Themenbereiche in
            # einem Durchgang und liefen auf der billigsten Stufe (4B) — Ergebnis waren
            # leere Antworten und Abbrueche. Nur bei Fehlschlag, also ohne Dauerkosten.
            events.emit("cron_eskaliert", {"label": job["label"], "grund": grund})
            r = act(prompt, session_id=f"cron-{job['id']}", escalate=True, task_type="reason")
            volltext = (r.get("text") or "").strip()
            ok, grund = _lauf_bewerten(volltext)
        summary = volltext[:300] if volltext else (grund or "(leere Antwort)")
    except Exception as e:  # noqa: BLE001
        volltext = ""
        summary = str(e)
        grund = f"{type(e).__name__} beim Ausfuehren"
        ok = False
    job["last_run"] = time.time()
    job["next_run"] = _next_run(job["schedule"])
    job["runs"] = (job.get("runs", []) + [{"ts": time.time(), "ok": ok, "summary": summary}])[-20:]
    events.emit("cron_run", {"label": job["label"], "ok": ok, "summary": summary})
    # Nur ECHTE Ergebnisse gehen raus — und dann ungekappt (die 300 Zeichen sind das
    # Dashboard-Mass, der Zusteller stueckelt selbst sauber bei 3800).
    if notify and ok:
        if _notify(f"⏰ {job['label']}:\n{volltext}") is False:
            # Das fertige Ergebnis darf nicht am Zustellweg verenden: ab in den
            # Melde-Puffer, dann geht es mit dem naechsten Buendel raus. Vorher war ein
            # gelungener Lauf bei klemmendem Telegram spurlos weg — im Cockpit stand ein
            # Haken, beim Nutzer kam nichts an (Befund 27.07.).
            try:
                from core.agency.missions import melde

                melde.merken(f"⏰ {job['label']}: {volltext[:300]}")
                events.emit("cron_zustellung_gescheitert", {"label": job["label"]})
            except Exception:  # noqa: BLE001
                pass
    elif notify and _fehlschlag_melden(job):
        # Nachbesserung 27.07.: seit dem Ehrlichkeits-Fix ging bei ok=False GAR NICHTS
        # mehr raus — ein ausgefallenes Briefing war fuer den Nutzer nicht von einem
        # nie geplanten zu unterscheiden. Jetzt: ehrliche Absage, aber hoechstens
        # einmal pro Job und Tag, damit ein dauerhaft kaputter Job nicht flutet.
        _notify(f"⏰ {job['label']} konnte ich nicht fertigstellen: {grund or summary}.\n"
                "Beim naechsten regulaeren Termin versuche ich es wieder.")
    return {"ok": ok, "summary": summary}


def _fehlschlag_melden(job: dict) -> bool:
    """Darf der Fehlschlag dieses Jobs jetzt gemeldet werden? (max. 1x pro Tag)"""
    heute = time.strftime("%Y-%m-%d")
    if job.get("fehler_gemeldet") == heute:
        return False
    job["fehler_gemeldet"] = heute
    return True


# Ehrliches ok (Audit-Fund 26.07.): frueher hiess ok=True nur "act() hat nicht
# geworfen". Von 49 gruenen Laeufen waren 21 Absagen, Leer-Antworten oder rohe
# ACT-Leaks — Cockpit und Selbst-Diagnose sahen ueberall ✓ und meldeten "alles gut".
# Ein Assistent, dessen Erfolgsmeldung nichts bedeutet, kann sich nicht verbessern.
def _lauf_bewerten(text: str) -> tuple[bool, str]:
    """(ok, grund) aus dem ERGEBNIS ableiten. Konservativ: nur eindeutige Ausfaelle
    gelten als Fehlschlag — inhaltliche Qualitaet beurteilt das hier nicht."""
    t = (text or "").strip()
    if not t:
        return False, "leere Antwort (Modell lieferte keinen Text)"
    from core.agency.verifier import _DEGRADE_MARKER

    if _DEGRADE_MARKER in t:
        return False, "Modell-/Netzwerk-Abbruch (Degrade-Marker)"
    if "Wall-Clock-Grenze" in t:
        return False, "Zeitlimit gerissen (Wall-Clock)"
    # roher Werkzeug-Aufruf als Endergebnis: der ACT-Text ist nie eine Nachricht
    if re.match(r"^\s*(ACT\s+\w+\s*[{(]|<tool_call>)", t) or "\nACT " in t[:400]:
        return False, "Werkzeug-Aufruf statt Antwort (ACT-Leak)"
    return True, ""


# Verfallsfenster fuer Tages-Crons (Fund: Sunrise-Job von 05:55 lief um 17:28
# nach PC-Neustart): mehr als N Sekunden ueberfaellig -> NICHT nachholen, sondern als
# 'verpasst' protokollieren und auf den naechsten regulaeren Termin legen.
# Intervall-Jobs sind davon ausgenommen — die laufen einfach einmal und takten neu ab jetzt.
MISSED_GRACE_S = 2 * 3600


def _job_zurueckschreiben(job: dict) -> None:
    """NUR diesen einen Job in die Datei uebernehmen — frisch laden, ersetzen, speichern.

    Audit-Fund 26.07.: run_due lud die Liste EINMAL, lief dann minutenlang durch act()
    und schrieb am Ende den alten Speicherstand zurueck. Legte Kira waehrenddessen per
    cron_add einen Job an (was sie tat — 11.07. und 21.07., beide Male mit korrekter
    Erfolgsmeldung an den Nutzer), war er nach dem Stapel-Speichern GARANTIERT weg.
    Aus Nutzersicht hat Kira gelogen; aus Modellsicht war alles richtig. Deshalb wird
    ab jetzt pro Job geschrieben, nie die ganze Liste aus dem Gedaechtnis."""
    aktuell = _load()
    for i, vorhanden in enumerate(aktuell):
        if vorhanden.get("id") == job.get("id"):
            aktuell[i] = job
            _save(aktuell)
            return
    # Job wurde zwischenzeitlich geloescht -> nicht wiederbeleben.


def run_due(now: float | None = None) -> list[dict]:
    now = now or time.time()
    ran = []
    verpasst: list[tuple[str, float]] = []
    nachgeholt = 0
    for j in _load():
        if not (j.get("enabled") and j.get("next_run", 0) <= now):
            continue
        overdue = now - float(j.get("next_run") or 0)
        if j.get("schedule", {}).get("type") in ("daily", "weekly") and overdue > MISSED_GRACE_S:
            if _darf_nachgeholt_werden(j, now, nachgeholt):
                # Nachholen statt ersatzlos streichen (Fund 27.07.): der Rechner des
                # Nutzers laeuft nicht durch — nur 13 % aller Ereignisse fallen zwischen
                # 6 und 10 Uhr, wo vier von sechs Jobs terminiert sind. Ergebnis waren
                # Erfolgsquoten von 4/19 bis 10/20, fast ausschliesslich "PC aus".
                # Ein Briefing um 11 statt um 8 ist noch nuetzlich; ein Weckl-Licht nicht.
                nachgeholt += 1
                j["next_run"] = _next_run(j["schedule"], ref=now)
                _job_zurueckschreiben(j)
                events.emit("cron_nachgeholt", {"label": j["label"],
                                                "overdue_h": round(overdue / 3600, 1)})
                res = run_job(j, verspaetet_min=round(overdue / 60))
                _job_zurueckschreiben(j)
                ran.append({"label": j["label"], "nachgeholt": True, **res})
                continue
            j["next_run"] = _next_run(j["schedule"], ref=now)
            j["runs"] = (j.get("runs", []) + [{
                "ts": now, "ok": False,
                "summary": f"verpasst ({round(overdue / 3600, 1)}h ueberfaellig, PC aus?) — "
                           f"uebersprungen statt nachgeholt"}])[-20:]
            events.emit("cron_missed", {"label": j["label"],
                                        "overdue_h": round(overdue / 3600, 1)})
            _job_zurueckschreiben(j)
            verpasst.append((j["label"], j["next_run"]))
            continue
        # Termin SOFORT weiterdrehen (vor act!): stirbt der Prozess mitten im Lauf,
        # laeuft der Job nach dem Neustart nicht ein zweites Mal (22.07.: Morgen-
        # Briefing lief doppelt, Sunrise dreimal als verpasst gebucht).
        j["next_run"] = _next_run(j["schedule"], ref=now)
        _job_zurueckschreiben(j)
        res = run_job(j)
        _job_zurueckschreiben(j)      # Ergebnis/last_run frisch drueberlegen
        ran.append({"label": j["label"], **res})
    if verpasst:
        _melde_verpasste(verpasst)
    return ran


MAX_NACHHOLEN = 2   # pro Durchlauf, damit nach langer Auszeit keine Flut losbricht

# Zeitgebundene Aktionen: nachts um 6 das Licht hochdimmen ergibt um 11 Uhr keinen Sinn
# mehr. Informationen dagegen schon — ein Briefing um 11 statt 8 ist immer noch nuetzlich.
_ZEITGEBUNDEN_RE = re.compile(
    r"\b(sunrise|weck|wecker|licht|lampe|hue|dimm|alarm|klingel|schalte\s+\w*\s*(an|aus|ein))\b"
    r"|\.py\b|\brun_command\b", re.IGNORECASE)


def nachholbar(job: dict) -> bool:
    """Darf dieser Job verspaetet laufen? Explizites Feld schlaegt die Heuristik.

    Default ja: die grosse Mehrheit der Jobs liefert Informationen, und die sind auch
    verspaetet etwas wert. Nur was eine zeitgebundene Aktion ausloest, faellt aus."""
    if "nachholen" in job:
        return bool(job["nachholen"])
    text = f"{job.get('label', '')} {job.get('prompt', '')}"
    return not _ZEITGEBUNDEN_RE.search(text)


def _darf_nachgeholt_werden(job: dict, now: float, schon: int) -> bool:
    """Nachholen nur am SELBEN Kalendertag und nur begrenzt oft.

    Ein Morgen-Briefing von vorgestern ist Altpapier; eines von heute Morgen nicht."""
    if schon >= MAX_NACHHOLEN or not nachholbar(job):
        return False
    faellig = dt.datetime.fromtimestamp(float(job.get("next_run") or 0)).date()
    return faellig == dt.datetime.fromtimestamp(now).date()


def _melde_verpasste(verpasst: list[tuple[str, float]]) -> None:
    """EINE Sammelnachricht ueber ausgefallene Termine.

    Bis 27.07. wurde ein verpasster Job nur ins Protokoll geschrieben (66 Ereignisse
    in der Live-DB, alle sechs Tagesjobs betroffen) — der Nutzer erfuhr nie, dass sein
    Morgen-Briefing ausgefallen war. Aus seiner Sicht 'funktionieren die Crons nicht'."""
    zeilen = []
    for label, next_run in verpasst:
        wann = dt.datetime.fromtimestamp(next_run).strftime("%d.%m. um %H:%M")
        zeilen.append(f"• {label} — naechster Termin: {wann}")
    was = "ist ein Termin" if len(verpasst) == 1 else f"sind {len(verpasst)} Termine"
    _notify(f"⏰ Waehrend der Rechner aus war, {was} ausgefallen:\n"
            + "\n".join(zeilen)
            + "\n\nDiese hole ich nicht nach — sie waeren jetzt sinnlos oder von gestern. "
              "Was noch etwas taugt, reiche ich von selbst nach.")


def run_now(jid: str) -> dict:
    """"Jetzt ausfuehren" aus dem Cockpit.

    Schrieb frueher am Ende die GANZE Liste zurueck (_save) — derselbe Fehler, der am
    26.07. in run_due behoben wurde: alles, was waehrend des Laufs an cron.json
    geschrieben wurde (ein per cron_add angelegter Job, der Fortschritt eines parallel
    laufenden Jobs), war danach weg."""
    for j in _load():
        if j.get("id") == jid:
            res = run_job(j)
            _job_zurueckschreiben(j)
            return res
    return {"ok": False, "summary": "Job nicht gefunden"}
