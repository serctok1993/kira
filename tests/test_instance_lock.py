"""Instanz-Lock + Waisen-Uebernahme: Dienste duerfen nie doppelt laufen.

Hintergrund (12.-14.07.2026): Autostart + manueller Start + Dev-Preview starteten
Supervisor/Bot/Runner doppelt (nach PC-Absturz vierfach) — zwei Bots klauten sich per
getUpdates die Nachrichten, Crons feuerten doppelt. Hier abgesichert:
1. Zweiter Lock-Erwerb scheitert; Meldung nennt die haltende PID.
2. pid_alive ist auf Windows KEIN os.kill(pid, 0) (das wuerde toeten) und stimmt.
3. Waisen-Uebernahme beendet eigene Alt-Kinder, laesst fremde Prozesse in Ruhe.
4. Supervisor und Telegram-Bot beenden sich beim zweiten Start sauber, ohne zu starten.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn_marked(marker: str) -> subprocess.Popen:
    """Harmloser Schlaefer-Prozess mit Marker in der Kommandozeile (wie ein Dienst-Kind)."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", marker],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- 1) Lock-Mechanik ---------------------------------------------------------------
def test_zweiter_lock_scheitert_und_release_gibt_frei(tmp_path, monkeypatch):
    from core import config
    from core.kernel import instance_lock as il

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    port = _free_port()
    l1 = il.acquire("supervisor", port=port)
    assert l1 is not None
    assert il.acquire("supervisor", port=port) is None  # zweiter Start -> abgewiesen

    h = il.holder("supervisor")
    assert h and h["pid"] == os.getpid() and h["alive"] is True

    l1.release()
    assert not (tmp_path / "supervisor.lock").exists()
    l2 = il.acquire("supervisor", port=port)  # nach Freigabe klappt es wieder
    assert l2 is not None
    l2.release()


def test_blocked_msg_nennt_lebende_pid(tmp_path, monkeypatch):
    from core import config
    from core.kernel import instance_lock as il

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    lock = il.acquire("telegram_bot", port=_free_port())
    try:
        msg = il.blocked_msg("telegram_bot", "Ein Telegram-Bot")
        assert str(os.getpid()) in msg
        assert "beendet sich sauber" in msg
    finally:
        lock.release()


def test_lock_ports_pro_dienst_verschieden():
    from core.kernel import instance_lock as il

    assert {"supervisor", "telegram_bot"} <= set(il.LOCK_PORTS)
    assert len(set(il.LOCK_PORTS.values())) == len(il.LOCK_PORTS)


# --- 2) pid_alive (Windows-sicher, ohne Kill-Nebenwirkung) ---------------------------
def test_pid_alive_lebend_und_tot():
    from core.kernel import instance_lock as il

    assert il.pid_alive(os.getpid()) is True
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=30)
    assert il.pid_alive(p.pid) is False
    assert il.pid_alive(0) is False and il.pid_alive(-5) is False
    assert il.pid_alive(None) is False  # kaputte Registry-Eintraege reissen nichts


def test_pid_alive_toetet_nicht():
    """Der historische Fallstrick: os.kill(pid, 0) beendet auf Windows den Prozess.
    pid_alive darf nur SCHAUEN — der Prozess muss danach noch leben."""
    from core.kernel import instance_lock as il

    p = _spawn_marked("nur.gucken.nicht.anfassen")
    try:
        assert il.pid_alive(p.pid) is True
        time.sleep(0.3)
        assert p.poll() is None  # lebt immer noch
    finally:
        p.kill()


