"""Live-Ops-Transparenz: events.describe (Klartext + Detail, serverseitig, 0 Token),
/api/events mit text/detail, Cockpit-Feed mit Payload-Aufklapper, /wall-Live-Ticker.
"""
from __future__ import annotations


# --- events.describe: WAS laeuft, nicht nur DASS etwas laeuft ---------------
def test_describe_tool_call_zeigt_werkzeug_und_ziel():
    from core.kernel import events
    d = events.describe("tool_call", {"tool": "web_search", "args": {"query": "GLM 5.3 release"}})
    assert "recherchiert" in d["text"]
    assert "web_search" in d["detail"] and "GLM 5.3" in d["detail"]


def test_describe_act_step_zeigt_datei():
    from core.kernel import events
    d = events.describe("act_step", {"step": 2, "tool": "edit_datei",
                                     "args": {"pfad": "core/api/server.py", "suche": "x"}})
    assert "aendert Code" in d["text"] and "core/api/server.py" in d["detail"]


def test_describe_mission_und_cron():
    from core.kernel import events
    d = events.describe("mission_task_start", {"id": "t1", "desc": "Akquise-Mail an Firma X"})
    assert "Task" in d["text"] and "Akquise-Mail" in d["detail"]
    c = events.describe("cron_run", {"label": "Morgen-Briefing", "ok": True, "summary": "3 Punkte"})
    assert "ok" in c["text"] and "Morgen-Briefing" in c["detail"]


def test_describe_fallback_zeigt_payload_statt_nur_aktiv():
    from core.kernel import events
    d = events.describe("irgendein_neuer_typ", {"foo": "bar", "n": 7})
    assert "irgendein_neuer_typ" in d["text"]
    assert "foo=bar" in d["detail"] and "n=7" in d["detail"]


def test_describe_fehler_typ_traegt_error_detail():
    from core.kernel import events
    d = events.describe("llm_call_error", {"error": "timeout nach 60s"})
    assert d["text"].startswith("⚠") and "timeout" in d["detail"]


def test_describe_raist_nie():
    from core.kernel import events
    assert events.describe(None, None)["text"]
    assert events.describe("tool_call", {"args": "kaputt-kein-dict"})["text"]
    assert events.describe("plan_made", {"steps": 3})["text"]  # steps mal als Zahl


def test_describe_write_blocked_und_crash():
    from core.kernel import events
    d = events.describe("write_blocked", {"path": "/x/core/act.py", "tool": "write_file"})
    assert "geblockt" in d["text"] and "write_file" in d["detail"]
    c = events.describe("service_crash", {"service": "runner", "exit_code": 1})
    assert "runner" in c["detail"]


# --- /api/events liefert text+detail fuer beide Ansichten -------------------
def test_api_events_hat_text_und_detail(monkeypatch):
    from fastapi.testclient import TestClient
    import core.api.server as s
    from core.kernel import events
    monkeypatch.setattr(events, "recent", lambda limit=60, before=None: [
        {"id": "1", "ts": 1.0, "type": "tool_call", "session_id": "desktop-x",
         "payload": {"tool": "read_file", "args": {"path": "INDEX.md"}}}])
    evs = TestClient(s.app).get("/api/events").json()
    assert evs[0]["text"] and "INDEX.md" in evs[0]["detail"]
    assert evs[0]["sev"] == "action"


# --- Cockpit: Feed mit Detail + Aufklapper ----------------------------------
def test_cockpit_ops_feed_hat_detail_und_payload_aufklapper():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert "opd" in html and "oppay" in html      # Detail-Span + Payload-Pre (CSS+JS)
    assert "e.text||pulsePhrase" in html          # Server-Klartext mit Fallback


# --- /wall: Live-Ticker ------------------------------------------------------
def test_wall_hat_ticker_und_schalter():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/wall").text
    assert 'id="ticker"' in html and 'id="w-ticker"' in html
    assert "loadTicker" in html and "/api/events?limit=8" in html
    assert 'class="tkh"' in html  # Panel-Kopf "Live · was Kira gerade tut"


def test_wall_graph_hoehe_und_maske_folgen_position():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/wall").text
    assert 'id="w-posy"' in html                 # Hoehe-Wahl im Zahnrad
    assert "var(--gx" in html and "applyMask" in html   # Sichtfenster folgt dem Graph
    assert '"rechts"' in html and '"oben"' in html      # Standard: Graph oben rechts


def test_wall_editor_im_cockpit_hat_ticker_schalter():
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="wp-ticker"' in html and 'id="wp-posy"' in html


def test_wall_settings_akzeptieren_ticker(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import core.api.server as s
    monkeypatch.setattr(s, "_WALL_FILE", tmp_path / "wall_settings.json")
    c = TestClient(s.app)
    r = c.post("/api/wall/settings", json={"ticker": False, "posy": "unten"}).json()
    assert r["settings"]["ticker"] is False and r["settings"]["posy"] == "unten"
    got = c.get("/api/wall/settings").json()
    assert got["ticker"] is False and got["posy"] == "unten"
