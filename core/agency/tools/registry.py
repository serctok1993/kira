"""Tool-Registry: Werkzeuge werden per @tool-Dekorator registriert.

Jedes Werkzeug hat Name, Beschreibung, Parameter (Name -> Beschreibung) und die
Funktion. manifest() erzeugt die Werkzeug-Liste fuer den Prompt.
Synthetisierte Werkzeuge (Phase 3, naechster Schritt) registrieren sich genauso.
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


_REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, params: dict[str, str] | None = None):
    def deco(func: Callable) -> Callable:
        _REGISTRY[name] = Tool(name, description, func, params or {})
        return func

    return deco


def register(name: str, description: str, func: Callable, params: dict[str, str] | None = None) -> None:
    _REGISTRY[name] = Tool(name, description, func, params or {})


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def unregister(name: str) -> bool:
    """Ein Werkzeug wieder entfernen (z.B. wenn ein MCP-Server abgeschaltet wird)."""
    return _REGISTRY.pop(name, None) is not None


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def manifest() -> str:
    if not _REGISTRY:
        return "(keine Werkzeuge verfuegbar)"
    lines = []
    # Snapshot: die MCP-Bruecke registriert Werkzeuge zur LAUFZEIT (anderer Thread) —
    # direkte Dict-Iteration kann dann 'dictionary changed size' werfen.
    for t in list(_REGISTRY.values()):
        params = ", ".join(f'"{k}": {v}' for k, v in t.params.items()) or "keine"
        lines.append(f"- {t.name} (Argumente: {params}): {t.description}")
    return "\n".join(lines)


def tool_schemas() -> list[dict]:
    """OpenAI-Function-Calling-Schema fuer alle Werkzeuge (natives Tool-Calling).

    Alle Argumente als String (die Tool-Funktionen casten selbst). 'required' ohne
    als optional markierte Parameter (Beschreibung enthaelt 'optional'/'Standard')."""
    schemas: list[dict] = []
    for t in list(_REGISTRY.values()):  # Snapshot (Laufzeit-Registrierung, s. manifest)
        props = {k: {"type": "string", "description": v} for k, v in t.params.items()}
        required = [k for k, v in t.params.items()
                    if "optional" not in v.lower() and "standard" not in v.lower()]
        schemas.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        })
    return schemas
