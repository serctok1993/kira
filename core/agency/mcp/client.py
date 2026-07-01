"""Minimaler MCP-Client: Subprozess starten, Handshake, Tools listen & aufrufen.

Nutzt die offizielle ``mcp``-Bibliothek (v1.28.1) — robustes JSON-RPC+Streaming
via stdio, statt rohem Protokoll-Gefrickel.

Bietet zwei Interfaces:
- ``McpServer`` — asynchroner Kontextmanager für dauerhaften Betrieb
- ``quick_call()`` — One-Shot: Start → List → (optional) Call → Stop

Jede Netzwerk-/Prozess-Kommunikation ist mit einem konfigurierbaren Timeout
abgesichert (Default 15 s). Bei Überschreitung wird ``McpTimeoutError`` geworfen.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ---------------------------------------------------------------------------
# Custom Errors
# ---------------------------------------------------------------------------

class McpTimeoutError(asyncio.TimeoutError):
    """Wird geworfen, wenn eine MCP-Operation (z.B. Handshake, tools/list) das
    konfigurierte Zeitlimit überschreitet."""

    def __init__(self, operation: str, timeout: float) -> None:
        self.operation = operation
        self.timeout = timeout
        super().__init__(f"MCP-Timeout nach {timeout}s bei '{operation}'")


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

async def _with_timeout(coro: Any, operation: str, timeout: float) -> Any:
    """Wickle eine awaitable in ``asyncio.wait_for`` und wandle TimeoutError
    in ``McpTimeoutError`` um."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise McpTimeoutError(operation=operation, timeout=timeout) from None


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class McpServer:
    """Handle zu einem laufenden MCP-Server-Subprozess.

    Usage::

        async with McpServer(command="npx", args=["-y", "server-pkg"]) as srv:
            tools = await srv.list_tools()
            result = await srv.call_tool("some_tool", {"arg": "val"})
    """

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    timeout: float = 15.0       # Sekunden — gilt für initialize, list_tools, call_tool

    # interne Laufzeit-Felder (nicht im Konstruktor)
    _session: ClientSession | None = field(default=None, repr=False, init=False)
    _session_ctx: Any = field(default=None, repr=False, init=False)
    _stdio_ctx: Any = field(default=None, repr=False, init=False)
    _read: Any = field(default=None, repr=False, init=False)
    _write: Any = field(default=None, repr=False, init=False)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Starte den Subprozess, verbinde und führe den MCP-Handshake aus."""
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
            cwd=self.cwd,
        )
        # stdio_client() → async context manager → (read_stream, write_stream)
        self._stdio_ctx = stdio_client(params)
        self._read, self._write = await self._stdio_ctx.__aenter__()

        # ClientSession darauf aufsetzen
        self._session_ctx = ClientSession(self._read, self._write)
        self._session = await self._session_ctx.__aenter__()

        # Handshake — mit Timeout
        await _with_timeout(
            self._session.initialize(),
            operation="initialize",
            timeout=self.timeout,
        )

    async def stop(self) -> None:
        """Fahre den Subprozess sauber herunter."""
        if self._session is not None:
            await self._session_ctx.__aexit__(None, None, None)
            self._session = None
            self._session_ctx = None

        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None
            self._read = None
            self._write = None

    async def __aenter__(self) -> McpServer:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # MCP-Operationen (alle mit Timeout)
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        """Liefere alle verfügbaren Tools als Dict-Liste.

        Jedes Dict enthält ``name``, ``description`` und ``inputSchema``.
        """
        if self._session is None:
            raise RuntimeError("Server nicht gestartet — ruf start() oder das async-with auf.")
        result = await _with_timeout(
            self._session.list_tools(),
            operation="list_tools",
            timeout=self.timeout,
        )
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema,
            }
            for t in result.tools
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Rufe ein Tool auf und gib das Ergebnis zurück.

        Returns:
            Dict mit ``isError`` (bool) und ``content`` — eine Liste von
            ``{"type": ..., "text"/"data": ...}``-Blöcken.
        """
        if self._session is None:
            raise RuntimeError("Server nicht gestartet — ruf start() oder das async-with auf.")
        result = await _with_timeout(
            self._session.call_tool(name, arguments),
            operation=f"call_tool({name})",
            timeout=self.timeout,
        )

        # Content-Blöcke in einfache Dicts umwandeln
        contents: list[dict[str, Any]] = []
        for c in result.content:
            if hasattr(c, "text"):
                contents.append({"type": "text", "text": c.text})
            elif hasattr(c, "data"):
                contents.append({"type": c.type if hasattr(c, "type") else "resource", "data": str(c.data)})
            else:
                contents.append({"type": "unknown", "data": str(c)})

        return {"isError": result.isError, "content": contents}


# ---------------------------------------------------------------------------
# One-Shot
# ---------------------------------------------------------------------------

async def quick_call(
    command: str,
    args: list[str] | None = None,
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """One-Shot: Server starten, Tools listen, optional ein Tool aufrufen, stoppen.

    Returns:
        ``{"tools": [...], "call": {...} | None}``
    """
    async with McpServer(
        command=command,
        args=args or [],
        env=env,
        cwd=cwd,
        timeout=timeout,
    ) as server:
        tools = await server.list_tools()
        result: dict[str, Any] = {"tools": tools, "call": None}
        if tool_name:
            result["call"] = await server.call_tool(tool_name, tool_args or {})
        return result