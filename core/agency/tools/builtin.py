"""Eingebaute Werkzeuge — Kiras erste echte Faehigkeiten.

Bewusst abhaengigkeitsarm (nur httpx + Regex). Spaeter baut Kira sich weitere
Werkzeuge selbst (synthesize.py).
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

from core import identity as _id
from core.agency.tools.registry import tool
from core.config import MIND_DIR, ROOT
from core.kernel import events

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Schreibgeschuetzte Dateien: die Verfassung darf KEIN Werkzeug anfassen.
# (write_file hatte frueher keinerlei Pfadschutz — so entstanden Root-Strays
# und die Verfassung war de facto beschreibbar.)
_PROTECTED = {(MIND_DIR / "constitution.md").resolve()}

# Quelltext-Endungen: eine BESTEHENDE Datei dieser Art IM Repo darf write_file NICHT
# komplett ueberschreiben — das umginge self_edit/edit_datei (Verify + Gate + Diff).
# Neue Dateien, Nicht-Code (.md/.json/.txt/.yaml …) und alles AUSSERHALB des Repos
# bleiben frei — Flexibilitaet bleibt oberste Regel.
_CODE_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".css", ".scss",
             ".html", ".vue", ".svelte", ".go", ".rs", ".java", ".kt", ".c", ".cc",
             ".cpp", ".h", ".hpp", ".rb", ".php", ".sh", ".ps1", ".sql"}


def _write_guard(p: Path, tool_name: str) -> str | None:
    """Liefert einen Blockier-Text, wenn das Ziel schreibgeschuetzt ist, sonst None."""
    try:
        rp = p.resolve()
    except OSError:
        rp = p
    if rp in _PROTECTED:
        try:
            events.emit("write_blocked", {"path": str(rp), "tool": tool_name})
        except Exception:  # noqa: BLE001
            pass
        return ("BLOCKIERT: constitution.md ist unantastbar (Verfassung). "
                f"Aenderungen daran macht nur {_id.user_name()} selbst via Git.")
    # Loch geschlossen: bestehende Code-Datei im Repo nicht blind komplett ueberschreiben.
    if rp.suffix.lower() in _CODE_EXT and rp.exists():
        try:
            in_repo = rp.is_relative_to(ROOT.resolve())
        except Exception:  # noqa: BLE001
            in_repo = False
        if in_repo:
            try:
                rel = rp.relative_to(ROOT.resolve()).as_posix()
            except Exception:  # noqa: BLE001
                rel = str(rp)
            try:
                events.emit("write_blocked",
                            {"path": str(rp), "tool": tool_name, "grund": "code_overwrite"})
            except Exception:  # noqa: BLE001
                pass
            return (f"BLOCKIERT: bestehende Code-Datei ({rel}) nicht mit {tool_name} komplett "
                    "ueberschreiben — das umgeht Verify + Gate. Nutze edit_datei fuer gezielte "
                    "Aenderungen (exakter Suchtext) oder self_edit fuer groessere Umbauten.")
    return None


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


def _fmt_hits(hits: list[tuple[str, str, str]], n: int) -> str | None:
    """(titel, url, snippet)-Treffer einheitlich formatieren — None bei leer."""
    if not hits:
        return None
    return "\n".join(f"- {t}\n  {u}" + (f"\n  {_strip_html(s)[:180]}" if s else "")
                     for t, u, s in hits[:n])


def _search_brave(query: str, n: int, key: str) -> tuple[str | None, str]:
    r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                  params={"q": query, "count": n},
                  headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=20)
    if r.status_code == 200:
        res = (r.json().get("web") or {}).get("results", [])
        return _fmt_hits([(x.get("title", ""), x.get("url", ""), x.get("description", ""))
                          for x in res], n), ""
    if r.status_code == 429:
        return None, "Brave: Kontingent aufgebraucht"
    if r.status_code in (401, 422):
        return None, "Brave: Key ungueltig (Zugaenge pruefen)"
    return None, f"Brave: Fehler {r.status_code}"


def _search_tavily(query: str, n: int, key: str) -> tuple[str | None, str]:
    """Tavily — fuer KI-Agenten gebaute Suche, kostenloser Plan ~1000 Anfragen/Monat."""
    r = httpx.post("https://api.tavily.com/search",
                   json={"query": query, "max_results": n},
                   headers={"Authorization": f"Bearer {key}"}, timeout=20)
    if r.status_code == 200:
        res = r.json().get("results", [])
        return _fmt_hits([(x.get("title", ""), x.get("url", ""), x.get("content", ""))
                          for x in res], n), ""
    return None, f"Tavily: Fehler {r.status_code}"


def _search_google_cse(query: str, n: int, key: str, cx: str) -> tuple[str | None, str]:
    """Google Programmable Search — echtes Google, kostenlos 100 Anfragen/Tag."""
    r = httpx.get("https://www.googleapis.com/customsearch/v1",
                  params={"key": key, "cx": cx, "q": query, "num": min(n, 10)}, timeout=20)
    if r.status_code == 200:
        res = r.json().get("items", []) or []
        return _fmt_hits([(x.get("title", ""), x.get("link", ""), x.get("snippet", ""))
                          for x in res], n), ""
    return None, f"Google: Fehler {r.status_code}"


def _search_searxng(query: str, n: int, base: str) -> tuple[str | None, str]:
    """SearXNG — selbst gehostete Meta-Suche (0 Euro, unbegrenzt, unabhaengig)."""
    r = httpx.get(base.rstrip("/") + "/search",
                  params={"q": query, "format": "json"}, timeout=20, headers=_UA)
    if r.status_code == 200:
        res = r.json().get("results", []) or []
        return _fmt_hits([(x.get("title", ""), x.get("url", ""), x.get("content", ""))
                          for x in res], n), ""
    return None, f"SearXNG: Fehler {r.status_code}"


@tool("web_search",
      "Sucht im Web und liefert Top-Treffer (Titel + URL + kurzer Snippet). Provider-Kette: "
      "Brave -> Tavily -> Google CSE -> SearXNG -> DuckDuckGo — es wird automatisch der erste "
      "funktionierende genutzt (Keys unter 'Zugaenge': BRAVE_API_KEY, TAVILY_API_KEY, "
      "GOOGLE_CSE_KEY + GOOGLE_CSE_ID, SEARXNG_URL).",
      {"query": "die Suchanfrage"})
def web_search(query: str, max_results: int = 5) -> str:
    import os

    def _env(name: str) -> str:
        v = (os.getenv(name) or "").strip()
        # kaputte Keys (Leerzeichen/zu lang) still ueberspringen statt die Kette zu stoppen
        return v if (v and v.isascii() and " " not in v and len(v) <= 300) else ""

    notes: list[str] = []
    kette: list[tuple[str, callable]] = []
    if _env("BRAVE_API_KEY"):
        kette.append(("brave", lambda: _search_brave(query, max_results, _env("BRAVE_API_KEY"))))
    if _env("TAVILY_API_KEY"):
        kette.append(("tavily", lambda: _search_tavily(query, max_results, _env("TAVILY_API_KEY"))))
    if _env("GOOGLE_CSE_KEY") and _env("GOOGLE_CSE_ID"):
        kette.append(("google", lambda: _search_google_cse(
            query, max_results, _env("GOOGLE_CSE_KEY"), _env("GOOGLE_CSE_ID"))))
    if (os.getenv("SEARXNG_URL") or "").strip().startswith("http"):
        kette.append(("searxng", lambda: _search_searxng(
            query, max_results, os.getenv("SEARXNG_URL").strip())))
    for name, fn in kette:
        try:
            out, note = fn()
            if out:
                return out
            notes.append(note or f"{name}: keine Treffer")
        except Exception as e:  # noqa: BLE001 — ein toter Provider stoppt nicht die Kette
            notes.append(f"{name}: {e}")

    # Letzte Instanz: DuckDuckGo-HTML (gratis, aber drosselt gern)
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query},
                       timeout=20, headers=_UA, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        return f"(Suche fehlgeschlagen: {e}" + (f" — vorher: {'; '.join(notes)}" if notes else "") + ")"
    if r.status_code == 202 or "anomaly" in r.text.lower():
        return ("(Suche gerade BLOCKIERT — DuckDuckGo drosselt die IP"
                + (f"; vorher: {'; '.join(notes)}" if notes else "") + ". "
                "Kostenlose Abhilfe unter 'Zugaenge': TAVILY_API_KEY (~1000 Suchen/Monat) oder "
                "GOOGLE_CSE_KEY + GOOGLE_CSE_ID (100/Tag, echtes Google). "
                "Fuer eine bestimmte Seite geht auch das Browser-Werkzeug 'browse'.)")
    hits = re.findall(r'class="result__a"[^>]*href="([^"]+)".*?>(.*?)</a>', r.text, flags=re.DOTALL)
    out = []
    for href, title in hits[:max_results]:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote

            href = unquote(m.group(1))
        out.append(f"- {_strip_html(title)}\n  {href}")
    return "\n".join(out) if out else ("(keine Ergebnisse"
                                       + (f" — {'; '.join(notes)}" if notes else "") + ")")


# --- Datei-Haende: Kira kann auf dem PC lesen/schreiben/auflisten/Ordner anlegen ---
def _pfad(path) -> Path:
    """Pfad-Eingaben robust aufloesen: Umgebungsvariablen (%USERPROFILE%, $HOME) und '~'.

    Kleine Modelle uebergeben solche Platzhalter woertlich — expandvars macht daraus
    nutzbare Pfade, statt an '%USERPROFILE%\\Desktop' zu scheitern (Fund 10.07.)."""
    return Path(os.path.expandvars(str(path))).expanduser()


def _env_hinweis(p: Path) -> str:
    """Zusatz-Hinweis, wenn ein Platzhalter im Pfad NICHT aufgeloest werden konnte."""
    s = str(p)
    if "%" in s or "$" in s:
        return " — Hinweis: Platzhalter im Pfad unbekannt; nutze den vollen Pfad (z.B. C:/Users/Name/...)."
    return ""


def _lehr_fehler(tool_name: str, falsche_args: dict, erwartet: str, beispiel: str) -> str:
    """Lehrende Fehlermeldung statt nacktem TypeError: das Problem benennen UND einen
    korrekten Minimal-Aufruf zeigen — nur so korrigieren sich kleine Modelle selbst.
    (Ein TypeError liefe zudem durch die Executor-Retries, obwohl er deterministisch ist.)"""
    problem = (f"unbekannte Argumente: {', '.join(sorted(falsche_args))}" if falsche_args
               else "Pflicht-Argument fehlt")
    return f"Falscher Aufruf von {tool_name} ({problem}). Erwartet: {erwartet}. Beispiel: {beispiel}"


@tool("read_file",
      "Liest eine Datei vom PC (UTF-8-korrekt) und gibt den Textinhalt zurueck. Bei langen Dateien "
      "wird gestueckelt — nutze dann 'offset', um den naechsten Teil zu lesen. IMMER dieses Werkzeug "
      "fuer Quelltext nutzen, NIE PowerShell Get-Content (das verfaelscht Emojis/Umlaute).",
      {"path": "Dateipfad", "offset": "optional: ab welchem Zeichen lesen (Standard 0)"})
def read_file(path: str = "", max_chars: int = 40000, offset: int = 0, **falsche_args) -> str:
    if falsche_args or not str(path).strip():
        return _lehr_fehler("read_file", falsche_args, "'path' (Dateipfad), optional 'offset'",
                            'read_file(path="C:/Users/Name/Desktop/notiz.txt")')
    p = _pfad(path)
    if not p.exists():
        return f"(Datei nicht gefunden: {p}){_env_hinweis(p)}"
    if p.is_dir():
        return f"(Das ist ein Ordner, keine Datei: {p} — nutze list_dir dafuer)"
    try:
        offset = max(0, int(offset))
    except Exception:  # noqa: BLE001
        offset = 0
    try:
        max_chars = max(1, int(max_chars))
    except Exception:  # noqa: BLE001
        max_chars = 40000
    full = p.read_text(encoding="utf-8", errors="replace")
    chunk = full[offset:offset + max_chars]
    if offset + max_chars < len(full):
        chunk += f"\n\n[… Datei laenger ({len(full)} Zeichen) — read_file mit offset={offset + max_chars} fuer den Rest]"
    return chunk


@tool("write_file", "Schreibt Text in eine Datei (erstellt sie / ueberschreibt KOMPLETT). Legt fehlende "
      "Ordner an. Fuer gezielte Aenderungen an BESTEHENDEN Code-Dateien edit_datei nutzen "
      "(chirurgisch + Tests) statt blind zu ueberschreiben.",
      {"path": "Dateipfad", "content": "der Inhalt"})
def write_file(path: str = "", content: str | None = None, **falsche_args) -> str:
    from core.kernel.fs import atomic_write

    if falsche_args or not str(path).strip() or content is None:
        return _lehr_fehler("write_file", falsche_args, "'path' und 'content'",
                            'write_file(path="C:/Users/Name/Desktop/notiz.md", content="Hallo")')
    p = _pfad(path)
    blocked = _write_guard(p, "write_file")
    if blocked:
        return blocked
    atomic_write(p, str(content))  # atomar: nie halbe Dateien bei Absturz
    return f"OK, geschrieben: {p} ({len(str(content))} Zeichen)"


# feature="legacy" existiert bewusst NICHT in config.yaml -> feature_on liefert False ->
# dauerhaft aus dem Manifest (nie benutzt, write_file deckt den Fall ab). Code bleibt.
@tool("append_file", "Haengt Text an eine Datei an (erstellt sie bei Bedarf).",
      {"path": "Dateipfad", "content": "anzuhaengender Text"}, feature="legacy")
def append_file(path: str = "", content: str | None = None, **falsche_args) -> str:
    if falsche_args or not str(path).strip() or content is None:
        return _lehr_fehler("append_file", falsche_args, "'path' und 'content'",
                            'append_file(path="C:/Users/Name/Desktop/log.md", content="Zeile")')
    p = _pfad(path)
    blocked = _write_guard(p, "append_file")
    if blocked:
        return blocked
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(str(content))
    return f"OK, angehaengt an {p}"


@tool("list_dir", "Listet Dateien und Ordner in einem Verzeichnis.", {"path": "Verzeichnis (Standard: aktuell)"})
def list_dir(path: str = ".", **falsche_args) -> str:
    if falsche_args:
        return _lehr_fehler("list_dir", falsche_args, "'path' (Verzeichnis, optional)",
                            'list_dir(path="C:/Users/Name/Desktop")')
    p = _pfad(path or ".")
    if not p.exists():
        return f"(Verzeichnis nicht gefunden: {p}){_env_hinweis(p)}"
    if p.is_file():
        return f"(Das ist eine Datei, kein Ordner: {p} — nutze read_file dafuer)"
    items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    lines = [("[DIR] " if i.is_dir() else "      ") + i.name for i in items[:200]]
    return "\n".join(lines) if lines else "(leer)"


@tool("make_dir", "Erstellt einen Ordner (inklusive Elternordner).", {"path": "Ordnerpfad"})
def make_dir(path: str = "", **falsche_args) -> str:
    if falsche_args or not str(path).strip():
        return _lehr_fehler("make_dir", falsche_args, "'path' (Ordnerpfad)",
                            'make_dir(path="C:/Users/Name/Desktop/neuer-ordner")')
    p = _pfad(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"OK, Ordner angelegt: {p}"


@tool("request_secret",
      "Fordert einen Zugang/Key an, den du brauchst. {{USER_NAME}} traegt ihn sicher im Dashboard "
      "(Zugaenge) ein. NICHT im Chat nach Passwoertern/Keys fragen.",
      {"name": "Env-Name, z.B. OPENROUTER_API_KEY", "reason": "wofuer du ihn brauchst"})
def request_secret(name: str, reason: str = "") -> str:
    from core.governance import secrets

    secrets.request(name, reason)
    return f"Zugang '{name}' angefordert. {_id.user_name()} traegt ihn im Dashboard unter 'Zugaenge' ein."


# Gedaechtnis-Diaet (Fund 09.07.): "okay, super." landete als Dauer-Fakt im
# Langzeit-Gedaechtnis. Deterministischer Waechter: Smalltalk/Bestaetigungen und
# Duplikate kommen NICHT mehr rein — der Chat-Verlauf (episodic) bleibt unberuehrt.
_SMALLTALK = {"ok", "okay", "oki", "super", "nice", "top", "cool", "mega", "geil", "perfekt",
              "passt", "gut", "prima", "toll", "stark", "danke", "dankeschoen", "dankeschön",
              "ja", "nein", "jo", "jap", "ne", "klar", "alles", "gerne", "bitte", "sehr",
              "los", "gehts", "geht's", "weiter", "machen", "wir", "so", "dann", "mal",
              "lol", "haha", "hi", "hallo", "hey", "moin", "servus", "tschau", "ciao",
              "laeuft", "läuft", "lets", "let's", "go", "bis", "gleich", "morgen", "spaeter",
              "später", "nacht", "gute", "guten", "schoen", "schön", "und", "auch", "das", "ist"}


def _zu_banal(fact: str) -> bool:
    """True fuer Smalltalk ('okay, super.') — kein Langzeit-Wert, nichts speichern."""
    import re as _re

    woerter = _re.sub(r"[^\w'äöüÄÖÜß]+", " ", (fact or "").lower()).split()
    if len((fact or "").strip()) < 15 or not woerter:
        return True
    return all(w in _SMALLTALK for w in woerter)


@tool("remember_fact",
      "Speichere eine wichtige DAUER-Erinnerung (Fakt ueber {{USER_NAME}}, ein Projekt, eine "
      "Entscheidung, eine Praeferenz). Wird spaeter bevorzugt wieder erinnert. "
      "NUR fuer Informationen mit Langzeit-Wert — KEIN Smalltalk, keine Bestaetigungen, "
      "kein Gespraechsverlauf (der wird ohnehin erinnert).",
      {"fact": "die zu merkende Information, knapp formuliert"})
def remember_fact(fact: str) -> str:
    from core.mind.memory import store as memory

    fact = " ".join((fact or "").split())
    if _zu_banal(fact):
        return (f"NICHT gespeichert — '{fact[:40]}' ist Smalltalk/Bestaetigung, kein Dauer-Fakt. "
                "Merke nur Informationen mit Langzeit-Wert (Personen, Daten, Vorlieben, Entscheidungen).")
    memory.init_memory()
    if memory.find_duplicate(fact, kind="fact"):
        return f"Schon im Gedaechtnis (nicht doppelt gespeichert): {fact[:90]}"
    memory.remember(fact, role="self", kind="fact")
    return f"Dauerhaft gemerkt: {fact[:90]}"


@tool("request_approval",
      "Lege eine Aussen-Aktion / oeffentliche oder irreversible Handlung (Post, Mail, "
      "Veroeffentlichung) oder einen fertigen Entwurf zur FREIGABE vor. Sie wird NICHT "
      "sofort ausgefuehrt, sondern wartet in {{USER_NAME_S}} Freigabe-Inbox auf sein GO. Nutze "
      "das IMMER, bevor etwas nach aussen geht.",
      {"title": "kurze Bezeichnung, z.B. 'Blogartikel posten'",
       "detail": "der Entwurf / Volltext / was genau passieren soll",
       "kind": "publish | external | email | generic (Standard: generic)"})
def request_approval(title: str, detail: str = "", kind: str = "generic") -> str:
    from core.agency import approvals

    aid = approvals.create(title, kind=kind, detail=detail, source="kira")
    return (f"Zur Freigabe vorgelegt: '{title}'. Ich fuehre es aus, sobald {_id.user_name()} es in der "
            f"Inbox freigibt (id {aid[:8]}). Bis dahin geht nichts nach aussen.")


@tool("self_edit",
      "Bearbeite deinen EIGENEN Code (eine Datei im Projekt, z.B. das Dashboard oder ein Tool). "
      "Sicher: Syntax-Check + automatischer SELBST-TEST (Kernmodule muessen importierbar bleiben) "
      "+ Git-Commit; faellt der Test durch, wird die Aenderung automatisch zurueckgerollt. "
      "Danach muss der betroffene Dienst neu gestartet werden.",
      {"path": "Datei relativ zum Projekt, z.B. core/api/server.py", "instruction": "was genau geaendert werden soll"})
def self_edit(path: str, instruction: str) -> str:
    from core.agency.selfdev import self_edit as _se

    r = _se(path, instruction)
    if not r.get("ok"):
        return "Fehlgeschlagen: " + r.get("error", "")
    add, rem = r.get("stat", (0, 0))
    head = f"OK (+{add} −{rem}) — {r.get('note', '')}".strip()
    diff = r.get("diff", "")
    return head + (("\n" + diff) if diff else "")


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
      "Weist einer ROLLE ein Modell zu — sofort live + im Dashboard sichtbar. Rollen: 'chat' (Smalltalk), "
      "'reason' (Coding/schweres Denken), 'bulk' (einfache Crons), 'escalation' (Plan/Selbst-Edit), "
      "'default' (alles). Modell-ID im litellm-Format, z.B. 'openrouter/deepseek/deepseek-v4-flash' "
      "oder 'ollama_chat/qwythos' (lokal, 0 EUR).",
      {"model": "die Modell-ID", "role": "optional: chat/reason/bulk/escalation/default (Standard: default)"})
def switch_model(model: str, role: str = "default") -> str:
    from core.kernel import models

    mid = model.strip()
    if not (mid.startswith("openrouter/") or mid.startswith("ollama")):
        mid = "openrouter/" + mid
    return f"'{role}' laeuft jetzt auf: {models.set_role((role or 'default').strip(), mid)}"


@tool("list_models", "Zeigt, welches Modell fuer welche Rolle laeuft (chat/reason/bulk/escalation) + lokale Modelle.", {})
def list_models() -> str:
    from core.kernel import models

    r = models.roles()
    local = ", ".join(models.ollama_models()) or "(keine)"
    return (f"chat: {r['chat']} | reason: {r['reason']} | bulk: {r['bulk']} | "
            f"escalation: {r['escalation']} | lokal: {local}")


@tool("set_context",
      "Setzt Kontextfenster (num_ctx) und/oder max. Ausgabetokens (max_tokens), sofort live. "
      "0 lassen heisst 'nicht aendern'.",
      {"num_ctx": "Kontext-Token, z.B. 16384", "max_tokens": "max. Ausgabetokens, z.B. 8192"})
def set_context(num_ctx: int = 0, max_tokens: int = 0) -> str:
    from core.kernel import models

    r = models.set_params(num_ctx=int(num_ctx) or None, max_tokens=int(max_tokens) or None)
    return f"Gesetzt: num_ctx={r['num_ctx']}, max_tokens={r['max_tokens']} (laedt beim naechsten Aufruf neu)."


@tool("cron_add",
      "Plant eine WIEDERKEHRENDE Aufgabe. Zeitplan: '30m'/'2h' (Intervall) ODER '08:00' "
      "(taeglich). scope ordnet sie ein: 'me' = {{USER_NAME_S}} Routine (z.B. Morgen-Briefing, "
      "erscheint in seinem Me-Bereich), sonst 'system'. {{USER_NAME}} kann dir Routinen per "
      "Telegram diktieren — lege sie damit an.",
      {"label": "kurzer Name", "prompt": "was du dann jeweils tun sollst",
       "schedule": "z.B. '30m', '2h' oder '08:00'",
       "scope": "optional: 'me' | 'system' (Default system)"})
def cron_add(label: str, prompt: str, schedule: str, scope: str = "system") -> str:
    import datetime as _dt

    from core.agency.missions import cron

    scope = (scope or "system").strip().lower()
    if scope not in ("me", "system"):
        scope = "system"
    j = cron.add_job(label, prompt, schedule, scope=scope)
    nxt = _dt.datetime.fromtimestamp(j["next_run"]).strftime("%d.%m. %H:%M")
    where = {"me": f"{_id.user_name()}s Routinen (Me)", "system": "System"}[scope]
    return f"Geplant: {j['label']} ({j['schedule_text']}, {where}) — naechster Lauf {nxt}."


@tool("cron_list", "Zeigt alle geplanten (Cron-)Aufgaben mit Zeitplan und id.", {})
def cron_list() -> str:
    from core.agency.missions import cron

    js = cron.list_jobs()
    if not js:
        return "(keine geplanten Aufgaben)"
    return "\n".join(f"- {j['label']} ({j['schedule_text']}) {'an' if j['enabled'] else 'aus'} (id={j['id']})" for j in js)


@tool("cron_remove",
      "Loescht eine geplante (Cron-)Aufgabe dauerhaft. Die id kommt aus cron_list "
      "(auch 8-Zeichen-Kurzform reicht).",
      {"job_id": "die id der zu loeschenden Aufgabe (aus cron_list)"})
def cron_remove(job_id: str) -> str:
    from core.agency.missions import cron

    jid = (job_id or "").strip()
    js = cron.list_jobs()
    match = next((j for j in js if j["id"] == jid or j["id"].startswith(jid)), None) if jid else None
    if not match:
        return f"Keine geplante Aufgabe mit id '{jid}' gefunden. cron_list zeigt die aktuellen ids."
    cron.remove_job(match["id"])
    return f"Geplante Aufgabe geloescht: {match['label']} (id={match['id']})"


@tool("plan_and_execute",
      "Fuer GROSSE, mehrstufige Aufgaben: zerlege sie selbst in einen Plan und arbeite ihn Schritt "
      "fuer Schritt mit Werkzeugen ab (inkl. self_edit zum Coden). Nutze das, wenn eine Aufgabe "
      "mehrere Teilschritte braucht.",
      {"task": "die komplette Gesamtaufgabe in einem Satz"})
def plan_and_execute(task: str) -> str:
    from core.agency.act import plan_and_execute as _pe

    return _pe(task, escalate=True)


@tool("run_command",
      "Fuehre einen Shell-Befehl im Projektordner aus: Code/Tests laufen lassen, git, pip/uv, "
      "python-Skripte. Du bekommst Exit-Code + Ausgabe (stdout/stderr) zurueck — LIES sie und "
      "korrigiere dich noetigenfalls selbst (ausfuehren -> pruefen -> fixen). "
      "Sicher: Not-Aus, Timeout, Projekt-Sandbox, Audit.",
      {"command": "der Shell-Befehl", "timeout": "Sekunden (optional, Standard 60)"})
def run_command(command: str, timeout: int = 60) -> str:
    from core.agency.shelltool import run_shell

    return run_shell(command, timeout=timeout)


# --- Skills: Kira lernt wiederverwendbare Faehigkeiten und pflegt sie selbst ---
@tool("learn_skill",
      "Speichere eine wiederverwendbare FAEHIGKEIT (Skill): wie man eine bestimmte Art Aufgabe "
      "loest — knappe Schritte/Befehle/Stolperfallen. Wird kuenftig automatisch erinnert und genutzt.",
      {"name": "kurzer Skill-Name", "steps": "die Anleitung, knapp und konkret"})
def learn_skill(name: str, steps: str) -> str:
    from core.mind.memory import store as memory

    memory.init_memory()
    memory.remember(f"SKILL [{name}]: {steps}", role="self", kind="skill")
    return f"Skill '{name}' gelernt und gespeichert."


@tool("list_skills", "Zeigt die gelernten Skills (wiederverwendbare Faehigkeiten).", {})
def list_skills() -> str:
    from core.mind.memory import store as memory

    sk = memory.recall_skills(limit=30)
    return "\n".join(f"- {s}" for s in sk) if sk else "(noch keine Skills)"


@tool("curate_skills",
      "Raeumt deine Skill-Bibliothek auf (Aehnliches zusammenfassen, Veraltetes/Triviales entfernen). "
      "Gut als regelmaessige Pflege (z.B. per Cron).", {})
def curate_skills() -> str:
    from core.mind.curator import curate_skills as _cs

    r = _cs()
    return f"Skills aufgeraeumt: {r['before']} -> {r['after']}." if "before" in r else r.get("note", "ok")


@tool("read_logs",
      "Liest die letzten Zeilen eines Dienst-Logs (cockpit/bot/runner) — zum Debuggen, wenn etwas "
      "haengt, abbricht oder du wissen willst, was zuletzt passiert ist.",
      {"name": "cockpit, bot oder runner (Standard: bot)", "lines": "Anzahl Zeilen (Standard 80)"})
def read_logs(name: str = "bot", lines: int = 80) -> str:
    from core.config import ROOT

    nm = (name or "bot").strip().lower()
    if nm not in ("cockpit", "bot", "runner"):
        nm = "bot"
    p = ROOT / "data" / "logs" / f"{nm}.log"
    if not p.exists():
        return f"(noch kein Log fuer '{nm}' — laeuft der Supervisor mit Logging?)"
    try:
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:  # noqa: BLE001
        return f"(Log-Lesefehler: {e})"
    try:
        n = max(1, int(lines))
    except Exception:  # noqa: BLE001
        n = 80
    return "\n".join(content[-n:]) or "(Log leer)"


@tool("health",
      "Pruefe deinen eigenen Laufzeit-Zustand: laeuft das Cockpit, gab es zuletzt Fehler, sind "
      "Werkzeuge gesperrt/degradiert (Circuit), wie viel Budget ist heute verbraucht. Nutze das, "
      "wenn etwas klemmt oder du wissen willst, ob alles gesund laeuft.", {})
def health() -> str:
    import socket
    import time
    from collections import Counter

    from core.kernel import events, executor

    lines = []
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    cockpit_ok = s.connect_ex(("127.0.0.1", 8000)) == 0
    s.close()
    lines.append(("✅" if cockpit_ok else "❌") + " Cockpit (Port 8000)")

    degraded = {k: v for k, v in executor._failures.items() if v > 0}
    lines.append("🔧 Werkzeuge: " + (", ".join(f"{k} ({v}x Fehler)" for k, v in degraded.items()) if degraded else "alle frei"))

    now = time.time()
    errs = [e for e in events.recent(300)
            if now - e["ts"] < 3600 and any(x in e["type"] for x in ("error", "fail", "timeout", "circuit_open"))]
    c = Counter(e["type"] for e in errs)
    lines.append("⚠️ Fehler (letzte 60 min): " + (", ".join(f"{t} x{n}" for t, n in c.most_common(6)) if c else "keine"))

    try:
        from core.governance import treasury

        lines.append(f"💶 Heute ausgegeben: {treasury.today_spend():.3f} EUR")
    except Exception:  # noqa: BLE001
        pass

    return "🩺 Mein Zustand:\n" + "\n".join(lines)


# --- Echter Browser (Chromium via Playwright): sehen + lesen, was web_fetch nicht laedt ---
@tool("screenshot_url",
      "Oeffnet eine Webseite in einem ECHTEN Browser (Chromium) und macht einen ganzseitigen "
      "Screenshot — fuer Seiten, die web_fetch nicht sauber laedt, oder wenn du sie visuell sehen "
      "willst. Gibt den Datei-Pfad zum Bild zurueck.",
      {"url": "die vollstaendige URL inkl. https://"})
def screenshot_url(url: str) -> str:
    from pathlib import Path

    out_dir = Path.home() / "Desktop" / "kira-screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]+", "_", url.replace("https://", "").replace("http://", ""))[:60] or "page"
    img = out_dir / f"{name}.png"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright ist nicht installiert."
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1366, "height": 900})
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                title = page.title()
                page.screenshot(path=str(img), full_page=True)
            finally:
                browser.close()  # IMMER schliessen -> kein Chromium-Leck bei Fehler/Timeout
        return f"Screenshot gemacht: {img}  (Titel: {title})"
    except Exception as e:  # noqa: BLE001
        return f"Screenshot fehlgeschlagen: {e}"


@tool("browse",
      "Oeffnet eine Seite in einem echten Browser (Chromium, MIT JavaScript) und gibt den sichtbaren "
      "TEXT zurueck — fuer moderne/JS-Seiten, die web_fetch nicht lesen kann. Erst web_fetch versuchen, "
      "bei Bedarf hierauf ausweichen.",
      {"url": "die vollstaendige URL inkl. https://"})
def browse(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright ist nicht installiert."
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                title = page.title()
                text = page.inner_text("body")
            finally:
                browser.close()  # IMMER schliessen -> kein Chromium-Leck bei Fehler/Timeout
        return f"Titel: {title}\n\n{text[:6000]}"
    except Exception as e:  # noqa: BLE001
        return f"Browse fehlgeschlagen: {e}"


@tool("restart_self",
      "Startet Kira SICHER neu (sauberer Bounce ueber den Supervisor via data/restart.flag) — nutze dies, "
      "wenn Code-/Config-Aenderungen aktiv werden sollen oder ein Dienst haengt. Laeuft gerade eine Antwort, "
      "wird der Neustart AUTOMATISCH bis nach dem aktuellen Zug aufgeschoben (kein Selbst-Abschuss mitten in "
      "der Arbeit). Prozesse per taskkill / Stop-Process zu killen ist verboten und gefaehrlich (du wuerdest "
      "dich SELBST beenden); dieses Werkzeug ist der EINZIGE sichere Weg.",
      {"which": "optional: 'all' (Standard) oder Dienste kommagetrennt: bot,cockpit,runner"})
def restart_self(which: str = "all") -> str:
    from core.kernel import runstate

    # Laeuft gerade ein Chat-Zug -> Neustart bis idle aufschieben (kein Selbst-Abschuss).
    return runstate.request_restart(which)


@tool("db_query",
      "Fuehrt eine READ-ONLY SQL-Abfrage auf der Event-/Gedaechtnis-DB (data/state.db) aus. NUR lesend "
      "(SELECT/WITH/PRAGMA/EXPLAIN — die Verbindung ist read-only, Schreiben ist unmoeglich). Nutze dies "
      "fuer Selbst-Diagnose (Events, Fehler, Kosten) STATT Temp-Skripte oder Shell-Gewuergel. Tabelle "
      "events(id, ts REAL, type, session_id, payload JSON). Bsp: "
      "SELECT type, COUNT(*) FROM events GROUP BY type ORDER BY 2 DESC LIMIT 20  |  "
      "SELECT ts, payload FROM events WHERE type LIKE '%error%' ORDER BY ts DESC LIMIT 10",
      {"sql": "die lesende SQL-Abfrage", "limit": "optional: max. Zeilen (Default 50, max 500)"})
def db_query(sql: str, limit: int = 50) -> str:
    import sqlite3

    from core.config import DB_PATH

    q = (sql or "").strip().rstrip(";")
    if not q.lower().startswith(("select", "with", "pragma", "explain")):
        return "Nur lesende Abfragen erlaubt (SELECT / WITH / PRAGMA / EXPLAIN)."
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)  # read-only: Schreiben unmoeglich
        try:
            cur = con.execute(q)
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(max(1, min(int(limit or 50), 500)))
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return f"SQL-Fehler: {e}"
    if not rows:
        return "(keine Zeilen)"
    head = " | ".join(cols)
    body = "\n".join(" | ".join("" if v is None else str(v)[:300] for v in r) for r in rows)
    return f"{head}\n{body}"


@tool("jetzt", "Gibt aktuelles Datum, Uhrzeit und Wochentag auf Deutsch zurueck (z.B. 'Montag, 30.06.2025, 18:52 Uhr').", {})
def jetzt() -> str:
    tage = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    jetzt = datetime.now()
    wochentag = tage[jetzt.weekday()]
    return f"{wochentag}, {jetzt.strftime('%d.%m.%Y')}, {jetzt.strftime('%H:%M')} Uhr"


@tool("harness_report",
      "Gibt einen kompakten Selbst-Report ueber Kiras eigenen Betrieb (LLM-Kosten, Tool-Nutzung, "
      "Fehler-/Haertungs-Signale, Latenz) fuer einen Zeitraum. NUR read-only DB-Zugriff, keine Shell.",
      {"window": "Zeitraum: 'today' (Standard), '24h' oder '7d'"})
def harness_report(window: str = "today") -> str:
    import sqlite3
    import time as _t
    from datetime import datetime as _dt

    from core.config import DB_PATH

    w = (window or "today").strip().lower()
    if w == "24h":
        cutoff = _t.time() - 86400
    elif w == "7d":
        cutoff = _t.time() - 7 * 86400
    else:
        w = "today"
        cutoff = _dt.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)  # read-only: Schreiben unmoeglich
        try:
            def one(sql, *args):
                return con.execute(sql, args).fetchone()

            def rows(sql, *args):
                return con.execute(sql, args).fetchall()

            n_llm, cost = one(
                "SELECT COUNT(*), COALESCE(SUM(json_extract(payload,'$.cost_usd')),0) "
                "FROM events WHERE type='llm_call' AND ts>=?", cutoff)
            per_sess = rows(
                "SELECT COALESCE(NULLIF(session_id,''),'(ohne Session)'), "
                "COALESCE(SUM(json_extract(payload,'$.cost_usd')),0) c, COUNT(*) "
                "FROM events WHERE type='llm_call' AND ts>=? GROUP BY session_id ORDER BY c DESC LIMIT 5", cutoff)
            n_tools = one("SELECT COUNT(*) FROM events WHERE type='tool_call' AND ts>=?", cutoff)[0]
            n_fail = one("SELECT COUNT(*) FROM events WHERE type='tool_call' AND ts>=? "
                         "AND json_extract(payload,'$.ok')=0", cutoff)[0]

            def cnt(t):
                return one("SELECT COUNT(*) FROM events WHERE type=? AND ts>=?", t, cutoff)[0]

            deg, err, crash = cnt("act_degraded"), cnt("llm_call_error"), cnt("service_crash")
            restart_def = cnt("restart_deferred_fired")
            turn_to = cnt("turn_timeout")
            tool_rec = cnt("tool_calls_recovered")
            top_tools = rows(
                "SELECT json_extract(payload,'$.tool') t, COUNT(*) n FROM events "
                "WHERE type='tool_call' AND ts>=? GROUP BY t ORDER BY n DESC LIMIT 5", cutoff)
            lat_avg, lat_max = one(
                "SELECT COALESCE(AVG(json_extract(payload,'$.latency_s')),0), "
                "COALESCE(MAX(json_extract(payload,'$.latency_s')),0) "
                "FROM events WHERE type='llm_call' AND ts>=?", cutoff)
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 -> nie crashen, immer einen String liefern
        return f"Harness-Report Fehler: {e}"

    sess_lines = "\n".join(
        f"    - {s}: {c:.2f} EUR ({calls} calls)" for s, c, calls in per_sess) or "    - (keine)"
    tool_lines = ", ".join(f"{t or '?'}:{n}" for t, n in top_tools) or "(keine)"
    return (
        f"📊 Harness-Report ({w})\n"
        f"- LLM-Calls: {n_llm} | Kosten: {cost:.2f} EUR\n"
        f"- Kosten/Session (Top 5):\n{sess_lines}\n"
        f"- Tool-Calls: {n_tools} gesamt, {n_fail} fehlgeschlagen\n"
        f"- Haertung: act_degraded={deg} | llm_call_error={err} | service_crash={crash}\n"
        f"- Top-Werkzeuge: {tool_lines}\n"
        f"- LLM-Latenz: avg {lat_avg:.2f}s | max {lat_max:.2f}s\n"
        f"- Neustart-Signale: restart_deferred_fired={restart_def} | turn_timeout={turn_to} | tool_calls_recovered={tool_rec}"
    )

# Email-Werkzeuge (S3): senden hinterm Autonomie-Gate, lesen frei.
from core.agency.tools import mail_tools  # noqa: E402,F401
from core.agency.tools import social_tools  # noqa: E402,F401
# Browser-Aktor (S3): klicken/ausfuellen mit Zahlungsfeld-Stopp + Audit.
from core.agency.tools import browser as _browser_tools  # noqa: E402,F401
# Proaktive Trigger (S4): Wenn-Dann-Reflexe auf Events.
from core.agency.tools import trigger_tools  # noqa: E402,F401
# Lebens-Ebene (S5): Todos, Ziele, Metriken — Kiras Coach-Griff.
from core.agency.tools import life_tools  # noqa: E402,F401
# Wissens-Archiv (S5): suchen/ablegen im Schreibtisch.
from core.agency.tools import knowledge_tools  # noqa: E402,F401
# Playbooks (S11): feste Prozeduren mit Reifegrad + Lernschleife.
from core.agency.tools import playbook_tools  # noqa: E402,F401
# Delegation: Unteragenten nach Rang (reflex/arbeiter/denker/richter) + Schwarm.
from core.agency.tools import delegate_tools  # noqa: E402,F401
# Coding-Grundausstattung: code_suche/datei_finden/edit_datei (suchen -> chirurgisch editieren -> verifizieren).
from core.agency.tools import code_tools  # noqa: E402,F401
# Widget-System (Werkbank PR 8): Cockpit-Kacheln per Config einblenden, nie Code.
from core.agency.tools import widget_tools  # noqa: E402,F401
# Computer-Use (Macht-Schritt 1): Bildschirm sehen + Maus/Tastatur/Fenster. Standard AUS,
# Freigabe im Steuerpult, Not-Aus/Testmodus blocken, jede Aktion auditiert.
from core.agency import computer as _computer_tools  # noqa: E402,F401
# Alltags-Kern (Phase 2): Kalender + aktiver Obsidian-Schreibpfad + Stammbaum-Pflege.
from core.agency.tools import termin_tools  # noqa: E402,F401
from core.agency.tools import vault_tools  # noqa: E402,F401
