"""Unit-Test für den MCP-Client (core/agency/mcp/client.py).

Testet Handshake, tools/list und tools/call GEGEN FAKE-STREAMS —
KEIN externer Prozess, kein node/npx. Die Selbst-Test-Suite bleibt offline.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake-MCP-Streams (simulieren stdio_client + ClientSession)
# ---------------------------------------------------------------------------

@dataclass
class FakeTool:
    name: str
    description: str = ""
    inputSchema: dict[str, Any] | None = None

class FakeToolContent:
    def __init__(self, text: str = "", data: str = "", content_type: str = "text"):
        self.text = text
        self.data = data
        self.type = content_type

class FakeCallToolResult:
    def __init__(self, is_error: bool = False, content: list[FakeToolContent] | None = None):
        self.isError = is_error
        self.content = content or []

class FakeListToolsResult:
    def __init__(self, tools: list[FakeTool] | None = None):
        self.tools = tools or []

class FakeInitializeResult:
    def __init__(self):
        self.protocolVersion = "2024-11-05"
        self.capabilities = MagicMock()

# ---------------------------------------------------------------------------
# Hängende Session für Timeout-Tests
# ---------------------------------------------------------------------------

async def _never_completes() -> None:
    """Blockierende Coroutine, die niemals zurückkehrt."""
    await asyncio.Event().wait()


class FakeClientSession:
    """Simuliert eine mcp.ClientSession mit vorbereiteten Antworten."""

    def __init__(self, tools: list[FakeTool] | None = None, call_results: dict[str, FakeCallToolResult] | None = None):
        self._tools = tools or []
        self._call_results = call_results or {}
        self.initialize = AsyncMock(return_value=FakeInitializeResult())

    async def list_tools(self, cursor=None, *, params=None):
        return FakeListToolsResult(self._tools)

    async def call_tool(self, name: str, arguments=None, **kwargs):
        if name in self._call_results:
            return self._call_results[name]
        return FakeCallToolResult(is_error=False, content=[FakeToolContent(text=f"ok: {name}")])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class HangingClientSession:
    """Simuliert einen MCP-Server, der bei einem bestimmten Vorgang hängt.

    Ermöglicht gezielte Timeout-Tests für initialize / list_tools / call_tool.
    """

    def __init__(self, hang_on: str = "initialize"):
        self._hang_on = hang_on

        if hang_on == "initialize":
            self.initialize = _never_completes
        else:
            self.initialize = AsyncMock(return_value=FakeInitializeResult())

    async def list_tools(self, cursor=None, *, params=None):
        if self._hang_on == "list_tools":
            await _never_completes()
        return FakeListToolsResult([])

    async def call_tool(self, name: str, arguments=None, **kwargs):
        if self._hang_on == "call_tool":
            await _never_completes()
        return FakeCallToolResult(is_error=False, content=[FakeToolContent(text="never")])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Hilfsfunktion: McpServer starten mit gemockten Streams
# ---------------------------------------------------------------------------

def _make_server_with_session(
    session: Any,
    command: str = "dummy",
    args: list[str] | None = None,
    timeout: float = 15.0,
) -> Any:
    """Erzeuge einen McpServer, dessen stdio_client + ClientSession gemockt sind."""
    from core.agency.mcp.client import McpServer

    srv = McpServer(command=command, args=args or [], timeout=timeout)

    mock_streams = (AsyncMock(), AsyncMock())

    patcher_stdio = patch("core.agency.mcp.client.stdio_client")
    patcher_session = patch("core.agency.mcp.client.ClientSession", return_value=session)

    mock_stdio = patcher_stdio.start()
    mock_stdio.return_value.__aenter__ = AsyncMock(return_value=mock_streams)
    mock_stdio.return_value.__aexit__ = AsyncMock(return_value=None)

    patcher_session.start()

    def cleanup():
        patcher_stdio.stop()
        patcher_session.stop()

    return srv, cleanup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMcpServerUnit:
    """Testet McpServer-Logik OHNE echten Subprozess."""

    @pytest.fixture
    def fake_session(self):
        return FakeClientSession(
            tools=[
                FakeTool("read", "Liest eine Datei", {"type": "object"}),
                FakeTool("write", "Schreibt eine Datei", {"type": "object"}),
            ],
            call_results={
                "read": FakeCallToolResult(
                    is_error=False,
                    content=[FakeToolContent(text="inhalt der datei")],
                ),
                "fail_tool": FakeCallToolResult(
                    is_error=True,
                    content=[FakeToolContent(text="etwas ging schief")],
                ),
            },
        )

    @pytest.fixture
    def mock_streams(self):
        """Mock für stdio_client → (read_stream, write_stream)."""
        read_stream = AsyncMock()
        write_stream = AsyncMock()
        return read_stream, write_stream

    def test_params_passed_to_stdio_server_parameters(self):
        """Stellt sicher, dass McpServer-Parameter korrekt an StdioServerParameters gehen."""
        from core.agency.mcp.client import McpServer

        srv = McpServer(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            env={"NODE_ENV": "test"},
            cwd="/home",
        )
        assert srv.command == "npx"
        assert srv.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        assert srv.env == {"NODE_ENV": "test"}
        assert srv.cwd == "/home"

    def test_call_before_start_raises(self):
        """Ohne start() / async-with muss list_tools/call_tool RuntimeError werfen."""
        from core.agency.mcp.client import McpServer

        srv = McpServer(command="echo", args=["hi"])

        with pytest.raises(RuntimeError, match="nicht gestartet"):
            asyncio.run(srv.list_tools())

        with pytest.raises(RuntimeError, match="nicht gestartet"):
            asyncio.run(srv.call_tool("x"))

    def test_list_tools_transforms_correctly(self, fake_session, mock_streams):
        """list_tools() soll eine Liste von Dicts mit name/description/inputSchema liefern."""
        from core.agency.mcp.client import McpServer

        srv = McpServer(command="dummy", args=[])
        srv._session = fake_session

        tools = asyncio.run(srv.list_tools())
        assert len(tools) == 2
        assert tools[0] == {
            "name": "read",
            "description": "Liest eine Datei",
            "inputSchema": {"type": "object"},
        }
        assert tools[1]["name"] == "write"

    def test_call_tool_success(self, fake_session):
        """Erfolgreicher Tool-Aufruf: isError=False, content als Dict-Liste."""
        from core.agency.mcp.client import McpServer

        srv = McpServer(command="dummy", args=[])
        srv._session = fake_session

        result = asyncio.run(srv.call_tool("read", {"path": "/tmp/test.txt"}))
        assert result["isError"] is False
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "inhalt der datei"

    def test_call_tool_error(self, fake_session):
        """Fehlerhafter Tool-Aufruf: isError=True."""
        from core.agency.mcp.client import McpServer

        srv = McpServer(command="dummy", args=[])
        srv._session = fake_session

        result = asyncio.run(srv.call_tool("fail_tool"))
        assert result["isError"] is True
        assert result["content"][0]["text"] == "etwas ging schief"

    def test_async_context_manager_lifecycle(self, fake_session, mock_streams):
        """async-with soll start() und stop() korrekt aufrufen."""
        from core.agency.mcp.client import McpServer

        srv = McpServer(command="dummy", args=[])

        # Wir patchen stdio_client + ClientSession, damit kein echter Prozess startet
        with patch("core.agency.mcp.client.stdio_client") as mock_stdio, \
             patch("core.agency.mcp.client.ClientSession") as mock_session_cls:

            mock_stdio.return_value.__aenter__ = AsyncMock(return_value=mock_streams)
            mock_stdio.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            async def run():
                async with srv as server:
                    tools = await server.list_tools()
                    assert len(tools) == 2
                    return tools

            tools = asyncio.run(run())
            assert tools[0]["name"] == "read"

            # Verify cleanup was called
            mock_stdio.return_value.__aexit__.assert_called()
            mock_session_cls.return_value.__aexit__.assert_called()

    # ------------------------------------------------------------------
    # Timeout-Tests
    # ------------------------------------------------------------------

    def test_initialize_timeout_raises_mcp_timeout_error(self):
        """Wenn initialize nicht antwortet, muss McpTimeoutError fliegen."""
        from core.agency.mcp.client import McpTimeoutError

        hanging = HangingClientSession(hang_on="initialize")
        srv, cleanup = _make_server_with_session(hanging, timeout=0.1)

        try:
            with pytest.raises(McpTimeoutError) as exc_info:
                asyncio.run(srv.start())
            assert "initialize" in str(exc_info.value)
        finally:
            cleanup()

    def test_list_tools_timeout_raises_mcp_timeout_error(self, fake_session):
        """Wenn list_tools nicht antwortet, muss McpTimeoutError fliegen."""
        from core.agency.mcp.client import McpTimeoutError, McpServer

        hanging = HangingClientSession(hang_on="list_tools")
        srv = McpServer(command="dummy", args=[], timeout=0.1)
        srv._session = hanging
        srv._session_ctx = MagicMock()
        srv._session_ctx.__aexit__ = AsyncMock()

        with pytest.raises(McpTimeoutError) as exc_info:
            asyncio.run(srv.list_tools())
        assert "list_tools" in str(exc_info.value)

    def test_call_tool_timeout_raises_mcp_timeout_error(self, fake_session):
        """Wenn call_tool nicht antwortet, muss McpTimeoutError fliegen."""
        from core.agency.mcp.client import McpTimeoutError, McpServer

        hanging = HangingClientSession(hang_on="call_tool")
        srv = McpServer(command="dummy", args=[], timeout=0.1)
        srv._session = hanging
        srv._session_ctx = MagicMock()
        srv._session_ctx.__aexit__ = AsyncMock()

        with pytest.raises(McpTimeoutError) as exc_info:
            asyncio.run(srv.call_tool("some_tool"))
        assert "call_tool" in str(exc_info.value)


class TestQuickCall:
    """Testet die quick_call()-One-Shot-Funktion."""

    def test_quick_call_list_only(self):
        """quick_call ohne tool_name listet nur Tools."""
        from core.agency.mcp.client import quick_call

        with patch("core.agency.mcp.client.McpServer") as MockServer:
            mock_srv = MagicMock()
            mock_srv.list_tools = AsyncMock(return_value=[
                {"name": "t1", "description": "d1", "inputSchema": {}},
            ])
            mock_srv.call_tool = AsyncMock()
            mock_srv.__aenter__ = AsyncMock(return_value=mock_srv)
            mock_srv.__aexit__ = AsyncMock(return_value=None)
            MockServer.return_value = mock_srv

            result = asyncio.run(quick_call(command="npx", args=["-y", "pkg"]))
            assert len(result["tools"]) == 1
            assert result["call"] is None
            mock_srv.call_tool.assert_not_called()

    def test_quick_call_with_tool(self):
        """quick_call mit tool_name ruft das Tool auf."""
        from core.agency.mcp.client import quick_call

        with patch("core.agency.mcp.client.McpServer") as MockServer:
            mock_srv = MagicMock()
            mock_srv.list_tools = AsyncMock(return_value=[])
            mock_srv.call_tool = AsyncMock(return_value={
                "isError": False,
                "content": [{"type": "text", "text": "hello"}],
            })
            mock_srv.__aenter__ = AsyncMock(return_value=mock_srv)
            mock_srv.__aexit__ = AsyncMock(return_value=None)
            MockServer.return_value = mock_srv

            result = asyncio.run(quick_call(
                command="npx", args=["-y", "pkg"],
                tool_name="greet", tool_args={"name": "Kira"},
            ))
            assert result["call"]["isError"] is False
            assert result["call"]["content"][0]["text"] == "hello"
            mock_srv.call_tool.assert_called_once_with("greet", {"name": "Kira"})