"""S5.3a: Dashboard-Shell — DOM-Regressionsnetz + WS-Chat-Vertrag (der unantastbare Kern)."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s


def _page() -> str:
    return TestClient(s.app).get("/").text


def test_page_boots_with_new_ia():
    """S6.6a: Sergens 7-Bereiche-Zuschnitt (Zentrale/Chat/Kira/Workspace/To-Do/Config/Einstellungen)."""
    html = _page()
    assert "KIRA" in html
    for vid in ("v-home", "v-chat", "v-kira", "v-work", "v-todo", "v-config", "v-settings"):
        assert f'id="{vid}"' in html, f"View fehlt: {vid}"
    # Config-Subtabs (Modelle/Gewissen/Cron/Monitor/Zugaenge/Protokoll)
    for sub in ("v-models", "v-gov", "v-cron", "v-monitor", "v-keys", "v-log"):
        assert f'id="{sub}"' in html, f"Config-Subview fehlt: {sub}"
    # Kira-Subtabs (Seele & Dateien / Gedaechtnis / Anatomie)
    for sub in ("v-files", "v-mem", "v-anatomie"):
        assert f'id="{sub}"' in html, f"Kira-Subview fehlt: {sub}"
    assert 'id="sys-tabs"' in html and 'id="kira-tabs"' in html


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
    """S6.6a: alle Panels haben Container + Loader in der neuen IA."""
    html = _page()
    for el in ("life-board", "life-goals", "life-metrics",       # To-Do (Leben)
               "inbox-list", "todo-secrets",                       # To-Do (braucht dich)
               "ag-organs", "ag-infra",                            # Kira (Anatomie)
               "vent-list", "vent-detail", "rd-list", "kn-docs",   # Workspace
               "digest", "hud-strip", "ops-feed",                  # Zentrale
               "m-or"):                                            # Config (S6.6a: UI wiederhergestellt)
        assert f'id="{el}"' in html, f"Container fehlt: {el}"
    for fn in ("loadLeben", "loadAgenten", "loadVentures", "loadVentureTrace",
               "loadTodoSecrets", "loadDigest", "kirat(", "function spark"):
        assert fn in html, f"Loader fehlt: {fn}"
    # Die alten Dopplungen sind wirklich raus (Zentrale zeigte Freigaben ohne Buttons)
    assert 'id="needs-list"' not in html and 'id="z-digest"' not in html


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


def test_ui_v3_robustness_markers():
    """S6.4: Toasts + Fetch-Wrapper + EIN Poll-Scheduler + WS-Backoff + mobiles Menue."""
    html = _page()
    for marker in ("function toast(", "async function J(", "function pollTick(",
                   "visibilitychange", "wsDelay", 'id="burger"', 'id="ws-dot"',
                   "@media(max-width:900px)"):
        assert marker in html, f"S6.4-Marker fehlt: {marker}"


def test_single_poll_scheduler_no_naked_intervals():
    """Der alte 5s-setInterval-Hammer ist raus — Polling laeuft ueber pollTick (Backoff+Pause).
    Erlaubt bleibt nur der UI-lokale thinkTimer im Chat."""
    html = _page()
    js = html[html.find("<script>"):html.rfind("</script>")]
    assert "setInterval(()=>{refreshStatus" not in js
    assert "setInterval(updatePulse" not in js
    assert js.count("setInterval(") <= 1  # nur thinkTimer


def test_chat_v3_markers():
    """S6.6b: Markdown-Renderer, Nachrichten-Meta, Session-Panel, Chips sind verdrahtet."""
    html = _page()
    for marker in ("function md(", "function msgEl(", 'id="sess-panel"', 'id="sess-items"',
                   'id="chip-work"', 'id="chip-ziel"', "markActiveSession", "mcopy"):
        assert marker in html, f"Chat-v3-Marker fehlt: {marker}"
    assert 'id="sess-list"' not in html  # Dropdown ist durch das Panel ersetzt


def test_md_renderer_semantics(tmp_path):
    """Fuehrt md()+esc() in node aus: Markdown wird gerendert, Injection bleibt escaped."""
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node nicht verfuegbar")
    html = _page()
    js = html[html.find("<script>") + 8:html.rfind("</script>")]
    esc_src = re.search(r"^function esc\(x\).*$", js, re.M).group(0)
    md_src = js[js.find("function md(src){"):js.find("/* Nachricht mit Koerper")]
    checks = r"""
