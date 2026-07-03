"""Planbare Aufgaben (Cron-lite): wiederkehrende Tasks mit Verlaufs-Tracking.

Jeder Job hat einen Prompt (was Kira tun soll) und einen Zeitplan:
  - Intervall:  "30m", "2h", "90"        -> alle N Minuten
  - taeglich:   "08:00", "daily 08:00"   -> jeden Tag zu der Uhrzeit (lokal)

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

from core.config import CONFIG, ROOT
from core.kernel import events
from core.kernel.fs import atomic_write

JOBS = ROOT / "data" / "cron.json"


def _load() -> list[dict]:
    if JOBS.exists():
        try:
            return json.loads(JOBS.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(jobs: list[dict]) -> None:
    atomic_write(JOBS, json.dumps(jobs, ensure_ascii=False, indent=2))


def _hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8", "replace")).hexdigest()[:8]


def parse_schedule(s: str) -> dict:
    s = (s or "").strip().lower()
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
    """Alle Jobs; scope filtert (S8.4): 'me' (Sergens Routinen) | 'projekt:<vid>' |
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
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
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
    if "{{standup}}" in prompt:
        # S5: Briefings/Coach lesen echte Boards (Leben, Ziele, Ventures, Metriken)
        # statt zu raten — der Platzhalter wird pro Lauf frisch expandiert.
        try:
            from core.agency.missions import standup

            prompt = prompt.replace("{{standup}}", standup.build_context(scope=job.get("label", "cron")))
        except Exception:  # noqa: BLE001
            prompt = prompt.replace("{{standup}}", "(Lagebericht nicht verfuegbar)")
    try:
        r = act(prompt, session_id=f"cron-{job['id']}", escalate=job.get("escalate", False),
                task_type="bulk")  # einfache Crons -> lokal (0 EUR); escalate-Crons gehen weiter zu GLM
        summary = (r.get("text") or "").strip()[:300]
        ok = True
    except Exception as e:  # noqa: BLE001
        summary = str(e)
        ok = False
    job["last_run"] = time.time()
    job["next_run"] = _next_run(job["schedule"])
    job["runs"] = (job.get("runs", []) + [{"ts": time.time(), "ok": ok, "summary": summary}])[-20:]
    events.emit("cron_run", {"label": job["label"], "ok": ok, "summary": summary})
    if notify:
        _notify(f"⏰ {job['label']}:\n{summary}")
    return {"ok": ok, "summary": summary}


def run_due(now: float | None = None) -> list[dict]:
    now = now or time.time()
    jobs = _load()
    ran = []
    changed = False
    for j in jobs:
        if j.get("enabled") and j.get("next_run", 0) <= now:
            res = run_job(j)
            ran.append({"label": j["label"], **res})
            changed = True
    if changed:
        _save(jobs)
    return ran


def run_now(jid: str) -> dict:
    jobs = _load()
    for j in jobs:
        if j.get("id") == jid:
            res = run_job(j)
            _save(jobs)
            return res
    return {"ok": False, "summary": "Job nicht gefunden"}
