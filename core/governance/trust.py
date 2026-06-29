"""Trust-Level: wieviel darf Kira allein entscheiden.

Stufen 0-3 (Start aus config.yaml: governance.trust_level). Die Policy
`requires_approval(kind)` sagt, ob eine Aktionsart ein Go von Sergen braucht.
Erfolge/Fehlschlaege werden protokolliert (Grundlage fuer spaeteres Lernen).
"""
from __future__ import annotations

from core.config import CONFIG
from core.kernel import events

LEVELS = {
    0: "alles vorlegen",
    1: "reversibles autonom",
    2: "meiste autonom, Geld/Posts vorlegen",
    3: "voll-autonom (nur durch Budget begrenzt)",
}


def level() -> int:
    return int(CONFIG.get("governance", {}).get("trust_level", 0))


def stats() -> dict:
    succ = fail = 0
    for e in events.recent(5000):
        if e["type"] == "trust_outcome":
            if e["payload"].get("ok"):
                succ += 1
            else:
                fail += 1
    return {"success": succ, "fail": fail}


def record_outcome(ok: bool, action: str = "") -> str:
    return events.emit("trust_outcome", {"ok": bool(ok), "action": action})


def requires_approval(kind: str, amount: float = 0.0) -> bool:
    """kind: 'reversible' | 'irreversible' | 'money' | 'public'.

    True => braucht Sergens Go. Bei voller Autonomie (Level 3) begrenzt nur das
    Budget (das die Treasury prueft), daher hier False.
    """
    lv = level()
    if lv >= 3:
        return False
    if lv == 2:
        return kind in ("money", "public")
    if lv == 1:
        return kind in ("money", "public", "irreversible")
    return True  # Level 0: alles vorlegen
