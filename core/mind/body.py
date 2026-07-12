"""BODY: Kiras Anatomie-Selbstwissen — generiert aus der Wirklichkeit (S5).

Idee: eine Datei, die JEDEM LLM im Harness sofort sagt, welchen Koerper
es bewohnt — modell-agnostisch, zukunftssicher. Zwei Schichten in core/mind/BODY.md:

  1. Kompakt-Kopf (bis <!-- REFERENZ -->): wird in JEDEN System-Prompt injiziert
     (compact()). Handgepflegt + knapp — Kontext-Diaet gilt.
  2. Referenz darunter: liest Kira bei Bedarf selbst (read_file). Enthaelt den
     AUTO-Block zwischen <!-- AUTO:START --> und <!-- AUTO:END -->, den refresh()
     aus der REALITAET rendert (Registry, MCP-Status, DB-Tabellen, Modell-Routing)
     — abgeschrieben statt erinnert, kann also nicht halluzinieren.

Erzaehl-Absaetze pflegt Kira ueber den Evolution-Weg (BODY.md ist MUTABLE).
"""
from __future__ import annotations

import sqlite3
import time

from core.config import DB_PATH, MIND_DIR

_PATH = MIND_DIR / "BODY.md"
_REF_MARK = "<!-- REFERENZ -->"
_AUTO_START = "<!-- AUTO:START -->"
_AUTO_END = "<!-- AUTO:END -->"
_COMPACT_CAP = 1500


def compact() -> str:
    """Der Kompakt-Kopf fuer die System-Prompt-Injektion ('' wenn Datei fehlt)."""
    try:
        text = _PATH.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""
    head = text.split(_REF_MARK, 1)[0].strip()
    return head[:_COMPACT_CAP]


def _render_auto() -> str:
    """Die harten Fakten, frisch abgeschrieben — jede Sektion fail-soft."""
    lines: list[str] = [f"Stand: {time.strftime('%d.%m.%Y %H:%M')} (automatisch generiert — nicht von Hand editieren)"]

    try:
        from core.agency.tools.registry import all_tools

        tools = sorted(t.name for t in all_tools())
        lines.append(f"\n### Werkzeuge ({len(tools)})")
        lines.append(", ".join(tools))
    except Exception as e:  # noqa: BLE001
        lines.append(f"(Werkzeuge nicht lesbar: {e})")

    try:
        from core.agency.mcp import registry_bridge

        status = registry_bridge.server_status()
        if status:
            lines.append("\n### MCP-Server")
            for name, s in status.items():
                lines.append(f"- {name}: {'aktiv' if s.get('enabled') else 'aus'}, "
                             f"{'laeuft' if s.get('running') else 'gestoppt'}, {s.get('tools', 0)} Tools")
    except Exception:  # noqa: BLE001
        pass

    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute("PRAGMA busy_timeout=5000")  # Nebenlaeufigkeit: nie sofort 'locked'

            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE '%_fts%' ORDER BY name")]
        lines.append(f"\n### Datenbank-Tabellen (state.db)")
        lines.append(", ".join(tables))
    except Exception:  # noqa: BLE001
        pass

    try:
        from core.kernel import models

        st = models.status()
        lines.append("\n### Modell-Routing")
        lines.append(f"- default: {st.get('default')} | Eskalation: {st.get('escalation_model')}")
        routing = st.get("routing") or {}
        if routing:
            lines.append("- " + ", ".join(f"{k}={v}" for k, v in routing.items()))
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines)


def refresh() -> dict:
    """AUTO-Block in BODY.md neu schreiben (idempotent). Laeuft taeglich als Wartung."""
    if not _PATH.exists():
        return {"ok": False, "error": "BODY.md fehlt"}
    text = _PATH.read_text(encoding="utf-8")
    if _AUTO_START not in text or _AUTO_END not in text:
        return {"ok": False, "error": "AUTO-Marker fehlen in BODY.md"}
    head, rest = text.split(_AUTO_START, 1)
    _, tail = rest.split(_AUTO_END, 1)
    new = head + _AUTO_START + "\n" + _render_auto() + "\n" + _AUTO_END + tail
    _PATH.write_text(new, encoding="utf-8")
    return {"ok": True, "chars": len(new)}
