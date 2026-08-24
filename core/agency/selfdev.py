"""Selbst-Entwicklung: Kira bearbeitet seinen EIGENEN Code — sicher.

Ablauf von apply_edit():
1. Alte Version sichern.
2. Neue Version ATOMAR schreiben (fs.atomic_write).
3. Bei .py: Syntax-Check (py_compile) + Truncation-Guard. Fehler -> nur DIESE Datei zurueck.
4. VERIFY (Testsuite) — erst bei GRUEN wird git add + commit gemacht. Roter Verify setzt
   nur die editierte Datei zurueck; anderes ungespeichertes Arbeiten im Repo bleibt heil
   (frueher: commit vor verify + git reset --hard, das den ganzen Tree verwarf).

self_edit() laesst ein (vorzugsweise starkes/escaliertes) Modell GEZIELTE Such-/Ersetz-
Bloecke (SEARCH/REPLACE bzw. APPEND) erzeugen — NIE die ganze Datei (darum keine Truncation
bei grossen Dateien) — und wendet sie via apply_edit() an. Die Verfassung bleibt gesperrt.
"""
from __future__ import annotations

import difflib
import py_compile
import re
import subprocess

from core.config import MIND_DIR, ROOT
from core.kernel import events
from core.kernel.fs import atomic_write


def _ident_name() -> str:
    """Nutzer-Name fuer lehrende Fehlertexte (W3) — live aus identity."""
    from core import identity
    return identity.user_name()


def diff_summary(old: str, new: str) -> tuple[int, int]:
    """(hinzugefuegte, entfernte) Zeilen — fuer das '+3 −1' hinter jedem Edit."""
    add = rem = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            add += 1
        elif line.startswith("-") and not line.startswith("---"):
            rem += 1
    return add, rem


def compact_diff(old: str, new: str, path: str, max_lines: int = 30) -> str:
    """Kompakter unified diff als ```diff-Block (fuer den Cockpit-Trace: gruen/rot wie in Claude Code).
    Header-Zeilen (---/+++) weg, auf max_lines gedeckelt. Leerer String, wenn nichts unterschiedlich."""
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                     fromfile=path, tofile=path, lineterm="", n=2))
    body = diff[2:] if len(diff) > 2 else diff  # ---/+++ Kopf weg, @@-Huenks bleiben
    if not body:
        return ""
    clip = body[:max_lines]
    out = "\n".join(clip)
    if len(body) > max_lines:
        out += f"\n… (+{len(body) - max_lines} weitere Diff-Zeilen)"
    return "```diff\n" + out + "\n```"


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


def _verify_cmd() -> str:
    """Das Verifikations-Kommando, plattformfest (config selfdev.verify_cmd).

    Ein Windows-venv-Pfad in der Config heisst auf posix schlicht 'Testsuite laufen
    lassen' -> Kommando wird deterministisch NEU gebaut statt am String zu operieren.
    Windows-Verhalten bleibt unveraendert."""
    import os as _os
    import sys as _sys
    from core.config import CONFIG

    cmd = (CONFIG.get("selfdev", {}) or {}).get("verify_cmd")
    if cmd and _os.name != "nt" and "\\Scripts\\" in cmd:
        posix_py = ROOT / ".venv" / "bin" / "python"
        py = str(posix_py) if posix_py.exists() else _sys.executable
        return f'"{py}" -m pytest tests -q'
    if cmd and cmd.startswith(".venv/") and not (ROOT / ".venv").exists():
        # Worktree-Fall (Bench/Sandbox): .venv ist gitignored und existiert dort NICHT —
        # der relative Config-Pfad lief auf exit 127, die Endabnahme wurde ROT und rollte
        # einen GRUENEN Fix zurueck (Suite-v3-Befund: edit-bugfix, Nemotron). Kommando
        # deterministisch neu bauen wie im Windows-Zweig; im Hauptrepo aendert sich nichts.
        return f'"{_sys.executable}" -m pytest tests -q'
    if cmd:
        return cmd
    for cand in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            py = str(cand)
            break
    else:
        py = _sys.executable
    return (f'"{py}" -c "import core.api.server, core.agency.act, core.agency.tools.builtin, '
            'core.mind.agent, core.agency.connectors.telegram_bot, core.agency.shelltool"')


# Lauf-Modus (Paket B): waehrend eines code:/plan:-Laufs laeuft pro .py-Edit NUR der
# schnelle Syntax-/Truncation-Check — die volle Testsuite prueft der Lauf EINMAL am Ende
# (plan_and_execute) und rollt bei Rot den GANZEN Lauf zurueck. Spart die 375-Test-Suite
# nach jedem einzelnen Edit (das waren des Nutzers 5-15 Minuten). Config: selfdev.fast_verify_in_run.
_FAST_VERIFY = False


