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


def test_cockpit_js_is_syntactically_valid(tmp_path):
    """Faengt genau den S5.3a-Bug: die UI-Extraktion als raw-String fror Python-Escapes
    (nav(\\'x\\')) ein und brach das GANZE Skript -> keine Tab-Navigation. Ein toter
    Syntaxfehler legt das komplette Cockpit lahm, deshalb hier ein echter JS-Parse."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node nicht verfuegbar")
    html = _page()
    js = html[html.find("<script>") + 8:html.rfind("</script>")]
    f = tmp_path / "cockpit.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, f"Cockpit-JS hat einen Syntaxfehler:\n{r.stderr[:600]}"


def test_no_double_backslash_quote_in_onclick():
    """Schneller node-freier Waechter gegen das exakte Fehlermuster (zwei Backslashes
    vor einem Apostroph in einem JS-String = immer kaputt in diesem Codebase)."""
    html = _page()
    assert "\\\\'" not in html, "doppeltes Backslash-vor-Quote — raw-String-Escaping-Bug zurueck!"


def test_no_rawstring_escape_corruption():
    """S5.3a-Regression: die UI-Extraktion in raw-strings darf keine Python-Escapes
    (\\' \\") als doppelte Backslashes einfrieren — das brach das gesamte Cockpit-JS
    (Tabs unklickbar). Diese Signatur ('\\\\'' / '\\\\\"') darf nirgends im JS stehen."""
    html = _page()
    js = html[html.find("<script>"):html.rfind("</script>")]
    assert "\\\\'" not in js, "kaputte raw-string-Escape-Sequenz \\\\' im JS!"
    assert '\\\\"' not in js, 'kaputte raw-string-Escape-Sequenz \\\\" im JS!'


def test_js_syntax_valid_if_node_present():
    """Wenn node da ist: echter Syntax-Check des zusammengesetzten Cockpit-JS.
    Offline-tolerant — ohne node wird der Check uebersprungen (kein CI-Zwang)."""
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node nicht installiert")
    html = _page()
    js = html[html.find("<script>") + len("<script>"):html.rfind("</script>")]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        path = f.name
    r = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, f"Cockpit-JS Syntaxfehler:\n{r.stderr[:400]}"


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


def test_esc_helper_and_audit_escaping():
    """S6.1: zentrales esc() existiert und die bekannten XSS-Spots (Audit-Panel,
    Inbox-Titel/Detail) laufen hindurch. Rohes '+p.action+' darf nicht zurueckkommen."""
    html = _page()
    assert "function esc(" in html
    assert "esc(p.action)" in html and "esc(p.target||'')" in html
    assert "'<b>'+p.action+'</b>'" not in html


def test_inbox_buttons_have_doubleclick_guard():
    """S6.1: Freigabe-Buttons sperren sich beim Klick (decideOnce) — der 10x-Apply-Bug
    kam u.a. durch ungebremste Mehrfach-Klicks."""
    html = _page()
    assert "decideOnce" in html
    assert 'x.disabled=true' in html


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
