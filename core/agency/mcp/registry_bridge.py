"""MCP-Registry-Bruecke: Externe MCP-Server-Tools automatisch als
Kira-Werkzeuge registrieren.

Jedes MCP-Tool wird mit dem Namenspraefix ``mcp_<server>_<tool>`` registriert.
Lesende Tools werden DIREKT ausgefuehrt. Schreibende Tools laufen durch das
Autonomie-Gate (core/governance/gate.py): bei 'Ketten ab' werden sie ausgefuehrt
und lueckenlos auditiert — NUR geld-bewegende und fremd-mailende Werkzeuge
(hard_gate) halten an und landen in der Freigabe-Inbox. Die Aktions-Art kommt
aus einer Namens-Heuristik, pro Server ueberschreibbar via "kinds" in
data/mcp_servers.json (z.B. {"create_payment_link": "external"}).

Verwendung beim Startup::

    from core.agency.mcp.registry_bridge import load_and_bridge
    load_and_bridge()  # liest data/mcp_servers.json, startet Server, registriert Tools
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from core.agency.mcp.client import McpServer
from core.agency.tools import registry
from core.agency.tools.registry import register

# ---------------------------------------------------------------------------
# Modul-Zustand
# ---------------------------------------------------------------------------

_servers: dict[str, "_ServerHandle"] = {}     # server_name → dauerhaftes Server-Handle
_tool_registry: dict[str, str] = {}           # tool_name → server_name (für spätere Referenz)


def _emit(etype: str, payload: dict) -> None:
    """Event-Emission, die nie den Bridge-Betrieb bricht (z.B. DB noch nicht initialisiert)."""
    try:
        from core.kernel import events

        events.emit(etype, payload)
    except Exception:  # noqa: BLE001
        pass

# ---------------------------------------------------------------------------
# Schreib-/Lese-Heuristik
# ---------------------------------------------------------------------------

def _resolve_token(v: Any) -> Any:
    """$VAR aus der Umgebung (inkl. Tresor-Zugaenge) aufloesen — sonst unveraendert.
    Damit sind Zugaenge/Pfade sowohl in env als auch in args steckbar
    (z.B. WhatsApp-Repo-Pfad $WHATSAPP_MCP_MAIN)."""
    return os.getenv(v[1:], "") if isinstance(v, str) and v.startswith("$") else v


def _resolve_args(args: list) -> list:
    return [_resolve_token(a) for a in (args or [])]


_WRITE_VERBS = [
    "create", "update", "delete", "remove", "write", "post", "send",
    "deploy", "publish", "push", "commit", "merge", "insert", "upsert",
    "put", "patch", "set", "add", "upload", "execute", "run", "apply",
    "migrate", "sync", "trigger", "invoke",
    "fork", "star", "dispatch", "enable", "disable", "pause", "restore",
]

# Aktions-Art fuers Autonomie-Gate: Namens-Hints. Fehlklassifikation blockt in die
# SICHERE Richtung (Inbox statt Ausfuehrung); Korrektur-Hebel ist das per-Server
# "kinds"-Override in mcp_servers.json.
_MONEY_HINTS = ("payment", "charge", "refund", "payout", "transfer", "invoice",
                "subscription", "billing", "checkout")
_EMAIL_HINTS = ("send_email", "send_mail", "send_message", "sendmessage")


def _classify_kind(tool_name: str) -> str:
    """'money' | 'email_stranger' | 'external' — die Gate-Art eines Schreib-Tools."""
    n = tool_name.lower()
    if any(h in n for h in _MONEY_HINTS):
        return "money"
    if any(h in n for h in _EMAIL_HINTS):
        return "email_stranger"
    return "external"


def _is_write_tool(name: str) -> bool:
    """Heuristik: Enthaelt der Tool-Name ein Schreib-Verb?"""
    name_lower = name.lower()
    for verb in _WRITE_VERBS:
        # Ganze-Wort-Match oder Bindestrich/Underscore-getrennt
        if f"_{verb}" in name_lower or f"-{verb}" in name_lower:
            return True
        if name_lower.startswith(verb) or name_lower.endswith(verb):
            return True
        if verb in name_lower.split("_") or verb in name_lower.split("-"):
            return True
    return False


def _build_tool_name(server_name: str, tool_name: str) -> str:
    """Baut den registrierten Kira-Tool-Namen: mcp_<server>_<tool>."""
    return f"mcp_{server_name}_{tool_name}"


# ---------------------------------------------------------------------------
# Server-Lifecycle: EIN dediziertes MCP-Event-Loop (Daemon-Thread) + EIN
# Owner-Task pro Server.
#
# Warum: Das fruehere asyncio.run()-pro-Aufruf oeffnete und schloss je eine
# eigene Event-Schleife — die stdio-Streams der Server hingen aber an der
# (laengst geschlossenen) Start-Schleife -> jeder spaetere Aufruf lief bis zum
# Timeout ins Leere. Zusaetzlich verlangt anyio, dass stdio_client/ClientSession
# im SELBEN Task betreten und verlassen werden. Deshalb haelt EIN Owner-Task
# das async-with ueber die gesamte Lebensdauer und bedient eine Queue; sync-
# Aufrufer reichen (Future, Tool, Args) thread-sicher hinein.
# ---------------------------------------------------------------------------

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Das dedizierte MCP-Loop (lazy, ein Daemon-Thread fuer alle Server)."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run, name="mcp-loop", daemon=True)
        t.start()
        _loop, _loop_thread = loop, t
        return loop


class _ServerHandle:
    """Ein dauerhaft laufender MCP-Server hinter einer sync-Fassade."""

    RESPAWN_COOLDOWN = 60.0  # Sekunden zwischen Wiederbelebungs-Versuchen

    def __init__(self, name: str, config: dict) -> None:
        self.name = name
        self.config = config
        self.state = "starting"          # starting | ready | dead
        self.tools: list[dict] = []
        self.last_error = ""
        self._died_at = 0.0
        self._queue: asyncio.Queue | None = None

    # ---- laeuft komplett im MCP-Loop (EIN Task = ganze Server-Lebensdauer) ----
    async def _owner(self, ready: concurrent.futures.Future) -> None:
        cfg = self.config
        resolved_env = {**os.environ}
        for k, v in (cfg.get("env") or {}).items():
            resolved_env[k] = _resolve_token(v) if isinstance(v, str) and v.startswith("$") else str(v)
        args = _resolve_args(cfg.get("args", []))
        try:
            async with McpServer(command=cfg["command"], args=args,
                                 env=resolved_env,
                                 timeout=float(cfg.get("timeout", 15.0))) as srv:
                self.tools = await srv.list_tools()
                self._queue = asyncio.Queue()
                self.state = "ready"
                if not ready.done():
                    ready.set_result(self.tools)
                while True:
                    item = await self._queue.get()
                    if item is None:  # Shutdown-Sentinel
                        break
                    fut, tool_name, args = item
                    try:
                        res = await srv.call_tool(tool_name, args)
                        if not fut.done():
                            fut.set_result(res)
                    except Exception as e:  # noqa: BLE001 — Fehler zum Aufrufer, Server lebt weiter
                        if not fut.done():
                            fut.set_exception(e)
        except Exception as e:  # noqa: BLE001 — Start/Transport kaputt
            self.last_error = str(e)[:300]
            if not ready.done():
                ready.set_exception(e)
        finally:
            was_ready = self.state == "ready"
            self.state = "dead"
            self._died_at = time.time()
            q, self._queue = self._queue, None
            while q is not None and not q.empty():  # Wartende nicht haengen lassen
                try:
                    item = q.get_nowait()
                except Exception:  # noqa: BLE001
                    break
                if item is not None and not item[0].done():
                    item[0].set_exception(RuntimeError(f"MCP-Server '{self.name}' wurde beendet"))
            if was_ready:
                _emit("mcp_server_died", {"server": self.name, "error": self.last_error})

    # ---- sync-Fassade (von Werkzeug-Wrappern aus beliebigen Threads) ----
    def start(self, wait_s: float | None = None) -> list[dict]:
        """Owner-Task starten; blockiert bis Handshake+list_tools fertig sind."""
        loop = _ensure_loop()
        ready: concurrent.futures.Future = concurrent.futures.Future()
        self.state = "starting"
        self.last_error = ""
        asyncio.run_coroutine_threadsafe(self._owner(ready), loop)
        # npx laedt beim Kaltstart ggf. erst Pakete -> grosszuegig warten
        return ready.result(timeout=wait_s or float(self.config.get("timeout", 15.0)) + 45)

    def call(self, tool_name: str, args: dict, timeout: float | None = None) -> dict:
        if threading.current_thread() is _loop_thread:
            raise RuntimeError("MCP-Aufruf vom MCP-Loop-Thread selbst — Deadlock-Gefahr, abgebrochen.")
        if self.state != "ready" or self._queue is None:
            self._maybe_respawn()
        q = self._queue
        if self.state != "ready" or q is None:
            wait = max(0, int(self.RESPAWN_COOLDOWN - (time.time() - self._died_at)))
            raise RuntimeError(
                f"MCP-Server '{self.name}' ist tot ({self.last_error or 'unbekannt'}) — "
                f"naechster Neustart-Versuch in ~{wait}s")
        fut: concurrent.futures.Future = concurrent.futures.Future()
        _ensure_loop().call_soon_threadsafe(q.put_nowait, (fut, tool_name, args))
        t = timeout or float(self.config.get("timeout", 15.0))
        return fut.result(timeout=t + 10)

    def _maybe_respawn(self) -> None:
        """Genau EIN Wiederbelebungs-Versuch pro Cooldown-Fenster."""
        if self.state != "dead" or time.time() - self._died_at < self.RESPAWN_COOLDOWN:
            return
        try:
            self.start()
            _emit("mcp_server_restarted", {"server": self.name})
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)[:300]
            self._died_at = time.time()

    def stop(self) -> None:
        q = self._queue
        if q is not None and _loop is not None:
            _loop.call_soon_threadsafe(q.put_nowait, None)


def _coerce_args(kwargs: dict, input_schema: dict) -> dict:
    """Argumente nach dem echten inputSchema typisieren (fail-soft).

    Kiras tool_schemas() deklariert alle Parameter als String — MCP-Server
    validieren aber gegen ihr Schema, daher hier die Rueck-Uebersetzung."""
    props = (input_schema or {}).get("properties", {})
    out: dict = {}
    for k, v in kwargs.items():
        typ = (props.get(k) or {}).get("type")
        try:
            if isinstance(v, str):
                if typ == "integer":
                    v = int(v)
                elif typ == "number":
                    v = float(v)
                elif typ == "boolean":
                    v = v.strip().lower() in ("true", "1", "ja", "yes")
                elif typ in ("object", "array"):
                    v = json.loads(v)
        except Exception:  # noqa: BLE001 — im Zweifel Original lassen, Server meldet sauber
            pass
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Tool-Wrapper
# ---------------------------------------------------------------------------

def _call_server_text(server_name: str, tool_name: str, kwargs: dict) -> str:
    """Fuehrt ein MCP-Tool aus und baut die Content-Bloecke zu lesbarem Text zusammen.

    Gemeinsamer Pfad fuer Lese-Tools (direkt) und Schreib-Tools (via gate.guarded)."""
    handle = _servers.get(server_name)
    if handle is None:
        return (
            f"(MCP-Server '{server_name}' laeuft nicht. "
            f"Ist er in data/mcp_servers.json aktiviert?)"
        )

    try:
        result = handle.call(tool_name, kwargs)
    except Exception as e:
        return f"(MCP-Fehler bei {server_name}/{tool_name}: {e})"

    parts: list[str] = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            parts.append(block["text"])
        else:
            parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(parts) if parts else (
        "(leeres Ergebnis)" if not result.get("isError") else f"(Fehler: {result})"
    )


def _make_wrapper(
    server_name: str,
    tool_name: str,
    description: str,
    input_schema: dict,
    kind_overrides: dict[str, str] | None = None,
) -> tuple[Any, dict[str, str]]:
    """Baut eine synchrone Wrapper-Funktion fuer ein MCP-Tool.

    Returns:
        (func, params) — die Funktion und ihre Parameter-Beschreibungen.
    """

    read_only = not _is_write_tool(tool_name)

    def wrapper(**kwargs: Any) -> str:
        kwargs = _coerce_args(kwargs, input_schema)  # LLM liefert Strings, Server will Typen
        # --- Schreib-Tool: durchs Autonomie-Gate (Ketten ab: ausfuehren + Audit;
        #     nur hard_gate-Arten wie money/email_stranger halten an der Inbox) ---
        if not read_only:
            from core.governance import gate

            kind = (kind_overrides or {}).get(tool_name) or _classify_kind(tool_name)
            return gate.guarded(
                kind=kind,
                title=f"MCP: {server_name}/{tool_name}",
                detail=json.dumps(kwargs, indent=2, ensure_ascii=False),
                execute=lambda: _call_server_text(server_name, tool_name, kwargs),
                target=tool_name,
                action=_build_tool_name(server_name, tool_name),
            )

        # --- Lese-Tool: direkt ausführen ---
        return _call_server_text(server_name, tool_name, kwargs)

    # --- Parameter aus inputSchema ableiten ---
    params: dict[str, str] = {}
    props = input_schema.get("properties", {})
    required_list: list[str] = input_schema.get("required", [])
    for prop_name, prop_info in props.items():
        desc = prop_info.get("description", prop_info.get("title", ""))
        # Typ-Hinweis
        typ = prop_info.get("type", "string")
        if typ and typ != "string":
            desc = f"[{typ}] {desc}".strip()
        # Optional-Flag
        if prop_name not in required_list:
            desc += " (optional)"
        params[prop_name] = desc

    # Sicherstellen, dass **kwargs funktioniert — die Funktion nimmt
    # alle Parameter als Keyword-Argumente entgegen
    wrapper.__name__ = _build_tool_name(server_name, tool_name)
    wrapper.__doc__ = f"[MCP:{server_name}] {description}"

    return wrapper, params


# ---------------------------------------------------------------------------
# Bruecken-Aufbau
# ---------------------------------------------------------------------------

def bridge_server(server_name: str, config: dict) -> int:
    """Startet einen MCP-Server (dauerhaft) und registriert seine Tools.

    Flut-Kontrolle: optionale Allowlist config["tools"] / Denylist config["deny"] —
    das Manifest geht bei JEDEM LLM-Call mit, ungefilterte Server (GitHub: ~80
    Tools) wuerden jeden Prompt massiv verteuern.

    Returns:
        Anzahl erfolgreich registrierter Tools.
    """
    handle = _ServerHandle(server_name, config)
    tools = handle.start()
    _servers[server_name] = handle

    allow = set(config.get("tools") or [])
    deny = set(config.get("deny") or [])
    kind_overrides = config.get("kinds", {})

    count = 0
    skipped = 0
    for tool in tools:
        t_name = tool["name"]
        if (allow and t_name not in allow) or t_name in deny:
            skipped += 1
            continue
        kira_name = _build_tool_name(server_name, t_name)
        if registry.get(kira_name) is not None:
            # Nie blind ueberschreiben (Re-Bridge nach Respawn ODER Namens-Kollision).
            # Bestehende Wrapper zeigen per Namens-Lookup ohnehin aufs neue Handle.
            _tool_registry.setdefault(kira_name, server_name)
            continue

        t_desc = tool.get("description", "")
        wrapper, params = _make_wrapper(server_name, t_name, t_desc,
                                        tool.get("inputSchema", {}),
                                        kind_overrides=kind_overrides)
        register(name=kira_name, description=f"[MCP:{server_name}] {t_desc}",
                 func=wrapper, params=params)
        _tool_registry[kira_name] = server_name
        count += 1

    if skipped:
        _emit("mcp_tools_skipped", {"server": server_name, "skipped": skipped, "registered": count})
    if count > 20:
        _emit("mcp_manifest_warning", {"server": server_name, "count": count,
                                       "hint": "Allowlist in mcp_servers.json setzen — Manifest-Kosten pro Call"})
    return count


def shutdown_all() -> None:
    """Faehrt alle laufenden MCP-Server sauber herunter."""
    for name, handle in list(_servers.items()):
        try:
            handle.stop()
        except Exception:  # noqa: BLE001
            pass
        del _servers[name]
    _tool_registry.clear()


_EXAMPLE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "mcp_servers.example.json"


def load_and_bridge(config_path: str = "data/mcp_servers.json") -> dict[str, int]:
    """Laedt die Server-Konfiguration und brueckt alle aktivierten Server.

    Fehlt data/mcp_servers.json (data/ ist gitignored), wird sie aus der
    versionierten Vorlage config/mcp_servers.example.json geseedet.

    Returns:
        {server_name: anzahl_registrierter_tools}
    """
    path = Path(config_path)
    if not path.exists():
        try:
            from core.kernel.fs import atomic_write
            atomic_write(path, _EXAMPLE_CONFIG.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    try:
        configs = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _emit("mcp_bridge_error", {"error": f"Config unlesbar: {e}"})
        return {}
    if not isinstance(configs, dict):
        return {}

    results: dict[str, int] = {}
    for name, cfg in configs.items():
        if not isinstance(cfg, dict) or not cfg.get("enabled", True):
            continue
        try:
            results[name] = bridge_server(name, cfg)
        except Exception as e:  # noqa: BLE001 — ein kaputter Server bricht nie die anderen
            results[name] = 0
            _emit("mcp_bridge_error", {"server": name, "error": str(e)[:300]})
    return results


_init_started = False


def init_background() -> None:
    """Bridge-Aufbau im Hintergrund — MCP-Ausfall darf den Boot NIE bricken.

    Idempotent; in Cockpit, Runner und Bot beim Start aufgerufen. Tools tauchen
    in der Registry auf, sobald sie bereit sind (Manifest wird pro Call gelesen,
    spaete Registrierung ist unproblematisch)."""
    global _init_started
    from core import config as _cfg
    if _cfg.outbound_blocked():  # Firewall (Benchmark/Sandbox): keinen npx-MCP-Prozess spawnen
        return
    if _init_started:
        return
    _init_started = True

    def _boot() -> None:
        try:
            res = load_and_bridge()
            _emit("mcp_bridge_ready", {"servers": res})
        except Exception as e:  # noqa: BLE001
            _emit("mcp_bridge_error", {"error": str(e)[:300]})

    threading.Thread(target=_boot, name="mcp-bridge-init", daemon=True).start()


def server_status() -> dict[str, dict]:
    """Liefert Status aller konfigurierten Server (fürs Cockpit).

    S8.0: defensiv gegen korrupte Config — vorher warf ein halb geschriebenes
    JSON hier 'Expecting value: line 1 column 1' bis in die API hoch."""
    path = Path("data/mcp_servers.json")
    try:
        configs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError) as e:
        _emit("mcp_bridge_error", {"error": f"Config unlesbar (server_status): {e}"})
        return {}
    if not isinstance(configs, dict):
        return {}

    status = {}
    for name, cfg in configs.items():
        if not isinstance(cfg, dict):
            continue
        running = name in _servers
        tool_count = len([
            t for t, s in _tool_registry.items()
            if s == name
        ])
        handle = _servers.get(name)
        status[name] = {
            "enabled": cfg.get("enabled", True),
            "running": running,
            "tools": tool_count,
            "command": cfg.get("command", ""),
            "comment": cfg.get("comment", ""),
            "error": (handle.last_error if handle else "") or "",
        }
    return status


# ---------------------------------------------------------------------------
# Macht-Schritt 2: MCP-Universum — Server zur Laufzeit per Config einstoepseln.
# Damit kann Sergen (oder Kira) beliebige MCP-Server ohne Code-Aenderung hinzufuegen.
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path("data/mcp_servers.json")


def _read_config() -> dict:
    try:
        d = json.loads(_CONFIG_PATH.read_text(encoding="utf-8")) if _CONFIG_PATH.exists() else {}
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(configs: dict) -> None:
    from core.kernel.fs import atomic_write

    atomic_write(_CONFIG_PATH, json.dumps(configs, indent=2, ensure_ascii=False))


def _unbridge_server(name: str) -> None:
    """Server stoppen und ALLE seine Tools aus der Registry entfernen."""
    handle = _servers.pop(name, None)
    if handle is not None:
        try:
            handle.stop()
        except Exception:  # noqa: BLE001
            pass
    for kira_name in [t for t, s in _tool_registry.items() if s == name]:
        _tool_registry.pop(kira_name, None)
        try:
            registry.unregister(kira_name)
        except Exception:  # noqa: BLE001
            pass


def add_server(name: str, config: dict, *, start: bool = True) -> dict:
    """Fuegt einen MCP-Server hinzu (oder ersetzt ihn) und brueckt ihn sofort live.

    Returns {ok, tools, error}. Wirft nie — Fehler kommen im Feld 'error' zurueck,
    damit ein kaputter Server das Cockpit nicht bricht."""
    name = (name or "").strip()
    if not name or not isinstance(config, dict) or not config.get("command"):
        return {"ok": False, "error": "Name und command sind Pflicht."}
    configs = _read_config()
    _unbridge_server(name)                       # evtl. alte Version sauber weg
    config.setdefault("enabled", True)
    configs[name] = config
    _write_config(configs)
    _emit("mcp_server_added", {"server": name, "command": config.get("command", "")})
    if not (start and config.get("enabled", True)):
        return {"ok": True, "tools": 0, "error": ""}
    try:
        n = bridge_server(name, config)
        return {"ok": True, "tools": n, "error": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "tools": 0, "error": str(e)[:300]}


def remove_server(name: str) -> dict:
    """Entfernt einen MCP-Server ganz (stoppt ihn + loescht aus der Config)."""
    configs = _read_config()
    if name not in configs:
        return {"ok": False, "error": f"'{name}' ist nicht konfiguriert."}
    _unbridge_server(name)
    del configs[name]
    _write_config(configs)
    _emit("mcp_server_removed", {"server": name})
    return {"ok": True}


def toggle_server(name: str, enabled: bool) -> dict:
    """Schaltet einen Server an/aus (startet bzw. stoppt ihn live)."""
    configs = _read_config()
    cfg = configs.get(name)
    if not isinstance(cfg, dict):
        return {"ok": False, "error": f"'{name}' ist nicht konfiguriert."}
    cfg["enabled"] = bool(enabled)
    configs[name] = cfg
    _write_config(configs)
    _emit("mcp_server_toggled", {"server": name, "enabled": bool(enabled)})
    if enabled:
        try:
            n = bridge_server(name, cfg)
            return {"ok": True, "tools": n, "error": ""}
        except Exception as e:  # noqa: BLE001
            return {"ok": True, "tools": 0, "error": str(e)[:300]}
    _unbridge_server(name)
    return {"ok": True, "tools": 0}


# Kuratierter Katalog gaengiger MCP-Server (Ein-Klick-Anlegen im Cockpit). Jeder Eintrag
# ist eine fertige Config-Vorlage; 'secret' nennt den Tresor-Schluessel, den der Server braucht.
CATALOG: list[dict] = [
    {"id": "github", "label": "GitHub", "secret": "GITHUB_TOKEN",
     "info": "Repos, Issues, PRs, Code-Suche",
     "config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "$GITHUB_TOKEN"}, "timeout": 60,
                "tools": ["get_file_contents", "search_repositories", "create_issue",
                          "list_issues", "create_pull_request", "list_commits"]}},
    {"id": "supabase", "label": "Supabase", "secret": "SUPABASE_ACCESS_TOKEN",
     "info": "Datenbank, Tabellen, SQL, Logs",
     "config": {"command": "npx", "args": ["-y", "@supabase/mcp-server-supabase@latest"],
                "env": {"SUPABASE_ACCESS_TOKEN": "$SUPABASE_ACCESS_TOKEN"}, "timeout": 60,
                "tools": ["list_projects", "list_tables", "execute_sql", "get_logs"]}},
    {"id": "filesystem", "label": "Dateisystem", "secret": "",
     "info": "Ordner lesen/schreiben (MCP-Referenz)",
     "config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem",
                                            "$HOME"], "timeout": 30}},
    # Der meistempfohlene Server 2026: aktuelle, versionsgenaue Bibliotheks-Doku live in den
    # Prompt -> Kira halluziniert beim Coden keine veralteten APIs mehr. Laeuft keyless.
    {"id": "context7", "label": "Context7 (Doku)", "secret": "",
     "info": "Aktuelle Bibliotheks-Doku live — killt erfundene APIs beim Coden",
     "config": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"], "timeout": 60}},
    # Exa: fuer Agenten gebaute semantische Web-Suche + Crawling (2026 die meistgenutzte).
    {"id": "exa", "label": "Exa (Web-Suche)", "secret": "EXA_API_KEY",
     "info": "Semantische Web-Suche & Crawling — schaerfer als DuckDuckGo/Brave",
     "config": {"command": "npx", "args": ["-y", "exa-mcp-server"],
                "env": {"EXA_API_KEY": "$EXA_API_KEY"}, "timeout": 60}},
    {"id": "brave", "label": "Brave Search", "secret": "BRAVE_API_KEY",
     "info": "Web-Suche als MCP",
     "config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {"BRAVE_API_KEY": "$BRAVE_API_KEY"}, "timeout": 30}},
    {"id": "notion", "label": "Notion", "secret": "NOTION_TOKEN",
     "info": "Seiten, Datenbanken, Notizen",
     "config": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"],
                "env": {"NOTION_TOKEN": "$NOTION_TOKEN"}, "timeout": 60}},
    {"id": "slack", "label": "Slack", "secret": "SLACK_BOT_TOKEN",
     "info": "Kanaele lesen, Nachrichten posten",
     "config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-slack"],
                "env": {"SLACK_BOT_TOKEN": "$SLACK_BOT_TOKEN"}, "timeout": 60,
                "kinds": {"post_message": "external"}}},
    # Macht-Schritt 3 (als MCP): WhatsApp KOSTENLOS ueber deine (Zweit-)Nummer (Baileys/QR,
    # wie OpenWA — inoffiziell). Einmal klonen, Pfad zu src/main.ts als Zugang WHATSAPP_MCP_MAIN.
    # send_message = 'external' -> laeuft durchs Freigabe-Gate (Ban-Schutz + Aussenwirkung).
    {"id": "whatsapp", "label": "WhatsApp", "secret": "WHATSAPP_MCP_MAIN",
     "info": "Senden/Empfangen ueber deine Nummer — gratis (Baileys)",
     "setup": "Einmalig: git clone https://github.com/jlucaso1/whatsapp-mcp-ts && cd whatsapp-mcp-ts "
              "&& bun install (oder npm i). Dann den absoluten Pfad zu src/main.ts als Zugang "
              "WHATSAPP_MCP_MAIN eintragen. Erststart zeigt einen QR — mit der Zweitnummer scannen "
              "(WhatsApp > Verknuepfte Geraete). ACHTUNG: inoffiziell — bei Massen-/Kaltnachrichten "
              "Sperr-Risiko. Nummer warmlaufen lassen, langsam dosieren, nur relevante Nachrichten.",
     "config": {"command": "node", "args": ["$WHATSAPP_MCP_MAIN"], "timeout": 60,
                "kinds": {"send_message": "external"}}},
    # Macht-Schritt 3 (als MCP): Google Kalender — Termine lesen/anlegen/verschieben.
    {"id": "gcal", "label": "Google Kalender", "secret": "GOOGLE_OAUTH_CREDENTIALS",
     "info": "Termine lesen, anlegen, verschieben",
     "setup": "OAuth-Client-JSON in der Google Cloud Console anlegen (Calendar-API aktivieren), "
              "herunterladen und den absoluten Pfad als Zugang GOOGLE_OAUTH_CREDENTIALS eintragen. "
              "Beim ersten Aufruf einmal im Browser autorisieren.",
     "config": {"command": "npx", "args": ["-y", "@cocal/google-calendar-mcp"],
                "env": {"GOOGLE_OAUTH_CREDENTIALS": "$GOOGLE_OAUTH_CREDENTIALS"}, "timeout": 60,
                "kinds": {"create-event": "external", "update-event": "external",
                          "delete-event": "external"}}},
]
