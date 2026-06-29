"""Eingebaute Werkzeuge — Kiras erste echte Faehigkeiten.

Bewusst abhaengigkeitsarm (nur httpx + Regex). Spaeter baut Kira sich weitere
Werkzeuge selbst (synthesize.py).
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import httpx

from core.agency.tools.registry import tool

_UA = {"User-Agent": "Mozilla/5.0 (Kira/Kira)"}


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


# --- Datei-Haende: Kira kann auf dem PC lesen/schreiben/auflisten/Ordner anlegen ---
@tool("read_file", "Liest eine Datei vom PC und gibt den Textinhalt zurueck.", {"path": "Dateipfad"})
def read_file(path: str, max_chars: int = 8000) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"(Datei nicht gefunden: {p})"
    if p.is_dir():
        return f"(Das ist ein Ordner, keine Datei: {p})"
    return p.read_text(encoding="utf-8", errors="replace")[:max_chars]


@tool("write_file", "Schreibt Text in eine Datei (erstellt sie / ueberschreibt). Legt fehlende Ordner an.",
      {"path": "Dateipfad", "content": "der Inhalt"})
def write_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(content), encoding="utf-8")
    return f"OK, geschrieben: {p} ({len(str(content))} Zeichen)"


@tool("append_file", "Haengt Text an eine Datei an (erstellt sie bei Bedarf).",
      {"path": "Dateipfad", "content": "anzuhaengender Text"})
def append_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(str(content))
    return f"OK, angehaengt an {p}"


@tool("list_dir", "Listet Dateien und Ordner in einem Verzeichnis.", {"path": "Verzeichnis (Standard: aktuell)"})
def list_dir(path: str = ".") -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"(Verzeichnis nicht gefunden: {p})"
    items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    lines = [("[DIR] " if i.is_dir() else "      ") + i.name for i in items[:200]]
    return "\n".join(lines) if lines else "(leer)"


@tool("make_dir", "Erstellt einen Ordner (inklusive Elternordner).", {"path": "Ordnerpfad"})
def make_dir(path: str) -> str:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return f"OK, Ordner angelegt: {p}"


@tool("request_secret",
      "Fordert einen Zugang/Key an, den du brauchst. Sergen traegt ihn sicher im Dashboard "
      "(Zugaenge) ein. NICHT im Chat nach Passwoertern/Keys fragen.",
      {"name": "Env-Name, z.B. OPENROUTER_API_KEY", "reason": "wofuer du ihn brauchst"})
def request_secret(name: str, reason: str = "") -> str:
    from core.governance import secrets

    secrets.request(name, reason)
    return f"Zugang '{name}' angefordert. Sergen traegt ihn im Dashboard unter 'Zugaenge' ein."


@tool("remember_fact",
      "Speichere eine wichtige DAUER-Erinnerung (Fakt ueber Sergen, ein Projekt, eine "
      "Entscheidung, eine Praeferenz). Wird spaeter bevorzugt wieder erinnert.",
      {"fact": "die zu merkende Information, knapp formuliert"})
def remember_fact(fact: str) -> str:
    from core.mind.memory import store as memory

    memory.init_memory()
    memory.remember(fact, role="self", kind="fact")
    return f"Dauerhaft gemerkt: {fact[:90]}"


@tool("self_edit",
      "Bearbeite deinen EIGENEN Code (eine Datei im Projekt, z.B. das Dashboard oder ein Tool). "
      "Sicher: Python-Syntax-Check + Git-Commit, automatischer Rollback bei Fehler. "
      "Danach muss der betroffene Dienst neu gestartet werden.",
      {"path": "Datei relativ zum Projekt, z.B. core/api/server.py", "instruction": "was genau geaendert werden soll"})
def self_edit(path: str, instruction: str) -> str:
    from core.agency.selfdev import self_edit as _se

    r = _se(path, instruction)
    return ("OK — " + r.get("note", "")) if r.get("ok") else ("Fehlgeschlagen: " + r.get("error", ""))
