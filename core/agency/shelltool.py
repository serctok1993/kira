"""Sichere Shell-/Code-Ausfuehrung fuer Kira — der Schritt vom Code-Schreiber zum
selbst-verifizierenden Entwickler: Befehle/Tests laufen lassen, Ausgabe lesen, sich
selbst korrigieren.

Sicherungen:
- Not-Aus (Kill-Switch) wird respektiert.
- Projekt-Sandbox: Arbeitsverzeichnis bleibt im Repo (ROOT), kein cwd ausserhalb.
- Timeout (Standard 60 s, hart begrenzt).
- Gefahren-Filter gegen klar zerstoererische Befehle (rm -rf /, format, dd, fork-bomb, …).
- Audit: jeder Lauf wird protokolliert (Befehl, Exit-Code).
Die echten Sicherheitsnetze bleiben Kill-Switch + Git (alles rueckrollbar).
"""
from __future__ import annotations

import re
import subprocess

from core.config import ROOT
from core.governance import audit
from core.kernel import events
from core.kernel.scheduler import kill_switch_active

_BLOCKED = [
    r"rm\s+-rf\s+(/|~|\*)",          # Root/Home/alles loeschen
    r":\s*\(\s*\)\s*\{",             # Fork-Bomb
    r"\bmkfs\b", r"\bdd\s+if=",      # Dateisysteme/Datentraeger ueberschreiben
    r"\bformat\s+[a-z]:",            # Windows-Laufwerk formatieren
    r"\b(del|erase)\s+/[sq]",        # rekursives Loeschen (cmd)
    r"\b(rd|rmdir)\s+/s",            # Verzeichnisbaum loeschen (cmd)
    r"Remove-Item.*-Recurse.*[A-Za-z]:\\\s*['\"]?\s*$",  # PS: Laufwerk-Root rekursiv
    r"\b(shutdown|reboot)\b",        # System runterfahren/neustarten
    r"\bdiskpart\b", r">\s*/dev/sd",  # Datentraeger
    r"\|\s*(sh|bash|iex)\b", r"iex\s*\(",  # Pipe-to-Shell aus dem Netz
]


def _is_dangerous(cmd: str) -> bool:
    return any(re.search(p, cmd, re.IGNORECASE) for p in _BLOCKED)


def run_shell(command: str, cwd: str | None = None, timeout: int = 60) -> str:
    command = (command or "").strip()
    if not command:
        return "(kein Befehl)"
    if kill_switch_active():
        return "Not-Aus ist aktiv — ich fuehre gerade nichts aus."
    if _is_dangerous(command):
        events.emit("shell_blocked", {"command": command[:200]})
        return "Blockiert: dieser Befehl wirkt potenziell zerstoererisch. Ausfuehrung verweigert."

    base = str(ROOT)
    wd = ROOT
    if cwd:
        cand = (ROOT / cwd).resolve()
        if not str(cand).startswith(base):
            return f"Arbeitsverzeichnis ausserhalb des Projekts ist nicht erlaubt: {cwd}"
        wd = cand

    try:
        timeout = max(1, min(int(timeout or 60), 600))
    except Exception:  # noqa: BLE001
        timeout = 60

    try:
        p = subprocess.run(
            command, shell=True, cwd=str(wd), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        events.emit("shell_timeout", {"command": command[:200], "timeout": timeout})
        return f"Timeout nach {timeout}s — Befehl abgebrochen."
    except Exception as e:  # noqa: BLE001
        return f"Fehler beim Ausfuehren: {e}"

    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    audit.record("shell", target=command[:120], details={"cwd": str(wd), "exit": p.returncode})
    events.emit("shell_run", {"command": command[:200], "exit": p.returncode}, session_id=None)

    body = out
    if err:
        body += ("\n[stderr]\n" + err) if body else ("[stderr]\n" + err)
    body = body[:3000] or "(keine Ausgabe)"
    return f"[exit {p.returncode}]\n{body}"
