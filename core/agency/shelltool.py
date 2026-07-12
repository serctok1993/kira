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

import os
import re
import subprocess

from core.config import ROOT

# W4b: die Shell selbst ist portabel (shell=True -> cmd.exe bzw. /bin/sh). Nur der
# Unix-Verwechslungs-Hinweis ist ein WINDOWS-Schutz — unter Linux sind head/grep/cat
# ja richtig und duerfen nie geblockt werden.
_IS_WIN = os.name == "nt"
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
    r"\b(shutdown|reboot|Restart-Computer|logoff)\b",  # System runterfahren/neustarten
    # --- KEINE Prozesse killen (auch/gerade nicht sich selbst -> Suizid-Schutz) ---
    r"\btaskkill\b", r"\btskill\b", r"\bpskill\b",     # Windows-Prozess-Killer
    r"\bStop-Process\b", r"\bStop-Service\b",          # PowerShell stoppt Prozess/Dienst
    r"\.Kill\s*\(",                                    # .NET-Methode: (Get-Process ...).Kill()
    r"\b(pkill|killall)\b", r"\bkill\s+-?\d",          # unix kill/pkill/killall
    r"wmic\s+process.*\bdelete\b",                     # wmic process ... delete
    r"\bdiskpart\b", r">\s*/dev/sd",  # Datentraeger
    r"\|\s*(sh|bash|iex)\b", r"iex\s*\(",  # Pipe-to-Shell aus dem Netz
    # --- Audit-Fund: die Shell umging ALLE Code-Schutzwaelle (write_file-Guard,
    # constitution-Sperre, self_edit-Verify+Rollback). Quellcode wird NUR ueber die
    # Werkzeuge geaendert (edit_datei/self_edit) — nie per Redirect/Set-Content/
    # destruktivem Git. data/, Logs, Desktop-Dateien bleiben frei.
    r"(>>?\s*|Set-Content\b|Out-File\b|Add-Content\b)[^|&\n]{0,120}\.(py|js|ts|ps1|bat)\b",
    r"constitution\.md",                               # Verfassung: via Shell gar nicht anfassen
    r"git\s+reset\s+--hard",                           # verwirft Arbeit/Selbst-Edits
    r"git\s+checkout\s+(--\s|\.$|\.\s|-f\b)",          # Arbeitsbaum-Verwerfen
    r"git\s+clean\s+-[a-z]*[fd]",
    r"git\s+push\s+[^|&\n]*(--force|-f\b)",            # niemals Historie ueberschreiben
]


def _is_dangerous(cmd: str) -> bool:
    return any(re.search(p, cmd, re.IGNORECASE) for p in _BLOCKED)


# Haeufige Unix/cmd-Verwechslungen auf Windows: statt kryptisch zu scheitern (und einen
# Fehl-Call-Sturm auszuloesen) sofort einen korrigierenden Hinweis geben. Nur klare Faelle.
_UNIX_ISH = re.compile(
    r"(^|\|)\s*(head|tail|grep|sed|awk|wc|less|man|cat|ls)\b"   # Unix-Tools als Kommando
    r"|(^|\s)cd\s+/[a-zA-Z]/"                                    # Unix-Mount-Pfad: cd /d/kira
    r"|2>\s*/dev/null",                                          # Unix-Null-Umleitung
    re.IGNORECASE)

_UNIX_HINT = (
    "⚠️ Windows-Shell (cmd) — keine Unix-Tools: kein head/tail/grep/cat/ls/sed/awk, "
    "kein `/d/pfad`, kein `2>/dev/null`. Nutze die WERKZEUGE statt Shell-Gewuergel:\n"
    "• Dateien lesen/auflisten → read_file / list_dir (statt cat/ls/grep)\n"
    "• Logs → read_logs\n"
    "• Events/Fehler/Kosten/DB → db_query (read-only SQL) statt Temp-Skripte\n"
    "• Wenn wirklich PowerShell: powershell -Command \"... | Select-Object -First N\" "
    "(kein head), 2>$null (kein 2>/dev/null).")


def run_shell(command: str, cwd: str | None = None, timeout: int = 60) -> str:
    command = (command or "").strip()
    if not command:
        return "(kein Befehl)"
    if kill_switch_active():
        return "Not-Aus ist aktiv — ich fuehre gerade nichts aus."
    if _is_dangerous(command):
        events.emit("shell_blocked", {"command": command[:200]})
        return "Blockiert: dieser Befehl wirkt potenziell zerstoererisch. Ausfuehrung verweigert."
    if _IS_WIN and _UNIX_ISH.search(command):  # Unix-Verwechslung (nur Windows) -> sofort korrigieren
        events.emit("shell_hint", {"command": command[:200]})
        return _UNIX_HINT

    # erlaubte Arbeitsverzeichnisse: ihr Repo + Desktop (fuer Kundenprojekte) - Gefahren-Filter bleibt
    allowed = (str(ROOT), str(ROOT.home() / "Desktop"))
    wd = ROOT
    if cwd:
        cand = (ROOT / cwd).resolve()
        if not any(str(cand).startswith(b) for b in allowed):
            return f"Arbeitsverzeichnis nur im Repo oder auf dem Desktop erlaubt: {cwd}"
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
