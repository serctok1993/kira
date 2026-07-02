"""S3.3: MCP-Brücke — Lifecycle (Owner-Task + dediziertes Loop), Allowlist, Koersion.

Kein echtes npx in pytest (Smoke bleibt in tests/smoke_mcp.py); der Server wird
durch eine Fake-Klasse ersetzt, die das McpServer-Protokoll spricht.
"""
from __future__ import annotations

import json
import time

import pytest

from core.agency.mcp import registry_bridge as bridge
from core.agency.tools import registry


class FakeMcpServer:
    """Spricht das McpServer-Protokoll (async context manager + list/call)."""

    instances: list["FakeMcpServer"] = []
    fail_call = False

    def __init__(self, command, args=None, env=None, timeout=15.0, cwd=None):
        self.command = command
        self.env = env or {}
        self.calls: list[tuple] = []
        FakeMcpServer.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def list_tools(self):
        return [
            {"name": "list_items", "description": "liest Dinge",
             "inputSchema": {"properties": {"n": {"type": "integer"}, "deep": {"type": "boolean"}}}},
            {"name": "get_item", "description": "liest ein Ding", "inputSchema": {}},
            {"name": "create_item", "description": "schreibt", "inputSchema": {}},
        ]

    async def call_tool(self, name, args):
        if FakeMcpServer.fail_call:
            raise RuntimeError("Server-Wackler")
        self.calls.append((name, args))
        return {"isError": False, "content": [{"type": "text", "text": f"{name}:{json.dumps(args)}"}]}


@pytest.fixture()
def clean_bridge(monkeypatch):
    """Fake-Server rein, Modul-/Registry-Zustand nach dem Test zurücksetzen."""
    monkeypatch.setattr(bridge, "McpServer", FakeMcpServer)
    FakeMcpServer.instances = []
    FakeMcpServer.fail_call = False
    before = set(registry._REGISTRY)
    yield
    bridge.shutdown_all()
    for name in set(registry._REGISTRY) - before:
        registry._REGISTRY.pop(name, None)
    bridge._servers.clear()
    bridge._tool_registry.clear()


def _wait_dead(handle, deadline=3.0):
    t0 = time.time()
    while handle.state != "dead" and time.time() - t0 < deadline:
        time.sleep(0.02)
    assert handle.state == "dead"


def test_bridge_registers_and_persists_across_calls(clean_bridge):
    count = bridge.bridge_server("testsrv", {"command": "fake", "timeout": 5})
    assert count == 3
    tool = registry.get("mcp_testsrv_list_items")
    assert tool is not None and "[MCP:testsrv]" in tool.description

    # DER Regressionstest zum alten Bug: zweiter (und dritter) Aufruf funktioniert,
    # weil der Server an EINEM dauerhaften Loop haengt statt an einer toten Schleife.
    assert "list_items" in tool.func(n="1")
    assert "list_items" in tool.func(n="2")
    assert len(FakeMcpServer.instances) == 1  # kein Neustart noetig
    assert len(FakeMcpServer.instances[0].calls) == 2


def test_allowlist_and_deny_filter(clean_bridge):
    count = bridge.bridge_server("filtered", {"command": "fake", "tools": ["list_items", "get_item"],
                                              "deny": ["get_item"]})
    assert count == 1
    assert registry.get("mcp_filtered_list_items") is not None
    assert registry.get("mcp_filtered_get_item") is None
    assert registry.get("mcp_filtered_create_item") is None


def test_collision_is_not_overwritten(clean_bridge):
    registry.register("mcp_coll_list_items", "schon da", lambda **k: "original", {})
    bridge.bridge_server("coll", {"command": "fake"})
    assert registry.get("mcp_coll_list_items").func(n="1") == "original"  # nicht ueberschrieben


def test_arg_coercion_from_schema(clean_bridge):
    bridge.bridge_server("co", {"command": "fake"})
    registry.get("mcp_co_list_items").func(n="5", deep="true")
    name, args = FakeMcpServer.instances[0].calls[0]
    assert args == {"n": 5, "deep": True}  # LLM-Strings -> echte Typen


def test_call_error_returns_string(clean_bridge):
    bridge.bridge_server("err", {"command": "fake"})
    FakeMcpServer.fail_call = True
    out = registry.get("mcp_err_list_items").func(n="1")
    assert "MCP-Fehler" in out and "Server-Wackler" in out  # kein Raise -> executor retried nicht


def test_dead_server_cooldown_and_respawn(clean_bridge):
    bridge.bridge_server("dead", {"command": "fake", "timeout": 5})
    handle = bridge._servers["dead"]
    handle.stop()
    _wait_dead(handle)

    # Frisch gestorben -> Cooldown blockt, Fehler-String statt Haenger
    out = registry.get("mcp_dead_list_items").func(n="1")
    assert "ist tot" in out

    # Cooldown abgelaufen -> genau EIN Respawn, Aufruf klappt wieder
    handle._died_at = 0.0
    out = registry.get("mcp_dead_list_items").func(n="1")
    assert "list_items" in out
    assert handle.state == "ready"
    assert len(FakeMcpServer.instances) == 2  # neuer Server-Prozess


def test_load_and_bridge_corrupt_and_seed(clean_bridge, tmp_path):
    bad = tmp_path / "kaputt.json"
    bad.write_text("kein json {", encoding="utf-8")
    assert bridge.load_and_bridge(str(bad)) == {}  # unlesbar -> leer, kein Raise

    # Fehlende Datei -> wird aus der versionierten Vorlage geseedet
    seeded = tmp_path / "neu" / "mcp_servers.json"
    results = bridge.load_and_bridge(str(seeded))
    assert seeded.exists()
    cfg = json.loads(seeded.read_text(encoding="utf-8"))
    assert "github" in cfg and cfg["filesystem"]["enabled"] is False
    # Aktivierte Server wurden (mit dem Fake) gebrueckt, deaktivierte nicht
    assert set(results) == {k for k, v in cfg.items() if v.get("enabled", True)}


def test_disabled_server_not_bridged(clean_bridge, tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"aus": {"command": "fake", "enabled": False}}), encoding="utf-8")
    assert bridge.load_and_bridge(str(p)) == {}
    assert "aus" not in bridge._servers
