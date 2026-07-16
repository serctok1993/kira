"""Tool-Registry: Werkzeuge werden per @tool-Dekorator registriert.

Jedes Werkzeug hat Name, Beschreibung, Parameter (Name -> Beschreibung) und die
Funktion. manifest() erzeugt die Werkzeug-Liste fuer den Prompt.
Synthetisierte Werkzeuge (Phase 3, naechster Schritt) registrieren sich genauso.

Feature-Gating (S12 Rezentrierung): Werkzeuge koennen mit feature="business" etc.
getaggt werden. Ist das Flag (config.yaml features:) aus, verschwindet das Werkzeug
aus manifest()/tool_schemas()/get()/all_tools() — Code und Registrierung bleiben,
ein Toggle (set_override) holt es ohne Neustart zurueck. get() liefert dann None,
wodurch der Lehr-Fehlerpfad in act.py greift ("Werkzeug existiert nicht ...").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    func: Callable
    params: dict[str, str]
    feature: str = ""  # leer = immer an; sonst nur bei feature_on(feature)


_REGISTRY: dict[str, Tool] = {}


def _enabled(t: Tool) -> bool:
    if not t.feature:
        return True
    from core.config import feature_on  # lazy: liest CONFIG live -> Toggle wirkt sofort

    return feature_on(t.feature)


def _render(text: str) -> str:
    """W2: {{AGENT_NAME}}/{{USER_NAME}}/{{USER_NAME_S}} in Werkzeug-Texten fuellen —
    zur LESEZEIT (manifest/tool_schemas), damit ein Namens-Override sofort wirkt.
    Traegt der Text keine Platzhalter, ist das ein No-Op (byte-identisch)."""
    if "{{" not in text:
        return text
    from core import identity  # lazy — kein Import-Zyklus

    return identity.render(text)


def tool(name: str, description: str, params: dict[str, str] | None = None, feature: str = ""):
    def deco(func: Callable) -> Callable:
        _REGISTRY[name] = Tool(name, description, func, params or {}, feature)
        return func

    return deco


def register(name: str, description: str, func: Callable, params: dict[str, str] | None = None,
             feature: str = "") -> None:
    _REGISTRY[name] = Tool(name, description, func, params or {}, feature)


def get(name: str) -> Tool | None:
    t = _REGISTRY.get(name)
    return t if t is not None and _enabled(t) else None


def unregister(name: str) -> bool:
    """Ein Werkzeug wieder entfernen (z.B. wenn ein MCP-Server abgeschaltet wird)."""
    return _REGISTRY.pop(name, None) is not None


def all_tools(include_disabled: bool = False) -> list[Tool]:
    tools = list(_REGISTRY.values())
    if include_disabled:
        return tools
    return [t for t in tools if _enabled(t)]


def manifest(nur: frozenset[str] | set[str] | None = None) -> str:
    # Snapshot: die MCP-Bruecke registriert Werkzeuge zur LAUFZEIT (anderer Thread) —
    # direkte Dict-Iteration kann dann 'dictionary changed size' werfen.
    # P5: 'nur' = Rollen-Toolset (rollen.toolset) — None bleibt byte-identisch zur Vollflotte.
    lines = []
    for t in list(_REGISTRY.values()):
        if not _enabled(t) or (nur is not None and t.name not in nur):
            continue
        params = ", ".join(f'"{k}": {_render(v)}' for k, v in t.params.items()) or "keine"
        lines.append(f"- {t.name} (Argumente: {params}): {_render(t.description)}")
    return "\n".join(lines) if lines else "(keine Werkzeuge verfuegbar)"


def tool_schemas(nur: frozenset[str] | set[str] | None = None) -> list[dict]:
    """OpenAI-Function-Calling-Schema fuer alle Werkzeuge (natives Tool-Calling).

    Alle Argumente als String (die Tool-Funktionen casten selbst). 'required' ohne
    als optional markierte Parameter (Beschreibung enthaelt 'optional'/'Standard').
    P5: 'nur' filtert auf ein Rollen-Toolset; None = volle Flotte (unveraendert)."""
    schemas: list[dict] = []
    for t in list(_REGISTRY.values()):  # Snapshot (Laufzeit-Registrierung, s. manifest)
        if not _enabled(t) or (nur is not None and t.name not in nur):
            continue
        props = {k: {"type": "string", "description": _render(v)} for k, v in t.params.items()}
        required = [k for k, v in t.params.items()
                    if "optional" not in v.lower() and "standard" not in v.lower()]
        schemas.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": _render(t.description),
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        })
    return schemas
