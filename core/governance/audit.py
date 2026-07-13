"""Audit: append-only Protokoll aller nach AUSSEN wirkenden Aktionen.

Geld, E-Mails, Posts, Vertraege — mit Reversibilitaets-Info. Schuetzt den Nutzer:
saubere Buecher, jederzeit pruefbar, und (wo moeglich) rueckrollbar.

Feedback 13.07. (Fund: Bot-Token stand im Klartext im Cockpit-Audit): ALLES, was
wie ein Secret aussieht, wird GESCHWAERZT — beim Schreiben (record) UND beim Lesen
(recent, fuer Alt-Eintraege). Die Lektion des Agenten selbst: "schwaerze API-Keys
vollstaendig" — sie gilt auch fuer die eigene Oberflaeche.
"""
from __future__ import annotations

import re

from core.kernel import events

_SECRET_MUSTER = [
    re.compile(r"\d{8,12}:[A-Za-z0-9_-]{30,}"),               # Telegram-Bot-Token (auch in bot…-URLs)
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),                   # sk-Keys (OpenRouter/OpenAI)
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),                    # GitHub-Token
    re.compile(r"\bAKIA[A-Z0-9]{12,}"),                       # AWS
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(token|api[_-]?key|secret|passwor[dt]|app[_-]?password)\b(\s*[=:]\s*)['\"]?[^\s'\"]{8,}"),
]


def schwaerze(text: str) -> str:
    """Secret-Muster durch ••• ersetzen — Schluesselnamen bleiben lesbar."""
    t = str(text or "")
    for m in _SECRET_MUSTER[:-1]:
        t = m.sub("•••geschwaerzt•••", t)
    t = _SECRET_MUSTER[-1].sub(lambda mo: f"{mo.group(1)}{mo.group(2)}•••geschwaerzt•••", t)
    return t


def _schwaerze_payload(p: dict) -> dict:
    out = dict(p or {})
    if out.get("target"):
        out["target"] = schwaerze(out["target"])
    det = out.get("details")
    if isinstance(det, dict):
        out["details"] = {k: (schwaerze(v) if isinstance(v, str) else v) for k, v in det.items()}
    return out


def record(
    action: str,
    target: str = "",
    details: dict | None = None,
    reversible: bool = False,
    undo: str | None = None,
) -> str:
    payload = _schwaerze_payload(
        {"action": action, "target": target, "details": details or {}})
    payload.update({"reversible": reversible, "undo": undo})
    return events.emit("audit", payload)


def recent(limit: int = 50) -> list[dict]:
    """Juengste Audit-Eintraege — Alt-Eintraege (vor der Schwaerzung geschrieben)
    werden beim LESEN geschwaerzt, damit nie ein Secret die Oberflaeche erreicht."""
    out = []
    for e in events.recent(3000):
        if e["type"] != "audit":
            continue
        e = dict(e)
        e["payload"] = _schwaerze_payload(e.get("payload") or {})
        out.append(e)
        if len(out) >= limit:
            break
    return out
