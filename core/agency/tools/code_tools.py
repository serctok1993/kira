"""Coding-Grundausstattung (Claude-Code-Stil): suchen -> chirurgisch editieren -> verifizieren.

code_suche   : Python-natives grep unter ROOT (run_shell blockiert grep bewusst).
datei_finden : Glob unter ROOT.
code_symbol  : P4 — wo ist ein Symbol DEFINIERT, wo VERWENDET (ast-Index, mtime-Cache).
code_umriss  : P4 — Landkarte einer Python-Datei (Klassen/Funktionen/Zeilen/Docstring).
edit_datei   : chirurgischer Edit OHNE LLM-Umweg — eindeutiger Suchtext wird ersetzt
               (selfdev._apply_edits; P3 Anker-Edits: Einrueckungs-Drift wird repariert,
               Fehlschlaege zitieren frische Anker-Zeilen aus der Datei) und laeuft durch
               das volle Sicherheitsnetz (py_compile, Truncation-Guard, Verify + Rollback).

Windows-first: reine pathlib/os.walk-Implementierung, utf-8 mit errors=replace,
Ausgaben als posix-Relativpfade. Alle Werkzeuge liefern Strings und raisen nie.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from core.config import ROOT
from core.agency.tools.registry import tool

_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "data", ".pytest_cache"}
_MAX_TREFFER = 60
_MAX_ZEICHEN = 4000
_MAX_DATEI_BYTES = 1_000_000


def _unter_root(pfad: str) -> Path | None:
    """Loest pfad (relativ oder absolut) auf; None, wenn ausserhalb des Projekts."""
    try:
        p = (ROOT / pfad).resolve() if not Path(pfad).is_absolute() else Path(pfad).resolve()
    except Exception:  # noqa: BLE001
        return None
    if p != ROOT and ROOT not in p.parents:
        return None
    return p


def _ist_binaer(p: Path) -> bool:
    try:
        return b"\x00" in p.open("rb").read(1024)
    except Exception:  # noqa: BLE001
        return True


@tool("code_suche",
      "Durchsucht Projekt-Dateien nach einem Regex-Muster (wie grep). Gross/klein egal: "
      "Muster mit (?i) beginnen. Ausgabe: pfad:zeile: text.",
      {"muster": "Regex, z.B. 'def resolve_model' oder '(?i)todo'",
       "pfad": "optional: Unterordner, Standard = ganzes Projekt",
       "dateimuster": "optional: nur Dateinamen wie '*.py' (Standard: alle)"})
def code_suche(muster: str, pfad: str = ".", dateimuster: str = "") -> str:
    try:
        rx = re.compile(muster)
    except re.error as e:
        return f"Ungueltiges Regex-Muster: {e}"
    start = _unter_root(pfad or ".")
    if start is None or not start.exists():
        return "Pfad ausserhalb des Projekts oder nicht vorhanden."
    name_rx = None
    if (dateimuster or "").strip():
        import fnmatch
        name_rx = re.compile(fnmatch.translate(dateimuster.strip()))

    zeilen: list[str] = []
    zeichen = 0
    for wurzel, dirs, dateien in os.walk(start):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in sorted(dateien):
            if name_rx and not name_rx.match(name):
                continue
            f = Path(wurzel) / name
            try:
                if f.stat().st_size > _MAX_DATEI_BYTES or _ist_binaer(f):
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            rel = f.relative_to(ROOT).as_posix()
            for nr, zeile in enumerate(text.splitlines(), 1):
                if rx.search(zeile):
                    eintrag = f"{rel}:{nr}: {zeile.strip()[:200]}"
                    zeilen.append(eintrag)
                    zeichen += len(eintrag)
                    if len(zeilen) >= _MAX_TREFFER or zeichen >= _MAX_ZEICHEN:
                        zeilen.append(f"… (gedeckelt bei {len(zeilen)} Treffern — Muster/Pfad eingrenzen)")
                        return "\n".join(zeilen)
    return "\n".join(zeilen) if zeilen else "Keine Treffer."


@tool("datei_finden",
      "Findet Dateien im Projekt per Glob-Muster (rekursiv), z.B. '*.py' oder 'test_*.py'.",
      {"muster": "Glob wie '*.py', 'core/**/*.md' oder 'test_delegate*'"})
def datei_finden(muster: str) -> str:
    m = (muster or "").strip()
    if not m:
        return "Kein Muster angegeben."
    if m.startswith("**/"):
        m = m[3:]  # rglob ist bereits rekursiv
    try:
        treffer = []
        for p in sorted(ROOT.rglob(m)):
            if set(p.parts) & _SKIP_DIRS or not p.is_file():
                continue
            treffer.append(p.relative_to(ROOT).as_posix())
            if len(treffer) >= 200:
                treffer.append("… (gedeckelt bei 200 — Muster eingrenzen)")
                break
        return "\n".join(treffer) if treffer else "Keine Datei gefunden."
    except Exception as e:  # noqa: BLE001
        return f"Fehler bei der Suche: {e}"


@tool("edit_datei",
      "Chirurgischer Edit einer BESTEHENDEN Datei: 'suche' muss GENAU EINMAL in der "
      "Datei stehen, sonst schlaegt der Edit laut fehl (nichts wird still zerschossen); "
      "leichte Einrueckungs-Abweichungen repariert das Werkzeug selbst. Schlaegt er "
      "fehl, ZITIERT die Fehlermeldung frische Anker-Zeilen aus der Datei — direkt "
      "damit erneut aufrufen, die Datei NICHT neu lesen. suche='' haengt ans Dateiende "
      "an. Bei Code-Dateien laufen automatisch Syntax-Check + Testsuite; rot -> Datei "
      "kommt zurueck. Ganze Funktionen loeschen lehnt der Guard ab -> kleiner editieren.",
      {"pfad": "Datei im Projekt (relativ oder absolut)",
       "suche": "wortgenauer, eindeutiger Ausschnitt ('' = anhaengen)",
       "ersetze": "der neue Text"})
def edit_datei(pfad: str, suche: str, ersetze: str) -> str:
    from core.agency import selfdev

    p = _unter_root(pfad)
    if p is None:
        return "Fehlgeschlagen: Pfad ausserhalb des Projekts."
    if not p.exists() or not p.is_file():
        return f"Fehlgeschlagen: Datei nicht gefunden: {pfad} (zum Neuanlegen write_file nutzen)."
    rel = p.relative_to(ROOT).as_posix()
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"Fehlgeschlagen: Datei nicht lesbar: {e}"

    blocks = [("append", ersetze)] if suche == "" else [("replace", suche, ersetze)]
    new_content, err = selfdev._apply_edits(content, blocks)
    if err:
        return "Fehlgeschlagen: " + err
    if new_content == content:
        return "Fehlgeschlagen: Der Edit ergab keine Aenderung."
    r = selfdev.apply_edit(rel, new_content, reason=f"edit_datei: {rel}"[:80])
    if r.get("ok"):
        add, rem = selfdev.diff_summary(content, new_content)
        note = r.get("note", "")
        head = f"OK — {rel} geaendert (+{add} −{rem}). {note}".strip()
        diff = selfdev.compact_diff(content, new_content, rel)
        return head + (("\n" + diff) if diff else "")
    detail = r.get("verify", "")
    return f"Fehlgeschlagen: {r.get('error', 'unbekannt')}" + (f"\n{detail[:800]}" if detail else "")


# ---- P4: Symbol-Navigation (ast-basiert, 0 Abhaengigkeiten) --------------------------
# Der groesste Kontext-Hebel fuer kleine Modelle: EINE praezise Antwort "wo definiert /
# wo verwendet" bzw. die Datei-Landkarte — statt Dateien zu raten und zu stapeln.
# Index-Cache pro Datei mit mtime-Invalidierung; SyntaxError-Dateien fallen still raus.

_SYM_CACHE: dict[str, tuple[float, dict]] = {}


def _def_kopf(node) -> str:
    import ast
    try:
        args = ast.unparse(node.args)
    except Exception:  # noqa: BLE001
        args = "..."
    a = "async " if node.__class__.__name__ == "AsyncFunctionDef" else ""
    return f"{a}def {node.name}({args})"


def _datei_symbole(f: Path, rel: str) -> dict:
    """{'defs': [(zeile, name, kopf)], 'verw': {name: [zeilen]}} — raist nie."""
    import ast
    try:
        mtime = f.stat().st_mtime
        hit = _SYM_CACHE.get(rel)
        if hit and hit[0] == mtime:
            return hit[1]
        baum = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return {"defs": [], "verw": {}}
    defs: list[tuple] = []
    verw: dict[str, list[int]] = {}
    for node in ast.walk(baum):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append((node.lineno, node.name, _def_kopf(node)))
        elif isinstance(node, ast.ClassDef):
            defs.append((node.lineno, node.name, f"class {node.name}"))
        elif isinstance(node, ast.Name):
            verw.setdefault(node.id, []).append(node.lineno)
        elif isinstance(node, ast.Attribute):
            verw.setdefault(node.attr, []).append(node.lineno)
    for node in baum.body:                      # Modul-Konstanten als Definition
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defs.append((node.lineno, t.id, f"{t.id} = …"))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs.append((node.lineno, node.target.id, f"{node.target.id}: …"))
    ergebnis = {"defs": defs, "verw": verw}
    _SYM_CACHE[rel] = (mtime, ergebnis)
    return ergebnis


def _py_dateien():
    for wurzel, dirs, dateien in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in sorted(dateien):
            if not name.endswith(".py"):
                continue
            f = Path(wurzel) / name
            try:
                if f.stat().st_size <= _MAX_DATEI_BYTES:
                    yield f, f.relative_to(ROOT).as_posix()
            except Exception:  # noqa: BLE001
                continue


@tool("code_symbol",
      "Findet ein Python-Symbol im PROJEKT: wo DEFINIERT (Datei:Zeile + Kopfzeile) und "
      "wo VERWENDET — eine Anfrage statt mehrerer code_suche. Vor jedem Edit aufrufen, "
      "statt Dateien zu raten. Bei Tippfehlern schlaegt die Antwort aehnliche Namen vor.",
      {"name": "Funktions-, Klassen- oder Variablenname, z.B. 'resolve_model'"})
def code_symbol(name: str) -> str:
    n = (name or "").strip().split("(")[0].strip()
    if not n:
        return 'Kein Symbolname angegeben. Beispiel: code_symbol("resolve_model").'
    defs: list[str] = []
    verw: list[str] = []
    verw_zeilen = 0
    alle_namen: set[str] = set()
    for f, rel in _py_dateien():
        sym = _datei_symbole(f, rel)
        for zeile, nm, kopf in sym["defs"]:
            alle_namen.add(nm)
            if nm == n:
                defs.append(f"{rel}:{zeile}  {kopf}")
        z = sorted(set(sym["verw"].get(n, [])))
        if z and len(verw) < 20:
            verw.append(f"{rel}: {', '.join(map(str, z[:12]))}")
            verw_zeilen += len(z)
    if not defs and not verw:
        import difflib
        nah = difflib.get_close_matches(n, sorted(alle_namen), n=3, cutoff=0.6)
        return (f"Symbol '{n}' nicht gefunden."
                + (f" Meintest du: {', '.join(nah)}? Erneut mit dem exakten Namen aufrufen."
                   if nah else " Fuer Textmuster code_suche nutzen."))
    out = []
    if defs:
        out.append("DEFINITION:")
        out.extend(defs[:8])
    if verw:
        out.append(f"VERWENDUNGEN ({verw_zeilen} Zeilen in {len(verw)} Dateien):")
        out.extend(verw)
    return "\n".join(out)[:2500]


@tool("code_umriss",
      "Die LANDKARTE einer Python-Datei, ohne sie ganz zu lesen: Klassen, Funktionen, "
      "Signaturen, Zeilennummern und erste Docstring-Zeile. Der richtige erste Blick "
      "vor read_file/edit_datei — spart Kontext.",
      {"pfad": "Python-Datei im Projekt (relativ oder absolut)"})
def code_umriss(pfad: str) -> str:
    import ast
    p = _unter_root(pfad)
    if p is None:
        return "Pfad ausserhalb des Projekts."
    if not p.exists() or not p.is_file():
        return f"Datei nicht gefunden: {pfad} (datei_finden hilft beim Suchen)."
    rel = p.relative_to(ROOT).as_posix()
    if p.suffix != ".py":
        return f"{rel} ist keine Python-Datei — fuer andere Formate read_file nutzen."
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        baum = ast.parse(text)
    except SyntaxError as e:
        return f"Syntaxfehler in {rel} (Zeile {e.lineno}): {e.msg} — erst reparieren."

    def _doc1(node) -> str:
        d = ast.get_docstring(node) or ""
        return f'  — "{d.splitlines()[0][:80]}"' if d else ""

    zeilen = [f"{rel} — {len(text.splitlines())} Zeilen"]
    for node in baum.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            zeilen.append(f"{node.lineno:>5} {_def_kopf(node)}{_doc1(node)}")
        elif isinstance(node, ast.ClassDef):
            zeilen.append(f"{node.lineno:>5} class {node.name}{_doc1(node)}")
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    zeilen.append(f"{m.lineno:>5}   {_def_kopf(m)}")
        elif isinstance(node, ast.Assign):
            namen = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if namen:
                zeilen.append(f"{node.lineno:>5} {', '.join(namen)} = …")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            zeilen.append(f"{node.lineno:>5} {node.target.id}: …")
    if len(zeilen) == 1:
        zeilen.append("(keine Top-Level-Definitionen)")
    return "\n".join(zeilen)[:_MAX_ZEICHEN]
