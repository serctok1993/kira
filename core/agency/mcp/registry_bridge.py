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
from pathlib import Path
from typing import Any

from core.agency.mcp.client import McpServer
from core.agency.tools.registry import register

# ---------------------------------------------------------------------------
# Modul-Zustand
# ---------------------------------------------------------------------------

_servers: dict[str, McpServer] = {}          # server_name → laufende McpServer-Instanz
_tool_registry: dict[str, str] = {}           # tool_name → server_name (für spätere Referenz)

# ---------------------------------------------------------------------------
# Schreib-/Lese-Heuristik
# ---------------------------------------------------------------------------

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
# Async-Helfer: sync → async (thread-safe)
# ---------------------------------------------------------------------------

def _run_async(coro: Any) -> Any:
    """Fuehre eine Coroutine aus – funktioniert auch, wenn bereits ein
    Event-Loop laeuft (z.B. im Bot-Chat-Thread)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Kein laufender Loop → einfach asyncio.run()
        return asyncio.run(coro)
    else:
        # Loop laeuft schon → Coroutine in separatem Thread ausfuehren
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()


# ---------------------------------------------------------------------------
# Tool-Wrapper
# ---------------------------------------------------------------------------

def _call_server_text(server_name: str, tool_name: str, kwargs: dict) -> str:
    """Fuehrt ein MCP-Tool aus und baut die Content-Bloecke zu lesbarem Text zusammen.

    Gemeinsamer Pfad fuer Lese-Tools (direkt) und Schreib-Tools (via gate.guarded)."""
    server = _servers.get(server_name)
    if server is None:
        return (
            f"(MCP-Server '{server_name}' laeuft nicht. "
            f"Ist er in data/mcp_servers.json aktiviert?)"
        )

    try:
        result = _run_async(server.call_tool(tool_name, kwargs))
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
# Server-Lifecycle
# ---------------------------------------------------------------------------

async def bridge_server(server_name: str, config: dict) -> int:
    """Startet einen MCP-Server und registriert alle seine Tools.

    Args:
        server_name: Name des Servers (Schluessel in mcp_servers.json)
        config: Dict mit command, args, env, timeout, enabled

    Returns:
        Anzahl erfolgreich registrierter Tools.
    """
    command = config["command"]
    args = config.get("args", [])
    timeout = float(config.get("timeout", 15.0))
    raw_env = config.get("env", {})

    # Env-Variablen aufloesen: direkte Werte oder $-Referenzen auf os.environ
    resolved_env = {**os.environ}
    for k, v in raw_env.items():
        if isinstance(v, str) and v.startswith("$"):
            resolved_env[k] = os.getenv(v[1:], "")
        else:
            resolved_env[k] = str(v)

    server = McpServer(
        command=command,
        args=args,
        env=resolved_env,
        timeout=timeout,
    )

    await server.start()
    _servers[server_name] = server

    tools = await server.list_tools()

    kind_overrides = config.get("kinds", {})

    count = 0
    for tool in tools:
        t_name = tool["name"]
        t_desc = tool.get("description", "")
        t_schema = tool.get("inputSchema", {})

        wrapper, params = _make_wrapper(server_name, t_name, t_desc, t_schema,
                                        kind_overrides=kind_overrides)

        kira_name = _build_tool_name(server_name, t_name)
        register(
            name=kira_name,
            description=f"[MCP:{server_name}] {t_desc}",
            func=wrapper,
            params=params,
        )
        _tool_registry[kira_name] = server_name
        count += 1

    return count


async def shutdown_all() -> None:
    """Faehrt alle laufenden MCP-Server sauber herunter."""
    for name, server in list(_servers.items()):
        try:
            await server.stop()
        except Exception:
            pass
        del _servers[name]
    _tool_registry.clear()


def load_and_bridge(config_path: str = "data/mcp_servers.json") -> dict[str, int]:
    """Laedt die Server-Konfiguration und brueckt alle aktivierten Server.

    Wird beim Bot-Start aufgerufen — bringt alle MCP-Tools in die Registry.

    Returns:
        {server_name: anzahl_registrierter_tools}
    """
    path = Path(config_path)
    if not path.exists():
        return {}

    try:
        configs = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"[mcp-bridge] Fehler beim Lesen von {config_path}: {e}")
        return {}

    results: dict[str, int] = {}

    async def _bridge_all() -> None:
        for name, cfg in configs.items():
            if not cfg.get("enabled", True):
                continue
            try:
                count = await bridge_server(name, cfg)
                results[name] = count
                print(f"[mcp-bridge] '{name}': {count} Tools registriert")
            except Exception as e:
                results[name] = 0
                print(f"[mcp-bridge] Fehler bei '{name}': {e}")

    _run_async(_bridge_all())
    return results


def server_status() -> dict[str, dict]:
    """Liefert Status aller konfigurierten Server (fürs Cockpit)."""
    path = Path("data/mcp_servers.json")
    configs = json.loads(path.read_text()) if path.exists() else {}

    status = {}
    for name, cfg in configs.items():
        running = name in _servers
        tool_count = len([
            t for t, s in _tool_registry.items()
            if s == name
        ])
        status[name] = {
            "enabled": cfg.get("enabled", True),
            "running": running,
            "tools": tool_count,
            "command": cfg.get("command", ""),
        }
    return status
