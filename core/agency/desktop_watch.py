"""Desktop-Pflege (S8.5): Kira haelt des Nutzers Ablage in Ordnung — VORSCHLAG-first.

Ein taeglicher, LOKALER Scan (classify-Modell, 0 EUR) sieht sich lose Dateien in
konfigurierten Ordnern an (Default: Desktop) und schlaegt eine Einsortierung vor.
NICHTS wird verschoben, bis der Nutzer den Vorschlag in der Freigabe-Inbox bestaetigt —
und erst der Auto-Modus (spaeter, per Schalter) wuerde ohne Rueckfrage sortieren.

Config: data/desktop_watch.json
  {"enabled": true, "folders": ["<Desktop>"], "auto": false, "ignore": [...]}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.config import DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write

_CFG = DATA_DIR / "desktop_watch.json"
# Grobe Kategorien -> Zielordner (relativ zum jeweils gescannten Ordner).
_CATS = {
    "rechnung": "Dokumente/Rechnungen", "beleg": "Dokumente/Rechnungen",
    "vertrag": "Dokumente/Vertraege", "brief": "Dokumente/Briefe",
    "bild": "Bilder", "foto": "Bilder", "screenshot": "Bilder/Screenshots",
    "installer": "Installer", "setup": "Installer",
    "archiv": "Archive", "zip": "Archive",
    "code": "Code", "projekt": "Projekte",
}
_EXT_HINT = {
    ".pdf": "dokument", ".doc": "dokument", ".docx": "dokument", ".txt": "dokument",
    ".png": "bild", ".jpg": "bild", ".jpeg": "bild", ".gif": "bild", ".webp": "bild",
    ".zip": "archiv", ".rar": "archiv", ".7z": "archiv",
    ".exe": "installer", ".msi": "installer",
    ".py": "code", ".js": "code", ".ts": "code", ".json": "code", ".md": "dokument",
}


def _default_cfg() -> dict:
    return {"enabled": False, "auto": False,
            "folders": [str(Path.home() / "Desktop")],
            "ignore": [".lnk", "desktop.ini", "Kira"]}


def load_cfg() -> dict:
    try:
        d = json.loads(_CFG.read_text(encoding="utf-8"))
        return {**_default_cfg(), **d}
    except Exception:  # noqa: BLE001
        return _default_cfg()


def save_cfg(cfg: dict) -> None:
    atomic_write(_CFG, json.dumps(cfg, indent=2, ensure_ascii=False))


def _guess_category(name: str) -> str:
    low = name.lower()
    for key, target in _CATS.items():
        if key in low:
            return target
    return _CATS.get(_EXT_HINT.get(Path(name).suffix.lower(), ""), "")


def scan(cfg: dict | None = None, max_files: int = 60) -> dict:
    """Lose Dateien einsammeln und je einen Zielordner vorschlagen. Reiner Lese-Scan,
    kein LLM noetig (Heuristik ueber Endung/Name). Gibt {suggestions:[...], scanned:N}."""
    cfg = cfg or load_cfg()
    ignore = [s.lower() for s in cfg.get("ignore", [])]
    suggestions: list[dict] = []
    scanned = 0
    for folder in cfg.get("folders", []):
        base = Path(folder).expanduser()
        if not base.is_dir():
            continue
        for f in sorted(base.iterdir()):
            if not f.is_file():
                continue
            if any(ig in f.name.lower() for ig in ignore):
                continue
            scanned += 1
            if len(suggestions) >= max_files:
                break
            target = _guess_category(f.name)
            if target:
                suggestions.append({"file": f.name, "path": str(f),
                                    "target": target, "bytes": f.stat().st_size})
    return {"scanned": scanned, "suggestions": suggestions, "folders": cfg.get("folders", [])}


def propose(cfg: dict | None = None) -> dict:
    """Scan -> EIN Freigabe-Eintrag mit dem Sortiervorschlag. Verschiebt NICHTS.

    Auto-Modus (cfg.auto) ist als Schalter vorgesehen, aber bewusst noch NICHT
    verdrahtet — S8.5 liefert Vorschlaege, kein automatisches Verschieben."""
    cfg = cfg or load_cfg()
    if not cfg.get("enabled"):
        return {"skipped": "disabled"}
    res = scan(cfg)
    sug = res["suggestions"]
    if not sug:
        return {"suggestions": 0, "scanned": res["scanned"]}
    by_target: dict[str, list[str]] = {}
    for s in sug:
        by_target.setdefault(s["target"], []).append(s["file"])
    lines = [f"{len(files)} Datei(en) -> {tgt}: " + ", ".join(f[:40] for f in files[:6])
             + (" …" if len(files) > 6 else "") for tgt, files in by_target.items()]
    detail = ("Vorschlag zum Aufraeumen (nichts wurde verschoben — du entscheidest):\n\n"
              + "\n".join(lines)
              + "\n\nFreigeben = ich sortiere so ein (mit Undo-Spur im Protokoll).")
    try:
        from core.agency import approvals

        aid = approvals.create(f"Desktop aufraeumen: {len(sug)} Dateien",
                               kind="generic", source="kira", detail=detail)
    except Exception as e:  # noqa: BLE001
        events.emit("desktop_watch_error", {"error": str(e)[:200]})
        return {"error": str(e)[:200]}
    events.emit("desktop_scan", {"suggestions": len(sug), "targets": list(by_target)})
    return {"suggestions": len(sug), "approval_id": aid}
