"""Instanz-Lock: genau EIN Prozess pro Dienst (Supervisor, Telegram-Bot).

Beobachtet 12.-14.07.2026: Autostart + manueller Start + Dev-Preview starteten Dienste
DOPPELT (zwei Bots klauten sich per getUpdates gegenseitig die Nachrichten, zwei Runner
feuerten Crons zweimal; nach einem PC-Absturz sogar vierfach). Der Lock hier ist ein
Loopback-Port-Bind: atomar (kein Check-then-Act-Race) und das OS raeumt ihn beim
Prozesstod von selbst weg — kein Stale-File nach einem harten Absturz. Zusaetzlich
liegt eine Lock-Datei (data/<name>.lock) mit PID daneben, damit die Meldung des
zweiten Starts sagen kann, WER schon laeuft.

Dazu die Werkzeuge fuer die Waisen-Uebernahme des Supervisors: pid_alive /
looks_like_ours / terminate — mit Schutz gegen PID-Wiederverwendung (im Zweifel wird
NIE ein fremder Prozess beendet).
"""
from __future__ import annotations

import json
import os
import signal
import socket
import time
from pathlib import Path

from core import config

# Feste Loopback-Ports NUR als Singleton-Lock (niemand spricht inhaltlich darauf).
LOCK_PORTS = {"supervisor": 8009, "telegram_bot": 8010}


def _lock_file(name: str) -> Path:
    return config.DATA_DIR / f"{name}.lock"


class InstanceLock:
    """Haelt den Lock (offener Loopback-Socket) fuer die Lebenszeit des Prozesses."""

    def __init__(self, name: str, sock: socket.socket) -> None:
        self.name = name
        self._sock = sock

    def release(self) -> None:
        try:
            self._sock.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            _lock_file(self.name).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def acquire(name: str, port: int | None = None) -> InstanceLock | None:
    """Exklusiver Singleton-Lock OHNE Race: bindet SOFORT einen Loopback-Port und haelt
    ihn offen. Ein zweiter Prozess scheitert am bind -> None (der Aufrufer beendet sich
    mit klarer Meldung, siehe blocked_msg). Die Lock-Datei mit PID ist reine Diagnose —
    die Wahrheit ist der Socket, und der stirbt garantiert mit dem Prozess."""
    port = port or LOCK_PORTS[name]
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
    except OSError:
        s.close()
        return None
    try:
        f = _lock_file(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"pid": os.getpid(), "port": port, "started": time.time()}),
                     encoding="utf-8")
    except Exception:  # noqa: BLE001 — Datei ist nur Diagnose, der Socket ist der Lock
        pass
    return InstanceLock(name, s)


def holder(name: str) -> dict | None:
    """Wer haelt den Lock laut Lock-Datei? {'pid': …, 'alive': …} oder None."""
    try:
        d = json.loads(_lock_file(name).read_text(encoding="utf-8"))
        d["alive"] = pid_alive(int(d.get("pid") or 0))
        return d
    except Exception:  # noqa: BLE001
        return None


def blocked_msg(name: str, label: str) -> str:
    """Klare Meldung fuer den zweiten Start: wer laeuft schon, warum beenden wir uns."""
    h = holder(name)
    wer = (f"PID {h['pid']}" if h and h.get("alive")
           else f"unbekannter Prozess haelt Lock-Port {LOCK_PORTS.get(name, '?')}")
    return f"{label} laeuft bereits ({wer}) -> dieser Start beendet sich sauber, statt zu duplizieren."


# ---- Prozess-Werkzeuge (Waisen-Uebernahme) ----------------------------------------

_K32 = None  # kernel32 mit gesetzten Signaturen (einmal konfiguriert, dann gecacht)


def _k32():
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        k.GetProcessTimes.restype = wintypes.BOOL
        k.GetProcessTimes.argtypes = (
            wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
        _K32 = k
    return _K32


def pid_alive(pid: int) -> bool:
    """Lebt der Prozess? Windows via OpenProcess/WaitForSingleObject — bewusst KEIN
    os.kill(pid, 0): das ruft auf Windows TerminateProcess und wuerde den Prozess KILLEN.
    POSIX via Signal 0 (ESRCH = tot, EPERM = lebt, gehoert aber jemand anderem)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        k = _k32()
        PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE = 0x1000, 0x00100000
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not h:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: existiert (fremder Nutzer)
        try:
            WAIT_TIMEOUT = 0x102
            return k.WaitForSingleObject(h, 0) == WAIT_TIMEOUT  # nicht signalisiert = laeuft noch
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _win_info(pid: int) -> tuple[str | None, float | None]:
    """(exe-Pfad, Startzeit als Unix-Sekunden) eines Prozesses — nur Windows, best effort."""
    import ctypes
    from ctypes import wintypes

    k = _k32()
    h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None, None
    try:
        exe = None
        buf = ctypes.create_unicode_buffer(4096)
        size = wintypes.DWORD(4096)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            exe = buf.value
        started = None
        ftc, fte, ftk, ftu = (wintypes.FILETIME() for _ in range(4))
        if k.GetProcessTimes(h, ctypes.byref(ftc), ctypes.byref(fte),
                             ctypes.byref(ftk), ctypes.byref(ftu)):
            ticks = (ftc.dwHighDateTime << 32) | ftc.dwLowDateTime
            started = ticks / 1e7 - 11644473600.0  # FILETIME (seit 1601) -> Unix-Epoche
        return exe, started
    finally:
        k.CloseHandle(h)


def looks_like_ours(pid: int, marker: str | None, recorded_ts: float | None = None) -> bool:
    """Schutz gegen PID-Wiederverwendung: nur dann 'unser Kind', wenn der lebende Prozess
    zum Protokoll passt. Linux: der Marker (Modulpfad) muss in /proc/<pid>/cmdline stehen.
    Windows (kein billiger cmdline-Zugriff): exe muss ein Python sein UND die echte
    Prozess-Startzeit zur protokollierten passen (±90s). Im Zweifel False — es wird NIE
    blind ein fremder Prozess beendet."""
    if not pid_alive(pid):
        return False
    if os.name == "nt":
        exe, started = _win_info(int(pid))
        if not exe or "python" not in os.path.basename(exe).lower():
            return False
        if recorded_ts is not None and started is not None \
                and abs(started - float(recorded_ts)) > 90:
            return False
        return True
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\x00", b" ")
        cmdline = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — kein /proc (macOS o.ae.) -> lieber nicht anfassen
        return False
    return bool(marker) and marker in cmdline


def terminate(pid: int, grace: float = 4.0) -> bool:
    """Prozess beenden: TERM (Windows: TerminateProcess), kurz nachpruefen, POSIX
    eskaliert danach auf KILL. True = der Prozess ist weg."""
    pid = int(pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except Exception:  # noqa: BLE001
        return not pid_alive(pid)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.15)
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    return not pid_alive(pid)