def set_fast_verify(on: bool) -> None:
    """Schaltet den Lauf-Modus (schneller Per-Edit-Check, Suite am Lauf-Ende)."""
    global _FAST_VERIFY
    _FAST_VERIFY = bool(on)


def fast_verify_active() -> bool:
    """Entfesselung 23.08. (Inventur H7/H11): der schnelle Per-Edit-Check ist jetzt
    DEFAULT fuer alle Pfade — auch ausserhalb von code:-Laeufen kostete sonst jeder
    einzelne chirurgische Edit die komplette Testsuite (Minuten pro Edit). Wer die
    volle Suite pro Edit zurueck will: selfdev.edit_vollpruefung: true in config.yaml.
    Config-Dateien (.yaml/.json) behalten IMMER die volle Verify (siehe apply_edit)."""
    if _FAST_VERIFY:
        return True
    try:
        from core.config import CONFIG

        return not bool((CONFIG.get("selfdev", {}) or {}).get("edit_vollpruefung", False))
    except Exception:  # noqa: BLE001
        return True


def _verify() -> tuple[bool, str]:
    """Selbst-Test nach einer Aenderung. Timeout grosszuegig (600s = shelltool-Maximum):
    die volle Suite braucht inzwischen ~6 Minuten — beim alten 300s-Deckel zaehlte der
    Timeout als FEHLSCHLAG und rollte GUTE Edits zurueck (W0-Fund B4, 8x in 7 Tagen).
    Gibt (ok, ausgabe)."""
    from core import config as _cfg

    if _cfg.sandbox_active():
        # Bench-/Sandbox-Worktree: die Suite laeuft wie in CI — OHNE die Bench-Variablen.
        # Gemessen (Suite-v3-Diagnose): unter Bench-Env fallen 165 Tests, die im selben
        # Worktree unter Normal-Env gruen sind — KIRA_FORCE_MODEL kippt Routing-Tests,
        # KIRA_NO_OUTBOUND Outbound-Tests, und mit gesetztem KIRA_ROOT/KIRA_DATA_DIR legt
        # conftest keine eigene Wegwerf-Datenwurzel (+ onboarded.flag) an -> das
        # Onboarding-Gate faerbt die halbe API-Suite rot. Massstab der Endabnahme ist der
        # WORKTREE-CODE unter Normalbedingungen, nicht das Bench-Env; die Firewall der
        # Sandbox bleibt unberuehrt (pytest setzt KIRA_TEST_MODE selbst).
        import os as _os
        import subprocess as _sp

        env = {k: v for k, v in _os.environ.items()
               if k not in ("KIRA_FORCE_MODEL", "KIRA_NO_OUTBOUND", "KIRA_ALLOW_LLM",
                            "KIRA_ROOT", "KIRA_DATA_DIR", "KIRA_TEST_DATA_DIR")}
        try:
            pr = _sp.run(_verify_cmd(), shell=True, cwd=str(ROOT), env=env,
                         capture_output=True, text=True, timeout=600,
                         encoding="utf-8", errors="replace")
        except _sp.TimeoutExpired:
            return False, "[timeout] Endabnahme-Suite ueberschritt 600s"
        body = (pr.stdout or "").strip()
        if pr.stderr:
            body += "\n[stderr]\n" + pr.stderr.strip()
        return pr.returncode == 0, f"[exit {pr.returncode}]\n" + body[:3000]

    from core.agency.shelltool import run_shell

    out = run_shell(_verify_cmd(), timeout=600)
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
    if p == (MIND_DIR / "constitution.md").resolve():
        events.emit("write_blocked", {"path": str(p), "tool": "self_edit"})
        return {"ok": False, "error": "constitution.md ist unantastbar (Verfassung) — "
                                      f"Aenderungen macht nur {_ident_name()} selbst via Git."}
    # Sicherheit: nur innerhalb des Projekts
    if ROOT not in p.parents and p != ROOT:
        return {"ok": False, "error": "Pfad ausserhalb des Projekts."}
    old = p.read_text(encoding="utf-8") if p.exists() else None
    atomic_write(p, new_content)  # atomar (legt Elternordner selbst an)

    def _restore() -> None:
        """Nur DIESE Datei zurueck — anderes ungespeichertes Arbeiten bleibt heil."""
        if old is not None:
            atomic_write(p, old)
        else:
            p.unlink(missing_ok=True)

    if p.suffix == ".py":
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            _restore()
            events.emit("selfdev_rejected", {"file": rel_path, "error": str(e)[:200]})
            return {"ok": False, "error": f"Syntaxfehler -> zurueckgerollt: {str(e)[:160]}"}

        # Truncation-Schutz: self_edit laesst das LLM die GANZE Datei neu schreiben -> bei grossen
        # Dateien reisst die Ausgabe am max_tokens-Limit ab und loescht still den Rest (verlorene
        # Tools/Funktionen sehen py_compile+pytest NICHT). Verschwinden bestehende Top-Level-defs
        # -> als kaputt ablehnen und zurueckrollen, statt einen falschen 'Erfolg' zu committen.
        if old is not None:
            missing = _lost_defs(old, new_content)
            if missing:
                _restore()
                events.emit("selfdev_rejected", {"file": rel_path, "error": "lost_defs", "missing": missing[:20]})
                return {"ok": False, "error": "Abgelehnt (evtl. Truncation): bestehende Definitionen wuerden "
                        f"verschwinden: {', '.join(missing[:12])}. Mach einen GEZIELTEN, kleineren Edit."}

    # Selbst-Test-Disziplin VOR dem Commit: Code UND Konfig pruefen (pytest importiert
    # core.config -> faengt auch kaputtes YAML/JSON ab). Rot -> nur diese Datei zurueck,
    # git bleibt UNBERUEHRT (kein reset --hard mehr, kein Commit-Muell).
    if verify and p.suffix in (".py", ".yaml", ".yml", ".json", ".toml"):
        # Lauf-Modus: fuer .py sind py_compile + _lost_defs oben schon gruen -> committen,
        # die volle Suite prueft der Lauf am Ende. Config-Dateien (.yaml/.json) behalten IMMER
        # die volle Verify (pytest importiert core.config -> faengt kaputtes YAML ab).
        if fast_verify_active() and p.suffix == ".py":
            _git("add", rel_path)
            _git("commit", "-m", f"selfdev: {reason or rel_path}")
            events.emit("selfdev_applied", {"file": rel_path, "reason": reason, "fast": True})
            return {"ok": True, "file": rel_path, "verified": False,
                    "note": "Angewendet (Syntax gruen). Endabnahme der Testsuite folgt am Lauf-Ende."}
        ok_v, out_v = _verify()
        if not ok_v:
            _restore()
            events.emit("selfdev_verify_failed", {"file": rel_path, "out": out_v[:300]})
            return {"ok": False, "error": "Verifizierung fehlgeschlagen -> Datei zurueckgesetzt.",
                    "verify": out_v[:1500]}
        _git("add", rel_path)
        _git("commit", "-m", f"selfdev: {reason or rel_path}")
        events.emit("selfdev_applied", {"file": rel_path, "reason": reason, "verified": True})
        _request_restart()  # Supervisor laedt die Aenderung sicher neu (kein Selbst-Kill)
        return {"ok": True, "file": rel_path, "verified": True,
                "note": "Angewendet, Selbst-Test gruen, committet. Wird automatisch neu geladen (Supervisor)."}

    _git("add", rel_path)
    _git("commit", "-m", f"selfdev: {reason or rel_path}")
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


