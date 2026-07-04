"""Coding-Grundausstattung (Claude-Code-Stil): suchen -> chirurgisch editieren -> verifizieren.

code_suche   : Python-natives grep unter ROOT (run_shell blockiert grep bewusst).
datei_finden : Glob unter ROOT.
edit_datei   : chirurgischer Edit OHNE LLM-Umweg — exakter, EINDEUTIGER Suchtext wird
               ersetzt (selfdev._apply_edits) und laeuft durch das volle Sicherheitsnetz
               (Verfassungs-Block, py_compile, Truncation-Guard, Verify + Rollback).

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
      "Chirurgischer Edit einer BESTEHENDEN Datei: 'suche' muss ZEICHENGENAU (inkl. "
      "Einrueckung) und GENAU EINMAL in der Datei stehen, sonst schlaegt der Edit laut "
      "fehl (nichts wird still zerschossen). suche='' haengt ans Dateiende an. Bei "
      "Code-Dateien laufen automatisch Syntax-Check + Testsuite; rot -> Datei kommt "
      "zurueck. Ganze Funktionen loeschen lehnt der Guard ab -> kleiner editieren.",
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
        note = r.get("note", "")
        return f"OK — {rel} geaendert. {note}".strip()
    detail = r.get("verify", "")
    return f"Fehlgeschlagen: {r.get('error', 'unbekannt')}" + (f"\n{detail[:800]}" if detail else "")
