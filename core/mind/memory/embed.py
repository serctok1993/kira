"""Embeddings fuer semantisches Erinnern — lokal via Ollama (nomic-embed-text, 0 EUR).

Wird beim Speichern (pro Erinnerung) und beim Abrufen (Anfrage) benutzt. Faellt
still aus (gibt None), wenn Ollama/Modell nicht verfuegbar ist -> dann nutzt der
Recall automatisch den Stichwort-/Recency-Fallback.
"""
from __future__ import annotations

import math

import httpx

from core.config import CONFIG

_MODEL = CONFIG["models"].get("embeddings", "ollama/nomic-embed-text").split("/", 1)[-1]


def embed(text: str) -> list[float] | None:
    if not text:
        return None
    try:
        r = httpx.post(
            "http://localhost:11434/api/embeddings",
            json={"model": _MODEL, "prompt": text[:2000]},
            timeout=20,
        )
        v = r.json().get("embedding")
        return v if v else None
    except Exception:
        return None


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else -1.0
