"""Selbst-Entwicklung: Kira bearbeitet seinen EIGENEN Code — sicher.

Ablauf von apply_edit():
1. Alte Version sichern (Git ist ohnehin der Sicherheitsnetz).
2. Neue Version schreiben.
3. Bei .py: Syntax-Check (py_compile). Faellt er durch -> ROLLBACK (alte Version zurueck).
4. Sonst: git add + commit (revertierbar) und Hinweis, den betroffenen Dienst neu zu starten.

self_edit() laesst ein (vorzugsweise starkes/escaliertes) Modell GEZIELTE Such-/Ersetz-
Bloecke (SEARCH/REPLACE bzw. APPEND) erzeugen — NIE die ganze Datei (darum keine Truncation
bei grossen Dateien) — und wendet sie via apply_edit() an. Die Verfassung bleibt fuer Kira
gesperrt (evolution.py); hier geht es um Code/Dashboard/Tools — nicht um die Grundregeln.
"""
from __future__ import annotations

import py_compile
import re
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
    """Bittet um einen SICHEREN Neustart (statt Selbst-Kill via taskkill). Laeuft gerade
    ein Chat-Zug (z.B. self_edit mitten im Gespraech), wird der Bounce ueber runstate bis
    idle aufgeschoben -> Kira schiesst ihre eigene Antwort nicht ab."""
    try:
        from core.kernel import runstate
        runstate.request_restart(which)
    except Exception:  # noqa: BLE001
        try:  # Fallback: den self_edit-Erfolg nie an einem Restart-Problem scheitern lassen
            flag = ROOT / "data" / "restart.flag"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(which, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _lost_defs(old_src: str, new_src: str) -> list[str]:
    """Top-Level def/class-Namen, die in old existieren, in new aber FEHLEN — starker
    Truncation-Indikator (self_edit-Ganzdatei-Rewrite riss am max_tokens-Limit ab)."""
    import ast

    def names(src: str) -> set[str]:
        try:
            tree = ast.parse(src)
        except Exception:  # noqa: BLE001
            return set()
        return {n.name for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

    old_names = names(old_src)
    if not old_names:
        return []
    return sorted(old_names - names(new_src))


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

        # Truncation-Schutz: self_edit laesst das LLM die GANZE Datei neu schreiben -> bei grossen
        # Dateien reisst die Ausgabe am max_tokens-Limit ab und loescht still den Rest (verlorene
        # Tools/Funktionen sehen py_compile+pytest NICHT). Verschwinden bestehende Top-Level-defs
        # -> als kaputt ablehnen und zurueckrollen, statt einen falschen 'Erfolg' zu committen.
        if old is not None:
            missing = _lost_defs(old, new_content)
            if missing:
                p.write_text(old, encoding="utf-8")
                events.emit("selfdev_rejected", {"file": rel_path, "error": "lost_defs", "missing": missing[:20]})
                return {"ok": False, "error": "Abgelehnt (evtl. Truncation): bestehende Definitionen wuerden "
                        f"verschwinden: {', '.join(missing[:12])}. Mach einen GEZIELTEN, kleineren Edit."}

    _git("add", rel_path)
    _git("commit", "-m", f"selfdev: {reason or rel_path}")

    # Selbst-Test-Disziplin: Code UND Konfig pruefen (pytest importiert core.config -> faengt
    # auch kaputtes YAML/JSON ab, das sonst das ganze System beim Start crashen wuerde).
    if verify and p.suffix in (".py", ".yaml", ".yml", ".json", ".toml"):
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


_SELF_EDIT_SYS = (
    "Du bist ein praeziser Software-Entwickler und bearbeitest EINE Datei mit GEZIELTEN Edits. "
    "Gib die Datei NIEMALS komplett neu aus. Antworte NUR mit einem oder mehreren Edit-Bloecken "
    "in GENAU diesem Format (nichts sonst — keine Erklaerung, keine Code-Fences):\n\n"
    "ERSETZEN eines vorhandenen Stuecks:\n"
    "<<<<<<< SEARCH\n"
    "<ein KURZER, wortgenau aus der Datei kopierter Ausschnitt>\n"
    "=======\n"
    "<der neue Text, der ihn ersetzt>\n"
    ">>>>>>> REPLACE\n\n"
    "HINZUFUEGEN am Dateiende (z.B. eine neue Funktion / ein neues Tool):\n"
    "<<<<<<< APPEND\n"
    "<der neue Code>\n"
    ">>>>>>> APPEND\n\n"
    "Regeln: SEARCH muss ZEICHENGENAU (inkl. Einrueckung) so in der Datei stehen und EINDEUTIG "
    "sein (kommt genau einmal vor) — nimm ein paar Zeilen Kontext, wenn noetig. Aendere nur, was "
    "der Auftrag verlangt. Mehrere Stellen -> mehrere Bloecke."
)

_EDIT_BLOCK_RE = re.compile(
    r"<{3,}\s*SEARCH\s*\n(.*?)\n={3,}\s*\n(.*?)\n>{3,}\s*REPLACE"
    r"|<{3,}\s*APPEND\s*\n(.*?)\n>{3,}\s*APPEND",
    re.DOTALL)


def _parse_edit_blocks(text: str) -> list[tuple]:
    """Extrahiert Edit-Bloecke in Dokument-Reihenfolge: ('replace', search, repl) | ('append', text)."""
    blocks: list[tuple] = []
    for m in _EDIT_BLOCK_RE.finditer(text or ""):
        if m.group(1) is not None:
            blocks.append(("replace", m.group(1), m.group(2)))
        else:
            blocks.append(("append", m.group(3)))
    return blocks


def _apply_edits(original: str, blocks: list[tuple]) -> tuple[str | None, str | None]:
    """Wendet die Bloecke auf 'original' an (all-or-nothing, in Reihenfolge).
    Rueckgabe: (neuer_inhalt, None) oder (None, fehlermeldung)."""
    content = original
    for i, b in enumerate(blocks, 1):
        if b[0] == "append":
            content = content.rstrip("\n") + "\n\n\n" + b[1].strip("\n") + "\n"
            continue
        _, search, replace = b
        n = content.count(search)
        if n != 1:
            why = "nicht gefunden" if n == 0 else f"{n}x gefunden (nicht eindeutig)"
            return None, (f"Edit-Block {i}: SEARCH {why} — nimm einen groesseren, EINDEUTIGEN "
                          "Ausschnitt (wortgenau inkl. Einrueckung).")
        content = content.replace(search, replace, 1)
    return content, None


def self_edit(rel_path: str, instruction: str, escalate: bool = True) -> dict:
    """Bearbeitet eine Datei mit GEZIELTEN Such-/Ersetz-Bloecken (kein Ganzdatei-Rewrite ->
    keine Truncation bei grossen Dateien) und wendet das Ergebnis sicher an (apply_edit)."""
    from core.kernel import llm_router

    p = ROOT / rel_path
    if not p.exists():
        return {"ok": False, "error": f"Datei nicht gefunden: {rel_path}"}
    content = p.read_text(encoding="utf-8")
    user = (f"DATEI: {rel_path}\n---\n{content}\n---\nAENDERUNGSWUNSCH: {instruction}\n\n"
            "Gib NUR die Edit-Bloecke aus:")
    res = llm_router.complete([{"role": "user", "content": user}], system=_SELF_EDIT_SYS,
                              task_type="reason", escalate=escalate)
    blocks = _parse_edit_blocks(res["text"])
    if not blocks:
        return {"ok": False, "error": "Keine gueltigen Edit-Bloecke erhalten (Format SEARCH/REPLACE "
                "bzw. APPEND). Nichts geaendert — formuliere den Auftrag ggf. konkreter."}
    new_content, err = _apply_edits(content, blocks)
    if err:
        return {"ok": False, "error": err}
    if new_content == content:
        return {"ok": False, "error": "Die Edit-Bloecke ergaben keine Aenderung."}
    return apply_edit(rel_path, new_content, reason=instruction[:80])
