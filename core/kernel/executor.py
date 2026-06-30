"""Executor: jeder Werkzeug-Aufruf laeuft hier durch.

Sicherheit + Resilienz an einer Stelle:
- prueft den Kill-Switch VOR jeder Aktion (Verfassungsregel #4),
- Retry mit Exponential-Backoff,
- Circuit-Breaker: nach zu vielen Fehlern wird ein Werkzeug vorerst gesperrt,
- alles wird als Event protokolliert (Audit-Grundlage).
"""
from __future__ import annotations

import time
from typing import Callable

from core.kernel import events
from core.kernel.scheduler import kill_switch_active

_OPEN_THRESHOLD = 3          # so viele Fehler in Folge -> Circuit offen
_failures: dict[str, int] = {}


class KillSwitchActive(RuntimeError):
    pass


class CircuitOpen(RuntimeError):
    pass


def reset(name: str | None = None) -> None:
    if name is None:
        _failures.clear()
    else:
        _failures.pop(name, None)


def run_tool(name: str, func: Callable, /, *args, retries: int = 3, base_delay: float = 1.0, **kwargs):
    if kill_switch_active():
        events.emit("executor_blocked", {"tool": name, "reason": "kill_switch"})
        raise KillSwitchActive("Kill-Switch aktiv — Aktion abgebrochen.")

    if _failures.get(name, 0) >= _OPEN_THRESHOLD:
        events.emit("circuit_open", {"tool": name})
        raise CircuitOpen(f"Circuit offen fuer '{name}' (zu viele Fehler). Mit executor.reset() loesen.")

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            t0 = time.time()
            result = func(*args, **kwargs)
            events.emit(
                "tool_call",
                {"tool": name, "ok": True, "attempt": attempt, "latency_s": round(time.time() - t0, 2)},
            )
            _failures[name] = 0
            return result
        except Exception as e:  # noqa: BLE001 - bewusst breit, wir loggen + retryen
            last_err = e
            events.emit("tool_call", {"tool": name, "ok": False, "attempt": attempt, "error": str(e)})
            if attempt < retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))

    _failures[name] = _failures.get(name, 0) + 1
    raise last_err  # type: ignore[misc]