def _einzug(zeile: str) -> int:
    return len(zeile) - len(zeile.lstrip())


def _tolerante_fenster(c_lines: list[str], s_lines: list[str]) -> list[int]:
    """Startindizes aller Zeilenfolgen, die dem SEARCH bis auf Einrueckung entsprechen
    (jede Zeile strip-gleich). Innen-Whitespace muss stimmen — bewusst konservativ."""
    s_strip = [z.strip() for z in s_lines]
    return [i for i in range(len(c_lines) - len(s_lines) + 1)
            if all(c_lines[i + j].strip() == s_strip[j] for j in range(len(s_lines)))]


def _kern_zeilen(search: str) -> list[str]:
    """SEARCH als Zeilenliste ohne fuehrende/abschliessende Leerzeilen."""
    s = search.split("\n")
    while s and not s[0].strip():
        s.pop(0)
    while s and not s[-1].strip():
        s.pop()
    return s


def _tolerant_ersetzen(content: str, search: str, replace: str) -> str | None:
    """Fallback, wenn der exakte SEARCH scheitert: EIN eindeutiges tolerantes Fenster
    wird ersetzt; uniformer Einrueckungs-Drift wandert auf REPLACE mit (das
    Sicherheitsnetz py_compile/Suite faengt den Rest)."""
    c_lines, s_lines = content.split("\n"), _kern_zeilen(search)
    if not s_lines:
        return None
    fenster = _tolerante_fenster(c_lines, s_lines)
    if len(fenster) != 1:
        return None
    i = fenster[0]
    drifts = {_einzug(c_lines[i + j]) - _einzug(s_lines[j])
              for j in range(len(s_lines)) if s_lines[j].strip()}
    delta = drifts.pop() if len(drifts) == 1 else 0
    r_lines = replace.split("\n")
    if delta:
        r_lines = [((" " * delta + z) if delta > 0 else z[min(-delta, _einzug(z)):])
                   if z.strip() else z for z in r_lines]
    return "\n".join(c_lines[:i] + r_lines + c_lines[i + len(s_lines):])


