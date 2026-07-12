"""Mind-Seeding (W2): neutrale Templates -> personalisierte Live-Dateien.

render_mind(agent, user) fuellt die {{AGENT_NAME}}/{{USER_NAME}}-Platzhalter der
Templates (core/mind/templates/) und schreibt die Live-.md nach core/mind/ —
atomar, und NIE ungefragt ueber bestehende Dateien (force=True nur vom
Werkszustand/Onboarding, W3). Fehlt eine Live-Datei, rendert agent._read()
das Template ohnehin in-memory — seeding macht den Zustand nur dauerhaft.
"""
from __future__ import annotations

from core.config import MIND_DIR
from core.kernel.fs import atomic_write

TEMPLATES = ("SOUL.md", "GOAL.md", "USER.md", "PERSONA.md", "BODY.md")


def render_mind(agent: str | None = None, user: str | None = None,
                force: bool = False) -> dict:
    """Templates -> Live-Dateien. Rueckgabe: {datei: 'geschrieben'|'uebersprungen'|'fehlt'}."""
    from core import identity

    a = (agent or identity.agent_name()).strip()
    u = (user or identity.user_name()).strip()
    out: dict[str, str] = {}
    for name in TEMPLATES:
        tpl = MIND_DIR / "templates" / name
        ziel = tpl.parent.parent / name
        if not tpl.exists():
            out[name] = "fehlt"
            continue
        if ziel.exists() and not force:
            out[name] = "uebersprungen"  # Live-Identitaet nie ungefragt ueberschreiben
            continue
        text = (tpl.read_text(encoding="utf-8")
                .replace("{{USER_NAME_S}}", u + ("'" if u[-1:].lower() in ("s", "x", "z") else "s"))
                .replace("{{USER_NAME}}", u)
                .replace("{{AGENT_NAME}}", a))
        atomic_write(ziel, text)
        out[name] = "geschrieben"
    return out
