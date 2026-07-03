"""Eingebaute Werkzeuge — Kiras erste echte Faehigkeiten.

Bewusst abhaengigkeitsarm (nur httpx + Regex). Spaeter baut Kira sich weitere
Werkzeuge selbst (synthesize.py).
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

import httpx

from core.agency.tools.registry import tool
from core.config import MIND_DIR
from core.kernel import events

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Schreibgeschuetzte Dateien: die Verfassung darf KEIN Werkzeug anfassen.
# (write_file hatte frueher keinerlei Pfadschutz — so entstanden Root-Strays
# und die Verfassung war de facto beschreibbar.)
_PROTECTED = {(MIND_DIR / "constitution.md").resolve()}


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
                "Aenderungen daran macht nur Sergen selbst via Git.")
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


@tool("web_search",
      "Sucht im Web und liefert Top-Treffer (Titel + URL + kurzer Snippet). Nutzt Brave Search "
      "(zuverlaessig), wenn BRAVE_API_KEY gesetzt ist — sonst DuckDuckGo als Fallback.",
      {"query": "die Suchanfrage"})
def web_search(query: str, max_results: int = 5) -> str:
    import os

    key = (os.getenv("BRAVE_API_KEY") or "").strip()
    if key and (not key.isascii() or " " in key or len(key) > 200):
        return ("(BRAVE_API_KEY unter 'Zugaenge' ist UNGUELTIG — zu lang / Leerzeichen / Sonderzeichen. "
                "Ein Brave-Key ist kurz & alphanumerisch (~32 Zeichen). Bitte den ECHTEN Key aus deinem "
                "Brave-API-Dashboard eintragen, keinen Text.)")
    if key:
        try:
            r = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
                timeout=20,
            )
            if r.status_code == 200:
                res = (r.json().get("web") or {}).get("results", [])[:max_results]
                if res:
                    return "\n".join(
                        f"- {x.get('title', '')}\n  {x.get('url', '')}\n  {_strip_html(x.get('description', ''))[:180]}"
                        for x in res
                    )
                return "(keine Treffer fuer diese Anfrage)"
            if r.status_code in (401, 422):
                return "(Brave lehnt den Key ab — ungueltiger Token. Bitte BRAVE_API_KEY unter 'Zugaenge' neu eintragen.)"
            return f"(Brave-Suche Fehler {r.status_code} — BRAVE_API_KEY unter 'Zugaenge' pruefen)"
        except Exception as e:  # noqa: BLE001
            return f"(Brave-Suche fehlgeschlagen: {e})"

    # Fallback: DuckDuckGo — kann bei Burst-Nutzung geblockt sein -> Fehler SICHTBAR machen, nicht verschlucken
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query},
                       timeout=20, headers=_UA, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        return f"(Suche fehlgeschlagen: {e})"
    if r.status_code == 202 or "anomaly" in r.text.lower():
        return ("(Suche gerade BLOCKIERT — DuckDuckGo drosselt die IP. Trage einen kostenlosen "
                "BRAVE_API_KEY unter 'Zugaenge' ein fuer zuverlaessige Suche, oder warte kurz und versuch es erneut. "
                "Fuer eine bestimmte Seite geht auch das echte Browser-Werkzeug 'browse'.)")
    hits = re.findall(r'class="result__a"[^>]*href="([^"]+)".*?>(.*?)</a>', r.text, flags=re.DOTALL)
    out = []
    for href, title in hits[:max_results]:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote

            href = unquote(m.group(1))
        out.append(f"- {_strip_html(title)}\n  {href}")
    return "\n".join(out) if out else "(keine Ergebnisse — evtl. Formatwechsel bei DuckDuckGo; BRAVE_API_KEY empfohlen)"


# --- Datei-Haende: Kira kann auf dem PC lesen/schreiben/auflisten/Ordner anlegen ---
@tool("read_file",
      "Liest eine Datei vom PC (UTF-8-korrekt) und gibt den Textinhalt zurueck. Bei langen Dateien "
      "wird gestueckelt — nutze dann 'offset', um den naechsten Teil zu lesen. IMMER dieses Werkzeug "
      "fuer Quelltext nutzen, NIE PowerShell Get-Content (das verfaelscht Emojis/Umlaute).",
      {"path": "Dateipfad", "offset": "optional: ab welchem Zeichen lesen (Standard 0)"})
def read_file(path: str, max_chars: int = 40000, offset: int = 0) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"(Datei nicht gefunden: {p})"
    if p.is_dir():
        return f"(Das ist ein Ordner, keine Datei: {p})"
    try:
        offset = max(0, int(offset))
    except Exception:  # noqa: BLE001
        offset = 0
    full = p.read_text(encoding="utf-8", errors="replace")
    chunk = full[offset:offset + max_chars]
    if offset + max_chars < len(full):
        chunk += f"\n\n[… Datei laenger ({len(full)} Zeichen) — read_file mit offset={offset + max_chars} fuer den Rest]"
    return chunk


@tool("write_file", "Schreibt Text in eine Datei (erstellt sie / ueberschreibt). Legt fehlende Ordner an.",
      {"path": "Dateipfad", "content": "der Inhalt"})
def write_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    blocked = _write_guard(p, "write_file")
    if blocked:
        return blocked
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(content), encoding="utf-8")
    return f"OK, geschrieben: {p} ({len(str(content))} Zeichen)"


@tool("append_file", "Haengt Text an eine Datei an (erstellt sie bei Bedarf).",
      {"path": "Dateipfad", "content": "anzuhaengender Text"})
def append_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    blocked = _write_guard(p, "append_file")
    if blocked:
        return blocked
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


@tool("request_approval",
      "Lege eine Aussen-Aktion / oeffentliche oder irreversible Handlung (Post, Mail, "
      "Veroeffentlichung) oder einen fertigen Entwurf zur FREIGABE vor. Sie wird NICHT "
      "sofort ausgefuehrt, sondern wartet in Sergens Freigabe-Inbox auf sein GO. Nutze "
      "das IMMER, bevor etwas nach aussen geht.",
      {"title": "kurze Bezeichnung, z.B. 'Blogartikel posten'",
       "detail": "der Entwurf / Volltext / was genau passieren soll",
       "kind": "publish | external | email | generic (Standard: generic)"})
def request_approval(title: str, detail: str = "", kind: str = "generic") -> str:
    from core.agency import approvals

    aid = approvals.create(title, kind=kind, detail=detail, source="kira")
    return (f"Zur Freigabe vorgelegt: '{title}'. Ich fuehre es aus, sobald Sergen es in der "
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
      "(taeglich). scope ordnet sie ein: 'me' = Sergens Routine (z.B. Morgen-Briefing, "
      "erscheint in seinem Me-Bereich), project = Projekt-Name -> Routine der Projekt-Akte, "
      "sonst 'system'. Sergen kann dir Routinen per Telegram diktieren — lege sie damit an.",
      {"label": "kurzer Name", "prompt": "was du dann jeweils tun sollst",
       "schedule": "z.B. '30m', '2h' oder '08:00'",
       "scope": "optional: 'me' | 'system' (Default system)",
       "project": "optional: Projekt-Name/Id -> Routine gehoert zu diesem Projekt"})
def cron_add(label: str, prompt: str, schedule: str, scope: str = "system", project: str = "") -> str:
    import datetime as _dt

    from core.agency.missions import cron

    scope = (scope or "system").strip().lower()
    if (project or "").strip():
        from core.agency import ventures

        token = project.strip().lower()
        hits = [v for v in ventures.list_all() if v["id"].startswith(project.strip())
                or token in (v.get("name") or "").lower()]
        if len(hits) != 1:
            names = ", ".join(v["name"] for v in ventures.list_all()[:6]) or "(keine Projekte)"
            return f"Projekt '{project}' nicht eindeutig. Vorhandene: {names}. Bitte praezisieren."
        scope = f"projekt:{hits[0]['id']}"
    if scope not in ("me", "system") and not scope.startswith("projekt:"):
        scope = "system"
    j = cron.add_job(label, prompt, schedule, scope=scope)
    nxt = _dt.datetime.fromtimestamp(j["next_run"]).strftime("%d.%m. %H:%M")
    where = {"me": "Sergens Routinen (Me)", "system": "System"}.get(scope, "Projekt-Akte")
    return f"Geplant: {j['label']} ({j['schedule_text']}, {where}) — naechster Lauf {nxt}."


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

# Venture-Werkzeuge (S3) registrieren — Import genuegt (Decorator-Registry).
from core.agency.tools import venture_tools  # noqa: E402,F401
# Email-Werkzeuge (S3): senden hinterm Autonomie-Gate, lesen frei.
from core.agency.tools import mail_tools  # noqa: E402,F401
# Browser-Aktor (S3): klicken/ausfuellen mit Zahlungsfeld-Stopp + Audit.
from core.agency.tools import browser as _browser_tools  # noqa: E402,F401
# Proaktive Trigger (S4): Wenn-Dann-Reflexe auf Events.
from core.agency.tools import trigger_tools  # noqa: E402,F401
# Lebens-Ebene (S5): Todos, Ziele, Metriken — Kiras Coach-Griff.
from core.agency.tools import life_tools  # noqa: E402,F401
# Wissens-Archiv (S5): suchen/ablegen im Schreibtisch.
from core.agency.tools import knowledge_tools  # noqa: E402,F401
# Business-Radar (S5): Chancen-Pipeline.
from core.agency.tools import radar_tools  # noqa: E402,F401
# Playbooks (S11): feste Prozeduren mit Reifegrad + Lernschleife.
from core.agency.tools import playbook_tools  # noqa: E402,F401