def _fund_zeilen(content: str, search: str) -> list[int]:
    """1-basierte Startzeilen aller exakten Fundstellen (max. 8)."""
    zeilen, start = [], 0
    while len(zeilen) < 8:
        pos = content.find(search, start)
        if pos < 0:
            break
        zeilen.append(content.count("\n", 0, pos) + 1)
        start = pos + 1
    return zeilen


def _anker_vorschlag(content: str, search: str) -> str:
    """Frische Anker nach dem hashline-Muster: der Fehler ZITIERT die echten
    Datei-Zeilen um die wahrscheinlichste Stelle — das Modell ruft direkt mit dem
    Zitat erneut auf, statt die Datei neu zu lesen (spart Kontext)."""
    c_lines = content.split("\n")
    kern = [z.strip() for z in search.split("\n") if z.strip()]
    if not kern or not any(z.strip() for z in c_lines):
        return ""
    leit = max(kern, key=len)
    idx = next((i for i, z in enumerate(c_lines) if z.strip() == leit), None)
    if idx is None:
        import difflib
        nah = difflib.get_close_matches(leit, [z.strip() for z in c_lines if z.strip()],
                                        n=1, cutoff=0.6)
        if nah:
            idx = next((i for i, z in enumerate(c_lines) if z.strip() == nah[0]), None)
    if idx is None:
        return ""
    a = max(0, idx - 1)
    b = min(len(c_lines), idx + max(2, min(len(kern) + 1, 5)))
    zitat = "\n".join(c_lines[a:b])[:600]
    return (f" So steht die Stelle WIRKLICH in der Datei (Zeilen {a + 1}-{b}):\n{zitat}\n"
            "Rufe erneut auf mit GENAU diesen Zeilen als suche — die Datei NICHT neu lesen.")


def _apply_edits(original: str, blocks: list[tuple]) -> tuple[str | None, str | None]:
    """Wendet die Bloecke auf 'original' an (all-or-nothing, in Reihenfolge).
    Rueckgabe: (neuer_inhalt, None) oder (None, fehlermeldung).
    P3 (Anker-Edits): exakter Match zuerst; scheitert er, repariert ein eindeutiges
    Einrueckungs-tolerantes Fenster den Drift; jeder Fehlschlag LEHRT mit frischen
    Ankern aus der Datei (Zeilennummern + Zitat) statt nur 'nicht gefunden'."""
    content = original
    for i, b in enumerate(blocks, 1):
        if b[0] == "append":
            content = content.rstrip("\n") + "\n\n\n" + b[1].strip("\n") + "\n"
            continue
        _, search, replace = b
        n = content.count(search)
        if n == 1:
            content = content.replace(search, replace, 1)
            continue
        if n > 1:
            zn = _fund_zeilen(content, search)
            c_lines = content.split("\n")
            a = max(0, zn[0] - 2)
            e = min(len(c_lines), zn[0] - 1 + search.count("\n") + 2)
            beispiel = "\n".join(c_lines[a:e])[:400]
            return None, (f"Edit-Block {i}: SEARCH {n}x gefunden (Zeilen "
                          f"{', '.join(map(str, zn))}) — nicht eindeutig. Erweitere suche um "
                          f"Nachbarzeilen, zeichengenau z.B. (Umfeld von Zeile {zn[0]}):\n{beispiel}")
        neu = _tolerant_ersetzen(content, search, replace)
        if neu is not None:
            content = neu                      # Drift repariert — der Diff belegt das Ergebnis
            continue
        fenster = _tolerante_fenster(content.split("\n"), _kern_zeilen(search) or [""])
        if len(fenster) > 1:
            zn = ", ".join(str(f + 1) for f in fenster[:8])
            return None, (f"Edit-Block {i}: SEARCH passt (bis auf Einrueckung) an "
                          f"{len(fenster)} Stellen (Zeilen {zn}) — nicht eindeutig. "
                          "Erweitere suche um Nachbarzeilen.")
        return None, (f"Edit-Block {i}: SEARCH nicht gefunden."
                      + (_anker_vorschlag(content, search)
                         or " Lies die Stelle (read_file) und kopiere sie zeichengenau."))
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
    r = apply_edit(rel_path, new_content, reason=instruction[:80])
    if r.get("ok"):
        r["stat"] = diff_summary(content, new_content)
        r["diff"] = compact_diff(content, new_content, rel_path)
    return r
