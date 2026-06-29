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


# --- Dashboard-Steuerung: Kira pflegt Monitor & Modell selbst (erscheint sofort im Cockpit) ---
@tool("watch_add",
      "Fuegt dem Web-/News-Monitor eine Beobachtung hinzu (erscheint sofort im Dashboard). "
      "kind='feed' fuer eine RSS-URL, kind='search' fuer ein Web-Thema/Suchbegriff.",
      {"kind": "'feed' oder 'search'", "value": "RSS-URL oder Suchbegriff", "label": "kurzer Name (optional)"})
def watch_add(kind: str, value: str, label: str = "") -> str:
    from core.agency.connectors import news_monitor

    w = news_monitor.add_watch(kind, value, label)
    return f"Beobachtung angelegt: {w['label']} [{w['kind']}] -> {w['value']}"


@tool("watch_list", "Zeigt alle aktiven Monitor-Beobachtungen (Feeds/Themen) mit ihrer id.", {})
def watch_list() -> str:
    from core.agency.connectors import news_monitor

    ws = news_monitor.list_watches()
    if not ws:
        return "(keine Beobachtungen)"
    return "\n".join(f"- {w['label']} [{w['kind']}] {w['value']} (id={w['id']})" for w in ws)


@tool("watch_remove", "Entfernt eine Monitor-Beobachtung anhand ihrer id (siehe watch_list).",
      {"id": "die id der Beobachtung"})
def watch_remove(id: str) -> str:
    from core.agency.connectors import news_monitor

    return "Entfernt." if news_monitor.remove_watch(id) else "Keine Beobachtung mit dieser id gefunden."


@tool("switch_model",
      "Wechselt dein aktives Hirn (Default-Modell), sofort live + im Dashboard sichtbar. "
      "Beispiele: 'ollama_chat/qwythos' (lokal, 0 EUR) oder 'openrouter/z-ai/glm-5.2' (stark, Cloud).",
      {"model": "die Modell-ID im litellm-Format"})
def switch_model(model: str) -> str:
    from core.kernel import models

    return f"Aktives Modell jetzt: {models.set_model(model.strip())}"


@tool("list_models", "Zeigt das aktive Modell, das Eskalations-Modell und die lokal verfuegbaren Ollama-Modelle.", {})
def list_models() -> str:
    from core.kernel import models

    s = models.status()
    local = ", ".join(s.get("ollama_local", [])) or "(keine)"
    return f"Aktiv: {s['default']} | Eskalation: {s['escalation_model']} | Lokal: {local}"


@tool("set_context",
      "Setzt Kontextfenster (num_ctx) und/oder max. Ausgabetokens (max_tokens), sofort live. "
      "0 lassen heisst 'nicht aendern'.",
      {"num_ctx": "Kontext-Token, z.B. 16384", "max_tokens": "max. Ausgabetokens, z.B. 8192"})
def set_context(num_ctx: int = 0, max_tokens: int = 0) -> str:
    from core.kernel import models

    r = models.set_params(num_ctx=int(num_ctx) or None, max_tokens=int(max_tokens) or None)
    return f"Gesetzt: num_ctx={r['num_ctx']}, max_tokens={r['max_tokens']} (laedt beim naechsten Aufruf neu)."


@tool("cron_add",
      "Plant eine WIEDERKEHRENDE Aufgabe (erscheint sofort im Dashboard unter 'Cron'). "
      "Zeitplan: '30m' oder '2h' (Intervall) ODER '08:00' (taeglich zu der Uhrzeit).",
      {"label": "kurzer Name", "prompt": "was du dann jeweils tun sollst", "schedule": "z.B. '30m', '2h' oder '08:00'"})
def cron_add(label: str, prompt: str, schedule: str) -> str:
    import datetime as _dt

    from core.agency.missions import cron

    j = cron.add_job(label, prompt, schedule)
    nxt = _dt.datetime.fromtimestamp(j["next_run"]).strftime("%d.%m. %H:%M")
    return f"Geplant: {j['label']} ({j['schedule_text']}) — naechster Lauf {nxt}."


@tool("cron_list", "Zeigt alle geplanten (Cron-)Aufgaben mit Zeitplan und id.", {})
def cron_list() -> str:
    from core.agency.missions import cron

    js = cron.list_jobs()
    if not js:
        return "(keine geplanten Aufgaben)"
    return "\n".join(f"- {j['label']} ({j['schedule_text']}) {'an' if j['enabled'] else 'aus'} (id={j['id']})" for j in js)


@tool("plan_and_execute",
      "Fuer GROSSE, mehrstufige Aufgaben: zerlege sie selbst in einen Plan und arbeite ihn Schritt "
      "fuer Schritt mit Werkzeugen ab (inkl. self_edit zum Coden). Nutze das, wenn eine Aufgabe "
      "mehrere Teilschritte braucht.",
      {"task": "die komplette Gesamtaufgabe in einem Satz"})
def plan_and_execute(task: str) -> str:
    from core.agency.act import plan_and_execute as _pe

    return _pe(task, escalate=True)
