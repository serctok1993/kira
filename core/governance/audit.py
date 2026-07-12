"""Audit: append-only Protokoll aller nach AUSSEN wirkenden Aktionen.

Geld, E-Mails, Posts, Vertraege — mit Reversibilitaets-Info. Schuetzt den Nutzer:
saubere Buecher, jederzeit pruefbar, und (wo moeglich) rueckrollbar. Sobald echte
Connectors (Mail/Social/Geld) live gehen, laufen ihre Aktionen hier durch.
"""
from __future__ import annotations

from core.kernel import events


def record(
    action: str,
    target: str = "",
    details: dict | None = None,
    reversible: bool = False,
    undo: str | None = None,
) -> str:
    return events.emit(
        "audit",
        {"action": action, "target": target, "details": details or {}, "reversible": reversible, "undo": undo},
    )


def recent(limit: int = 50) -> list[dict]:
    return [e for e in events.recent(3000) if e["type"] == "audit"][:limit]
