"""Fernzugriff (Punkt 4, PWA): Token-Middleware, Login, lokale Verwaltung, PWA-Endpunkte.
Offline; 'remote' wird ueber die ASGI-Client-Adresse simuliert.
"""
from __future__ import annotations

import contextlib


def _local_client():
    from fastapi.testclient import TestClient
    import core.api.server as s
    return TestClient(s.app)  # client host 'testclient' zaehlt als lokal


@contextlib.contextmanager
def _remote_client():
    from starlette.testclient import TestClient
    import core.api.server as s
    with TestClient(s.app, client=("10.7.7.7", 4711)) as c:
        yield c


def _tmp_token(monkeypatch, tmp_path):
    from core import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)


def test_ohne_token_alles_offen_wie_bisher(monkeypatch, tmp_path):
    _tmp_token(monkeypatch, tmp_path)
    assert _local_client().get("/api/status").status_code == 200
    with _remote_client() as rc:
        assert rc.get("/api/status").status_code == 200  # Fernzugriff aus -> kein Zwang


def test_enable_nur_lokal_und_token_fluss(monkeypatch, tmp_path):
    _tmp_token(monkeypatch, tmp_path)
    c = _local_client()
    with _remote_client() as rc:
        assert rc.post("/api/remote/enable").status_code == 403  # remote darf nicht schalten
    r = c.post("/api/remote/enable").json()
    tok = r["token"]
    assert r["ok"] and len(tok) > 20
    st = c.get("/api/remote/status").json()
    assert st["enabled"] and st["token"] == tok and st["local"]

    with _remote_client() as rc:
        # ohne Token: API -> 401 JSON, Browser-GET -> Login-Seite
        assert rc.get("/api/status").status_code == 401
        seite = rc.get("/", headers={"accept": "text/html"})
        assert seite.status_code == 401 and "Zugangstoken" in seite.text
        # Status remote: enabled sichtbar, Token NIE
        st2 = rc.get("/api/remote/status", headers={"authorization": f"Bearer {tok}"}).json()
        assert st2["enabled"] and st2["token"] is None and not st2["local"]
        # mit Bearer -> offen
        assert rc.get("/api/status", headers={"authorization": f"Bearer {tok}"}).status_code == 200
        # Login setzt Cookie -> danach offen
        li = rc.post("/api/login", json={"token": tok})
        assert li.status_code == 200 and "kira_token" in li.headers.get("set-cookie", "")
        rc.cookies.set("kira_token", tok)
        assert rc.get("/api/status").status_code == 200
        # falsches Token -> 401
        assert rc.post("/api/login", json={"token": "falsch"}).status_code == 401

    # lokal bleibt ALLES frei (Desktop/Wallpaper) — auch mit aktivem Fernzugriff
    assert c.get("/api/status").status_code == 200
    # disable raeumt auf
    assert c.post("/api/remote/disable").json()["ok"]
    with _remote_client() as rc:
        assert rc.get("/api/status").status_code == 200


def test_proxy_anfragen_brauchen_token(monkeypatch, tmp_path):
    """Tailscale Serve kommt von 127.0.0.1, traegt aber X-Forwarded-* -> Token noetig."""
    _tmp_token(monkeypatch, tmp_path)
    c = _local_client()
    tok = c.post("/api/remote/enable").json()["token"]
    r = c.get("/api/status", headers={"x-forwarded-for": "100.64.0.5"})
    assert r.status_code == 401
    r2 = c.get("/api/status", headers={"x-forwarded-for": "100.64.0.5",
                                       "authorization": f"Bearer {tok}"})
    assert r2.status_code == 200
    # Verwaltung ist fuer Proxy-Anfragen tabu, selbst mit Token
    r3 = c.post("/api/remote/disable", headers={"x-forwarded-for": "100.64.0.5",
                                                "authorization": f"Bearer {tok}"})
    assert r3.status_code == 403


def test_pwa_endpunkte_und_head(monkeypatch, tmp_path):
    _tmp_token(monkeypatch, tmp_path)
    c = _local_client()
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["display"] == "standalone"
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    html = c.get("/").text
    assert 'rel="manifest"' in html and "serviceWorker" in html
    assert 'id="remote-toggle"' in html  # Zugaenge-Karte


def test_pwa_endpunkte_ohne_token_erreichbar(monkeypatch, tmp_path):
    """Login-Seite braucht Icon/Manifest VOR dem Login -> exempt."""
    _tmp_token(monkeypatch, tmp_path)
    _local_client().post("/api/remote/enable")
    with _remote_client() as rc:
        assert rc.get("/manifest.webmanifest").status_code == 200
        assert rc.get("/sw.js").status_code == 200


def test_ws_endpunkte_pruefen_token():
    import inspect
    import core.api.server as s
    assert "security.ws_allowed" in inspect.getsource(s.ws_chat)
    assert "security.ws_allowed" in inspect.getsource(s.ws_bench)


def test_ws_allowed_regeln(monkeypatch, tmp_path):
    from core import config
    from core.api import security
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    class FakeWS:
        def __init__(self, host, headers=None, cookies=None, qp=None):
            class C:  # noqa: D401
                pass
            self.client = C(); self.client.host = host
            self.headers = headers or {}
            self.cookies = cookies or {}
            self.query_params = qp or {}

    assert security.ws_allowed(FakeWS("10.1.1.1"))          # aus -> offen
    tok = security.enable()
    assert security.ws_allowed(FakeWS("127.0.0.1"))          # lokal bleibt frei
    assert not security.ws_allowed(FakeWS("10.1.1.1"))       # remote ohne Token -> zu
    assert security.ws_allowed(FakeWS("10.1.1.1", qp={"token": tok}))
    assert security.ws_allowed(FakeWS("10.1.1.1", cookies={"kira_token": tok}))
    assert not security.ws_allowed(FakeWS("127.0.0.1", headers={"x-forwarded-for": "x"}))
