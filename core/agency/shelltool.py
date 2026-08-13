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

from pathlib import Path

from core.config import ROOT, CONFIG

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


# --- Kern-Schreibwache (Worktree-Vorfall 18./19.07.) --------------------------------
# Eine autonome Mission umging den selfdev-Verify-Rollback: nach selfdev_verify_failed
# schrieb sie data/_fix_v.py und patzte damit core/agency/verifier.py per run_command
# DIREKT — im Worktree UND im Hauptrepo. Deshalb: (1) Kommandos, die selbst einen
# core/-Pfad schreiben wollen, sind zu; (2) referenzierte Hilfsskripte AUSSERHALB von
# core/tests/scripts (Ad-hoc-Skripte in data/, Desktop, ...) werden vor dem Lauf
# gelesen — nennt eines einen core/-Pfad UND schreibt es Dateien, wird der Lauf
# verweigert. Lesen/py_compile/pytest auf core bleibt frei.
_CORE_PFAD = re.compile(r"\bcore[\\/](?:\w|[\\/.-])+", re.IGNORECASE)
_SCHREIBT = re.compile(
    r"write_text|write_bytes|open\s*\([^)]{0,200}['\"][wax]b?['\"]"
    r"|Set-Content|Out-File|Add-Content|shutil\.(?:copy\w*|move)"
    r"|os\.(?:replace|rename|remove|unlink)", re.IGNORECASE)
_SKRIPT_TOKEN = re.compile(r"[^\s\"';|&<>]+\.(?:py|ps1|bat|cmd|sh)\b", re.IGNORECASE)
_CORE_WACHE_TEXT = (
    "Blockiert: {was} schreibt in core/** — das umgeht den Verify. Kern-Aenderungen "
    "laufen NUR ueber edit_datei/self_edit (mit Verify + Rollback). Verify rot? "
    "STOPP und Strategie wechseln — nie am Pruefer vorbei.")


def _core_wache(command: str, wd) -> str | None:
    """Verweigerungs-Text, wenn das Kommando oder ein referenziertes Hilfsskript in
    core/** schreiben will — sonst None."""
    if _CORE_PFAD.search(command) and _SCHREIBT.search(command):
        return _CORE_WACHE_TEXT.format(was="dieses Kommando")
    eigen = Path(ROOT).resolve()
    for m in _SKRIPT_TOKEN.finditer(command):
        tok = m.group(0)
        try:
            p = Path(tok)
            if not p.is_absolute():
                p = Path(wd) / tok
            p = p.resolve()
            if not p.is_file() or p.stat().st_size > 262144:
                continue
            if any(p.is_relative_to(eigen / d) for d in ("core", "tests", "scripts")):
                continue  # eingecheckter, gepruefter Code — kein Ad-hoc-Skript
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _CORE_PFAD.search(text) and _SCHREIBT.search(text):
            return _CORE_WACHE_TEXT.format(was=f"das Skript {tok}")
    return None


# --- Sudo-Wache (13.08.2026, Serges Auftrag: Kira darf System-Pflege) -----------
# Enge Allowlist, deckungsgleich mit /etc/sudoers.d/kira-agent (~/local/kira-sudo/):
# Updates, Paket-Installation (validierter Wrapper), Hardware-Info, System-Logs.
# ALLES andere mit sudo wird nicht ausgefuehrt, sondern an Serge verwiesen —
# Kira fuehrt LLM-generierte Befehle aus, Root-Blanko waere ein Scheunentor.
_SUDO_RE = re.compile(r"(^|[;&|]\s*)sudo\b")
_SUDO_KETTE = re.compile(r"[;&|`]|\$\(")
_SUDO_ALLOW = (
    re.compile(r"^sudo\s+(/usr/bin/)?apt-get\s+update\s*$"),
    re.compile(r"^sudo\s+(/usr/bin/)?apt-get\s+upgrade\s+-y\s*$"),
    re.compile(r"^sudo\s+(/usr/local/bin/)?kira-apt-install(\s+[a-z0-9][a-z0-9.+-]*)+\s*$"),
    re.compile(r"^sudo\s+(/usr/sbin/)?dmidecode(\s+-t\s+[\w,]+)?\s*$"),
    re.compile(r"^sudo\s+(/usr/bin/)?journalctl(\s+[-\w=./:@ ]*)?$"),
)


