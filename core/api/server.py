"""FastAPI-Cockpit: Chat (mit Live-Thinking), Seele/Dateien, Modelle, Protokoll.

Ein Prozess, eine Seite (Terminal-Look). Start:
    uv run uvicorn core.api.server:app --reload   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import time

import anyio
from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from core.agency.tools import builtin as _builtin  # noqa: F401  (registriert eingebaute Tools)
from core.agency.tools import registry
from core.agency.tools import synthesize as _synth
from core.config import CONFIG, MIND_DIR, ROOT
from core.governance import audit, secrets, treasury
from core.kernel import events, models
from core.kernel.llm_router import today_spend_usd
from core.kernel.phrases import THINKING_PHRASES
from core.kernel.scheduler import heartbeat_on, kill_switch_active, kill_switch_path, set_heartbeat
from core.mind.agent import Agent
from core.mind.memory import store as memory

app = FastAPI(title="Kira Cockpit")
events.init_db()
memory.init_memory()

# W3: Bestands-Instanz beim Boot still stempeln (Lockout-Schutz) — eine gelebte
# Instanz (USER.md + gesetzter Nutzer-Name) sieht den Setup-Wizard NIEMALS.
from core.kernel import onboarding as _onboarding  # noqa: E402
_onboarding.auto_migrate()

# Onboarding-Gate: VOR _remote_guard registriert -> laeuft als INNERE Middleware
# NACH dem Fernzugriff-Schutz (Token-Pruefung zuerst, dann Setup-Umleitung).
_SETUP_FREI = ("/setup", "/api/setup", "/health", "/api/icon")


@app.middleware("http")
async def _onboarding_gate(request, call_next):
    """Frischer Klon (kein onboarded.flag): HTML -> /setup, API -> 503 setup_required."""
    path = request.url.path
    if _onboarding.is_onboarded() or any(path == p or path.startswith(p + "/") for p in _SETUP_FREI):
        return await call_next(request)
    if request.method == "GET" and "text/html" in (request.headers.get("accept") or ""):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/setup", status_code=302)
    return JSONResponse({"error": "setup_required", "hint": "Erst-Einrichtung unter /setup"},
                        status_code=503)


@app.middleware("http")
async def _remote_guard(request, call_next):
    """Fernzugriff-Schutz (Punkt 4, PWA): ohne aktivierten Fernzugriff ein No-Op.
    Aktiviert: Loopback bleibt frei (Desktop/Wallpaper), alles andere braucht das Token."""
    from core.api import security

    if security.http_allowed(request):
        return await call_next(request)
    if request.method == "GET" and "text/html" in (request.headers.get("accept") or ""):
        return HTMLResponse(security.LOGIN_HTML, status_code=401)
    return JSONResponse({"error": "Token noetig (Fernzugriff aktiv)"}, status_code=401)
try:  # Workspace-Tabellen (Ziele + Task-Felder + Freigabe-Inbox) sicherstellen
    from core.agency.missions import objectives as _objectives, queue as _queue0
    from core.agency import approvals as _approvals0
    _objectives.init_objectives()
    _queue0.init_queue()
    _approvals0.init_approvals()
except Exception:  # noqa: BLE001
    pass
_synth.load_synthesized()  # selbstgebaute Werkzeuge fuer die Uebersicht verfuegbar machen
try:  # MCP-Bruecke im Hintergrund anschliessen (Ausfall darf den Boot nie bricken)
    from core.agency.mcp import registry_bridge as _mcp_bridge
    _mcp_bridge.init_background()
except Exception:  # noqa: BLE001
    pass

def _stammbaum_wurzel_name() -> str:
    """Dateiname der Stammbaum-Wurzel — traegt den NUTZER-Namen (W2, z.B. SERGEN.md)."""
    from core import identity as _id

    return f"{_id.user_name().upper()}.md"


def _stammbaum_wurzel_pfad():
    return ROOT / "gedaechtnis" / "stammbaum" / _stammbaum_wurzel_name()


def _ident_tokens(html: str) -> str:
    """W2: __AGENT__/__AGENT_UC__/__USER__-Token + IDENTITY-Objekt beim Ausliefern
    fuellen — Umbenennen wirkt nach Reload, ohne dass Markup Namen hart traegt."""
    from core import identity as _id

    a, u = _id.agent_name(), _id.user_name()
    return (html.replace("/*__IDENTITY__*/", json.dumps({"agent": a, "user": u}, ensure_ascii=False)[1:-1])
            .replace("__AGENT_UC__", a.upper()).replace("__AGENT__", a).replace("__USER__", u))


# Im Dashboard sichtbare/bearbeitbare Dateien.
# Die Verfassung ist ueberall nur lesend (Cockpit, Tools, Evolution) — Aenderungen
# macht der Mensch bewusst via Git/Editor. Grund: am 02.07. wurde sie ueber genau diesen
# Endpoint abgeschwaecht, ohne dass es jemandem auffiel.
FILES: dict[str, dict] = {
    "constitution.md": {"path": MIND_DIR / "constitution.md", "editable": True, "label": "⚠ Verfassung — Kiras Kern-Regeln. Aenderung greift sofort; Backup vor jedem Speichern (core/mind/history)"},
    "SOUL.md": {"path": MIND_DIR / "SOUL.md", "editable": True, "label": "Seele — wer Kira ist (Identitaet, Haltung; Aenderung wirkt sofort, Backup automatisch)"},
    "GOAL.md": {"path": MIND_DIR / "GOAL.md", "editable": True, "label": "Ziel — wofuer sie da ist (Nordstern; die Meilensteine gehoeren Dir)"},
    "USER.md": {"path": MIND_DIR / "USER.md", "editable": True, "label": "Ueber Dich — dein Agent baut sein Bild von Dir daraus; kurz halten"},
    "PERSONA.md": {"path": MIND_DIR / "PERSONA.md", "editable": True, "label": "Verhalten & Ton — der Verhaltens-Kern (schlank halten, ~4200 Zeichen; wirkt sofort)"},
    "config.yaml": {"path": ROOT / "config.yaml", "editable": True, "label": "Konfiguration (Vorsicht: YAML)"},
    # Gedaechtnis + Handbuch (frei editierbar — nie im Prompt, siehe HANDBUCH §7)
    "HANDBUCH.md": {"path": ROOT / "docs" / "HANDBUCH.md", "editable": True, "label": "HANDBUCH (Bedienbuch)"},
    "INDEX.md": {"path": ROOT / "INDEX.md", "editable": True, "label": "INDEX (Vault-Einstieg; AUTO-Block nicht anfassen)"},
    _stammbaum_wurzel_name(): {"path": _stammbaum_wurzel_pfad(), "editable": True, "label": "Stammbaum-Wurzel"},
    "gedaechtnis-regeln.md": {"path": ROOT / "gedaechtnis" / "LIES-MICH.md", "editable": True, "label": "Gedaechtnis-Regeln"},
}


# ---------- REST ----------
@app.get("/health")
def health() -> dict:
    return {"status": "alive", "harness": CONFIG["identity"]["harness_name"]}


@app.get("/api/status")
def api_status() -> dict:
    m = models.status()
    from core.kernel import llm_router
    # Was der Chat JETZT WIRKLICH nutzt (nicht nur das gespeicherte Wunsch-Modell):
    # fehlt der Cloud-Key, laeuft es lokal — das soll das UI sehen, nicht verstecken.
    _resolved, _fb = llm_router.resolve_model("chat")
    return {
        "harness": CONFIG["identity"]["harness_name"],
        "partner": CONFIG["identity"].get("partner_name") or "Partner",
        "model": m["default"],
        "resolved_model": _resolved,
        "fallback_active": bool(_fb),
        "api_keys": m["api_keys"],
        "providers": m["providers"],
        "ollama_local": m["ollama_local"],
        "escalation_model": m["escalation_model"],
        "reasoning_markers": llm_router._REASON_MARKERS,   # welche Modelle 'denken' koennen (fuer den Live-Regler)
        "num_ctx": m.get("num_ctx"),
        "max_tokens": m.get("max_tokens"),
        "temperature": CONFIG["models"].get("temperature"),
        "keep_alive": CONFIG["models"].get("keep_alive"),
        "voice": CONFIG.get("channels", {}).get("telegram", {}).get("voice"),
        "whisper": CONFIG.get("channels", {}).get("telegram", {}).get("whisper_model"),
        "spend_usd_today": round(today_spend_usd(), 4),
        "budget": treasury.status(),
        "kill_switch": kill_switch_active(),
        "events": events.counts_by_type(),
        # Ehrliches Fehler-Fenster (7 Tage) statt kumulativem All-Time-Zaehler:
        "errors_recent": events.count_since(
            ("turn_timeout", "llm_call_timeout", "service_crash", "act_degraded"),
            time.time() - 7 * 86400),
        "lessons": memory.recall_lessons(8),
        "freigaben_offen": _freigaben_offen(),   # Serc-Badge in der Sidebar (Werkbank PR 7)
    }


def _freigaben_offen() -> int:
    """Offene Freigaben (Inbox + Vorschlaege) — fuer den Sidebar-Badge, raist nie."""
    try:
        from core.agency import approvals
        approvals.init_approvals()
        return len(approvals.pending()) + len(_pending_proposals())
    except Exception:  # noqa: BLE001
        return 0


@app.get("/api/overview")
def api_overview() -> dict:
    last_mission = None
    for e in events.recent(300):
        if e["type"] == "mission_task_done":
            last_mission = {"ts": e["ts"], "summary": str(e["payload"].get("summary", ""))}
            break
    return {
        "partner": CONFIG["identity"].get("partner_name") or "Partner",
        "model": models.status()["default"],
        "kill_switch": kill_switch_active(),
        "budget": treasury.status(),
        "mission": {"name": CONFIG.get("mission", {}).get("name"), "heartbeat": heartbeat_on()},
        "tools": [t.name for t in registry.all_tools()],
        "lessons": memory.recall_lessons(5),
        "last_mission": last_mission,
        "events_total": sum(events.counts_by_type().values()),
    }


@app.get("/api/governance")
def api_governance() -> dict:
    return {
        "treasury": treasury.status(),
        "audit": audit.recent(30),
    }


# S8.3: echte Autonomie-Schalter statt Vertrauensbarometer (trust.py ist deprecated —
# das Gating lief ohnehin schon ueber autonomy.needs_approval, die Stufe war Deko).
@app.get("/api/autonomy")
def api_autonomy() -> dict:
    from core.governance import autonomy

    d = autonomy._load()
    council = (CONFIG.get("governance", {}) or {}).get("council_gate", ["money"])
    return {"chains_off": bool(d.get("chains_off", True)),
            "hard_gate": list(d.get("hard_gate", [])),
            "council_gate": list(council) if isinstance(council, (list, tuple)) else ["money"],
            "kinds": ["money", "email_stranger", "publish", "external", "email"]}


@app.post("/api/autonomy")
async def api_autonomy_set(body: dict) -> dict:
    from core.governance import autonomy

    hard = body.get("hard_gate")
    if hard is not None and not isinstance(hard, list):
        return {"ok": False, "error": "hard_gate muss eine Liste sein"}
    d = autonomy.set_config(chains_off=body.get("chains_off"), hard_gate=hard)
    events.emit("autonomy_changed", {"chains_off": d.get("chains_off"),
                                     "hard_gate": d.get("hard_gate")})
    return {"ok": True, **d}


@app.get("/api/files")
def api_files() -> list[dict]:
    return [{"name": n, "label": f["label"], "editable": f["editable"]} for n, f in FILES.items()]


@app.get("/api/file")
def api_file(name: str) -> dict:
    f = FILES.get(name)
    if not f:
        return {"error": "unbekannte Datei"}
    p = f["path"]
    content = p.read_text(encoding="utf-8") if p.exists() else ""
    return {"name": name, "label": f["label"], "editable": f["editable"], "content": content}


@app.post("/api/file")
async def api_file_save(body: dict) -> dict:
    name = body.get("name", "")
    f = FILES.get(name)
    if not f or not f["editable"]:
        return {"ok": False, "error": "Datei ist nicht bearbeitbar."}
    p = f["path"]
    # Backup vor dem Ueberschreiben (Undo-Spur)
    hist = MIND_DIR / "history"
    hist.mkdir(parents=True, exist_ok=True)
    if p.exists():
        ts = time.strftime("%Y%m%d-%H%M%S")
        (hist / f"{name}.{ts}.bak").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(body.get("content", ""), encoding="utf-8")
    events.emit("file_edited", {"file": name, "via": "dashboard"})
    return {"ok": True}


# Gedaechtnis-Browser (B-024): der ganze Vault im Cockpit — nicht nur die 10 FILES.
# Nur .md, nur unterhalb dieser Wurzeln (Traversal-Guard), Backups vor jedem Speichern.
_VAULT_ROOTS = {"gedaechtnis": ROOT / "gedaechtnis",
                "playbooks": ROOT / "playbooks",
                "docs": ROOT / "docs"}


def _vault_resolve(path: str):
    """Pfad-Guard: nur .md-Dateien unterhalb der Vault-Wurzeln, kein ../-Ausbruch."""
    rel = (path or "").replace("\\", "/").strip("/")
    parts = rel.split("/", 1)
    base = _VAULT_ROOTS.get(parts[0])
    if not base or len(parts) < 2 or not rel.endswith(".md") or ".." in rel.split("/"):
        return None
    p = (base / parts[1]).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        return None
    return p


@app.get("/api/vault")
def api_vault() -> dict:
    """Alle .md-Dateien des Vaults (gedaechtnis/playbooks/docs), sortiert nach Pfad."""
    out = []
    for key, base in _VAULT_ROOTS.items():
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.md")):
            rel = f"{key}/{p.relative_to(base).as_posix()}"
            out.append({"path": rel, "name": p.name})
            if len(out) >= 500:  # Schutz gegen ausgeartete Vaults
                break
    return {"files": out}


@app.get("/api/vault/file")
def api_vault_file(path: str) -> dict:
    p = _vault_resolve(path)
    if not p:
        return {"error": "Pfad nicht erlaubt (nur .md unter gedaechtnis/playbooks/docs)."}
    content = p.read_text(encoding="utf-8") if p.exists() else ""
    return {"path": path.strip("/"), "content": content, "editable": True}


@app.post("/api/vault/file")
async def api_vault_file_save(body: dict) -> dict:
    from core.config import DATA_DIR

    rel = str(body.get("path") or "").strip("/")
    p = _vault_resolve(rel)
    if not p:
        return {"ok": False, "error": "Pfad nicht erlaubt (nur .md unter gedaechtnis/playbooks/docs)."}
    if p.exists():  # Undo-Spur wie beim FILES-Flow, nur im Datenordner (gitignored)
        hist = DATA_DIR / "vault_history"
        hist.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        (hist / f"{rel.replace('/', '__')}.{ts}.bak").write_text(
            p.read_text(encoding="utf-8"), encoding="utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)  # neue Blaetter (z.B. Stammbaum-Ast) erlaubt
    p.write_text(str(body.get("content") or ""), encoding="utf-8")
    events.emit("file_edited", {"file": rel, "via": "dashboard"})
    return {"ok": True}


@app.get("/api/steuer")
def api_steuer() -> dict:
    """Steuerpult-Daten: Rang-Tafel (gesetzt vs. real laufend) + Schwarm-Regler.

    Read-only; Aenderungen laufen ueber /api/model/role (Rang-Modell) und
    /api/config/set (Regler, Whitelist agency.delegate.*)."""
    from core.agency.tools.delegate_tools import _RANG, _kosten_deckel, _steps_for
    from core.kernel import llm_router

    m = CONFIG.get("models", {})
    rt = m.get("routing", {}) if isinstance(m.get("routing"), dict) else {}
    beschreibung = {"reflex": "trivial, lokal, 0 EUR", "arbeiter": "Masse, billig",
                    "denker": "Planung/Reasoning", "richter": "finale Urteile, selten"}
    rolle = {"reflex": "classify", "arbeiter": "worker", "denker": "reason", "richter": "escalation"}
    raenge = []
    for rang, (task_type, esc) in _RANG.items():
        gesetzt = m.get("escalation_model") if rang == "richter" else rt.get(task_type, m.get("default"))
        try:
            real, fb = llm_router.resolve_model(task_type, escalate=esc)
        except Exception:  # noqa: BLE001
            real, fb = gesetzt, False
        raenge.append({"rang": rang, "rolle": rolle[rang], "info": beschreibung[rang],
                       "modell": gesetzt, "real": real, "fallback": fb,
                       "schritte": _steps_for(rang)})
    ag = CONFIG.get("agency", {}) if isinstance(CONFIG.get("agency"), dict) else {}
    dg = ag.get("delegate", {}) if isinstance(ag.get("delegate"), dict) else {}
    cu = ag.get("computer_use", {}) if isinstance(ag.get("computer_use"), dict) else {}
    return {"raenge": raenge,
            "schwarm_max": int(dg.get("schwarm_max", 8) or 8),
            "max_kosten_eur": _kosten_deckel(),
            "computer_use": bool(cu.get("enabled"))}


@app.get("/api/kalibrierung")
def api_kalibrierung(days: int = 7) -> dict:
    """Selbstkalibrierung (B-025, read-only, 0 Token): Nudge-/Fehler-/Fallback-Raten
    pro Modell aus dem Event-Log — plus der lesbare Report-Text mit Empfehlungen."""
    from core.agency import calibration

    days = max(1, min(int(days or 7), 90))
    rep = calibration.report(days)
    rep["text"] = calibration.render(days, rep)
    return rep


@app.get("/api/tagewerk")
def api_tagewerk() -> dict:
    """Kiras Tagewerk (Achievements, read-only, 0 Token): was sie HEUTE getan hat.
    Aggregation lebt in core/agency/tagewerk.py — Telegram (/tagewerk) liest dieselben Zahlen."""
    from core.agency import tagewerk

    return tagewerk.heute()


@app.get("/api/checkliste")
def api_checkliste() -> dict:
    """System-Checkliste (read-only): Gedaechtnis-Frische + Fundament-Zustand.

    Ergaenzt die vorhandenen Endpunkte (overview/digest/playbooks) um das, was nur
    per Dateisystem pruefbar ist — das Cockpit baut daraus die Ampel-Liste."""
    heute = time.strftime("%Y-%m-%d")
    journal = ROOT / "gedaechtnis" / "journal"
    stammbaum = ROOT / "gedaechtnis" / "stammbaum"
    luecken = 0
    try:
        for p in stammbaum.rglob("*.md"):
            if "_VORLAGE" in p.name:
                continue
            luecken += sum(1 for z in p.read_text(encoding="utf-8").splitlines()
                           if z.strip().startswith("-") and z.strip().endswith("???"))
    except Exception:  # noqa: BLE001
        pass
    wochen = journal / "wochen"
    return {
        "journal_heute": (journal / f"{heute}.md").exists(),
        "journal_anzahl": len(list(journal.glob("*.md"))) - (1 if (journal / "LIES-MICH.md").exists() else 0),
        "wochen_anzahl": len(list(wochen.glob("*.md"))) if wochen.exists() else 0,
        "stammbaum_luecken": luecken,
        "stammbaum_dateien": len([p for p in stammbaum.rglob("*.md") if "_VORLAGE" not in p.name]) if stammbaum.exists() else 0,
        "handbuch": (ROOT / "docs" / "HANDBUCH.md").exists(),
    }


# ---------- Widget-System (Werkbank PR 8): Kira liefert Config, nie Code ----------

@app.get("/api/widgets")
def api_widgets() -> dict:
    """Deklarative Cockpit-Kacheln aus data/widgets/*.json (validiert, whitelisted)."""
    from core.agency import widgets

    return {"widgets": widgets.list_all(), "types": list(widgets.TYPES),
            "slots": list(widgets.SLOTS), "endpoints": list(widgets.LIST_ENDPOINTS)}


@app.post("/api/widgets/save")
async def api_widgets_save(body: dict) -> dict:
    from core.agency import widgets

    res = widgets.save(body or {})
    if res.get("ok"):
        events.emit("widget_saved", {"id": res["id"], "via": "cockpit"})
    return res


@app.post("/api/widgets/delete")
async def api_widgets_delete(body: dict) -> dict:
    from core.agency import widgets

    wid = str((body or {}).get("id", ""))
    ok = widgets.delete(wid)
    if ok:
        events.emit("widget_deleted", {"id": wid, "via": "cockpit"})
    return {"ok": ok}


@app.get("/api/events")
def api_events(limit: int = 60, before: float | None = None) -> list[dict]:
    evs = events.recent(limit, before=before)
    for e in evs:
        e["sev"] = events.severity(e["type"])
        # Klartext fuer Live-Ops + Desktop-Ticker: WAS laeuft (Werkzeug/Datei/Label/Score),
        # nicht nur DASS etwas laeuft — eine Uebersetzung fuer beide Ansichten.
        e.update(events.describe(e["type"], e.get("payload")))
    return evs


@app.get("/api/memory")
def api_memory(limit: int = 80, offset: int = 0, kind: str = "", q: str = "") -> list[dict]:
    """Erinnerungen — kuratiert statt Session-Dump (Werkbank PR 5): optional serverseitig
    nach kind ('fact'/'lesson'/'skill'/... oder Rolle 'partner'/'user') und Suchtext
    gefiltert, mit offset fuer 'aeltere laden'. Ohne Parameter: Alt-Verhalten."""
    limit = max(1, min(int(limit or 80), 500))
    offset = max(0, int(offset or 0))
    rows = memory.recent(min(limit + offset + 500, 2000))
    kind = (kind or "").strip().lower()
    if kind in ("partner", "user"):
        rows = [m for m in rows if m.get("role") == kind]
    elif kind:
        rows = [m for m in rows if (m.get("kind") or "") == kind]
    ql = (q or "").strip().lower()
    if ql:
        rows = [m for m in rows if ql in str(m.get("text") or "").lower()]
    return rows[offset:offset + limit]


@app.post("/api/memory/delete-batch")
async def api_memory_delete_batch(body: dict) -> dict:
    """Mehrfachauswahl loeschen: EIN Aufruf, EIN Confirm im UI (Sergens Kernwunsch)."""
    ids = [str(i) for i in (body.get("ids") or []) if i][:200]
    for mid in ids:
        memory.delete(mid)
    if ids:
        events.emit("memory_deleted_batch", {"count": len(ids), "via": "dashboard"})
    return {"ok": bool(ids), "deleted": len(ids)}


@app.get("/api/memory/history")
def api_memory_history(limit: int = 60) -> list[dict]:
    """Chronik der Gedaechtnis-Aenderungen (add/update/delete) — vorher/nachher
    nachvollziehbar, aus dem append-only Event-Log."""
    out: list[dict] = []
    for e in events.recent(500):
        if e["type"] in ("memory_add", "memory_update", "memory_delete"):
            p = e.get("payload") or {}
            out.append({"ts": e["ts"], "action": e["type"], "role": p.get("role"),
                        "kind": p.get("kind"), "old": p.get("old"), "new": p.get("new"),
                        "text": p.get("text"), "mem_id": p.get("mem_id")})
            if len(out) >= limit:
                break
    return out


@app.post("/api/memory/delete")
async def api_memory_delete(body: dict) -> dict:
    memory.delete(body.get("id", ""))
    events.emit("memory_deleted", {"id": body.get("id", ""), "via": "dashboard"})
    return {"ok": True}


@app.get("/api/secrets")
def api_secrets() -> dict:
    from core.kernel.llm_router import _PROVIDER_KEYS

    tel_tts = (CONFIG.get("channels", {}) or {}).get("telegram", {}).get("tts", {}) or {}
    status = secrets.names_status()
    return {
        "set": status,
        "pending": secrets.pending(),
        "suggested": list(_PROVIDER_KEYS.values())
        + ["TELEGRAM_BOT_TOKEN", "BRAVE_API_KEY", "TAVILY_API_KEY",
           "GOOGLE_CSE_KEY", "GOOGLE_CSE_ID", "SEARXNG_URL", "ELEVENLABS_API_KEY",
           "SMTP_USER", "SMTP_PASS", "BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"],
        # Kira-Stimme: alles an einem Ort (Key + An/Aus + Stimme) fuer die Zugaenge-Karte.
        "tts": {
            "enabled": bool(tel_tts.get("enabled")),
            "provider": tel_tts.get("provider") or "elevenlabs",
            "voice_id": tel_tts.get("voice_id") or "",
            "key_set": bool(status.get("ELEVENLABS_API_KEY")),
        },
    }


@app.post("/api/voice/test")
async def api_voice_test(body: dict) -> dict:
    """Testet die Kira-Stimme sofort (Cockpit-Prozess hat den Key live) und liefert
    Klartext-Grund. Kein Neustart/Telegram noetig — fuer den Test-Knopf in der Zugaenge-Karte."""
    from core.agency.connectors import tts

    return tts.diagnose()


@app.post("/api/voice/say")
async def api_voice_say(body: dict):
    """Text -> gesprochenes MP3 fuer den Sprich-Modus im Cockpit (Kira liest laut vor).
    Leer, Stimme aus oder Fehler -> 204 (der Browser bleibt dann einfach still)."""
    text = (body.get("text") or "").strip()
    if not text:
        return Response(status_code=204)

    def _s():
        from core.agency.connectors import tts

        return tts.synthesize(text, session_id="cockpit-voice")

    try:
        out = await anyio.to_thread.run_sync(_s)
    except Exception:  # noqa: BLE001 — Stimme darf das Cockpit nie brechen
        out = None
    if not out:
        return Response(status_code=204)
    audio, mime = out
    return Response(content=audio, media_type=mime)


@app.post("/api/secrets/set")
async def api_secrets_set(body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "Name fehlt"}
    secrets.set_secret(name, body.get("value", ""))
    return {"ok": True}


@app.post("/api/model/use")
async def api_model_use(body: dict) -> dict:
    from core.kernel import llm_router

    active = models.set_model(body.get("id", ""))
    # Ehrlich statt still: fehlt der Key, wird gespeichert, aber offen gewarnt
    # (statt blindem ok:True, das so tut, als liefe das Cloud-Modell schon).
    warning = None
    if not llm_router.has_key(active):
        prov = active.split("/", 1)[0] if "/" in active else active
        warning = f"Kein Key fuer {prov} — laeuft bis dahin lokal."
    events.emit("model_use_set", {"model": active, "warning": warning, "via": "dashboard"})
    return {"ok": True, "active": active, "warning": warning}


@app.post("/api/model/openrouter")
async def api_model_openrouter(body: dict) -> dict:
    return {"ok": True, "active": models.add_openrouter(body.get("model", ""))}


@app.get("/api/model/catalog")
def api_model_catalog() -> dict:
    return {"catalog": models.catalog(), "roles": models.roles()}


@app.post("/api/model/role")
async def api_model_role(body: dict) -> dict:
    role = (body.get("role") or "").strip()
    model = (body.get("model") or "").strip()
    if not role or not model:
        return {"ok": False, "error": "role + model noetig"}
    m = models.set_role(role, model)
    events.emit("model_role_set", {"role": role, "model": m, "via": "dashboard"})
    return {"ok": True, "role": role, "model": m}


@app.get("/api/model/loaded")
def api_model_loaded() -> dict:
    return models.loaded()


@app.post("/api/model/params")
async def api_model_params(body: dict) -> dict:
    p = models.set_params(num_ctx=body.get("num_ctx"), max_tokens=body.get("max_tokens"))
    # Warmup: Ollama laedt mit neuem Kontext neu -> GPU-Fit sofort sichtbar
    try:
        from core.kernel import llm_router

        await anyio.to_thread.run_sync(
            lambda: llm_router.complete([{"role": "user", "content": "ok"}], task_type="chat")
        )
    except Exception:
        pass
    return {"ok": True, **p, "loaded": models.loaded()}


@app.get("/api/mission")
def api_mission() -> dict:
    from core.agency.missions import queue as mqueue

    mqueue.init_queue()
    m = CONFIG.get("mission", {})
    recent = []
    for e in events.recent(250):
        if e["type"] == "mission_task_done":
            recent.append({"ts": e["ts"], "summary": str(e["payload"].get("summary", ""))})
            if len(recent) >= 8:
                break
    return {
        "enabled": heartbeat_on(),
        "notify": bool(m.get("notify_telegram")),
        "interval": CONFIG.get("heartbeat", {}).get("interval_seconds", 1800),
        "mission": m.get("name"),
        "goal": m.get("goal", ""),
        "pending": mqueue.pending(m.get("name", "default")),
        "recent": recent,
    }


@app.post("/api/mission/toggle")
async def api_mission_toggle(body: dict) -> dict:
    set_heartbeat(bool(body.get("on")))
    events.emit("heartbeat_toggle", {"on": heartbeat_on(), "via": "dashboard"})
    return {"ok": True, "enabled": heartbeat_on()}


@app.post("/api/mission/runonce")
async def api_mission_runonce(body: dict) -> dict:
    from core.agency.missions import runner

    out = await anyio.to_thread.run_sync(runner.run_once)
    return {"ok": True, "result": out}


@app.get("/api/monitor")
def api_monitor() -> dict:
    from core.agency.connectors import news_monitor

    recent = []
    for e in events.recent(250):
        if e["type"] == "monitor_new":
            recent.append({
                "ts": e["ts"], "label": e["payload"].get("label"),
                "count": e["payload"].get("count"), "summary": e["payload"].get("summary", ""),
            })
            if len(recent) >= 8:
                break
    return {"watches": news_monitor.list_watches(), "recent": recent}


@app.post("/api/monitor/add")
async def api_monitor_add(body: dict) -> dict:
    from core.agency.connectors import news_monitor

    return {"ok": True, "watch": news_monitor.add_watch(body.get("kind", "search"), body.get("value", ""), body.get("label", ""))}


@app.post("/api/monitor/remove")
async def api_monitor_remove(body: dict) -> dict:
    from core.agency.connectors import news_monitor

    return {"ok": news_monitor.remove_watch(body.get("id", ""))}


@app.post("/api/monitor/check")
async def api_monitor_check(body: dict) -> dict:
    from core.agency.connectors import news_monitor

    out = await anyio.to_thread.run_sync(lambda: news_monitor.run_all(force=True, notify=True))
    return {"ok": True, **out}


@app.get("/api/cron")
def api_cron() -> dict:
    from core.agency.missions import cron

    return {"jobs": cron.list_jobs()}


@app.post("/api/cron/add")
async def api_cron_add(body: dict) -> dict:
    from core.agency.missions import cron

    return {"ok": True, "job": cron.add_job(
        body.get("label", ""), body.get("prompt", ""), body.get("schedule", "60m"),
        scope=body.get("scope", "system"), enabled=bool(body.get("enabled", True)))}


@app.post("/api/cron/remove")
async def api_cron_remove(body: dict) -> dict:
    from core.agency.missions import cron

    return {"ok": cron.remove_job(body.get("id", ""))}


@app.post("/api/cron/toggle")
async def api_cron_toggle(body: dict) -> dict:
    from core.agency.missions import cron

    return {"ok": True, "enabled": cron.toggle_job(body.get("id", ""))}


@app.post("/api/cron/runnow")
async def api_cron_runnow(body: dict) -> dict:
    from core.agency.missions import cron

    out = await anyio.to_thread.run_sync(lambda: cron.run_now(body.get("id", "")))
    return {"ok": True, "result": out}


@app.post("/api/cron/update")
async def api_cron_update(body: dict) -> dict:
    from core.agency.missions import cron

    ok = cron.update_job(body.get("id", ""), body.get("label"), body.get("prompt"), body.get("schedule"))
    return {"ok": ok}


@app.get("/api/services")
def api_services() -> dict:
    import json as _json
    import socket as _sock

    try:
        d = _json.loads((ROOT / "data" / "services.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {"ts": 0, "services": {}}
    fresh = (time.time() - float(d.get("ts", 0))) < 20  # Supervisor-Herzschlag frisch?

    def _up(port: int) -> bool:
        with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as so:
            so.settimeout(0.6)
            return so.connect_ex(("127.0.0.1", port)) == 0

    return {"supervisor": fresh, "services": d.get("services", {}), "ollama": _up(11434), "heartbeat": heartbeat_on()}


@app.post("/api/restart")
async def api_restart(body: dict) -> dict:
    which = (body.get("which") or "all").strip().lower() or "all"
    flag = ROOT / "data" / "restart.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(which, encoding="utf-8")
    events.emit("restart_requested", {"which": which, "via": "dashboard"})
    return {"ok": True, "which": which}


# ---------- Steuerung: Direktive, Config, Mission-Ziel, Queue, Gedaechtnis ----------
_CONFIG_WHITELIST = {
    "models.temperature", "models.max_tokens", "models.num_ctx", "models.keep_alive", "models.request_timeout",
    "governance.budget.daily_eur", "governance.budget.monthly_eur", "governance.trust_level",
    "mission.goal", "mission.notify_telegram", "heartbeat.interval_seconds",
    "channels.telegram.voice", "channels.telegram.whisper_model",
    # Kira-Stimme (TTS): An/Aus + Stimmenwahl live aus dem Cockpit
    "channels.telegram.tts.enabled", "channels.telegram.tts.provider", "channels.telegram.tts.voice_id",
    # Steuerpult: Schwarm-Regler (greifen live — delegate liest CONFIG pro Aufruf)
    "agency.delegate.schritte.reflex", "agency.delegate.schritte.arbeiter",
    "agency.delegate.schritte.denker", "agency.delegate.schritte.richter",
    "agency.delegate.schwarm_max", "agency.delegate.max_kosten_eur",
    # Computer-Use (Macht-Schritt 1): Rechner-Steuerung ein/aus — Standard AUS, bewusste Freigabe
    "agency.computer_use.enabled",
    # Feature-Flags (S12 Rezentrierung): Bausteine togglen — Werkzeuge/Loop live, UI beim Reload
    "features.desktop_low_level", "features.linkedin",
}
_MODEL_LIVE = {"models.temperature": "temperature", "models.max_tokens": "max_tokens",
               "models.num_ctx": "num_ctx", "models.keep_alive": "keep_alive"}  # live, kein Neustart


@app.post("/api/config/set")
async def api_config_set(body: dict) -> dict:
    from core.config import set_override

    path = (body.get("path") or "").strip()
    if path not in _CONFIG_WHITELIST:
        return {"ok": False, "error": "Schluessel nicht erlaubt"}
    value = body.get("value")
    live = path in _MODEL_LIVE
    if live:
        models.set_params(**{_MODEL_LIVE[path]: value})
    else:
        set_override(path, value)
    events.emit("config_set", {"path": path, "live": live, "via": "dashboard"})
    return {"ok": True, "path": path, "value": value, "live": live}


@app.get("/api/direktive")
def api_direktive() -> dict:
    from core.agency import fokus

    return fokus.get()


# ---------- Post (Phase 3): Posteingang fuers Cockpit (rein lesend, IMAP) ----------
@app.get("/api/mails")
def api_mails(limit: int = 10) -> dict:
    from core.agency.connectors import mail

    res = mail.check(max(1, min(30, limit)))
    if isinstance(res, str):  # nicht eingerichtet / Fehler -> Hinweis statt Liste
        return {"mails": [], "hint": res}
    return {"mails": res, "unread": mail.unread_count()}


# ---------- Termine (Phase 2): Kalender lesen + loeschen (anlegen macht das termin_add-Tool) ----------
@app.get("/api/termine")
def api_termine(tage: int = 60) -> dict:
    from core.agency import termine

    return {"termine": termine.list_upcoming(tage), "gesamt": len(termine.alle())}


@app.post("/api/termine/delete")
async def api_termine_delete(body: dict) -> dict:
    from core.agency import termine

    ok = termine.remove(str(body.get("id") or ""))
    return {"ok": ok} if ok else {"ok": False, "error": "Termin nicht gefunden"}


@app.post("/api/direktive")
async def api_direktive_set(body: dict) -> dict:
    # Logik lebt in core/agency/fokus.py — Telegram (/fokus) nutzt denselben Hebel.
    from core.agency import fokus

    focus = fokus.set_focus(body.get("focus") or "", via="dashboard")
    return {"ok": True, "focus": focus}


@app.post("/api/direktive/now")
async def api_direktive_now(body: dict) -> dict:
    from core.agency.act import act

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "leer"}
    sid = "direktive"
    events.emit("direktive_now", {"prompt": prompt[:200], "via": "dashboard"})
    from core.kernel import runstate
    runstate.enter_turn(sid)  # aktiver Cockpit-Zug -> Neustart wartet bis danach
    try:
        out = await anyio.to_thread.run_sync(lambda: act(prompt, session_id=sid, escalate=bool(body.get("escalate"))))
    finally:
        runstate.exit_turn(sid)
    text = (out.get("text") or "").strip()
    try:
        import os as _os

        import httpx as _hx

        tok = _os.getenv("TELEGRAM_BOT_TOKEN")
        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        if tok and chat:
            _hx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                     json={"chat_id": chat, "text": ("🎯 Direktive erledigt:\n" + text)[:4000]}, timeout=15)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "result": text}


@app.post("/api/mission/config")
async def api_mission_config(body: dict) -> dict:
    from core.config import set_override

    if body.get("goal") is not None:
        set_override("mission.goal", str(body.get("goal")))
    if body.get("interval") is not None:
        try:
            set_override("heartbeat.interval_seconds", int(body.get("interval")))
        except Exception:  # noqa: BLE001
            pass
    if body.get("notify") is not None:
        set_override("mission.notify_telegram", bool(body.get("notify")))
    events.emit("mission_config", {"via": "dashboard"})
    (ROOT / "data" / "restart.flag").write_text("runner", encoding="utf-8")  # Ziel greift nach Runner-Bounce
    return {"ok": True}


@app.post("/api/mission/queue/add")
async def api_queue_add(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    desc = (body.get("description") or "").strip()
    if not desc:
        return {"ok": False, "error": "leer"}
    mqueue.init_queue()
    tid = mqueue.add(desc, mission=CONFIG.get("mission", {}).get("name", "default"),
                     priority=int(body.get("priority", 3)),
                     objective_id=body.get("objective_id") or None,
                     due_date=(body.get("due_date") or None),
                     kind=body.get("kind", "research"))
    return {"ok": True, "id": tid}


@app.post("/api/mission/queue/remove")
async def api_queue_remove(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    return {"ok": mqueue.remove(body.get("id", ""))}


@app.post("/api/mission/queue/clear")
async def api_queue_clear(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    mqueue.init_queue()
    return {"ok": True, "cleared": mqueue.clear(CONFIG.get("mission", {}).get("name", "default"))}


# ---------- Workspace: Ziele/Projekte + To-Do-Board (Phase 1) ----------
def _mission_name() -> str:
    return CONFIG.get("mission", {}).get("name", "default")


@app.get("/api/mission/board")
def api_mission_board() -> dict:
    from core.agency.missions import objectives, queue as mqueue

    objectives.init_objectives()
    mqueue.init_queue()
    return {"objectives": objectives.list_all(), "board": mqueue.board(_mission_name())}


@app.post("/api/mission/task/update")
async def api_task_update(body: dict) -> dict:
    from core.agency.missions import queue as mqueue

    tid = body.get("id", "")
    fields = {k: body[k] for k in ("priority", "status", "objective_id", "due_date",
                                   "deferred_until", "kind", "description") if k in body}
    if "priority" in fields:
        try:
            fields["priority"] = int(fields["priority"])
        except Exception:  # noqa: BLE001
            fields.pop("priority")
    return {"ok": mqueue.update_task(tid, **fields)}


@app.get("/api/objectives")
def api_objectives() -> list[dict]:
    from core.agency.missions import objectives

    objectives.init_objectives()
    return objectives.list_all()


@app.post("/api/objectives")
async def api_objectives_add(body: dict) -> dict:
    from core.agency.missions import objectives

    title = (body.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "leer"}
    objectives.init_objectives()
    oid = objectives.add(title, kind=body.get("kind", "weekly"),
                         parent_id=body.get("parent_id") or None,
                         target_date=body.get("target_date") or None,
                         notes=body.get("notes") or None,
                         domain=body.get("domain") or "business")
    events.emit("objective_add", {"id": oid, "title": title, "kind": body.get("kind", "weekly"), "via": "dashboard"})
    return {"ok": True, "id": oid}


@app.post("/api/objectives/update")
async def api_objectives_update(body: dict) -> dict:
    from core.agency.missions import objectives

    oid = body.get("id", "")
    fields = {k: body[k] for k in ("title", "kind", "status", "progress", "target_date",
                                   "notes", "parent_id", "domain") if k in body}
    if "progress" in fields and fields["progress"] is not None:
        try:
            fields["progress"] = max(0, min(100, int(fields["progress"])))
        except Exception:  # noqa: BLE001
            fields.pop("progress")
    return {"ok": objectives.update(oid, **fields)}


@app.post("/api/objectives/delete")
async def api_objectives_delete(body: dict) -> dict:
    from core.agency.missions import objectives

    return {"ok": objectives.delete(body.get("id", ""))}


@app.post("/api/objectives/plan")
async def api_objectives_plan(body: dict) -> dict:
    """Ein Ziel per Planner in konkrete To-Dos zerlegen (LLM) und der Queue hinzufuegen."""
    from core.agency.missions import objectives, planner, queue as mqueue

    oid = body.get("id", "")
    objectives.init_objectives()
    mqueue.init_queue()
    obj = next((o for o in objectives.list_all() if o["id"] == oid), None)
    if not obj:
        return {"ok": False, "error": "Ziel nicht gefunden"}
    goal = obj["title"] + (("\n" + obj["notes"]) if obj.get("notes") else "")
    existing = [t["description"] for t in mqueue.all_tasks(_mission_name()) if t.get("objective_id") == oid]
    context = "Bereits geplant:\n" + "\n".join(existing) if existing else "(noch nichts geplant)"
    tasks = await anyio.to_thread.run_sync(lambda: planner.generate_tasks(goal, context, n=int(body.get("n", 3))))
    for t in tasks:
        mqueue.add(t, mission=_mission_name(), priority=int(body.get("priority", 3)), objective_id=oid)
    events.emit("objective_planned", {"id": oid, "tasks": tasks})
    return {"ok": True, "tasks": tasks}


# ---------- Lebens-Ebene: Todos, Ziele, Metriken (S5) ----------
@app.get("/api/life/board")
def api_life_board() -> dict:
    from core.agency.missions import objectives, queue as mqueue

    objectives.init_objectives()
    mqueue.init_queue()
    return {"objectives": objectives.list_active(domain="leben"),
            "board": mqueue.board("leben")}


@app.post("/api/life/add")
async def api_life_add(body: dict) -> dict:
    """S9.4: Todo/Auftrag direkt im Me-Bereich anlegen (mission='leben' = dein Leben-Board)."""
    from core.agency.missions import queue as mqueue

    desc = str(body.get("description", "")).strip()
    if not desc:
        return {"ok": False, "error": "leer"}
    mqueue.init_queue()
    tid = mqueue.add(desc, mission="leben", priority=int(body.get("priority", 3)),
                     due_date=body.get("due_date") or None)
    events.emit("life_todo_added", {"id": tid, "via": "cockpit"})
    return {"ok": True, "id": tid}


@app.get("/api/metrics")
def api_metrics(name: str = "", days: int = 90) -> dict:
    from core.agency.missions import metrics

    if name.strip():
        return {"name": name.strip().lower(), "series": metrics.series(name, days=days)}
    return {"latest": metrics.latest(), "names": metrics.names(),
            "dashboard": metrics.dashboard(days=days), "pinned": metrics.pinned(days=days)}


@app.post("/api/metrics/meta")
async def api_metrics_meta(body: dict) -> dict:
    """Ziel-Metadaten setzen (Anheften/Zielwert/Einheit/Emoji) — vom Cockpit editierbar."""
    from core.agency.missions import metrics

    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name fehlt"}
    kw: dict = {}
    if "pinned" in body:
        kw["pinned"] = bool(body["pinned"])
    if "target" in body:
        t = body["target"]
        if t in (None, ""):
            kw["target"] = ""
        else:
            try:
                kw["target"] = float(str(t).replace(",", "."))
            except (TypeError, ValueError):
                return {"ok": False, "error": "target braucht eine Zahl"}
    if "unit" in body:
        kw["unit"] = (body["unit"] or "")
    if "emoji" in body:
        kw["emoji"] = (body["emoji"] or "")
    metrics.set_meta(name, **kw)
    return {"ok": True}


@app.post("/api/metrics/log")
async def api_metrics_log(body: dict) -> dict:
    from core.agency.missions import metrics

    name = (body.get("name") or "").strip()
    try:
        value = float(str(body.get("value")).replace(",", "."))
    except (TypeError, ValueError):
        return {"ok": False, "error": "value braucht eine Zahl"}
    if not name:
        return {"ok": False, "error": "name fehlt"}
    metrics.log(name, value, note=body.get("note") or None)
    return {"ok": True}


# ---------- Wissens-Archiv (S5.4) ----------
@app.get("/api/knowledge")
def api_knowledge() -> dict:
    from core.mind import knowledge

    return {"docs": knowledge.list_docs()}


@app.get("/api/knowledge/search")
def api_knowledge_search(q: str, k: int = 5) -> dict:
    from core.mind import knowledge

    return {"hits": knowledge.search(q, k=max(1, min(10, k)))}


@app.post("/api/knowledge/add")
async def api_knowledge_add(body: dict) -> dict:
    from core.mind import knowledge

    return await anyio.to_thread.run_sync(
        lambda: knowledge.ingest_text((body.get("title") or "Notiz").strip(),
                                      body.get("text") or "", source="paste",
                                      tags=body.get("tags") or ""))


@app.post("/api/knowledge/upload")
async def api_knowledge_upload(file: UploadFile = File(...), tags: str = Form("")) -> dict:
    from core.mind import knowledge

    data = await file.read()
    fname = file.filename or "upload.txt"
    return await anyio.to_thread.run_sync(
        lambda: knowledge.ingest_file(data, fname, source="upload", tags=tags))


@app.post("/api/knowledge/delete")
async def api_knowledge_delete(body: dict) -> dict:
    from core.mind import knowledge

    return {"ok": knowledge.delete(body.get("id", ""))}


@app.post("/api/chat/attach")
async def api_chat_attach(file: UploadFile = File(...)) -> dict:
    """Datei (PDF/txt/md/csv/html) im Chat anhaengen: Text extrahieren, damit Kira
    direkt darauf antworten/eine Mail schreiben kann. Bild-Anhaenge laufen ueber /api/vision."""
    from core.mind import knowledge

    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        return {"ok": False, "error": "Datei zu gross (max 15 MB)"}
    fname = file.filename or "datei"
    text, err = await anyio.to_thread.run_sync(lambda: knowledge._extract(data, fname))
    if not text:
        return {"ok": False, "name": fname, "error": err or "kein Text extrahierbar"}
    cap = 12000
    return {"ok": True, "name": fname, "text": text[:cap],
            "chars": len(text), "truncated": len(text) > cap}


# ---------- Agenten-Sicht + Projekt-Spuren (S5.3b, rein lesend) ----------
_ORGANS = {
    "Planner": ("mission_planned", "objective_planned", "plan_made"),
    "Actor": ("mission_task_start", "act_start", "tool_call"),
    "Pruefer": ("task_scored", "task_criteria"),
    "Council": ("council_verdict", "council_argument", "council_opening"),
    "Curator": ("skills_curated", "lessons_curated"),
    "Reflexion": ("reflection",),
    "Monitor": ("monitor_new",),
    "Trigger": ("trigger_fired",),
    "Selbst-Check": ("doctor_report",),
}


@app.get("/api/agents")
def api_agents() -> dict:
    """Rollen-Sicht: welches Organ zuletzt gearbeitet hat + Dienste + MCP (S5)."""
    last: dict[str, dict] = {}
    for e in events.recent(500):
        for organ, types in _ORGANS.items():
            if organ not in last and e["type"] in types:
                last[organ] = {"ts": e["ts"], "event": e["type"],
                               "detail": str(e.get("payload") or {})[:140]}
    mcp: dict = {}
    try:
        from core.agency.mcp import registry_bridge

        mcp = registry_bridge.server_status()
    except Exception:  # noqa: BLE001
        pass
    skills_total = 0
    try:
        skills_total = len(memory.all_skills())
    except Exception:  # noqa: BLE001
        pass
    doctor_report = None
    for e in events.recent(500):
        if e["type"] == "doctor_report":
            doctor_report = {"ts": e["ts"], **(e.get("payload") or {})}
            break
    return {
        "organs": [{"name": o, **(last.get(o) or {})} for o in _ORGANS],
        "mcp": mcp,
        "tools_total": len(registry.all_tools()),
        "skills_total": skills_total,
        "doctor": doctor_report,
    }


@app.get("/api/tuning/stats")
def api_tuning_stats() -> dict:
    """Tuning-Werkbank: wie viel Trainingsmaterial liegt bereit (read-only, 0 Tokens)."""
    from core.mind import tuning

    return tuning.stats()


@app.post("/api/tuning/export")
async def api_tuning_export(body: dict) -> dict:
    """Exportiert den Datensatz als ChatML-JSONL (data/tuning/) — Training laeuft AUSSERHALB."""
    from core.mind import tuning

    res = tuning.export(include_episodes=body.get("include_episodes", True))
    events.emit("tuning_export", {"count": res.get("count"), "path": res.get("path")})
    return res


@app.get("/api/factory/preview")
def api_factory_preview() -> dict:
    """Werkszustand-Vorschau: was fiele einem Reset zum Opfer (mit Anzahlen)."""
    from core.kernel import factory

    return factory.preview()


@app.post("/api/factory/reset")
async def api_factory_reset(body: dict) -> dict:
    """Blanko-Handover: ausgewaehlte Kategorien auf Werkszustand (jede vorher gesichert).
    Verlangt confirm='WERKSZUSTAND'."""
    from core.kernel import factory

    res = factory.reset(scope=body.get("scope") or [], confirm=body.get("confirm", ""))
    if res.get("ok"):
        events.emit("factory_reset_via", {"scope": body.get("scope"), "via": "dashboard"})
    return res


@app.get("/api/preflight")
def api_preflight() -> dict:
    """Uebergabe-Preflight: gruener Start-Blick (Modell, MCP, Wissensbasis, Abhaengigkeiten).
    Read-only, 0 Tokens."""
    from core.kernel import preflight

    try:
        return preflight.check()
    except Exception as e:  # noqa: BLE001
        return {"items": [{"label": "Preflight", "state": "blocker", "detail": str(e)[:160]}],
                "ready": False, "blockers": 1, "todos": 0, "warns": 0}


@app.get("/api/mcp/catalog")
def api_mcp_catalog() -> dict:
    """Macht-Schritt 2: kuratierter MCP-Server-Katalog fuers Ein-Klick-Anlegen +
    aktueller Status. Zeigt pro Katalog-Eintrag, ob der noetige Zugang schon im Tresor liegt."""
    from core.agency.mcp import registry_bridge

    have = secrets.names_status()
    cat = []
    for e in registry_bridge.CATALOG:
        sec = e.get("secret") or ""
        cat.append({**{k: e[k] for k in ("id", "label", "info", "secret")},
                    "setup": e.get("setup", ""),
                    "secret_ready": (not sec) or bool(have.get(sec))})
    return {"catalog": cat, "status": registry_bridge.server_status()}


@app.post("/api/mcp/add")
async def api_mcp_add(body: dict) -> dict:
    """Server aus dem Katalog oder frei per Config hinzufuegen (und live einstoepseln)."""
    from core.agency.mcp import registry_bridge

    name = (body.get("name") or "").strip()
    cfg = body.get("config")
    cat_id = body.get("catalog_id")
    if cat_id and not cfg:                       # Ein-Klick aus dem Katalog
        entry = next((e for e in registry_bridge.CATALOG if e["id"] == cat_id), None)
        if not entry:
            return {"ok": False, "error": f"Katalog-Eintrag '{cat_id}' unbekannt."}
        name = name or entry["id"]
        cfg = dict(entry["config"])
    if not isinstance(cfg, dict):
        return {"ok": False, "error": "config fehlt oder ist ungueltig."}
    return registry_bridge.add_server(name, cfg)


@app.post("/api/mcp/toggle")
async def api_mcp_toggle(body: dict) -> dict:
    from core.agency.mcp import registry_bridge

    return registry_bridge.toggle_server((body.get("name") or "").strip(), bool(body.get("enabled")))


@app.post("/api/mcp/remove")
async def api_mcp_remove(body: dict) -> dict:
    from core.agency.mcp import registry_bridge

    return registry_bridge.remove_server((body.get("name") or "").strip())


@app.post("/api/metrics/delete")
async def api_metrics_delete(body: dict) -> dict:
    """Metrik komplett entfernen (Werte + Ziel-Meta)."""
    from core.agency.missions import metrics as _metrics

    ok = _metrics.delete(body.get("name", ""))
    if ok:
        events.emit("metric_deleted", {"name": str(body.get("name", ""))[:60]})
    return {"ok": ok}


# ---------- Freigabe-Inbox + Tages-Digest (Phase 2) ----------
def _pending_proposals() -> list[dict]:
    """Offene Selbstaenderungs-Vorschlaege (alle MUTABLE-Docs) als Inbox-Eintraege (kind=evolution)."""
    from core.mind import evolution

    out = []
    pdir = ROOT / "data" / "proposals"
    try:
        for doc in sorted(evolution.MUTABLE):
            p = pdir / doc
            if p.exists():
                out.append({"id": "prop:" + doc, "ts": p.stat().st_mtime, "kind": "evolution",
                            "title": f"Selbst-Aenderung: {doc}", "detail": p.read_text(encoding="utf-8")[:4000],
                            "ref": doc, "source": "kira", "status": "pending"})
    except Exception:  # noqa: BLE001
        pass
    return out


@app.get("/api/approvals")
def api_approvals() -> dict:
    from core.agency import approvals

    approvals.init_approvals()
    pend = approvals.pending() + _pending_proposals()
    pend.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return {"pending": pend, "recent": approvals.recent(20)}


@app.post("/api/approvals/decide")
async def api_approvals_decide(body: dict) -> dict:
    from core.agency import approvals

    aid = body.get("id", "")
    approved = bool(body.get("approved"))
    note = body.get("note")
    if aid.startswith("prop:"):  # Selbstaenderungs-Vorschlag (MUTABLE-Doc)
        doc = aid[5:]
        pfile = ROOT / "data" / "proposals" / doc
        if not pfile.exists():  # bereits entschieden (Doppelklick) oder nie da
            return JSONResponse({"ok": False, "error": "kein offener Vorschlag (bereits entschieden?)"},
                                status_code=409)
        if approved:
            try:
                from core.mind import evolution
                # apply_update konsumiert den Vorschlag -> zweiter Klick landet oben im 409
                res = await anyio.to_thread.run_sync(lambda: evolution.apply_update(doc, "Freigabe via Inbox"))
                return {"ok": True, "status": "approved", "applied": res}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)}
        else:
            try:
                pfile.unlink()
            except OSError:
                pass
            events.emit("approval_decided", {"id": aid, "status": "rejected", "kind": "evolution"})
            return {"ok": True, "status": "rejected"}
    res = approvals.decide(aid, approved, note)
    if not res.get("ok") and res.get("error") == "already decided":
        return JSONResponse(res, status_code=409)
    return res


@app.get("/api/digest")
def api_digest() -> dict:
    """Tages-Digest: was Kira heute getan/produziert hat + offene Freigaben."""
    import datetime as _dt
    from core.agency import approvals

    start = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    done, planned, artifacts = [], 0, []
    errs = 0
    for e in events.recent(600):
        if e["ts"] < start:
            continue
        t, p = e["type"], (e.get("payload") or {})
        if t == "mission_task_done":
            done.append(str(p.get("summary", ""))[:160])
        elif t == "objective_planned":
            planned += len(p.get("tasks", []) or [])
        elif t in ("file_edited",):
            artifacts.append(str(p.get("file", "")))
        elif t in ("turn_timeout", "llm_call_timeout", "service_crash", "act_degraded"):
            errs += 1
    approvals.init_approvals()
    news = 0
    try:
        from core.agency.connectors import news_monitor
        news = len(news_monitor.recent_reports() or []) if hasattr(news_monitor, "recent_reports") else 0
    except Exception:  # noqa: BLE001
        news = 0
    return {
        "date": _dt.date.today().isoformat(),
        "tasks_done": done[:10], "tasks_done_count": len(done),
        "planned": planned, "artifacts": artifacts[:10],
        "pending_approvals": len(approvals.pending()) + len(_pending_proposals()),
        "errors": errs, "news": news,
        "spend_usd": round(today_spend_usd(), 4), "budget": treasury.status(),
    }


@app.get("/api/costs")
def api_costs() -> dict:
    """Kosten-Aufschluesselung aus den llm_call-Events: heute + 7 Tage, pro Modell + Top-Sessions."""
    import datetime as _dt
    from collections import defaultdict

    start_today = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    start_7d = time.time() - 7 * 86400
    m_today: dict = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    m_7d: dict = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    sess: dict = defaultdict(float)
    tot_today = tot_7d = 0.0
    for e in events.recent(4000):
        if e["type"] != "llm_call":
            continue
        p = e.get("payload") or {}
        cost = float(p.get("cost_usd") or 0.0)
        model = p.get("model", "?")
        if e["ts"] >= start_7d:
            m_7d[model]["calls"] += 1; m_7d[model]["cost"] += cost; tot_7d += cost
        if e["ts"] >= start_today:
            m_today[model]["calls"] += 1; m_today[model]["cost"] += cost; tot_today += cost
            sess[e.get("session_id") or "?"] += cost

    def _fmt(d):
        return sorted([{"model": m, "calls": v["calls"], "cost": round(v["cost"], 4)} for m, v in d.items()],
                      key=lambda x: -x["cost"])
    top = sorted([{"session": s, "cost": round(c, 4)} for s, c in sess.items() if c > 0], key=lambda x: -x["cost"])[:6]
    return {"today": {"total": round(tot_today, 4), "by_model": _fmt(m_today), "top_sessions": top},
            "week": {"total": round(tot_7d, 4), "by_model": _fmt(m_7d)},
            "budget": treasury.status()}


def _token_stats() -> dict:
    """Token-Verbrauch heute je Rolle (Fable-Review: bei Gratis-Modellen ist die $-Bremse blind —
    Sichtbarkeit in Tokens/Calls statt harter Limits, Sergens Entscheidung). Reines SQL-Aggregat
    ueber llm_call-Events, fail-soft."""
    import datetime as _dt
    import sqlite3 as _sq

    from core import config as _c  # Call-time-Read -> Sandbox/Test-Umlenkung greift

    try:
        start = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with _sq.connect(_c.DB_PATH) as c:
            c.execute("PRAGMA busy_timeout=5000")
            rows = c.execute(
                "SELECT COALESCE(json_extract(payload,'$.task_type'),'?') tt, COUNT(*) calls,"
                " SUM(COALESCE(json_extract(payload,'$.tokens.prompt'),0)"
                "   + COALESCE(json_extract(payload,'$.tokens.completion'),0)) tok,"
                " SUM(COALESCE(json_extract(payload,'$.cost_usd'),0)) cost"
                " FROM events WHERE type='llm_call' AND ts>=? GROUP BY tt ORDER BY tok DESC",
                (start,)).fetchall()
        by_role = [{"role": r[0], "calls": r[1], "tokens": int(r[2] or 0),
                    "cost_usd": round(r[3] or 0.0, 4)} for r in rows]
        return {"total_tokens": sum(x["tokens"] for x in by_role),
                "total_calls": sum(x["calls"] for x in by_role), "by_role": by_role}
    except Exception:  # noqa: BLE001
        return {"total_tokens": 0, "total_calls": 0, "by_role": []}


@app.get("/api/insights")
def api_insights(days: int = 14) -> dict:
    """Lern-Statistik (S6.6c): Outcome-Muster aus insights.py, rein lesend fuers Cockpit."""
    from core.agency import insights, outcomes, selfmetrics

    days = max(1, min(int(days or 14), 90))
    return {
        "days": days,
        "stats": outcomes.stats(days),
        "patterns": insights.fail_patterns(days),
        "strategies": insights.strategy_stats(days),
        "brief": insights.render_brief(days),
        "tokens_heute": _token_stats(),
        "selbstmessung": {"verlauf": selfmetrics.history(limit=26),
                          "trend": selfmetrics.trend()},
    }


@app.get("/api/playbooks")
def api_playbooks() -> dict:
    """S11: Playbook-Uebersicht (rein lesend) — Reifegrade, Zaehler, Lektionen fuers Cockpit."""
    from core.mind import playbooks

    return {"playbooks": playbooks.list_playbooks(),
            "grades": list(playbooks.GRADES),
            "promote_after": playbooks.PROMOTE_AFTER}


@app.get("/api/desktop")
def api_desktop() -> dict:
    """S8.5: Desktop-Pflege-Config + Vorschau des naechsten Scans (read-only)."""
    from core.agency import desktop_watch

    cfg = desktop_watch.load_cfg()
    preview = desktop_watch.scan(cfg) if cfg.get("enabled") else {"scanned": 0, "suggestions": []}
    return {"config": cfg, "preview": preview}


@app.post("/api/desktop/config")
async def api_desktop_config(body: dict) -> dict:
    from core.agency import desktop_watch

    cfg = desktop_watch.load_cfg()
    if "enabled" in body:
        cfg["enabled"] = bool(body["enabled"])
    if isinstance(body.get("folders"), list):
        cfg["folders"] = [str(f) for f in body["folders"] if str(f).strip()]
    desktop_watch.save_cfg(cfg)
    return {"ok": True, "config": cfg}


@app.post("/api/desktop/scan")
async def api_desktop_scan(body: dict) -> dict:
    """Sofort einen Sortiervorschlag erzeugen (landet in der Freigabe-Inbox)."""
    from core.agency import desktop_watch

    return await anyio.to_thread.run_sync(desktop_watch.propose)


@app.post("/api/desktop/shortcut")
async def api_desktop_shortcut(body: dict) -> dict:
    """Ein-Klick: legt (nur Windows) die Desktop-Verknuepfung 'Kira' mit Logo + Autostart an,
    indem desktop-setup.ps1 ausgefuehrt wird. So braucht Sergen keinen Ordner und keine .bat."""
    import sys

    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "nur unter Windows"}
    ps1 = ROOT / "desktop-setup.ps1"
    if not ps1.exists():
        return {"ok": False, "error": "desktop-setup.ps1 fehlt"}

    def _run() -> dict:
        import subprocess
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            ok = p.returncode == 0
            # bei Fehler die echte PowerShell-Ausgabe zurueckgeben (statt eines nichtssagenden "?")
            err = "" if ok else (out[-500:] or f"PowerShell-Exitcode {p.returncode}")
            return {"ok": ok, "output": out[-800:], "error": err}
        except FileNotFoundError:
            return {"ok": False, "error": "PowerShell nicht gefunden"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:400]}

    return await anyio.to_thread.run_sync(_run)


@app.get("/api/evolution")
def api_evolution(limit: int = 40) -> dict:
    """S8.1: 'Was ich zuletzt an mir verbessert habe' — Timeline aus dem Event-Log
    (self_edit/selfdev/self_tick/learn_skill/self_update/insights) + Skills + Lektionen."""
    _KINDS = {
        "self_tick": "🔧 Selbst-Optimierung", "selfdev_applied": "✅ Code geaendert",
        "selfdev_rejected": "↩ Aenderung verworfen (Test rot)", "selfdev_verify_failed": "↩ Verify fehlgeschlagen",
        "self_update_proposed": "🧬 Selbst-Update vorgeschlagen", "self_update_applied": "🧬 Selbst-Update angewendet",
        "insights_weekly": "💡 Wochen-Lektionen gezogen", "insights_lessons": "💡 Lektionen gezogen",
        "write_blocked": "🛡 Schreibschutz griff", "evolution_blocked": "🛡 Evolution blockiert",
    }
    timeline = []
    for e in events.recent(600):
        lbl = _KINDS.get(e["type"])
        if not lbl:
            continue
        p = e.get("payload") or {}
        detail = p.get("summary") or p.get("file") or p.get("doc") or p.get("name") or ""
        timeline.append({"ts": e["ts"], "type": e["type"], "label": lbl, "detail": str(detail)[:200]})
        if len(timeline) >= limit:
            break
    skills = memory.all_skills()[:20] if hasattr(memory, "all_skills") else []
    # Lektionen MIT id (statt recall_lessons-Strings) -> das ✕ im Cockpit kann loeschen.
    lessons = memory.all_lessons()[:8] if hasattr(memory, "all_lessons") else []
    return {"timeline": timeline, "skills": skills, "lessons": lessons}


_NEWS_CACHE: dict = {"ts": 0.0, "data": None}
_NEWS_FEEDS = [
    ("HN", "https://hnrss.org/frontpage"),
    ("HN·AI", "https://hnrss.org/newest?q=AI+OR+LLM+OR+agent"),
]


@app.get("/api/news")
def api_news() -> dict:
    """KI/Tech-News aus Default-RSS-Feeds (serverseitig, 15-min-Cache) — laeuft
    unabhaengig vom manuellen Monitor, damit der Ticker sofort lebt."""
    import time as _t
    import xml.etree.ElementTree as ET

    import httpx as _hx

    if _NEWS_CACHE["data"] and (_t.time() - _NEWS_CACHE["ts"]) < 900:
        return _NEWS_CACHE["data"]
    items: list[dict] = []
    for label, url in _NEWS_FEEDS:
        try:
            r = _hx.get(url, timeout=8, headers={"User-Agent": "KiraCockpit/1.0"})
            root = ET.fromstring(r.text)
            cnt = 0
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                if title:
                    items.append({"source": label, "title": title[:160], "link": link})
                    cnt += 1
                if cnt >= 7:
                    break
        except Exception:  # noqa: BLE001
            continue
    out = {"items": items[:16], "ts": _t.time()}
    _NEWS_CACHE.update(ts=_t.time(), data=out)
    return out


@app.post("/api/memory/update")
async def api_memory_update(body: dict) -> dict:
    ok = memory.update_text(body.get("id", ""), body.get("text", ""))
    events.emit("memory_updated", {"id": body.get("id", ""), "via": "dashboard"})
    return {"ok": ok}


@app.post("/api/memory/add")
async def api_memory_add(body: dict) -> dict:
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "leer"}
    mid = memory.remember(text, role=body.get("role", "user"), kind=body.get("kind", "semantic"))
    events.emit("memory_added", {"id": mid, "via": "dashboard"})
    return {"ok": True, "id": mid}


@app.post("/api/kill")
async def api_kill(body: dict) -> dict:
    if body.get("on"):
        kill_switch_path().write_text("stop", encoding="utf-8")
        events.emit("kill_switch_set", {"via": "dashboard"})
    else:
        p = kill_switch_path()
        if p.exists():
            p.unlink()
        events.emit("kill_switch_clear", {"via": "dashboard"})
    return {"ok": True, "kill_switch": kill_switch_active()}


@app.get("/api/bg")
def api_bg():
    # no-store: der Browser soll das Hintergrundbild nie aus dem Cache holen, sonst
    # "haengt" ein altes Bild nach dem Wechsel (Sergen: aendern -> neu laden -> alt).
    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"background.{ext}"
        if p.exists():
            return FileResponse(str(p), headers={"Cache-Control": "no-store, max-age=0"})
    return Response(status_code=404)


@app.post("/api/bg/upload")
async def api_bg_upload(body: dict) -> dict:
    import base64
    import re

    m = re.match(r"data:image/(\w+);base64,(.+)$", body.get("dataurl", ""), re.DOTALL)
    if not m:
        return {"ok": False, "error": "kein gueltiges Bild"}
    ext = m.group(1).lower().replace("jpeg", "jpg")
    raw = base64.b64decode(m.group(2))
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        old = data_dir / f"background.{e}"
        if old.exists():
            old.unlink()
    (data_dir / f"background.{ext}").write_bytes(raw)
    events.emit("background_set", {"ext": ext, "bytes": len(raw)})
    return {"ok": True, "ext": ext, "bytes": len(raw)}


@app.post("/api/bg/clear")
async def api_bg_clear(body: dict) -> dict:
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"background.{e}"
        if p.exists():
            p.unlink()
    return {"ok": True}


# ---------- Kira-Avatar (S6.6d) — Sergens Higgsfield-Bild fuer Hero + Chat ----------
@app.get("/api/avatar")
def api_avatar():
    # no-store wie bei /api/bg: sonst haelt der Browser das ALTE Avatarbild im Cache und
    # nach einem Wechsel/Reload springt es sichtbar zurueck (die Datei auf der Platte ist neu).
    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"avatar.{ext}"
        if p.exists():
            return FileResponse(str(p), headers={"Cache-Control": "no-store, max-age=0"})
    return Response(status_code=404)


@app.post("/api/avatar/upload")
async def api_avatar_upload(body: dict) -> dict:
    import base64
    import re

    m = re.match(r"data:image/(\w+);base64,(.+)$", body.get("dataurl", ""), re.DOTALL)
    if not m:
        return {"ok": False, "error": "kein gueltiges Bild"}
    ext = m.group(1).lower().replace("jpeg", "jpg")
    raw = base64.b64decode(m.group(2))
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        old = data_dir / f"avatar.{e}"
        if old.exists():
            old.unlink()
    (data_dir / f"avatar.{ext}").write_bytes(raw)
    events.emit("avatar_set", {"ext": ext, "bytes": len(raw)})
    return {"ok": True, "ext": ext, "bytes": len(raw)}


@app.post("/api/avatar/clear")
async def api_avatar_clear(body: dict) -> dict:
    for e in ("jpg", "jpeg", "png", "webp", "gif"):
        p = ROOT / "data" / f"avatar.{e}"
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.post("/api/transcribe")
async def api_transcribe(body: dict) -> dict:
    import base64
    import re

    m = re.match(r"data:audio/[\w.+-]+;base64,(.+)$", body.get("audio", ""), re.DOTALL)
    if not m:
        return {"ok": False, "error": "kein Audio"}
    raw = base64.b64decode(m.group(1))
    vdir = ROOT / "data" / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    fp = vdir / f"cockpit-{int(time.time())}.webm"
    fp.write_bytes(raw)

    def _t():
        from core.agency.connectors.transcribe import transcribe

        return transcribe(str(fp))

    try:
        txt = await anyio.to_thread.run_sync(_t)
    except ImportError:
        return {"ok": False, "error": "faster-whisper fehlt (uv sync)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": txt or ""}


@app.post("/api/vision")
async def api_vision(body: dict) -> dict:
    img = body.get("image", "")
    if not img.startswith("data:image"):
        return {"ok": False, "error": "kein Bild"}
    prompt = (body.get("prompt") or "").strip()

    def _call():
        from core.agency import vision

        return vision.describe(img, prompt)

    try:
        txt = await anyio.to_thread.run_sync(_call)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": txt}


# S7c: Session-Metadaten (Archiv-Flag) als Sidecar — Sessions selbst leben im Memory.
_CHAT_META = ROOT / "data" / "chat_meta.json"


def _chat_meta() -> dict:
    try:
        return json.loads(_CHAT_META.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_chat_meta(meta: dict) -> None:
    atomic_write(_CHAT_META, json.dumps(meta, indent=1, ensure_ascii=False))


@app.get("/api/chat/sessions")
def api_chat_sessions(archived: int = 0) -> dict:
    """Sessions-Liste; archivierte sind standardmaessig ausgeblendet (archived=1 zeigt alle)."""
    meta = _chat_meta()
    out = []
    for s in memory.sessions(limit=60):
        arch = bool((meta.get(s["session_id"]) or {}).get("archived"))
        if arch and not archived:
            continue
        out.append({**s, "archived": arch})
    return {"sessions": out}


@app.post("/api/chat/archive")
async def api_chat_archive(body: dict) -> dict:
    sid = str(body.get("sid", "")).strip()
    if not sid:
        return {"ok": False, "error": "sid fehlt"}
    meta = _chat_meta()
    meta.setdefault(sid, {})["archived"] = bool(body.get("archived", True))
    _save_chat_meta(meta)
    return {"ok": True, "archived": meta[sid]["archived"]}


@app.get("/api/chat/history")
def api_chat_history(sid: str = "") -> dict:
    return {"messages": memory.recent_dialogue(sid, limit=200) if sid else []}


@app.post("/api/chat/delete")
async def api_chat_delete(body: dict) -> dict:
    return {"ok": True, "deleted": memory.clear_session(body.get("sid", ""))}


@app.post("/api/memory/reset-episodic")
async def api_memory_reset_episodic(body: dict) -> dict:
    """Setzt den gesamten Chat-/Gespraechsstrang auf null (mit Backup) — Fakten bleiben.
    Bewusst confirm-gesichert, damit nichts aus Versehen passiert."""
    if not body.get("confirm"):
        return {"ok": False, "error": "confirm fehlt — nichts geloescht"}
    res = memory.reset_episodic(backup=True)
    return {"ok": True, **res}


# ---------- Chat (Live-Thinking) ----------
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    import uuid

    from core.agency.act import act_chat_stream

    from core.kernel import runstate
    from core.api import security

    if not security.ws_allowed(ws):  # Fernzugriff aktiv -> auch WS braucht das Token
        await ws.close(code=4401)
        return
    await ws.accept()
    sid = ws.query_params.get("sid") or ("cockpit-" + uuid.uuid4().hex[:8])
    # Kein "Verbunden. Session …"-Rauschen mehr im Chat — der Verbindungspunkt (ws-dot) reicht.
    try:
        while True:
            user_text = await ws.receive_text()
            runstate.enter_turn(sid)  # aktiver Cockpit-Zug -> Neustart (self_edit/restart_self) wartet bis danach
            try:
                gen = act_chat_stream(user_text, sid)

                def next_piece():
                    try:
                        return next(gen)
                    except StopIteration:
                        return None

                while True:
                    piece = await anyio.to_thread.run_sync(next_piece)
                    if piece is None:
                        break
                    await ws.send_json({"role": "partner", **piece})
                await ws.send_json({"role": "partner", "done": True})
            finally:
                runstate.exit_turn(sid)  # idle -> ein aufgeschobener Neustart wird jetzt ausgeloest (nach der Antwort)
    except WebSocketDisconnect:
        pass


def _bench_record(meta: dict, ev: dict) -> None:
    """Benchmark-Endstand dauerhaft ablegen (Leaderboard) — data/bench/results.jsonl."""
    import json as _j
    import time as _t
    from pathlib import Path as _P

    from core import config as _c

    try:
        row = {"ts": _t.time(), "suite": ev.get("suite") or meta.get("suite") or "harness",
               "role": ev.get("role") or meta.get("role") or "",
               "model": ev.get("model") or meta.get("model") or "",
               "total": ev.get("total"), "passed": ev.get("passed"),
               "pass_at_1": ev.get("pass_at_1")}
        d = _P(_c.DATA_DIR) / "bench"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "results.jsonl", "a", encoding="utf-8") as f:
            f.write(_j.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — Leaderboard-Schreiben darf den Lauf nie stoeren
        pass


@app.get("/api/model/resolve")
def api_model_resolve(role: str = "reason") -> dict:
    """Welches Modell laeuft WIRKLICH auf einer Rolle? (Benchmark-Anzeige: Sergen sah
    vorher das Chat-Modell und wunderte sich, warum 'Denker' nicht GLM zeigt.)"""
    from core.kernel import llm_router

    try:
        m, fb = llm_router.resolve_model(str(role or "reason"))
        return {"role": role, "model": m, "fallback": bool(fb)}
    except Exception as e:  # noqa: BLE001
        return {"role": role, "model": "?", "error": str(e)[:120]}


@app.get("/api/bench/results")
def api_bench_results(limit: int = 50) -> dict:
    """Alle bisherigen Benchmark-Laeufe (neueste zuerst) — fuers Leaderboard im Cockpit."""
    import json as _j
    from pathlib import Path as _P

    from core import config as _c

    p = _P(_c.DATA_DIR) / "bench" / "results.jsonl"
    rows: list[dict] = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(_j.loads(line))
                except Exception:  # noqa: BLE001
                    pass
    return {"results": rows[-max(1, min(int(limit or 50), 200)):][::-1]}


@app.post("/api/bench/delete")
async def api_bench_delete(body: dict) -> dict:
    """Einen Leaderboard-Eintrag loeschen (ts identifiziert die Zeile).
    Temp-Datei + os.replace gegen Race mit einem laufenden Lauf (append)."""
    import json as _j
    import os as _os
    from pathlib import Path as _P

    from core import config as _c

    try:
        ts = float(body.get("ts") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "ts fehlt"}
    p = _P(_c.DATA_DIR) / "bench" / "results.jsonl"
    if not ts or not p.exists():
        return {"ok": False, "error": "nichts zu loeschen"}
    kept, removed = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = _j.loads(line)
        except Exception:  # noqa: BLE001
            kept.append(line)
            continue
        if abs(float(row.get("ts") or 0) - ts) < 0.5:
            removed += 1
        else:
            kept.append(line)
    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    _os.replace(str(tmp), str(p))
    events.emit("bench_result_deleted", {"ts": ts, "removed": removed})
    return {"ok": removed > 0, "removed": removed}


@app.websocket("/ws/bench")
async def ws_bench(ws: WebSocket) -> None:
    """Coding-Benchmark live: startet die Suite in einem isolierten Worktree und streamt
    Kiras Denk-/Werkzeug-Strom + je Aufgabe das Ergebnis + den Endstand ans Cockpit."""
    from core.config import ROOT
    from core.testkit import bench
    from core.api import security

    if not security.ws_allowed(ws):  # Fernzugriff aktiv -> auch WS braucht das Token
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        try:
            msg = await ws.receive_text()
            cfg = json.loads(msg) if (msg or "").strip().startswith("{") else {}
        except Exception:  # noqa: BLE001
            cfg = {}
        if (cfg.get("suite") or "") == "humaneval":
            # Internationaler Standard (pass@1, vergleichbar mit publizierten Scores) —
            # misst das MODELL direkt, Rolle waehlbar (reason/bulk/chat/classify).
            from core.testkit import humaneval

            gen = humaneval.stream_humaneval(
                limit=max(1, min(int(cfg.get("limit") or 20), 164)),
                role=str(cfg.get("role") or "reason"),
                model=(str(cfg.get("model")).strip() or None) if cfg.get("model") else None)
        elif (cfg.get("suite") or "") == "swebench":
            # SWE-bench Lite: misst AGENT+MODELL zusammen (echte GitHub-Issues).
            # 'passed' = Prognose (Datei-Treffer); amtlicher Score via predictions.jsonl.
            from core.testkit import swebench

            gen = swebench.stream_swebench(
                limit=max(1, min(int(cfg.get("limit") or 3), 300)),
                allow_llm=bool(cfg.get("allow_llm", True)),
                model=(str(cfg.get("model")).strip() or None) if cfg.get("model") else None)
        else:
            suite = str(ROOT / (cfg.get("suite") or "tests/bench/suite.json"))
            allow = bool(cfg.get("allow_llm", True))  # echtes Modell testen (Modell-Vergleich)
            gen = bench.stream_suite(suite, allow_llm=allow)

        def _next():
            try:
                return next(gen)
            except StopIteration:
                return None

        meta = {"suite": (cfg.get("suite") or "harness"), "role": cfg.get("role") or ""}
        while True:
            ev = await anyio.to_thread.run_sync(_next)
            if ev is None:
                break
            if ev.get("kind") == "summary":
                _bench_record(meta, ev)  # Endstand fuers Leaderboard sichern
            await ws.send_json(ev)
        await ws.send_json({"kind": "done"})
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_json({"kind": "error", "text": str(e)[:300]})
        except Exception:  # noqa: BLE001
            pass


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # Sprüche-Katalog (eine Quelle) in die Seite injizieren -> kein Extra-Request, kein Drift.
    # [1:-1] = ohne aeussere Klammern (die stehen schon im JS: const PHRASES=[...]) -> bei
    # ausbleibender Injektion bleibt [] als sichere, gueltige Fallback-Form.
    inner = json.dumps(THINKING_PHRASES, ensure_ascii=False)[1:-1]
    # Feature-Flags fuers UI-Gating (gleiche [1:-1]-Technik, Fallback {} = alles sichtbar —
    # UI ist fail-open ok, das Werkzeug-Gating sitzt serverseitig in der Registry).
    feats = json.dumps(CONFIG.get("features") or {}, ensure_ascii=False)[1:-1]
    return _ident_tokens(DASHBOARD_HTML.replace("/*__PHRASES__*/", inner)
                         .replace("/*__FEATURES__*/", feats))


