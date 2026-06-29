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


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def manifest() -> str:
    if not _REGISTRY:
        return "(keine Werkzeuge verfuegbar)"
    lines = []
    for t in _REGISTRY.values():
        params = ", ".join(f'"{k}": {v}' for k, v in t.params.items()) or "keine"
        lines.append(f"- {t.name} (Argumente: {params}): {t.description}")
    return "\n".join(lines)
