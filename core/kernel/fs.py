"""Atomare Datei-Schreibhilfe: Temp-Datei im Zielordner + os.replace (S8.0).

Hintergrund: data/mcp_servers.json war transient korrupt ('Expecting value:
line 1 column 1') — ein nicht-atomares write_text kann bei Absturz oder
parallelem Zugriff eine halbe Datei hinterlassen. os.replace ist auf Windows
und POSIX atomar, solange Temp und Ziel im selben Verzeichnis liegen.
Alle JSON-Sidecars (mcp_servers, triggers, maintenance, cron, secrets,
autonomy, chat_meta, overrides, models) schreiben ueber diesen Helfer.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    """Schreibt text atomar nach path. Wirft weiter, was das Dateisystem wirft."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
