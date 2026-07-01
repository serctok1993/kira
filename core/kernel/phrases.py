"""Kiras Denk-/Arbeits-Wörter — rotierender Katalog im Claude-Code-Stil.

Kurze englische Gerundien („Thinking…", „Cooking…"), die als „was ich gerade
tue"-Anzeige rotieren — auf Telegram (Arbeits-Zeile) UND im Cockpit (Shimmer).
Eine Quelle, beide Oberflächen ziehen daraus. Anzeige jeweils mit „…".
"""
from __future__ import annotations

import random

# Ein-Wort-Gerundien (Claude-Code-Vibe + ein paar coole Extras).
THINKING_PHRASES: list[str] = [
    "Thinking", "Cooking", "Percolating", "Simmering", "Brewing", "Pondering",
    "Crunching", "Conjuring", "Wrangling", "Synthesizing", "Compiling", "Rendering",
    "Hacking", "Computing", "Scheming", "Manifesting", "Channeling", "Vibing",
    "Transmuting", "Spelunking", "Noodling", "Mulling", "Ruminating", "Deliberating",
    "Formulating", "Processing", "Calculating", "Reticulating", "Herding", "Untangling",
    "Decoding", "Assembling", "Forging", "Sculpting", "Distilling", "Marinating",
    "Baking", "Whisking", "Orchestrating", "Architecting", "Devising", "Plotting",
    "Puzzling", "Unraveling", "Bootstrapping", "Buffering", "Caffeinating",
    "Incubating", "Overclocking", "Summoning", "Divining", "Finagling", "Whirring",
    "Galaxy-braining", "Cogitating", "Tinkering",
]

# Rückwärts-kompatibler Alias (falls jemand THINKING_WORDS erwartet).
THINKING_WORDS = THINKING_PHRASES


def next_phrase(prev: str | None = None) -> str:
    """Zufälliges Wort, aber nie zweimal dasselbe hintereinander."""
    if len(THINKING_PHRASES) < 2:
        return THINKING_PHRASES[0] if THINKING_PHRASES else "Thinking"
    pick = random.choice(THINKING_PHRASES)
    while pick == prev:
        pick = random.choice(THINKING_PHRASES)
    return pick
