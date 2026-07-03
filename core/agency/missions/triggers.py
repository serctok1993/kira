"""Proaktive Trigger: 'wenn Ereignis X passiert -> lege Aufgabe Y an' (S4).

Bisher reagierte Kira nur auf die Uhr (Cron) und auf Sergen. Trigger machen sie
ereignis-getrieben: neue Stripe-Einnahme -> Skalierung pruefen; Task endgueltig
gescheitert -> Alternative planen; Server tot -> diagnostizieren.

Die ausgeloeste Aufgabe geht als normaler Task in die Queue (Prioritaet 3, vor
Planner-Tasks) und laeuft damit durch die volle S2-Ergebnis-Rueckkopplung.
Schutz gegen Endlos-Schleifen: Cooldown pro Trigger (Default 1h) + trigger_fired
kann nie selbst triggern. Persistenz: data/triggers.json (ueberlebt Neustarts;
beim allerersten Lauf wird nur die Basislinie gesetzt, Alt-Events feuern nicht).
"""
from __future__ import annotations

import json
import time
import uuid

from core.config import CONFIG, DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write

_PATH = DATA_DIR / "triggers.json"


def _load() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"triggers": []}
    except Exception:  # noqa: BLE001
        return {"triggers": []}


def _save(state: dict) -> None:
    atomic_write(_PATH, json.dumps(state, indent=2, ensure_ascii=False))


def _mission_name() -> str:
    return CONFIG.get("mission", {}).get("name", "default")


def add(label: str, event_type: str, task: str, contains: str = "",
        cooldown_s: int = 3600) -> str:
    tid = uuid.uuid4().hex
    state = _load()
    state.setdefault("triggers", []).append({
        "id": tid, "label": label.strip(), "event_type": event_type.strip(),
        "contains": contains.strip(), "task": task.strip(),
        "enabled": True, "cooldown_s": int(cooldown_s), "last_fired": 0.0,
        "fail_count": 0, "spawned": [],  # S6.2: Backoff-Buchhaltung
    })
    _save(state)
    events.emit("trigger_added", {"id": tid, "label": label, "event_type": event_type})
    return tid


def list_all() -> list[dict]:
    return _load().get("triggers", [])


def remove(tid: str) -> bool:
    state = _load()
    before = len(state.get("triggers", []))
    state["triggers"] = [t for t in state.get("triggers", []) if t["id"] != tid
                         and not t["id"].startswith(tid)]
    _save(state)
    return len(state["triggers"]) < before


def set_enabled(tid: str, enabled: bool) -> bool:
    state = _load()
    for t in state.get("triggers", []):
        if t["id"] == tid or t["id"].startswith(tid):
            t["enabled"] = bool(enabled)
            _save(state)
            return True
    return False


def _effective_cooldown(t: dict) -> float:
    """S6.2-Backoff: scheitern die ausgeloesten Aufgaben wiederholt, verdoppelt sich
    der Cooldown pro Fehlschlag (Cap 16x) — ein kaputter Trigger feuert nicht mehr
    stur jede Stunde. Erfolg setzt zurueck."""
    base = float(t.get("cooldown_s") or 3600)
    return base * (2 ** min(int(t.get("fail_count") or 0), 4))


def check() -> list[dict]:
    """Neue Events seit dem letzten Check gegen alle Trigger matchen.

    Laeuft periodisch im Runner-Loop (wie Cron/Monitor, unabhaengig vom
    Heartbeat-Toggle). Ausgeloeste Aufgaben warten in der Queue, bis der
    Heartbeat sie abarbeitet."""
    from core.agency.missions import queue

    state = _load()
    trigs = state.get("triggers", [])
    last_ts = state.get("last_ts")
    now = time.time()
    if last_ts is None:
        # Allererster Lauf: Basislinie setzen — Alt-Historie feuert nicht nach.
        state["last_ts"] = now
        state["seen_ids"] = [e["id"] for e in events.recent(300)]
        _save(state)
        return []

    fired: list[dict] = []
    # Neu = im Zeitfenster UND noch nie verarbeitet. Der ID-Abgleich macht das robust
    # gegen die Uhr-Aufloesung (Events im selben Millisekunden-Tick wie der letzte
    # Check gingen frueher verloren); das 5s-Rueckfenster haelt die seen-Liste klein.
    seen = set(state.get("seen_ids") or [])
    new_events = [e for e in events.recent(300)
                  if e["ts"] > float(last_ts) - 5.0 and e["id"] not in seen]
    for e in reversed(new_events):  # chronologisch
        # S6.2: Ausgang der selbst ausgeloesten Aufgaben verbuchen (Backoff-Futter).
        if e["type"] in ("task_failed_final", "mission_task_failed", "mission_task_done"):
            done_id = str((e.get("payload") or {}).get("id") or "")
            if done_id:
                for t in trigs:
                    if done_id in (t.get("spawned") or []):
                        t["fail_count"] = 0 if e["type"] == "mission_task_done" \
                            else int(t.get("fail_count") or 0) + 1
        if e["type"] in ("trigger_fired", "trigger_added"):
            continue  # nie selbst-triggern (Endlos-Schleifen-Schutz)
        for t in trigs:
            if not t.get("enabled", True) or t.get("event_type") != e["type"]:
                continue
            if t.get("contains"):
                haystack = json.dumps(e.get("payload") or {}, ensure_ascii=False).lower()
                if t["contains"].lower() not in haystack:
                    continue
            if now - float(t.get("last_fired") or 0) < _effective_cooldown(t):
                continue
            queue.init_queue()
            task_id = queue.add(f"[Trigger '{t['label']}'] {t['task']}",
                                mission=_mission_name(), priority=3)
            t["last_fired"] = now
            t["spawned"] = ((t.get("spawned") or []) + [task_id])[-10:]
            events.emit("trigger_fired", {"trigger": t["label"], "event": e["type"],
                                          "task_id": task_id})
            fired.append({"trigger": t["label"], "task_id": task_id})

    state["last_ts"] = now
    state["seen_ids"] = (state.get("seen_ids") or [])[-600:] + [e["id"] for e in new_events]
    _save(state)
    return fired
