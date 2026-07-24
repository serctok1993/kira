"""Supervisor / Watchdog: haelt Kiras Dienste am Leben.

Startet Cockpit, Telegram-Bot und Mission-Runner und ueberwacht sie. Stirbt einer
(Crash, Self-Edit, manueller Kill) -> Neustart in Sekunden. Ein Restart-Flag
(data/restart.flag) erlaubt einen SICHEREN Bounce nach self_edit, ohne dass Kira
sich selbst killt (Self-Kill ist in shelltool zusaetzlich gesperrt).

Singleton: Instanz-Lock via core.kernel.instance_lock (Loopback-Port 8009 + Lock-Datei
data/supervisor.lock mit PID) — ein zweiter Start (Autostart + manueller Start) erkennt
die laufende Instanz und beendet sich sauber. Beim Start werden ausserdem Waisen eines
frueheren Laufs (PC-Absturz, harter Kill) erkannt und beendet, bevor frische Kinder
starten — sonst laufen Bot/Runner doppelt.
Start:  uv run python -m core.kernel.supervisor   (oder via start-all.ps1 / Autostart)
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from core import config
from core.config import ROOT
from core.kernel import events, instance_lock

PY = sys.executable  # der (venv-)Python, mit dem der Supervisor laeuft
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

COMPONENTS: dict[str, list[str]] = {
    "cockpit": [PY, "-m", "uvicorn", "core.api.server:app", "--host", "127.0.0.1", "--port", "8000"],
    "bot": [PY, "-m", "core.agency.connectors.telegram_bot"],
    "runner": [PY, "-m", "core.agency.missions.runner"],
}
RESTART_FLAG = ROOT / "data" / "restart.flag"

# Absturz-Bremse: haelt einen kaputten Dienst nicht in einer Sekunden-Schleife am Leben.
_CRASH_WINDOW = 300.0   # Beobachtungsfenster (5 Min)
_CRASH_LIMIT = 5        # so viele Abstuerze im Fenster -> Krisenmodus (langer Cooldown + Alarm)
_MAX_BACKOFF = 60.0     # Deckel fuer den exponentiellen Wiederanlauf-Abstand


def _backoff_plan(recent: int) -> tuple[bool, float, bool]:
    """Reine Politik-Entscheidung fuer die Absturz-Bremse (testbar).

    recent = Zahl der Abstuerze im Fenster (inkl. diesem). Rueckgabe:
    (jetzt_neustarten?, Wartezeit_bis_naechster_Versuch_s, Krisenmodus?).
    Krise ab _CRASH_LIMIT: NICHT sofort neustarten, langer Cooldown. Sonst exponentiell
    (2,4,8,16,32 …) gedeckelt auf _MAX_BACKOFF."""
    if recent >= _CRASH_LIMIT:
        return False, _CRASH_WINDOW, True
    return True, min(_MAX_BACKOFF, 2.0 ** recent), False


def _alert(text: str) -> None:
    """Einmalige Telegram-Warnung bei Dauer-Crash — respektiert die Firewall."""
    try:
        from core.config import CONFIG, outbound_blocked, telegram_token

        if outbound_blocked():
            return
        import httpx

        # Gleiche Token-Aufloesung wie der Bot (channels.telegram.token_env) — sonst
        # gingen Crash-Alarme ueber ein geerbtes FREMDES Token an den falschen Bot.
        token = telegram_token()
        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        if token and chat:
            httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat, "text": text[:4000]}, timeout=15)
    except Exception:  # noqa: BLE001 — Alarm darf den Supervisor nie mitreissen
        pass


def _launch(name: str) -> subprocess.Popen:
    log = ROOT / "data" / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    f = open(log, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 (lebt mit dem Prozess)
    f.write(f"\n===== {name} gestartet {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    f.flush()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}  # Logs sofort sichtbar (kein Puffer)
    p = subprocess.Popen(COMPONENTS[name], cwd=str(ROOT), creationflags=_NO_WINDOW,
                         stdout=f, stderr=subprocess.STDOUT, env=env)
    p.kira_launched = time.time()  # echte Startzeit -> Waisen-Check gegen PID-Wiederverwendung
    return p


def _children_file() -> Path:
    return config.DATA_DIR / "supervisor_children.json"


def _marker(name: str) -> str:
    """Eindeutiges Kommandozeilen-Token eines Dienstes (fuer die Waisen-Erkennung)."""
    for a in COMPONENTS[name]:
        if a.startswith("core."):
            return a
    return COMPONENTS[name][-1]


def _record_children(procs: dict[str, subprocess.Popen]) -> None:
    """Kinder-PIDs festhalten (data/supervisor_children.json): stirbt der Supervisor hart
    (PC-Absturz, Kill), findet der naechste Start die Waisen darueber wieder und beendet
    sie, statt Duplikate danebenzustellen."""
    try:
        reg = {n: {"pid": p.pid, "marker": _marker(n),
                   "ts": getattr(p, "kira_launched", None) or time.time()}
               for n, p in procs.items()}
        f = _children_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(reg), encoding="utf-8")
    except Exception:  # noqa: BLE001 — Registry ist Best-Effort, darf den Betrieb nie brechen
        pass


def _adopt_orphans() -> None:
    """Waisen frueherer Supervisor-Laeufe uebernehmen = beenden. Ohne das laufen alter und
    neuer Bot/Runner parallel: zwei getUpdates-Poller klauen sich die Nachrichten
    (Telegram-409), Crons feuern doppelt, mehrere Cockpits halten Modelle im Speicher.
    Fremde Prozesse (PID-Wiederverwendung) bleiben unangetastet (looks_like_ours)."""
    f = _children_file()
    try:
        reg = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — keine/kaputte Registry -> nichts zu uebernehmen
        reg = {}
    for name, ent in (reg or {}).items():
        ent = ent or {}
        try:
            pid = int(ent.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid == os.getpid() or not instance_lock.pid_alive(pid):
            continue
        if not instance_lock.looks_like_ours(pid, ent.get("marker"), ent.get("ts")):
            print(f"[supervisor] PID {pid} ('{name}') lebt, passt aber nicht zum Protokoll "
                  "-> bleibt unangetastet (PID-Wiederverwendung?).")
            continue
        ok = instance_lock.terminate(pid)
        print(f"[supervisor] Waise '{name}' (PID {pid}) aus frueherem Lauf "
              + ("uebernommen und beendet." if ok else "NICHT beendet — bitte manuell pruefen."))
        try:
            events.emit("orphan_child_terminated", {"service": name, "pid": pid, "ok": ok})
        except Exception:  # noqa: BLE001
            pass
    try:
        f.unlink(missing_ok=True)  # die frischen Kinder werden gleich neu eingetragen
    except Exception:  # noqa: BLE001
        pass


def _log_tail(name: str, lines: int = 12) -> str:
    """Letzte Zeilen des Dienst-Logs (fuer die Crash-Diagnose im Dashboard)."""
    try:
        text = (ROOT / "data" / "logs" / f"{name}.log").read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:  # noqa: BLE001
        return ""


def main() -> None:
    # Worktree-Vorfall 18./19.07.: der Autostart-LNK zeigte in einen Worktree — dort
    # bootete eine Alt-Kira. Erst loggen, WELCHER Checkout hier laeuft, dann das Veto.
    print("[supervisor] ROOT:", ROOT)
    veto = config.dienststart_verweigert()
    if veto:
        print(veto)
        return

    lock = instance_lock.acquire("supervisor")
    if lock is None:
        print(instance_lock.blocked_msg("supervisor", "Ein Kira-Supervisor"))
        return
    # 'lock' bleibt als lokale Variable offen -> haelt den Singleton fuer die Lebenszeit des Supervisors

    _adopt_orphans()  # Waisen eines frueheren Laufs beenden, BEVOR frische Kinder starten

    RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
    if RESTART_FLAG.exists():
        RESTART_FLAG.unlink()

    procs: dict[str, subprocess.Popen] = {}
    crashes: dict[str, list[float]] = {n: [] for n in COMPONENTS}   # Absturz-Zeitpunkte je Dienst
    next_ok: dict[str, float] = {n: 0.0 for n in COMPONENTS}        # frueheste Neustart-Zeit (Backoff)
    alerted: set[str] = set()                                       # schon per Telegram gewarnt?
    for name in COMPONENTS:
        procs[name] = _launch(name)
        _record_children(procs)  # nach JEDEM Start sofort festhalten (Absturz-Fenster klein halten)
        time.sleep(1)  # Cockpit zuerst -> Port belegen, bevor andere starten
    print("Supervisor laeuft. Bewacht:", ", ".join(COMPONENTS))

    while True:
        try:
            time.sleep(5)
            now = time.time()

            # 1) Tote Komponenten neu starten — mit Absturz-Bremse gegen Crash-Loops
            for name, p in list(procs.items()):
                if p.poll() is None:
                    # Laeuft wieder stabil (letzter Absturz laenger als ein Fenster her)? -> Zaehler leeren
                    if crashes[name] and now - crashes[name][-1] > _CRASH_WINDOW:
                        crashes[name].clear()
                        alerted.discard(name)
                    continue
                if now < next_ok[name]:
                    continue  # noch im Backoff/Krisen-Cooldown -> diesmal NICHT neustarten
                code = p.returncode
                tail = _log_tail(name)
                crashes[name].append(now)
                crashes[name] = [t for t in crashes[name] if now - t <= _CRASH_WINDOW]
                recent = len(crashes[name])
                try:
                    events.emit("service_crash",
                                {"service": name, "exit_code": code, "tail": tail, "recent": recent})
                except Exception:  # noqa: BLE001
                    pass
                relaunch, wait_s, crisis = _backoff_plan(recent)
                next_ok[name] = now + wait_s
                if crisis:
                    print(f"[supervisor] {name}: {recent} Abstuerze in 5 Min -> Krisen-Cooldown "
                          f"{int(wait_s)}s (kein Neustart)")
                    if name not in alerted:
                        alerted.add(name)
                        _alert(f"⚠ Kira-Dienst '{name}' stuerzt dauernd ab "
                               f"({recent}× in 5 Min). Pausiert fuer 5 Min. Letzte Zeilen:\n{tail[-800:]}")
                    continue
                print(f"[supervisor] {name} gestorben (code {code}) -> Neustart in Kuerze "
                      f"(Absturz {recent}, naechster Versuch fruehestens +{int(wait_s)}s)")
                if relaunch:
                    procs[name] = _launch(name)
                    _record_children(procs)

            # 1b) Herzschlag fuers Dashboard: welche Dienste leben gerade?
            try:
                alive = {n: (pp.poll() is None) for n, pp in procs.items()}
                (ROOT / "data" / "services.json").write_text(
                    json.dumps({"ts": time.time(), "services": alive}, ensure_ascii=False),
                    encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

            # 2) Restart-Flag (z.B. nach self_edit): sicherer Bounce der genannten Dienste
            if RESTART_FLAG.exists():
                try:
                    # utf-8-sig: schluckt ein BOM (PowerShell 5.1 schreibt utf8 MIT BOM ->
                    # '﻿all' matchte sonst kein Ziel und der Bounce lief ins Leere).
                    want = RESTART_FLAG.read_text(encoding="utf-8-sig").strip().lower()
                    RESTART_FLAG.unlink()
                except Exception:  # noqa: BLE001
                    want = "all"
                targets = (list(COMPONENTS) if want in ("", "all")
                           else [w.strip() for w in want.split(",") if w.strip() in COMPONENTS])
                time.sleep(20)  # laufende Antwort fertig + Bericht senden lassen, dann erst bouncen
                for name in targets:
                    try:
                        procs[name].terminate()
                    except Exception:  # noqa: BLE001
                        pass
                time.sleep(2)
                for name in targets:
                    procs[name] = _launch(name)
                _record_children(procs)
                print("[supervisor] Bounce per Flag:", targets)
        except KeyboardInterrupt:
            print("\nSupervisor gestoppt.")
            break
        except Exception as e:  # noqa: BLE001
            print("[supervisor] Fehler:", e)
            time.sleep(5)
    lock.release()  # sauberer Stopp: Lock-Datei aufraeumen (den Socket schliesst das OS ohnehin)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
