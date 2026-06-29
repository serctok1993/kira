"""Selbst-Entwicklung: Kyros bearbeitet seinen EIGENEN Code — sicher.

Ablauf von apply_edit():
1. Alte Version sichern (Git ist ohnehin der Sicherheitsnetz).
2. Neue Version schreiben.
3. Bei .py: Syntax-Check (py_compile). Faellt er durch -> ROLLBACK (alte Version zurueck).
4. Sonst: git add + commit (revertierbar) und Hinweis, den betroffenen Dienst neu zu starten.

self_edit() laesst ein (vorzugsweise starkes/escaliertes) Modell den neuen Dateiinhalt
erzeugen und ruft apply_edit(). Die Verfassung bleibt fuer Kyros gesperrt (evolution.py);
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


def apply_edit(rel_path: str, new_content: str, reason: str = "") -> dict:
    p = (ROOT / rel_path).resolve()
    # Sicherheit: nur innerhalb des Projekts
    if ROOT not in p.parents and p != ROOT:
        return {"ok": False, "error": "Pfad ausserhalb des Projekts."}
    old = p.read_text(encoding="utf-8") if p.exists() else None
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