const a=md("**fett** und `code` mit [Link](https://example.de)\n- eins\n- zwei\n## Titel");
if(!a.includes("<b>fett</b>"))throw new Error("bold fehlt: "+a);
if(!a.includes("<code>code</code>"))throw new Error("code fehlt");
if(!a.includes("<ul><li>eins</li>"))throw new Error("liste fehlt: "+a);
if(!a.includes('rel="noopener"'))throw new Error("link unsicher");
if(!a.includes('class="mdh"'))throw new Error("ueberschrift fehlt");
const b=md("vorher <script>alert(1)</script> nachher");
if(b.includes("<script>"))throw new Error("XSS! script nicht escaped");
if(!b.includes("&lt;script&gt;"))throw new Error("escaping fehlt");
const c=md("```\nif (x<y) {}\n```");
if(!c.includes('<pre class="mdc">'))throw new Error("codeblock fehlt");
if(!c.includes("x&lt;y"))throw new Error("codeblock nicht escaped");
console.log("md ok");
"""
    f = tmp_path / "md_test.js"
    f.write_text(esc_src + "\n" + md_src + "\n" + checks, encoding="utf-8")
    r = subprocess.run([node, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, f"md()-Semantik verletzt:\n{r.stderr[:500]}"


def test_stats_tab_and_endpoint():
    """S6.6c: Statistik-Subtab (Lern-Kurve aus dem Outcome-Ledger) + /api/insights."""
    html = _page()
    for marker in ('data-s="stats"', 'id="v-stats"', "loadStats", 'id="st-kpi"',
                   'id="st-kinds"', 'id="st-costs"'):
        assert marker in html, f"Statistik-Marker fehlt: {marker}"
    d = TestClient(s.app).get("/api/insights").json()  # rein lesend gegen echte DB
    assert set(d) >= {"days", "stats", "patterns", "strategies", "brief"}
    assert "by_kind" in d["patterns"] and "by_objective" in d["patterns"]
    assert TestClient(s.app).get("/api/insights", params={"days": 999}).json()["days"] == 90  # Clamp


def test_fixed_dashboard_and_tool_groups():
    """S6.7b: Zentrale ist ein fester Kommandostand — Dopplungs-Karten raus (System/Modell/
    Vertrauen/Werkzeug-Wolke), Dienste-Punkte im HUD, Werkzeuge gruppiert in der Anatomie."""
    html = _page()
    for marker in ("function toolGroups", '<span class="k">Dienste</span>', "WERKZEUGKASTEN",
                   "#v-home .cmd-grid{flex:1"):
        assert marker in html, f"S6.7b-Marker fehlt: {marker}"
    # Die alte 73-Pillen-Wolke und die HUD-Dopplungs-Karten sind wirklich raus
    assert "o.tools.map(t=>" not in html
    for gone in ('card("System"', 'card("Modell', 'card("Vertrauen"', 'card("Werkzeuge'):
        assert gone not in html, f"Dopplungs-Karte lebt noch: {gone}"


def test_avatar_hero_and_endpoints():
    """S6.6d: Hero in der Zentrale + Avatar-Endpoints (Upload/Serve/Clear, bg-Muster)."""
    html = _page()
    for marker in ('id="hero"', 'id="hero-av"', 'id="hero-status"', "hasAvatar",
                   'id="set-avatar"', 'id="set-avatar-clear"', "aurapulse", 'className="mav"'):
        assert marker in html, f"Avatar-Marker fehlt: {marker}"
    client = TestClient(s.app)
    bad = client.post("/api/avatar/upload", json={"dataurl": "kein-bild"}).json()
    assert bad["ok"] is False  # Format-Wache; kein Schreiben auf Muell
    r = client.get("/api/avatar")
    assert r.status_code in (200, 404)  # 404 solange Sergen noch kein Bild hochgeladen hat


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
