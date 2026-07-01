"""Working-Set-Scratchpad: ein lebendes "Stand der Dinge"-Doc pro Objective (S2).

Statt zufaelliger Erinnerungen bekommt jeder Mission-Versuch den kompakten
Arbeitsstand seines Ziels injiziert: was lief, was scheiterte, worauf aufbauen.
Reines Datei-Modul (data/workspace/objective-<id>.md) — kein LLM, keine DB.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from core.config import DATA_DIR

_DIR = DATA_DIR / "workspace"
_MAX_BYTES = 12_000  # lebendes Doc: aeltester Anfang faellt weg, Datei bleibt kompakt


def path_for(objective_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(objective_id))[:64] or "unbekannt"
    return _DIR / f"objective-{safe}.md"


def append(objective_id: str, line: str) -> None:
    """Eine Zeile Arbeitsstand anhaengen; Datei auf ~_MAX_BYTES trimmen (ganze Zeilen)."""
    p = path_for(objective_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    entry = f"[{stamp}] {line.strip()}\n"
    text = ""
    if p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
    text += entry
    if len(text.encode("utf-8")) > _MAX_BYTES:
        # von vorne ganze Zeilen abschneiden, bis es wieder passt (das Neueste bleibt)
        lines = text.splitlines(keepends=True)
        while lines and len("".join(lines).encode("utf-8")) > _MAX_BYTES:
            lines.pop(0)
        text = "".join(lines)
    p.write_text(text, encoding="utf-8")


def render(objective_id: str, max_chars: int = 2000) -> str:
    """Der juengste Arbeitsstand (Tail) fuer die Prompt-Injektion; "" wenn leer."""
    p = path_for(objective_id)
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    nl = tail.find("\n")  # nicht mitten in einer Zeile beginnen
    return tail[nl + 1:] if 0 <= nl < len(tail) - 1 else tail
