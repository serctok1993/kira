"""Identitaet (W2): DIE einzige Namensquelle des Harness.

Werksname ist "Kira", der Nutzer benennt beim Onboarding um — beides lebt in
CONFIG["identity"] (config.yaml als Default, Personalisierung zur Laufzeit via
set_override -> data/overrides.json, gitignored). Alle Oberflaechen, Kanaele,
Prompts und Werkzeug-Texte holen die Namen HIER — nie hart verdrahtet.

Bewusst OHNE Cache (Muster feature_on): ein Override wirkt sofort, ohne Neustart.
"""
from __future__ import annotations

from core.config import CONFIG


def agent_name() -> str:
    """Name des Agenten (Werksname 'Kira'; der selbst-/nutzergewaehlte gewinnt)."""
    ident_cfg = CONFIG.get("identity") or {}
    return str(ident_cfg.get("partner_name") or ident_cfg.get("harness_name") or "Kira").strip() or "Kira"


def user_name() -> str:
    """Name des Menschen, dem dieser Agent dient (Werks-Fallback: 'Partner')."""
    ident_cfg = CONFIG.get("identity") or {}
    return str(ident_cfg.get("user") or "Partner").strip() or "Partner"


def ident() -> dict:
    """Beides als dict — fuer Injektionen (UI/Prompts) und den Trainings-Haken."""
    return {"agent": agent_name(), "user": user_name()}


def genitiv(name: str) -> str:
    """Deutscher Genitiv: 'der Nutzer' -> 'des Nutzers', 'Alex' -> 'Alex'' (s/x/z-Endung)."""
    n = (name or "").strip()
    return n + ("'" if n[-1:].lower() in ("s", "x", "z", "ß") else "s")


def render(text: str) -> str:
    """{{AGENT_NAME}}/{{USER_NAME}}-Platzhalter fuellen (Templates, Werkzeug-Texte).

    {{USER_NAME_S}} ist der Genitiv — damit Beschreibungen natuerlich klingen und
    die Instanz des Entwicklers byte-identisch bleibt."""
    a, u = agent_name(), user_name()
    return (text.replace("{{USER_NAME_S}}", genitiv(u))
                .replace("{{USER_NAME}}", u)
                .replace("{{AGENT_NAME}}", a))