@app.get("/setup", response_class=HTMLResponse)
def setup_page() -> str:
    # Erst-Einrichtung (W3). Eingerichtete Instanzen sehen den Wizard nie wieder.
    if _onboarding.is_onboarded():
        return '<meta http-equiv="refresh" content="0; url=/">'
    from core.api.ui.setup import SETUP_HTML
    return SETUP_HTML


@app.post("/api/setup")
def api_setup(body: dict) -> dict:
    """Wizard-Abschluss: Namen -> Overrides, Zugaenge -> Tresor, Mind-Seed +
    Stammbaum-Wurzel, Flag, Bot+Runner-Bounce. Nur EINMAL moeglich (Flag-Guard)."""
    if _onboarding.is_onboarded():
        return {"ok": False, "error": "Diese Instanz ist schon eingerichtet."}
    agent = str(body.get("agent") or "Kira").strip()[:40] or "Kira"
    user = str(body.get("user") or "").strip()[:40]
    if not user:
        return {"ok": False, "error": "Nutzer-Name fehlt."}
    from core.config import set_override
    set_override("identity.partner_name", agent)
    set_override("identity.user", user)
    chat = str(body.get("telegram_chat_id") or "").strip()
    if chat.isdigit():
        set_override("channels.telegram.allowed_chat_id", int(chat))
    for feld, secret_name in (("telegram_token", "TELEGRAM_BOT_TOKEN"),
                              ("openrouter_key", "OPENROUTER_API_KEY")):
        wert = str(body.get(feld) or "").strip()
        if wert:
            secrets.set_secret(secret_name, wert)
    from core import identity as _idm
    from core.mind import seed
    seed.render_mind(agent, user, force=True)
    wurzel = ROOT / "gedaechtnis" / "stammbaum" / f"{user.upper()}.md"
    vorlage = ROOT / "gedaechtnis" / "stammbaum" / "_WURZEL_VORLAGE.md"
    if not wurzel.exists() and vorlage.exists():
        from core.kernel.fs import atomic_write
        atomic_write(wurzel, _idm.render(vorlage.read_text(encoding="utf-8")))
    _onboarding.complete("wizard")
    # Bot + Runner neu starten lassen: frische Prozesse laden Token/Key aus dem Tresor
    flag = ROOT / "data" / "restart.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("bot,runner", encoding="utf-8")
    events.emit("onboarding_complete", {"agent": agent, "user": user})
    return {"ok": True}


