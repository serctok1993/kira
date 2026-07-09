"""Macht-Schritt 2: MCP-Universum — beliebige MCP-Server per Config einstoepseln,
ohne Code. Getestet werden Config-Persistenz, Live-(Un)Bridge, Katalog, Toggle/Remove
und die API — die echten npx-Prozesse werden gemockt (bridge_server), damit die Suite
keinen Server startet."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.agency.mcp import registry_bridge as rb
from core.agency.tools import registry


def _isolate(monkeypatch, tmp_path):
    """Config in einen Wegwerf-Pfad umbiegen + Bridge-Zustand leeren."""
    monkeypatch.setattr(rb, "_CONFIG_PATH", tmp_path / "mcp.json")
    rb._servers.clear()
    rb._tool_registry.clear()


# ---------- Config lesen/schreiben ----------

def test_read_write_roundtrip(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert rb._read_config() == {}                       # nichts da -> leer, kein Crash
    rb._write_config({"a": {"command": "npx", "enabled": True}})
    assert rb._read_config()["a"]["command"] == "npx"


# ---------- add / toggle / remove (bridge gemockt) ----------

def test_add_server_persistiert_und_brueckt(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(rb, "bridge_server", lambda n, c: calls.append(n) or 5)
    out = rb.add_server("meins", {"command": "npx", "args": ["-y", "x"]})
    assert out["ok"] and out["tools"] == 5 and calls == ["meins"]
    assert rb._read_config()["meins"]["command"] == "npx"      # in der Config gelandet


def test_add_ohne_command_wird_abgelehnt(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert rb.add_server("x", {})["ok"] is False
    assert rb.add_server("", {"command": "npx"})["ok"] is False


def test_add_kaputter_server_bricht_nicht(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    def boom(n, c):
        raise RuntimeError("npx nicht da")
    monkeypatch.setattr(rb, "bridge_server", boom)
    out = rb.add_server("kaputt", {"command": "npx"})
    assert out["ok"] is True and "npx nicht da" in out["error"]  # Fehler gemeldet, nicht geworfen


def test_toggle_startet_und_stoppt(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(rb, "bridge_server", lambda n, c: 3)
    unbridged = []
    monkeypatch.setattr(rb, "_unbridge_server", lambda n: unbridged.append(n))
    rb._write_config({"s1": {"command": "npx", "enabled": True}})
    assert rb.toggle_server("s1", False)["ok"] and unbridged == ["s1"]
    assert rb._read_config()["s1"]["enabled"] is False
    assert rb.toggle_server("s1", True)["tools"] == 3           # wieder an -> gebrueckt


def test_toggle_unbekannt(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert rb.toggle_server("gibtsnicht", True)["ok"] is False


def test_remove_loescht_und_entbrueckt(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(rb, "_unbridge_server", lambda n: seen.append(n))
    rb._write_config({"weg": {"command": "npx"}})
    assert rb.remove_server("weg")["ok"] and seen == ["weg"]
    assert "weg" not in rb._read_config()
    assert rb.remove_server("weg")["ok"] is False               # zweites Mal: nicht da


# ---------- _unbridge entfernt Tools aus der Registry ----------

def test_unbridge_raeumt_registry(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    registry.register("mcp_demo_ping", "test", lambda: "pong")
    rb._tool_registry["mcp_demo_ping"] = "demo"
    rb._unbridge_server("demo")
    assert registry.get("mcp_demo_ping") is None                # weg aus der Werkzeug-Liste
    assert "mcp_demo_ping" not in rb._tool_registry


def test_registry_unregister():
    registry.register("wegwerf_tool", "x", lambda: "")
    assert registry.unregister("wegwerf_tool") is True
    assert registry.unregister("wegwerf_tool") is False         # zweites Mal: nichts mehr da


# ---------- Katalog ----------

def test_katalog_hat_gaengige_server():
    ids = {e["id"] for e in rb.CATALOG}
    assert {"github", "supabase", "notion", "slack", "whatsapp", "gcal"} <= ids
    for e in rb.CATALOG:                                        # jede Vorlage ist startbar
        assert e["config"].get("command")


def test_aussenwelt_kanaele_gegated():
    # Macht-Schritt 3: WhatsApp-Senden und Kalender-Schreiben laufen durchs Freigabe-Gate
    wa = next(e for e in rb.CATALOG if e["id"] == "whatsapp")
    assert wa["config"]["kinds"]["send_message"] == "external"
    assert wa.get("setup") and "clone" in wa["setup"].lower()   # Einricht-Hinweis vorhanden
    gc = next(e for e in rb.CATALOG if e["id"] == "gcal")
    assert gc["config"]["kinds"]["create-event"] == "external"


def test_arg_variablen_werden_aufgeloest(monkeypatch):
    # $VAR in args muss aus der Umgebung (Tresor) kommen — sonst startet WhatsApp nie mit dem Repo-Pfad
    monkeypatch.setenv("WHATSAPP_MCP_MAIN", "/home/serge/wa/src/main.ts")
    assert rb._resolve_args(["$WHATSAPP_MCP_MAIN", "--flag", "-y"]) == [
        "/home/serge/wa/src/main.ts", "--flag", "-y"]
    assert rb._resolve_token("$NICHT_GESETZT") == ""            # unbekannt -> leer, kein Crash
    assert rb._resolve_token("wortlaut") == "wortlaut"          # ohne $ unveraendert


def test_api_katalog_zeigt_setup(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = TestClient(s.app).get("/api/mcp/catalog").json()
    wa = next(e for e in r["catalog"] if e["id"] == "whatsapp")
    assert wa["setup"] and wa["secret"] == "WHATSAPP_MCP_MAIN"


# ---------- API ----------

def test_api_catalog_zeigt_secret_bereitschaft(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = TestClient(s.app).get("/api/mcp/catalog").json()
    assert "catalog" in r and "status" in r
    fs = next(e for e in r["catalog"] if e["id"] == "filesystem")
    assert fs["secret_ready"] is True                           # kein Secret noetig -> immer bereit


def test_api_add_toggle_remove(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(rb, "bridge_server", lambda n, c: 4)
    monkeypatch.setattr(rb, "_unbridge_server", lambda n: None)
    c = TestClient(s.app)
    add = c.post("/api/mcp/add", json={"name": "t", "config": {"command": "npx"}}).json()
    assert add["ok"] and add["tools"] == 4
    assert c.post("/api/mcp/toggle", json={"name": "t", "enabled": False}).json()["ok"]
    assert c.post("/api/mcp/remove", json={"name": "t"}).json()["ok"]


def test_api_add_aus_katalog(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(rb, "bridge_server", lambda n, c: captured.update(name=n, cfg=c) or 6)
    r = TestClient(s.app).post("/api/mcp/add", json={"catalog_id": "github"}).json()
    assert r["ok"] and r["tools"] == 6
    assert captured["name"] == "github" and "server-github" in " ".join(captured["cfg"]["args"])
