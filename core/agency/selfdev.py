"""Selbst-Entwicklung: Kira bearbeitet seinen EIGENEN Code — sicher.

Ablauf von apply_edit():
1. Alte Version sichern (Git ist ohnehin der Sicherheitsnetz).
2. Neue Version schreiben.
3. Bei .py: Syntax-Check (py_compile). Faellt er durch -> ROLLBACK (alte Version zurueck).
4. Sonst: git add + commit (revertierbar) und Hinweis, den betroffenen Dienst neu zu starten.

self_edit() laesst ein (vorzugsweise starkes/escaliertes) Modell den neuen Dateiinhalt
erzeugen und ruft apply_edit(). Die Verfassung bleibt fuer Kira gesperrt (evolution.py);
hier geht es um Code/Dashboard/Tools — nicht um die Grundregeln.
"""
from __future__ import annotations

import py_compile
import subprocess

from core.config import ROOT
from core.kernel import events


def _git(*args) -> None:
    try:
        subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=30)
    except Exception:
        pass


def _git_out(*args) -> str:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _verify() -> tuple[bool, str]:
    """Selbst-Test nach einer Aenderung: Standard = Import-Smoke der Kernmodule mit dem
    venv-Python (faengt kaputte Imports). Per config.yaml selfdev.verify_cmd ueberschreibbar
    (z.B. 'uv run pytest -q'). Gibt (ok, ausgabe) zurueck."""
    from core.agency.shelltool import run_shell
    from core.config import CONFIG

    cmd = (CONFIG.get("selfdev", {}) or {}).get("verify_cmd")
    if not cmd:
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
        py = str(venv_py) if venv_py.exists() else "python"
        cmd = (f'"{py}" -c "import core.api.server, core.agency.act, core.agency.tools.builtin, '
               'core.mind.agent, core.agency.connectors.telegram_bot, core.agency.shelltool"')
    out = run_shell(cmd, timeout=180)
    return out.startswith("[exit 0]"), out


def _request_restart(which: str = "all") -> None:
    """Bittet den Supervisor um einen SICHEREN Neustart (statt Selbst-Kill via taskkill)."""
    try:
        flag = ROOT / "data" / "restart.flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(which, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def apply_edit(rel_path: str, new_content: str, reason: str = "", verify: bool = True) -> dict:
    p = (ROOT / rel_path).resolve()
    # Sicherheit: nur innerhalb des Projekts
    if ROOT not in p.parents and p != ROOT:
        return {"ok": False, "error": "Pfad ausserhalb des Projekts."}
    old = p.read_text(encoding="utf-8") if p.exists() else None
    prev_head = _git_out("rev-parse", "HEAD")  # Stand VOR der Aenderung (fuer Rollback)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_content, encoding="utf-8")

    if p.suffix == ".py":
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            if old is not None:
                p.write_text(old, encoding="utf-8")
            else:
                p.unlink(missing_ok=True)
            events.emit("selfdev_rejected", {"file": rel_path, "error": str(e)[:200]})
            return {"ok": False, "error": f"Syntaxfehler -> zurueckgerollt: {str(e)[:160]}"}

    _git("add", rel_path)
    _git("commit", "-m", f"selfdev: {reason or rel_path}")

    # Selbst-Test-Disziplin: nur .py-Aenderungen verifizieren (HTML/JS in .py inklusive Import-Smoke).
    if verify and p.suffix == ".py":
        ok_v, out_v = _verify()
        if not ok_v:
            if prev_head:
                _git("reset", "--hard", prev_head)  # Aenderung verwerfen, sauberer Stand zurueck
            elif old is not None:
                p.write_text(old, encoding="utf-8")
            else:
                p.unlink(missing_ok=True)
            events.emit("selfdev_verify_failed", {"file": rel_path, "out": out_v[:300]})
            return {"ok": False, "error": "Verifizierung fehlgeschlagen -> zurueckgerollt.",
                    "verify": out_v[:1500]}
        events.emit("selfdev_applied", {"file": rel_path, "reason": reason, "verified": True})
        _request_restart()  # Supervisor laedt die Aenderung sicher neu (kein Selbst-Kill)
        return {"ok": True, "file": rel_path, "verified": True,
                "note": "Angewendet, Selbst-Test gruen, committet. Wird automatisch neu geladen (Supervisor)."}

    events.emit("selfdev_applied", {"file": rel_path, "reason": reason})
    return {"ok": True, "file": rel_path, "note": "Angewendet + committet. Betroffenen Dienst (Cockpit/Bot) neu starten."}


def self_edit(rel_path: str, instruction: str, escalate: bool = True) -> dict:
    """Laesst ein Modell den neuen Dateiinhalt erzeugen und wendet ihn sicher an."""
    from core.kernel import llm_router

    p = ROOT / rel_path
    if not p.exists():
        return {"ok": False, "error": f"Datei nicht gefunden: {rel_path}"}
    content = p.read_text(encoding="utf-8")
    sysmsg = (
        "Du bist ein praeziser Software-Entwickler. Aendere genau das Gewuenschte, sonst nichts. "
        "Gib NUR den vollstaendigen neuen Dateiinhalt zurueck — ohne Erklaerung, ohne Code-Fences."
    )
    user = f"DATEI: {rel_path}\n---\n{content}\n---\nAENDERUNGSWUNSCH: {instruction}\n\nKompletter neuer Dateiinhalt:"
    res = llm_router.complete([{"role": "user", "content": user}], system=sysmsg, task_type="reason", escalate=escalate)
    new = res["text"].strip()
    if new.startswith("```"):
        lines = new.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        new = "\n".join(lines).strip()
    if len(new) < 20:
        return {"ok": False, "error": "Modell-Ausgabe zu kurz/leer — verworfen."}
    return apply_edit(rel_path, new, reason=instruction[:80])
