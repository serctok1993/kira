"""Fernzugriff-Schutz (Token-Middleware) — Punkt 4 des 5-Punkte-Plans (PWA/Handy).

Standard: AUS. Ohne Token-Datei verhaelt sich das Cockpit exakt wie bisher (nur
localhost erreichbar, Desktop/Wallpaper/Tests unberuehrt). Aktiviert Sergen den
Fernzugriff (Einstellungen -> Zugaenge), entsteht data/access_token.txt — ab dann
braucht jede Anfrage, die NICHT direkt von Loopback kommt (oder durch einen Proxy
wie Tailscale Serve gelaufen ist, erkennbar an X-Forwarded-*), das Token:
als Cookie (Login-Seite), Bearer-Header oder ?token=.

Empfohlener Weg aufs Handy: Tailscale Serve auf 127.0.0.1:8000 — nur eigene Geraete
im Tailnet kommen ueberhaupt ran (Schicht 1), HTTPS inklusive (PWA installierbar),
und das Token ist Schicht 2. Das Cockpit muss dafuer NICHT auf 0.0.0.0 lauschen.
"""
from __future__ import annotations

import secrets
from pathlib import Path

_LOCAL_HOSTS = {None, "", "127.0.0.1", "::1", "localhost", "testclient"}
# Ohne Token erreichbar (Login-Fluss + PWA-Grundgeruest muessen VOR dem Login laden)
EXEMPT_PATHS = {"/api/login", "/manifest.webmanifest", "/sw.js", "/api/icon"}


def _token_path() -> Path:
    from core import config

    return Path(config.DATA_DIR) / "access_token.txt"


def get_token() -> str | None:
    try:
        t = _token_path().read_text(encoding="utf-8").strip()
        return t or None
    except Exception:  # noqa: BLE001
        return None


def enabled() -> bool:
    return get_token() is not None


def enable() -> str:
    """Fernzugriff an: erzeugt (oder behaelt) das Token und gibt es zurueck."""
    tok = get_token()
    if not tok:
        from core.kernel.fs import atomic_write

        tok = secrets.token_urlsafe(32)
        atomic_write(_token_path(), tok + "\n")
    return tok


def disable() -> None:
    try:
        _token_path().unlink()
    except FileNotFoundError:
        pass


def is_local(host: str | None) -> bool:
    return host in _LOCAL_HOSTS


def token_ok(given: str | None) -> bool:
    tok = get_token()
    return bool(tok) and secrets.compare_digest(given or "", tok)


def request_allowed(client_host: str | None, given: str | None, forwarded: bool,
                    path: str = "") -> bool:
    """Die eine Regel: kein Token gesetzt -> alles wie bisher. Token gesetzt ->
    direkte Loopback-Anfragen bleiben frei (Desktop/Wallpaper), alles andere
    (fremder Host ODER Proxy-Header) braucht das Token."""
    if not enabled():
        return True
    if path in EXEMPT_PATHS:
        return True
    if is_local(client_host) and not forwarded:
        return True
    return token_ok(given)


def _given_from(headers, cookies, query_params) -> str | None:
    auth = (headers.get("authorization") or "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return cookies.get("kira_token") or query_params.get("token")


def http_allowed(request) -> bool:
    """Fuer die FastAPI-HTTP-Middleware."""
    host = request.client.host if request.client else None
    fwd = "x-forwarded-for" in request.headers or "x-forwarded-proto" in request.headers
    return request_allowed(host, _given_from(request.headers, request.cookies,
                                             request.query_params),
                           fwd, path=request.url.path)


def ws_allowed(ws) -> bool:
    """Fuer WebSocket-Endpunkte (Middleware greift bei WS nicht)."""
    host = ws.client.host if ws.client else None
    fwd = "x-forwarded-for" in ws.headers or "x-forwarded-proto" in ws.headers
    return request_allowed(host, _given_from(ws.headers, ws.cookies, ws.query_params), fwd)


# Minimale Login-Seite (401): Token einmal eingeben -> Cookie -> weiter zum Cockpit.
LOGIN_HTML = """<!doctype html><html lang="de"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Kira · Zugang</title><link rel="icon" href="/api/icon"/>
<style>body{margin:0;height:100vh;display:grid;place-items:center;background:#0a0a0d;color:#eceef4;
font-family:"Segoe UI",system-ui,sans-serif}form{display:flex;flex-direction:column;gap:12px;width:min(320px,86vw);
padding:26px;border:1px solid #26203a;border-radius:16px;background:#0e0e13;box-shadow:0 0 40px rgba(176,38,255,.15)}
h1{font-size:17px;margin:0;color:#c084fc}input{background:#0a0a0d;color:#eceef4;border:1px solid #26203a;
border-radius:9px;padding:11px;font-size:14px}button{background:#b026ff;color:#fff;border:0;border-radius:9px;
padding:11px;font-size:14px;font-weight:600;cursor:pointer}#err{color:#ff3d68;font-size:12.5px;min-height:16px}</style>
</head><body><form id="f"><h1>Kira · Zugangstoken</h1>
<input id="t" type="password" placeholder="Token (Cockpit &rarr; Einstellungen &rarr; Zugaenge)" autofocus/>
<button>Verbinden</button><div id="err"></div></form>
<script>document.getElementById("f").onsubmit=async e=>{e.preventDefault();
const r=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},
body:JSON.stringify({token:document.getElementById("t").value.trim()})});
if(r.ok)location.href="/";else document.getElementById("err").textContent="Token falsch.";};</script>
</body></html>"""
