"""Tagesfokus: des Nutzers Richtungs-Hebel — EINE Zeile, um die sich der Heartbeat plant.

Ein Speicher (data/focus.json), zwei Bedienwege: Cockpit-Zentrale ("Als Fokus
setzen") und Telegram (/fokus). Setzen leert die offene Mission-Queue, damit der
naechste Tick um den neuen Fokus herum plant statt Altlasten abzuarbeiten.
"""
from __future__ import annotations

import json
import time

from core.config import CONFIG, ROOT
from core.kernel import events

_PATH = ROOT / "data" / "focus.json"


def get() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    return {"focus": d.get("focus", ""), "ts": d.get("ts", 0)}


def set_focus(focus: str, via: str = "dashboard") -> str:
    """Fokus setzen (leer = loeschen). Leert die offene Queue, emittiert focus_set."""
    focus = (focus or "").strip()
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps({"focus": focus, "ts": time.time()}, ensure_ascii=False),
                     encoding="utf-8")
    try:  # offene Queue leeren -> naechster Tick plant um den neuen Fokus herum
        from core.agency.missions import queue as mqueue

        mqueue.init_queue()
        mqueue.clear(CONFIG.get("mission", {}).get("name", "default"))
    except Exception:  # noqa: BLE001
        pass
    events.emit("focus_set", {"focus": focus[:200], "via": via})
    return focus