# --- 3) Waisen-Uebernahme des Supervisors --------------------------------------------
def test_adopt_orphans_beendet_eigene_waise(tmp_path, monkeypatch):
    from core import config
    from core.kernel import supervisor as sv

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    p = _spawn_marked("core.agency.missions.runner")
    try:
        (tmp_path / "supervisor_children.json").write_text(json.dumps(
            {"runner": {"pid": p.pid, "marker": "core.agency.missions.runner",
                        "ts": time.time()}}), encoding="utf-8")
        sv._adopt_orphans()
        p.wait(timeout=10)  # Waise wurde uebernommen = beendet (sonst TimeoutExpired)
        assert not (tmp_path / "supervisor_children.json").exists()  # Registry geleert
    finally:
        if p.poll() is None:
            p.kill()


def test_adopt_orphans_verschont_fremde_prozesse(tmp_path, monkeypatch):
    """PID-Wiederverwendung: lebender Prozess passt nicht zum Protokoll (falscher Marker,
    Startzeit meilenweit daneben) -> er bleibt unangetastet."""
    from core import config
    from core.kernel import supervisor as sv

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    p = _spawn_marked("definitiv.nicht.unser.dienst")
    try:
        (tmp_path / "supervisor_children.json").write_text(json.dumps(
            {"runner": {"pid": p.pid, "marker": "core.agency.missions.runner",
                        "ts": time.time() - 99999}}), encoding="utf-8")
        sv._adopt_orphans()
        time.sleep(0.5)
        assert p.poll() is None  # lebt noch — fremd wird NIE beendet
    finally:
        p.kill()


def test_adopt_orphans_ignoriert_tote_und_kaputte_eintraege(tmp_path, monkeypatch):
    from core import config
    from core.kernel import supervisor as sv

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=30)
    (tmp_path / "supervisor_children.json").write_text(json.dumps({
        "runner": {"pid": dead.pid, "marker": "core.agency.missions.runner", "ts": time.time()},
        "bot": {"pid": "quatsch", "marker": None, "ts": None},
        "cockpit": None,
    }), encoding="utf-8")
    sv._adopt_orphans()  # darf nicht raisen
    assert not (tmp_path / "supervisor_children.json").exists()


def test_record_children_schreibt_registry(tmp_path, monkeypatch):
    from core import config
    from core.kernel import supervisor as sv

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    class P:  # Popen-Attrappe
        def __init__(self, pid):
            self.pid = pid
            self.kira_launched = 123.0

    sv._record_children({"bot": P(4711), "runner": P(4712)})
    reg = json.loads((tmp_path / "supervisor_children.json").read_text(encoding="utf-8"))
    assert reg["bot"]["pid"] == 4711
    assert reg["bot"]["marker"] == "core.agency.connectors.telegram_bot"
    assert reg["runner"]["marker"] == "core.agency.missions.runner"
    assert reg["bot"]["ts"] == 123.0


def test_marker_je_dienst_eindeutig():
    from core.kernel import supervisor as sv

    assert sv._marker("cockpit") == "core.api.server:app"
    assert sv._marker("bot") == "core.agency.connectors.telegram_bot"
    assert sv._marker("runner") == "core.agency.missions.runner"


# --- 4) Zweiter Start beendet sich sauber (Supervisor + Bot) --------------------------
def test_supervisor_zweiter_start_beendet_sich(monkeypatch, capsys):
    from core.kernel import instance_lock as il
    from core.kernel import supervisor as sv

    launches: list[str] = []
    monkeypatch.setattr(sv, "_launch", lambda name: launches.append(name))
    monkeypatch.setattr(il, "acquire", lambda name, port=None: None)
    sv.main()  # muss SOFORT zurueckkehren, ohne irgendetwas zu starten
    assert launches == []
    assert "laeuft bereits" in capsys.readouterr().out


def test_bot_zweiter_start_beendet_sich(monkeypatch, capsys):
    from core.agency.connectors import telegram_bot as tb
    from core.kernel import instance_lock as il

    monkeypatch.setattr(il, "acquire", lambda name, port=None: None)
    tb.run()  # muss SOFORT zurueckkehren (kein getUpdates-Poll, kein Token-Schlaf)
    assert "laeuft bereits" in capsys.readouterr().out