@app.get("/wall", response_class=HTMLResponse)
def wall() -> str:
    # Desktop-Wallpaper-Seite (rahmenlos): Stats + Live-Vault-Graph + ephemerer Chat.
    # Gleiche PHRASES-Injektion wie index() -> das Thinking im Wallpaper-Chat nutzt echte Sprueche.
    inner = json.dumps(THINKING_PHRASES, ensure_ascii=False)[1:-1]
    return _ident_tokens(WALL_HTML.replace("/*__PHRASES__*/", inner))


@app.get("/api/vault/graph")
def api_vault_graph() -> dict:
    # Live-Obsidian-Vault als Graph (rein lesend): Notizen + [[Verlinkungen]] -> Knoten + Faeden.
    from core.api import vault_graph
    return vault_graph.build_graph()


@app.get("/api/icon")
def api_icon():
    # App-Logo (data/kira-icon.*) fuer Cockpit-Kopf + Favicon + Desktop-App-Tray. 404 -> Default.
    for ext in ("png", "jpg", "jpeg", "webp", "ico"):
        p = ROOT / "data" / f"kira-icon.{ext}"
        if p.exists():
            return FileResponse(str(p), headers={"Cache-Control": "no-store"})
    return Response(status_code=404)


@app.post("/api/icon/upload")
async def api_icon_upload(body: dict) -> dict:
    # App-Logo bequem aus dem Cockpit setzen (kein Datei-Geschiebe): speichert data/kira-icon.<ext>.
    # Wird sofort ueberall genutzt (Cockpit-Kopf, /wall-Favicon, Desktop-Tray).
    import base64
    import re

    m = re.match(r"data:image/(\w+);base64,(.+)$", body.get("dataurl", ""), re.DOTALL)
    if not m:
        return {"ok": False, "error": "kein gueltiges Bild"}
    ext = m.group(1).lower().replace("jpeg", "jpg")
    if ext not in ("png", "jpg", "webp", "ico"):
        return {"ok": False, "error": f"Format .{ext} nicht unterstuetzt"}
    raw = base64.b64decode(m.group(2))
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for e in ("png", "jpg", "jpeg", "webp", "ico"):   # alte Logos raeumen -> nur eins bleibt
        old = data_dir / f"kira-icon.{e}"
        if old.exists():
            old.unlink()
    (data_dir / f"kira-icon.{ext}").write_bytes(raw)
    # Zusaetzlich ein .ico erzeugen -> Windows nutzt es als FENSTER- und TASKLEISTEN-Symbol der
    # Desktop-App (dafuer reicht .png/.jpg nicht). Pillow ist optional; fehlt es, laeuft alles weiter,
    # nur das Fenstersymbol bleibt generisch (dann greift ersatzweise kira-einrichten.bat).
    ico_made = False
    try:
        import io

        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        img.save(str(data_dir / "kira-icon.ico"), format="ICO",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        ico_made = True
    except Exception:  # noqa: BLE001 — Pillow optional / kaputtes Bild
        pass
    events.emit("app_icon_set", {"ext": ext, "bytes": len(raw), "ico": ico_made})
    return {"ok": True, "ext": ext, "bytes": len(raw), "ico": ico_made}


@app.post("/api/icon/clear")
async def api_icon_clear(body: dict) -> dict:
    for e in ("png", "jpg", "jpeg", "webp", "ico"):
        p = ROOT / "data" / f"kira-icon.{e}"
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.get("/api/mails/unread")
def api_mails_unread() -> dict:
    # Ungelesene Mails fuer die Desktop-Leiste (gecacht). None -> Postfach nicht eingerichtet.
    from core.agency.connectors import mail
    try:
        return {"count": mail.unread_count()}
    except Exception:  # noqa: BLE001
        return {"count": None}


@app.get("/api/system")
def api_system() -> dict:
    # CPU/RAM/GPU/Temperatur fuer die Desktop-Leiste (best effort, None wo keine Quelle da ist).
    from core.api import sysinfo
    try:
        return sysinfo.snapshot()
    except Exception:  # noqa: BLE001
        return {}


_WALL_FILE = ROOT / "data" / "wall_settings.json"
# labels/motion/color/pos/posy/size = Graph (posy = Hoehe oben/mitte/unten); stats = Liste
# sichtbarer Stat-Schluessel (Reihenfolge); colors = Modus-Akzente {chat,work,coding} (Hex);
# ticker = Live-Feed-Panel oben links. Alles ueber den Desktop-Editor (Kira->Wallpaper) setzbar.
_WALL_KEYS = ("labels", "motion", "color", "pos", "posy", "size", "stats", "colors", "ticker")


@app.get("/api/wall/settings")
def api_wall_settings() -> dict:
    # Desktop-Wallpaper-Einstellungen SERVERSEITIG -> jede /wall-Instanz (auch die Lively-WebView,
    # die keinen localStorage mit dem Browser teilt) zieht dieselben Werte.
    try:
        cur = json.loads(_WALL_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    # Migration Desktop-Layout (Juli 2026): Alt-Staende ohne 'posy' tragen noch das alte
    # Default pos="mitte" aus der Zeit VOR dem 3-Zonen-Layout (Feed links, Graph rechts
    # oben, Mitte frei). Nur dieses alte Default wird fallengelassen — eine bewusste
    # Wahl (links/rechts) bleibt unangetastet. Beim naechsten Speichern steht posy drin.
    if isinstance(cur, dict) and "posy" not in cur and cur.get("pos") == "mitte":
        cur.pop("pos")
    return cur


@app.post("/api/wall/settings")
async def api_wall_settings_set(body: dict) -> dict:
    cur: dict = {}
    try:
        cur = json.loads(_WALL_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cur = {}
    cur.update({k: body[k] for k in _WALL_KEYS if k in body})
    _WALL_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WALL_FILE.write_text(json.dumps(cur), encoding="utf-8")
    return {"ok": True, "settings": cur}


# ---- Fernzugriff (Punkt 4: Handy/PWA) -------------------------------------------------
def _is_local_request(request) -> bool:
    """Streng lokal: direkte Loopback-Verbindung OHNE Proxy-Header. Nur solche Anfragen
    duerfen den Fernzugriff verwalten oder das Token sehen."""
    from core.api import security

    host = request.client.host if request.client else None
    fwd = "x-forwarded-for" in request.headers or "x-forwarded-proto" in request.headers
    return security.is_local(host) and not fwd


@app.post("/api/login")
async def api_login(body: dict) -> Response:
    """Login von der 401-Seite: richtiges Token -> Cookie (180 Tage), sonst 401."""
    from core.api import security

    if not security.token_ok(str(body.get("token") or "")):
        return JSONResponse({"ok": False}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("kira_token", security.get_token() or "", max_age=180 * 86400,
                    httponly=True, samesite="lax")
    return resp


@app.get("/api/remote/status")
def api_remote_status(request: Request) -> dict:
    """Fernzugriff-Status; das Token selbst gibt es NUR fuer streng lokale Anfragen."""
    from core.api import security

    local = _is_local_request(request)
    return {"enabled": security.enabled(),
            "token": (security.get_token() if local else None),
            "local": local}


@app.post("/api/remote/enable")
def api_remote_enable(request: Request) -> JSONResponse:
    from core.api import security

    if not _is_local_request(request):
        return JSONResponse({"error": "nur lokal am PC schaltbar"}, status_code=403)
    return JSONResponse({"ok": True, "token": security.enable()})


@app.post("/api/remote/disable")
def api_remote_disable(request: Request) -> JSONResponse:
    from core.api import security

    if not _is_local_request(request):
        return JSONResponse({"error": "nur lokal am PC schaltbar"}, status_code=403)
    security.disable()
    return JSONResponse({"ok": True})


# ---- PWA (Cockpit als installierbare Handy-App) ---------------------------------------
@app.get("/manifest.webmanifest")
def pwa_manifest() -> JSONResponse:
    return JSONResponse({
        "name": "Kira Cockpit", "short_name": "Kira", "start_url": "/",
        "display": "standalone", "background_color": "#0a0a0d", "theme_color": "#0a0a0d",
        "icons": [{"src": "/api/icon", "sizes": "any", "type": "image/png",
                   "purpose": "any"}],
    }, media_type="application/manifest+json")


@app.get("/sw.js")
def pwa_service_worker() -> Response:
    # Minimaler Service Worker: macht das Cockpit installierbar. Bewusst network-first
    # ohne Cache-Magie — ein Live-Cockpit mit veralteten Daten waere schlimmer als keins.
    js = ("self.addEventListener('install',()=>self.skipWaiting());"
          "self.addEventListener('activate',e=>e.waitUntil(clients.claim()));"
          "self.addEventListener('fetch',()=>{});")
    return Response(content=js, media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


# Das komplette Cockpit-Frontend lebt seit S5.3a in core/api/ui/ (css.py, views.py,
# script.py) — drei handliche Module statt einer 90-KB-Wand hier. Der Export bleibt
# identisch: DASHBOARD_HTML ist weiterhin ueber core.api.server importierbar.
from core.api.ui import DASHBOARD_HTML  # noqa: E402
from core.api.ui.wall import WALL_HTML  # noqa: E402
from core.kernel.fs import atomic_write
