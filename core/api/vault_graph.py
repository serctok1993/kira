"""Live-Obsidian-Vault als Graph: liest die echten Markdown-Notizen (gedaechtnis/ + playbooks/)
und ihre [[Verlinkungen]] und baut daraus Knoten + Fäden fuer die Desktop-Wallpaper-Seite (/wall).

Rein lesend, kein LLM, kein Schreibzugriff — nur die Dateien, die der Nutzer in Obsidian pflegt.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.config import ROOT

# [[Ziel]] oder [[Ziel|Alias]] oder [[Ziel#Abschnitt]] -> faengt nur das Ziel (vor | und #)
_WIKILINK = re.compile(r"\[\[([^\]\|#]+)")

# Farbwelt je Vault-Bereich (rgb-Tripel fuer den Canvas)
_GROUP_COLOR = {
    "stammbaum": "176,38,255",   # Lila
    "journal": "0,229,255",      # Cyan
    "playbooks": "57,255,20",    # Gruen
    "vault": "255,45,149",       # Magenta (Rest / unaufgeloeste Ziele)
}


def _group_of(root: Path, p: Path) -> str:
    """Bereich einer Notiz: 'playbooks', der erste Unterordner unter gedaechtnis
    (stammbaum/journal/…) oder 'vault' fuer lose Dateien direkt im Wurzelordner."""
    if root.name == "playbooks":
        return "playbooks"
    rel = p.relative_to(root).parts
    return rel[0] if len(rel) > 1 else "vault"


def _default_roots() -> list[Path]:
    """Kiras Gedaechtnis + optionale echte Obsidian-Vaults aus der Config
    (desktop.vault_paths). So erscheint des Nutzers ganzer Obsidian-Graph, nicht nur die Memo-Dateien."""
    roots = [ROOT / "gedaechtnis", ROOT / "playbooks"]
    try:
        from core.config import CONFIG
        for p in (CONFIG.get("desktop") or {}).get("vault_paths") or []:
            if p:
                roots.append(Path(str(p)).expanduser())
    except Exception:  # noqa: BLE001 — fehlende/kaputte Config darf den Graph nie brechen
        pass
    return roots


def obsidian_vault_name() -> str | None:
    """Name des Obsidian-Vaults (fuer obsidian://open-Links) — der Ordnername des ersten
    konfigurierten desktop.vault_paths, z.B. 'Mein-Vault'."""
    try:
        from core.config import CONFIG
        for p in (CONFIG.get("desktop") or {}).get("vault_paths") or []:
            if p:
                return Path(str(p)).name
    except Exception:  # noqa: BLE001
        pass
    return None


def build_graph(roots: list[Path] | None = None) -> dict:
    """Scannt die Vault-Ordner, baut {nodes, links, counts}.

    nodes: [{id, group, color, heat}]  · links: [{source, target}]  ·
    counts: {notes, links} (notes = echte .md-Dateien, links = eindeutige Verbindungen).
    heat 0..1 = Frische der Notiz (mtime, ~2 Wochen Halbwertszeit) — die Galaxie
    laesst frisch beruehrte Notizen heller und weisser leuchten.
    """
    import math
    import time

    if roots is None:
        roots = _default_roots()

    files: list[tuple[Path, Path]] = []
    for r in roots:
        if r.exists():
            files.extend((r, p) for p in sorted(r.rglob("*.md")))

    nodes: dict[str, dict] = {}   # key = stem.lower() -> node
    note_count = 0
    jetzt = time.time()

    def _add(stem: str, group: str, heat: float = 0.0) -> None:
        key = stem.lower()
        if key not in nodes:
            nodes[key] = {"id": stem, "group": group,
                          "color": _GROUP_COLOR.get(group, _GROUP_COLOR["vault"]),
                          "heat": round(heat, 3)}

    for root, p in files:
        note_count += 1
        try:
            tage = max(0.0, (jetzt - p.stat().st_mtime) / 86400)
            heat = math.exp(-tage / 14)
        except OSError:
            heat = 0.0
        _add(p.stem, _group_of(root, p), heat)

    links: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for _root, p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001 — eine kaputte Datei darf den Graph nicht sprengen
            continue
        src = p.stem.lower()
        for m in _WIKILINK.finditer(text):
            tgt = m.group(1).strip()
            if not tgt:
                continue
            tk = tgt.lower()
            if tk not in nodes:                          # unaufgeloestes Ziel: Obsidian zeigt es auch
                _add(tgt, "vault")
            if tk == src:
                continue
            edge = (src, tk)
            if edge in seen:
                continue
            seen.add(edge)
            links.append({"source": nodes[src]["id"], "target": nodes[tk]["id"]})

    return {
        "nodes": list(nodes.values()),
        "links": links,
        "counts": {"notes": note_count, "links": len(links)},
        "vault": obsidian_vault_name(),   # fuer obsidian://open beim Node-Klick
    }
