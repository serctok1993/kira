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
import time

from core.config import ROOT
from core.kernel import events

_lock = threading.Lock()
_active_turns = 0
_turn_sids: dict[str, int] = {}   # aktive Zuege je Session — fuer den session-genauen Watchdog
_pending_restart: str | None = None
_RESTART_FLAG = ROOT / "data" / "restart.flag"


def _write_flag(which: str) -> None:
    _RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
    _RESTART_FLAG.write_text(which, encoding="utf-8")


def enter_turn(session_id: str | None = None) -> None:
    """Markiert den Beginn eines Chat-Zugs (Bot-Worker). Mit session_id kann der
    Watchdog den Stillstand DIESES Zugs messen statt der ganzen events-Tabelle."""
    global _active_turns
    with _lock:
        _active_turns += 1
        if session_id:
            _turn_sids[session_id] = _turn_sids.get(session_id, 0) + 1


def exit_turn(session_id: str | None = None) -> None:
    """Zug beendet. War ein Neustart aufgeschoben und sind wir jetzt idle -> jetzt ausloesen."""
    global _active_turns, _pending_restart
    with _lock:
        _active_turns = max(0, _active_turns - 1)
        if session_id and session_id in _turn_sids:
            _turn_sids[session_id] -= 1
            if _turn_sids[session_id] <= 0:
                del _turn_sids[session_id]
        fire = None
        if _active_turns == 0 and _pending_restart is not None:
            fire = _pending_restart
            _pending_restart = None
    if fire is not None:
        _write_flag(fire)
        events.emit("restart_deferred_fired", {"which": fire})


def active_turn_sids() -> list[str]:
    with _lock:
        return list(_turn_sids)


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


def start_watchdog(check_every: int = 30) -> None:
    """Hintergrund-Waechter gegen festgefahrene Chat-Zuege.

    Haengt ein Zug (aktiv, aber seit langem KEIN Fortschritt = kein neues Event) laenger als
    'turn_stall_seconds', wird ein Neustart ERZWUNGEN (Supervisor bounct den wedged Bot). Faengt
    genau den Fall ab, dass ein LLM-/Netz-Call sein Timeout ignoriert und der Zug nie endet -> der
    aufgeschobene Neustart wuerde sonst NIE feuern (beim Test: 8 Min Stillstand). Legitime lange
    Tasks produzieren laufend Events (act_step/tool_call/llm_call) und loesen den Waechter NICHT aus.
    """
    from core.config import DB_PATH

    try:
        from core.config import CONFIG
        stall_s = int(CONFIG.get("agency", {}).get("turn_stall_seconds", 720))
    except Exception:  # noqa: BLE001
        stall_s = 720

    def _newest_event_ts() -> float:
        """Juengstes Event der AKTIVEN Zuege. Audit-Fund: die alte globale MAX(ts)-Messung
        wurde im 24/7-Betrieb von Runner-Events maskiert — ein haengender Bot-Zug fiel nie
        auf. Kennt der Prozess die Session(s) seiner Zuege, wird NUR dort gemessen;
        ohne bekannte Sessions bleibt der globale Blick (altes Verhalten)."""
        import sqlite3
        sids = active_turn_sids()
        try:
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            try:
                if sids:
                    ph = ",".join("?" * len(sids))
                    r = con.execute(f"SELECT MAX(ts) FROM events WHERE session_id IN ({ph})",
                                    sids).fetchone()
                else:
                    r = con.execute("SELECT MAX(ts) FROM events").fetchone()
            finally:
                con.close()
            return float(r[0]) if r and r[0] else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    def _loop() -> None:
        while True:
            time.sleep(check_every)
            try:
                if not turn_active():
                    continue
                letzte = _newest_event_ts()
                if letzte <= 0.0:
                    # Fix 13.08.: 0.0 heisst "keine Events sichtbar" (frische Session oder
                    # DB-Fehler) — NICHT "seit 1970 kein Fortschritt". Der alte Vergleich
                    # ergab stalled_s=<Epoch> und schoss laufende Zuege sofort ab.
                    continue
                stalled = time.time() - letzte
                if stalled > stall_s:
                    events.emit("turn_timeout", {"stalled_s": round(stalled), "limit_s": stall_s})
                    _write_flag("all")  # Deferral bewusst umgangen: der festgefahrene Zug IST das Problem
                    return  # Supervisor bounct in ~20s; dieser Thread stirbt mit dem Prozess
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_loop, daemon=True, name="turn-watchdog").start()
    events.emit("watchdog_started", {"stall_s": stall_s, "check_every": check_every})
