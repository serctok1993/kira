"""Prozess-lokaler Laufzeit-Zustand: aktive Chat-Zuege + aufgeschobene Neustarts.

Verhindert, dass ein Neustart (restart_self ODER ein selfdev-Bounce nach self_edit)
den Bot MITTEN in einer laufenden Antwort abschiesst -> Kira wuerde sonst ihre eigene
Arbeit killen (genau der beobachtete 'Absturz'). Ein Neustart-Wunsch waehrend eines
aktiven Zugs wird gemerkt und erst ausgefuehrt, wenn der Zug fertig ist (idle).

Der Zustand ist PRO PROZESS: der Bot markiert seine Chat-Zuege (enter_turn/exit_turn).
Ruft Kira in diesem Zug restart_self/self_edit auf, wird der Bounce aufgeschoben und
beim Zug-Ende ausgeloest. In Prozessen ohne aktiven Zug wirkt ein Neustart sofort.
"""
from __future__ import annotations

import threading

from core.config import ROOT
from core.kernel import events

_lock = threading.Lock()
_active_turns = 0
_pending_restart: str | None = None
_RESTART_FLAG = ROOT / "data" / "restart.flag"


def _write_flag(which: str) -> None:
    _RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
    _RESTART_FLAG.write_text(which, encoding="utf-8")


def enter_turn() -> None:
    """Markiert den Beginn eines Chat-Zugs (Bot-Worker)."""
    global _active_turns
    with _lock:
        _active_turns += 1


def exit_turn() -> None:
    """Zug beendet. War ein Neustart aufgeschoben und sind wir jetzt idle -> jetzt ausloesen."""
    global _active_turns, _pending_restart
    with _lock:
        _active_turns = max(0, _active_turns - 1)
        fire = None
        if _active_turns == 0 and _pending_restart is not None:
            fire = _pending_restart
            _pending_restart = None
    if fire is not None:
        _write_flag(fire)
        events.emit("restart_deferred_fired", {"which": fire})


def turn_active() -> bool:
    with _lock:
        return _active_turns > 0


def request_restart(which: str = "all") -> str:
    """Neustart anfordern. Laeuft gerade ein Chat-Zug -> bis idle aufschieben statt
    sich selbst abzuschiessen. Sonst sofort (wie bisher)."""
    global _pending_restart
    which = (which or "all").strip().lower() or "all"
    with _lock:
        deferred = _active_turns > 0
        if deferred:
            _pending_restart = which
    events.emit("restart_requested", {"which": which, "deferred": deferred})
    if deferred:
        return ("Neustart gemerkt — ich fuehre ihn aus, sobald der aktuelle Zug fertig ist "
                "(damit ich meine Arbeit + Antwort nicht mittendrin abschiesse).")
    _write_flag(which)
    return "Sicherer Neustart angefordert — der Supervisor bounced in ~20s (Zeit fuer den Bericht)."
