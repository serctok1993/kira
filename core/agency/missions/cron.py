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

import httpx

from core import identity as _id
from core.config import CONFIG, ROOT
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
    m = re.fullmatch(r"(?:taeglich|täglich|daily\s+)?(\d{1,2}):(\d{2})", s)
    if m:
        return {"type": "daily", "time": f"{int(m.group(1)):02d}:{m.group(2)}"}
    m = re.fullmatch(r"(\d+)\s*(?:h|std|stunden)", s)
    if m:
        return {"type": "interval", "minutes": max(5, int(m.group(1)) * 60)}
    m = re.fullmatch(r"(\d+)\s*(?:m|min|minuten)?", s)
    if m:
        return {"type": "interval", "minutes": max(5, int(m.group(1)))}
    return {"type": "interval", "minutes": 60}


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


def _notify(text: str) -> None:
    from core import config as _cfg
    if _cfg.outbound_blocked():  # Firewall (Benchmark/Sandbox): kein Telegram
        return
    try:
        # Token-Hygiene-Nachzug: gleiche Aufloesung wie der Bot (token_env) — sonst
        # gingen Cron-Meldungen nach dem .env-Aufraeumen still verloren.
        token = _cfg.telegram_token()
        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        if token and chat:
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:4000]},
                timeout=15,
            )
    except Exception as e:  # noqa: BLE001
        events.emit("notify_error", {"error": str(e)})


def run_job(job: dict, notify: bool = True) -> dict:
    from core.agency.act import act

    prompt = job["prompt"]
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
    try:
        r = act(prompt, session_id=f"cron-{job['id']}", escalate=job.get("escalate", False),
                task_type="bulk")  # einfache Crons -> lokal (0 EUR); escalate-Crons gehen weiter zu GLM
        volltext = (r.get("text") or "").strip()
        ok, grund = _lauf_bewerten(volltext)
        summary = volltext[:300] if volltext else (grund or "(leere Antwort)")
    except Exception as e:  # noqa: BLE001
        volltext = ""
        summary = str(e)
        ok = False
    job["last_run"] = time.time()
    job["next_run"] = _next_run(job["schedule"])
    job["runs"] = (job.get("runs", []) + [{"ts": time.time(), "ok": ok, "summary": summary}])[-20:]
    events.emit("cron_run", {"label": job["label"], "ok": ok, "summary": summary})
    # Nur ECHTE Ergebnisse gehen raus — und dann ungekappt (die 300 Zeichen sind das
    # Dashboard-Mass, _notify stueckelt selbst sauber bei 3800).
    if notify and ok:
        _notify(f"⏰ {job['label']}:\n{volltext}")
    return {"ok": ok, "summary": summary}


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
    for j in _load():
        if not (j.get("enabled") and j.get("next_run", 0) <= now):
            continue
        overdue = now - float(j.get("next_run") or 0)
        if j.get("schedule", {}).get("type") in ("daily", "weekly") and overdue > MISSED_GRACE_S:
            j["next_run"] = _next_run(j["schedule"], ref=now)
            j["runs"] = (j.get("runs", []) + [{
                "ts": now, "ok": False,
                "summary": f"verpasst ({round(overdue / 3600, 1)}h ueberfaellig, PC aus?) — "
                           f"uebersprungen statt nachgeholt"}])[-20:]
            events.emit("cron_missed", {"label": j["label"],
                                        "overdue_h": round(overdue / 3600, 1)})
            _job_zurueckschreiben(j)
            continue
        # Termin SOFORT weiterdrehen (vor act!): stirbt der Prozess mitten im Lauf,
        # laeuft der Job nach dem Neustart nicht ein zweites Mal (22.07.: Morgen-
        # Briefing lief doppelt, Sunrise dreimal als verpasst gebucht).
        j["next_run"] = _next_run(j["schedule"], ref=now)
        _job_zurueckschreiben(j)
        res = run_job(j)
        _job_zurueckschreiben(j)      # Ergebnis/last_run frisch drueberlegen
        ran.append({"label": j["label"], **res})
    return ran


def run_now(jid: str) -> dict:
    jobs = _load()
    for j in jobs:
        if j.get("id") == jid:
            res = run_job(j)
            _save(jobs)
            return res
    return {"ok": False, "summary": "Job nicht gefunden"}
