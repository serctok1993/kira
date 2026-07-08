"""state.db-Backup (Audit-Fund: es gab KEINES — state.db ist Kiras komplettes Gedaechtnis,
Skills, Ziele, Outcome-Ledger und Budget-Historie; ihr Verlust waere der einzige echte
'alles neu aufsetzen'-Fall).

VACUUM INTO = SQLites Online-Backup: konsistente Kopie im laufenden Betrieb, keine
externen Abhaengigkeiten. Laeuft woechentlich ueber das maintenance-Gate im Runner;
behalten werden die juengsten KEEP Kopien in data/backups/.
"""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

KEEP = 4  # rotierend: ~1 Monat Sicherungs-Historie


def _backup_dir() -> Path:
    from core import config

    return Path(config.DATA_DIR) / "backups"


def backup_state_db() -> dict:
    """Konsistente Kopie der state.db anlegen + alte Kopien rotieren. Raist nie."""
    from core import config

    try:
        d = _backup_dir()
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.date.today().isoformat()
        dest = d / f"state-{stamp}.db"
        if dest.exists():  # heute schon gesichert (z.B. nach Neustart) -> fertig
            return {"ok": True, "path": str(dest), "skipped": "existiert"}
        con = sqlite3.connect(config.DB_PATH)
        try:
            con.execute("PRAGMA busy_timeout=15000")
            con.execute("VACUUM INTO ?", (str(dest),))
        finally:
            con.close()
        kopien = sorted(d.glob("state-*.db"))
        for alt in kopien[:-KEEP]:
            alt.unlink(missing_ok=True)
        return {"ok": True, "path": str(dest), "size": dest.stat().st_size,
                "kept": min(len(kopien), KEEP)}
    except Exception as e:  # noqa: BLE001 — Backup-Fehler darf den Betrieb nie stoeren
        return {"ok": False, "error": str(e)[:200]}
