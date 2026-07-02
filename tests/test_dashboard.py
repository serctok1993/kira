"""S5.3a: Dashboard-Shell — DOM-Regressionsnetz + WS-Chat-Vertrag (der unantastbare Kern)."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s


def _page() -> str:
    return TestClient(s.app).get("/").text


def test_page_boots_with_new_ia():
    html = _page()
    assert "KIRA" in html
    for vid in ("v-home", "v-chat", "v-leben", "v-mission", "v-agenten",
                "v-wissen", "v-radar", "v-system"):
        assert f'id="{vid}"' in html, f"View fehlt: {vid}"
    # System-Subtabs tragen die alten Panes weiter (IDs + Loader ueberleben)
    for sub in ("v-models", "v-gov", "v-cron", "v-monitor", "v-keys", "v-mem", "v-files", "v-log"):
        assert f'class="subview" id="{sub}"' in html, f"Subview fehlt: {sub}"
    assert 'id="sys-tabs"' in html


def test_phrases_injected():
    html = _page()
    assert "__PHRASES__" not in html  # Server-Injektion hat gegriffen
    assert "const PHRASES=[" in html


def test_new_panes_have_containers():
    """S5.3b: die neuen Panes sind echte Container mit Loader-Verdrahtung."""
    html = _page()
    for el in ("life-board", "life-goals", "life-metrics",       # Leben
               "ag-organs", "ag-infra",                            # Agenten
               "vent-list", "vent-detail",                         # Projekte
               "needs-list", "z-digest"):                          # Zentrale
        assert f'id="{el}"' in html, f"Container fehlt: {el}"
    for fn in ("loadLeben", "loadAgenten", "loadVentures", "loadVentureTrace",
               "loadNeeds", "loadZDigest", "function spark"):
        assert fn in html, f"Loader fehlt: {fn}"


def test_agents_endpoint_shape():
    """/api/agents ist rein lesend — Form-Check gegen die echte (read-only) DB."""
    from fastapi.testclient import TestClient as TC

    d = TC(s.app).get("/api/agents").json()
    assert {o["name"] for o in d["organs"]} >= {"Planner", "Actor", "Pruefer", "Council", "Curator"}
    assert isinstance(d["tools_total"], int) and d["tools_total"] > 20
    assert "mcp" in d and "skills_total" in d


def test_venture_trace_unknown_id():
    from fastapi.testclient import TestClient as TC

    d = TC(s.app).get("/api/venture/trace?id=gibtsnicht").json()
    assert d.get("error")  # sauberer Fehler statt Crash


def test_ws_contract_markers_present():
    """Die zweistufige Thinking-UI (Schimmer + aufklappbare Spur) bleibt verdrahtet."""
    html = _page()
    for marker in ("ensureTrace", 'kind==="think"', 'kind==="tool"', 'kind==="obs"',
                   "ws.onmessage", "startThinking", "stopThinking"):
        assert marker in html, f"Chat-Vertrags-Marker fehlt: {marker}"
    assert "updateFeed" not in html  # toter Poller ist raus


def test_ws_roundtrip_contract(monkeypatch):
    """Pinnt den WS-Vertrag {role, kind: think|tool|obs|final, done} VOR jedem Restyling."""
    import core.agency.act as act_mod

    def fake_stream(user_text, session_id=None):
        yield {"kind": "think", "text": "ueberlege kurz"}
        yield {"kind": "tool", "name": "web_search", "args": {"query": user_text}}
        yield {"kind": "obs", "text": "3 Treffer"}
        yield {"kind": "final", "text": "Fertig: alles gut."}

    monkeypatch.setattr(act_mod, "act_chat_stream", fake_stream)

    client = TestClient(s.app)
    with client.websocket_connect("/ws/chat?sid=t-vertrag") as ws:
        first = ws.receive_json()
        assert first["role"] == "system"
        ws.send_text("hi")
        kinds = []
        while True:
            m = ws.receive_json()
            assert m["role"] == "partner"
            if m.get("done"):
                break
            kinds.append(m.get("kind"))
        assert kinds == ["think", "tool", "obs", "final"]