def _sudo_wache(command: str) -> str | None:
    """None = darf laufen. Sonst: Erklaerung statt Ausfuehrung."""
    if not _SUDO_RE.search(command):
        return None
    if _SUDO_KETTE.search(command):
        return ("Blockiert: sudo in Befehlsketten (;, &&, |, Subshells) fuehre ich nicht aus. "
                "Bitte als EINZELNEN Befehl aus meiner Allowlist formulieren.")
    if any(rx.match(command.strip()) for rx in _SUDO_ALLOW):
        return None
    return ("Dieser sudo-Befehl steht nicht auf meiner Allowlist (apt-get update/upgrade, "
            "kira-apt-install <paket>, dmidecode, journalctl). Ich fuehre ihn nicht selbst aus — "
            "sag Serge Bescheid oder lass die Allowlist erweitern (~/local/kira-sudo/).")


# --- Landlock-Sandbox (13.08.2026, geplündert aus DeepSeek-Harness native/landlock-run) ---
# Kernel-erzwungene Dateisystem-Grenze statt Regex-Hoffnung: Lesen ueberall,
# Schreiben NUR in Repo, Brain-Vault, Schreibtisch, /tmp und ~/.cache.
# Fail-open: fehlt das Binary oder der Kernel-Support, laeuft der Befehl wie bisher
# (einmaliges Event statt Dauerbremse). Sudo-Allowlist-Befehle laufen UNGEWRAPPT —
# Landlock setzt no_new_privs, darunter verweigert sudo grundsaetzlich.
_LL_BIN = Path.home() / "local/bin/landlock-run"
_LL_STATUS: dict = {}  # {'ok': bool} nach erstem Probe


def _sandbox_argv(command: str) -> list[str] | None:
    """argv-Prefix fuer die Sandbox — None, wenn ungewrappt gelaufen werden soll."""
    cfg = (CONFIG.get("agency") or {}).get("shell_sandbox", {})
    if cfg.get("enabled") is False:
        return None
    if _SUDO_RE.search(command):
        return None  # Allowlist-sudo braucht echte Privilegien
    if not _LL_STATUS:
        try:
            ok = (_LL_BIN.exists() and subprocess.run(
                [str(_LL_BIN), "--probe"], capture_output=True, text=True, timeout=5
            ).returncode == 0)
        except Exception:  # noqa: BLE001
            ok = False
        _LL_STATUS["ok"] = ok
        if not ok:
            events.emit("sandbox_unavailable", {"binary": str(_LL_BIN)})
    if not _LL_STATUS.get("ok"):
        return None
    rw = [str(ROOT), str(Path.home() / "Brain"), str(Path.home() / "Schreibtisch"),
          "/tmp", str(Path.home() / ".cache")]
    rw += [str(p) for p in (cfg.get("extra_rw") or [])]
    argv = [str(_LL_BIN), "--ro", "/"]
    for p in rw:
        if Path(p).exists():
            argv += ["--rw", p]
    return argv + ["--", "/bin/sh", "-c"]


def run_shell(command: str, cwd: str | None = None, timeout: int = 60) -> str:
    command = (command or "").strip()
    if not command:
        return "(kein Befehl)"
    if kill_switch_active():
        return "Not-Aus ist aktiv — ich fuehre gerade nichts aus."
    if _is_dangerous(command):
        events.emit("shell_blocked", {"command": command[:200]})
        return "Blockiert: dieser Befehl wirkt potenziell zerstoererisch. Ausfuehrung verweigert."
    sudo_veto = _sudo_wache(command)
    if sudo_veto:
        events.emit("shell_blocked", {"command": command[:200], "grund": "sudo"})
        return sudo_veto
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

    kern = _core_wache(command, wd)
    if kern:
        events.emit("shell_blocked", {"command": command[:200], "grund": "core"})
        return kern

    try:
        timeout = max(1, min(int(timeout or 60), 600))
    except Exception:  # noqa: BLE001
        timeout = 60

    try:
        _sbx = _sandbox_argv(command)
        if _sbx:
            p = subprocess.run(
                _sbx + [command], shell=False, cwd=str(wd), capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
            )
        else:
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
