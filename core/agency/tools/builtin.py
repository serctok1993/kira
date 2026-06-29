"""Eingebaute Werkzeuge — Kyros' erste echte Faehigkeiten.

Bewusst abhaengigkeitsarm (nur httpx + Regex). Spaeter baut Kyros sich weitere
Werkzeuge selbst (synthesize.py).
"""
from __future__ import annotations

import html
import re

import httpx

from core.agency.tools.registry import tool

_UA = {"User-Agent": "Mozilla/5.0 (Prometheus/Kyros)"}


def _strip_html(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


@tool("web_fetch", "Laedt eine URL und gibt den lesbaren Textinhalt zurueck (gekuerzt).",
      {"url": "die vollstaendige URL inkl. https://"})
def web_fetch(url: str, limit: int = 3000) -> str:
    r = httpx.get(url, timeout=20, follow_redirects=True, headers=_UA)
    r.raise_for_status()
    text = _strip_html(r.text)
    return text[:limit] if text else "(kein Textinhalt gefunden)"


@tool("web_search", "Sucht im Web (DuckDuckGo) und liefert die Top-Treffer (Titel + URL).",
      {"query": "die Suchanfrage"})
def web_search(query: str, max_results: int = 5) -> str:
    r = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        timeout=20,
        headers=_UA,
        follow_redirects=True,
    )
    r.raise_for_status()
    hits = re.findall(r'class="result__a"[^>]*href="([^"]+)".*?>(.*?)</a>', r.text, flags=re.DOTALL)
    out = []
    for href, title in hits[:max_results]:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote

            href = unquote(m.group(1))
        out.append(f"- {_strip_html(title)}\n  {href}")
    return "\n".join(out) if out else "(keine Ergebnisse)"
