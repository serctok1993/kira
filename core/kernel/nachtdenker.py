"""Nachtdenker: GPU-Zeitteilung fuer ein grosses lokales Modell (llama.cpp-Server).

Tagsueber gehoert die GPU den kleinen Ollama-Modellen, nachts einem grossen
Modell hinter einem OpenAI-kompatiblen Endpunkt (z.B. llama.cpp-Server). Beide
zusammen passen nicht in den VRAM — deshalb ein ZEITFENSTER statt Nebeneinander.

Der Tick laeuft im Runner-Immer-Block (24/7, auch bei Heartbeat AUS; der
Not-Aus pausiert ihn wie alles andere) und ist ein kleiner Zustandsautomat:

  aus ── Fensterbeginn ──> startend   Server-Prozess gespawnt, Health ausstehend
  startend ── /models ok ──> aktiv    Rollen-Schnappschuss -> Rollen auf den
                                      Provider-Alias, Ollama-Modelle entladen
  aktiv ── Fensterende ──> aus        Rollen zurueck, Server-Prozessbaum beendet
  aktiv ── Prozess tot ──> startend   begrenzte Neustarts (max 3 pro Fenster),
                                      danach fehler + Rollen zurueck

Werkszustand: enabled=false (config.yaml, Abschnitt nachtdenker). Zustand liegt
in data/nachtdenker.json. Sicherheitsregel gegen PID-Wiederverwendung: nach
einem Reboot wird eine fremde PID NIE blind gekillt — der Prozessbaum faellt
nur, wenn der eigene Endpunkt antwortet ODER die PID nachweislich aus dieser
Boot-Sitzung stammt.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import signal
import subprocess
import time

import httpx

from core.config import CONFIG, DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write
from core.kernel.instance_lock import pid_alive

_STATE_FILE = DATA_DIR / "nachtdenker.json"
_LOG_FILE = DATA_DIR / "logs" / "nachtdenker.log"
_START_TIMEOUT_S = 240   # GGUF-Load braucht Zeit; danach gilt der Start als gescheitert
_MAX_NEUSTARTS = 3


def _cfg() -> dict:
    return CONFIG.get("nachtdenker") or {}


def _state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8")) if _STATE_FILE.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _merken(st: dict) -> None:
    try:
        atomic_write(_STATE_FILE, json.dumps(st, ensure_ascii=False, indent=1))
    except Exception:  # noqa: BLE001
        pass


def fenster_aktiv(now: _dt.datetime | None = None) -> bool:
    """True innerhalb des konfigurierten Fensters. start > ende = ueber Mitternacht
    (23:30-07:30); start == ende oder unparsebar = kein Fenster."""
    cfg = _cfg()
    try:
        s_h, s_m = (int(x) for x in str(cfg.get("start", "")).strip().split(":"))
        e_h, e_m = (int(x) for x in str(cfg.get("ende", "")).strip().split(":"))
    except (ValueError, AttributeError):
        return False
    start, ende = s_h * 60 + s_m, e_h * 60 + e_m
    if start == ende:
        return False
    t = now or _dt.datetime.now()
    minute = t.hour * 60 + t.minute
    if start < ende:
        return start <= minute < ende
    return minute >= start or minute < ende   # Fenster ueber Mitternacht


def _health() -> bool:
    base = str(_cfg().get("endpunkt") or "").rstrip("/")
    if not base:
        return False
    try:
        return httpx.get(base + "/models", timeout=3).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _boot_ts() -> float:
    """Zeitpunkt des letzten System-Boots — PIDs aus frueheren Boot-Sitzungen
    gelten als wiederverwendet und werden nie gekillt."""
    try:
        if os.name == "nt":
            import ctypes
            return time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000.0
        with open("/proc/uptime", encoding="ascii") as f:
            return time.time() - float(f.read().split()[0])
    except Exception:  # noqa: BLE001
        return 0.0


def _server_starten() -> int | None:
    cmd = str(_cfg().get("server_cmd") or "").strip()
    if not cmd:
        return None
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(_LOG_FILE, "ab")  # noqa: SIM115 — Handle gehoert dem Kindprozess
    log.write(f"\n--- Nachtdenker-Start {time.strftime('%d.%m.%Y %H:%M:%S')} ---\n".encode())
    if os.name == "nt":
        p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        p = subprocess.Popen(shlex.split(cmd), stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    return p.pid


def _server_beenden(pid: int) -> None:
    """Beendet den PROZESSBAUM (server_cmd spawnt i.d.R. Kinder: powershell ->
    llama-server) — instance_lock.terminate wuerde nur die Wurzel treffen."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        else:
            os.killpg(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and pid_alive(pid):
                time.sleep(0.2)
            if pid_alive(pid):
                os.killpg(pid, signal.SIGKILL)
    except Exception:  # noqa: BLE001
        pass


def _ollama_entladen() -> None:
    """VRAM freigeben: alles, was Ollama gerade warm haelt, mit keep_alive=0 entladen
    (best effort — ein toter Ollama-Dienst ist hier kein Fehler)."""
    try:
        geladen = httpx.get("http://localhost:11434/api/ps", timeout=5).json().get("models", [])
        for m in geladen:
            try:
                httpx.post("http://localhost:11434/api/generate",
                           json={"model": m.get("name"), "keep_alive": 0}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _aktivieren(st: dict) -> None:
    """Health ist da: Provider sicherstellen, Rollen-Schnappschuss ziehen und die
    konfigurierten Rollen auf den Nachtdenker legen; Ollama raeumt den VRAM."""
    from core.kernel import models
    cfg = _cfg()
    alias = str(cfg.get("provider") or "nachtdenker")
    if alias not in (CONFIG["models"].get("providers") or {}):
        models.add_provider(alias, str(cfg.get("modell") or "openai/nachtdenker"),
                            str(cfg.get("endpunkt") or ""), "")
    rollen = [str(r) for r in (cfg.get("rollen") or ["reason", "worker", "bulk"])]
    if not st.get("rollen_snapshot"):
        # nur beim ERSTEN Aktivieren schnappschiessen — bei einem Neustart mitten im
        # Fenster zeigen die Rollen schon auf den Alias, der wuerde sonst "vorher"
        vorher = models.roles()
        st["rollen_snapshot"] = {r: vorher.get(r) for r in rollen}
    for r in rollen:
        models.set_role(r, alias)
    _ollama_entladen()
    st["phase"] = "aktiv"
    _merken(st)
    events.emit("nachtdenker_start", {"pid": st.get("pid"), "alias": alias, "rollen": rollen})


def _abschalten(st: dict, grund: str) -> None:
    """Fensterende/Deaktivierung: Rollen zurueck, Server-Prozessbaum beenden."""
    from core.kernel import models
    for r, mid in (st.get("rollen_snapshot") or {}).items():
        if mid:
            try:
                models.set_role(r, mid)
            except Exception:  # noqa: BLE001
                pass
    pid = st.get("pid")
    if pid:
        if _health() or (pid_alive(pid) and float(st.get("gestartet") or 0) > _boot_ts()):
            _server_beenden(pid)
        elif pid_alive(pid):
            # PID lebt, aber Endpunkt tot UND Start vor dem letzten Boot ->
            # sehr wahrscheinlich wiederverwendete Fremd-PID: NIE blind killen.
            events.emit("nachtdenker_pid_verwaist", {"pid": pid})
    _merken({"phase": "aus"})
    events.emit("nachtdenker_stop", {"grund": grund})


def tick(now: _dt.datetime | None = None) -> None:
    """Ein Schritt des Zustandsautomaten — billig, raist nie, laeuft im Runner-Takt."""
    try:
        cfg = _cfg()
        st = _state()
        phase = st.get("phase", "aus")
        if not cfg.get("enabled"):
            if phase in ("startend", "aktiv", "fehler"):
                _abschalten(st, "deaktiviert")
            return
        if not fenster_aktiv(now):
            if phase in ("startend", "aktiv", "fehler"):
                _abschalten(st, "fensterende")
            return

        # --- im Fenster ---
        if phase == "aktiv":
            if st.get("pid") and pid_alive(st["pid"]):
                return
            versuche = int(st.get("versuche") or 0) + 1
            if versuche > _MAX_NEUSTARTS:
                events.emit("nachtdenker_fehler",
                            {"error": f"Server {_MAX_NEUSTARTS}x gestorben — gebe fuer dieses Fenster auf."})
                _abschalten(st, "zu-viele-neustarts")
                _merken({"phase": "fehler"})
                return
            events.emit("nachtdenker_neustart", {"versuch": versuche})
            pid = _server_starten()
            if pid is None:
                _abschalten(st, "server_cmd-leer")
                _merken({"phase": "fehler"})
                return
            _merken({"phase": "startend", "pid": pid, "gestartet": time.time(),
                     "versuche": versuche, "rollen_snapshot": st.get("rollen_snapshot")})
            return
        if phase == "startend":
            if _health():
                _aktivieren(st)
            elif time.time() - float(st.get("gestartet") or 0) > _START_TIMEOUT_S:
                if st.get("pid"):
                    _server_beenden(st["pid"])
                events.emit("nachtdenker_fehler",
                            {"error": f"Endpunkt nach {_START_TIMEOUT_S}s nicht erreichbar "
                                      f"({cfg.get('endpunkt')}) — pruefe server_cmd/Port."})
                if st.get("rollen_snapshot"):
                    _abschalten(st, "start-timeout")  # Rollen zurueck, nichts haengen lassen
                _merken({"phase": "fehler"})
            return
        if phase == "fehler":
            return  # bis Fensterende geparkt (naechste Nacht = neuer Versuch)
        # phase == "aus": Fenster beginnt -> Server zuenden
        if _health():
            # Endpunkt laeuft schon (von Hand gestartet) -> direkt uebernehmen
            st = {"phase": "startend", "pid": None, "gestartet": time.time(), "versuche": 0}
            _aktivieren(st)
            return
        pid = _server_starten()
        if pid is None:
            events.emit("nachtdenker_fehler",
                        {"error": "nachtdenker.server_cmd ist leer — trage das Start-Kommando "
                                  "deines llama.cpp-Servers ein (Einstellungen -> Nachtdenker)."})
            _merken({"phase": "fehler"})
            return
        _merken({"phase": "startend", "pid": pid, "gestartet": time.time(), "versuche": 0})
    except Exception as e:  # noqa: BLE001 — der Tick darf den Runner nie brechen
        try:
            events.emit("nachtdenker_fehler", {"error": str(e)[:200]})
        except Exception:  # noqa: BLE001
            pass


def status() -> dict:
    """Fuer /api/status + Cockpit-Karte: Zustand, Fenster und editierbare Felder."""
    cfg = _cfg()
    st = _state()
    return {"enabled": bool(cfg.get("enabled")),
            "phase": st.get("phase", "aus"),
            "aktiv": st.get("phase") == "aktiv",
            "start": cfg.get("start") or "",
            "ende": cfg.get("ende") or "",
            "server_cmd": cfg.get("server_cmd") or "",
            "endpunkt": cfg.get("endpunkt") or "",
            "provider": cfg.get("provider") or "nachtdenker"}
