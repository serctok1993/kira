"""Bluesky-Connector: posten ueber das offene AT-Protokoll (bsky.social).

Zugang: BLUESKY_HANDLE (z.B. sergen.bsky.social) + BLUESKY_APP_PASSWORD — ein
APP-Passwort aus den Bluesky-Einstellungen, NIE das Konto-Passwort. Posten ist
Aussenwirkung: das Werkzeug laeuft durchs publish-Gate (Freigabe-Inbox), und die
Freigabe fuehrt den Post deterministisch aus (wie bei E-Mails an Fremde).

Firewall-sicher: bei KIRA_NO_OUTBOUND passiert nichts (Trockenlauf-Meldung).
"""
from __future__ import annotations

import datetime
import os

_BASE = "https://bsky.social/xrpc"
MAX_LEN = 300  # Bluesky-Limit (Graphem-genau ist das API-Limit; wir kappen konservativ)


def configured() -> bool:
    return bool(os.getenv("BLUESKY_HANDLE") and os.getenv("BLUESKY_APP_PASSWORD"))


def post(text: str) -> str:
    """Einen Post veroeffentlichen. Fehler -> klarer Hinweis-String (nie Exception)."""
    from core import config as _c

    if _c.outbound_blocked():
        return "[TESTMODUS] Bluesky-Post NICHT gesendet (Firewall aktiv)."
    handle, pw = os.getenv("BLUESKY_HANDLE"), os.getenv("BLUESKY_APP_PASSWORD")
    if not (handle and pw):
        return ("Bluesky-Zugaenge fehlen — request_secret('BLUESKY_HANDLE', ...) und "
                "request_secret('BLUESKY_APP_PASSWORD', ...) anfragen (App-Passwort aus "
                "den Bluesky-Einstellungen, nie das Konto-Passwort).")
    text = (text or "").strip()
    if not text:
        return "Leerer Post — nichts gesendet."
    import httpx

    try:
        s = httpx.post(f"{_BASE}/com.atproto.server.createSession",
                       json={"identifier": handle, "password": pw}, timeout=20)
        if s.status_code >= 400:
            return f"Bluesky-Login fehlgeschlagen ({s.status_code}): {s.text[:150]}"
        sess = s.json()
        rec = {"$type": "app.bsky.feed.post", "text": text[:MAX_LEN],
               "createdAt": datetime.datetime.now(datetime.timezone.utc)
               .strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        r = httpx.post(f"{_BASE}/com.atproto.repo.createRecord",
                       headers={"Authorization": f"Bearer {sess['accessJwt']}"},
                       json={"repo": sess["did"], "collection": "app.bsky.feed.post",
                             "record": rec}, timeout=20)
        if r.status_code >= 400:
            return f"Bluesky-Fehler ({r.status_code}): {r.text[:150]}"
        uri = (r.json() or {}).get("uri", "")
        return f"Gepostet auf Bluesky ({len(text[:MAX_LEN])} Zeichen). {uri}"
    except Exception as e:  # noqa: BLE001
        return f"Bluesky nicht erreichbar: {str(e)[:150]}"
