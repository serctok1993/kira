"""Mail-Konnektor: Kiras eigene Email-Identitaet (S3).

Eigenes Postfach nur fuer Kira (bewusste Entscheidung): Senden via SMTP (oder
Resend-API, falls Key gesetzt), Empfangen via IMAP — alles stdlib + httpx,
provider-agnostisch. Config: config.yaml channels.email; Zugangsdaten kommen
aus dem Secrets-Tresor (SMTP_USER/SMTP_PASS bzw. RESEND_API_KEY, IMAP nutzt
die SMTP-Zugangsdaten).

Gate-Regel (siehe mail_tools): Mails an die eigenen Adressen des Nutzers fliessen frei,
Mails an FREMDE laufen als 'email_stranger' in die Freigabe-Inbox.
"""
from __future__ import annotations

import email as _email
import email.header
import imaplib
import os
import smtplib
from email.message import EmailMessage

from core.config import CONFIG


def _cfg() -> dict:
    c = CONFIG.get("channels", {}).get("email", {})
    return c if isinstance(c, dict) else {}


def enabled() -> bool:
    from core import config as _c
    if _c.outbound_blocked():  # Firewall (Benchmark/Sandbox): Mail komplett still
        return False
    return bool(_cfg().get("enabled"))


def provider() -> str:
    """'resend' | 'smtp' — via Config erzwingbar, sonst nach vorhandenem Key."""
    forced = str(_cfg().get("provider", "auto")).lower()
    if forced in ("resend", "smtp"):
        return forced
    return "resend" if os.getenv("RESEND_API_KEY") else "smtp"


def is_stranger(to: str) -> bool:
    """Fremde Adresse? Alles, was NICHT in own_addresses steht (case-insensitive)."""
    own = {str(a).strip().lower() for a in (_cfg().get("own_addresses") or [])}
    return (to or "").strip().lower() not in own


def send(to: str, subject: str, body: str, headers: dict | None = None) -> str:
    """Mail senden. Fehlende Zugaenge -> klarer Hinweis-String (nie Exception)."""
    if not enabled():
        return ("Email ist noch nicht eingerichtet (channels.email.enabled=false). "
                "Der Nutzer legt das Postfach an; Zugaenge via request_secret anfragen.")
    if provider() == "resend":
        return _send_resend(to, subject, body, headers)
    return _send_smtp(to, subject, body, headers)


def reply_subject(subject: str) -> str:
    """'Re: '-Praefix ergaenzen, falls er fehlt (idempotent — 'Re: Re:' entsteht nie)."""
    s = (subject or "").strip()
    return s if s.lower().startswith("re:") else f"Re: {s}"


def _thread_headers(in_reply_to: str) -> dict:
    """In-Reply-To/References aus einer Message-ID — haelt die Antwort im Gespraechsfaden.
    Spitzklammern werden normalisiert (Mail-Clients verlangen <...>)."""
    mid = (in_reply_to or "").strip()
    if not mid:
        return {}
    mid = f"<{mid.strip('<>')}>"
    return {"In-Reply-To": mid, "References": mid}


def reply(to: str, subject: str, body: str, in_reply_to: str = "") -> str:
    """Antwort im selben Gespraechsfaden (Phase 3): 'Re: '-Betreff + Threading-Header.
    Ohne in_reply_to faellt sie auf eine normale Mail mit 'Re: '-Betreff zurueck."""
    return send(to, reply_subject(subject), body, headers=_thread_headers(in_reply_to))


def _send_resend(to: str, subject: str, body: str, headers: dict | None = None) -> str:
    key = os.getenv("RESEND_API_KEY")
    if not key:
        return "RESEND_API_KEY fehlt — mit request_secret('RESEND_API_KEY', ...) anfragen."
    sender = _cfg().get("from_address") or ""
    if not sender:
        return "channels.email.from_address fehlt in config.yaml."
    import httpx

    payload: dict = {"from": sender, "to": [to], "subject": subject, "text": body}
    if headers:
        payload["headers"] = dict(headers)
    r = httpx.post("https://api.resend.com/emails",
                   headers={"Authorization": f"Bearer {key}"},
                   json=payload,
                   timeout=20)
    if r.status_code >= 400:
        return f"Resend-Fehler {r.status_code}: {r.text[:200]}"
    return f"Gesendet an {to}: {subject}"


# Bekannte Anbieter: Host/Port automatisch aus der Adresse — der Nutzer gibt nur noch
# Adresse (SMTP_USER) + App-Passwort (SMTP_PASS) ein, die Hosts kommen von hier.
# smtp_host/imap_host in config.yaml GEWINNEN, wenn gesetzt (Flexibilitaet bleibt).
_HOST_PRESETS = {
    "gmail.com": ("smtp.gmail.com", 587, "imap.gmail.com"),
    "googlemail.com": ("smtp.gmail.com", 587, "imap.gmail.com"),
    "outlook.com": ("smtp-mail.outlook.com", 587, "outlook.office365.com"),
    "hotmail.com": ("smtp-mail.outlook.com", 587, "outlook.office365.com"),
    "gmx.de": ("mail.gmx.net", 587, "imap.gmx.net"),
    "gmx.net": ("mail.gmx.net", 587, "imap.gmx.net"),
    "web.de": ("smtp.web.de", 587, "imap.web.de"),
}


def _preset() -> tuple | None:
    addr = (os.getenv("SMTP_USER") or _cfg().get("from_address") or "").strip().lower()
    return _HOST_PRESETS.get(addr.rsplit("@", 1)[-1]) if "@" in addr else None


def build_message(sender: str, to: str, subject: str, body: str,
                  headers: dict | None = None) -> EmailMessage:
    """EmailMessage bauen (pur, offline testbar) — Threading-Header kommen als dict."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    for k, v in (headers or {}).items():
        if v:
            msg[k] = v
    msg.set_content(body)
    return msg


def _send_smtp(to: str, subject: str, body: str, headers: dict | None = None) -> str:
    cfg = _cfg()
    host, port = cfg.get("smtp_host") or "", int(cfg.get("smtp_port") or 587)
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not host:  # bekannter Anbieter? -> Hosts automatisch (Gmail & Co.)
        pre = _preset()
        if pre:
            host, port = pre[0], pre[1]
    sender = cfg.get("from_address") or user or ""
    if not (host and user and pw):
        return ("SMTP-Zugaenge fehlen — SMTP_USER (deine Adresse) + SMTP_PASS (App-Passwort) "
                "via request_secret anfragen; bei Gmail/Outlook/GMX/web.de sind die Hosts "
                "automatisch, sonst smtp_host in config.yaml setzen.")
    msg = build_message(sender, to, subject, body, headers)
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    return f"Gesendet an {to}: {subject}"


def _decode(value: str | None) -> str:
    """MIME-kodierte Header (=?utf-8?...) lesbar machen."""
    if not value:
        return ""
    parts = []
    for text, charset in _email.header.decode_header(value):
        parts.append(text.decode(charset or "utf-8", errors="replace") if isinstance(text, bytes) else text)
    return "".join(parts)


def _parse_message(raw: bytes, snippet_chars: int = 400) -> dict:
    """Rohe Mail -> {from, to, subject, date, snippet, message_id}. Pur und offline testbar.
    message_id ist der Threading-Anker fuer email_reply (In-Reply-To/References)."""
    msg = _email.message_from_bytes(raw)
    snippet = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                payload = part.get_payload(decode=True) or b""
                snippet = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                break
    else:
        payload = msg.get_payload(decode=True) or b""
        snippet = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return {
        "from": _decode(msg.get("From")),
        "to": _decode(msg.get("To")),
        "subject": _decode(msg.get("Subject")),
        "date": msg.get("Date") or "",
        "snippet": " ".join(snippet.split())[:snippet_chars],
        "message_id": (msg.get("Message-ID") or "").strip(),
    }


_UNREAD_CACHE: dict = {"ts": 0.0, "count": None}


def unread_count(max_age: float = 120.0) -> int | None:
    """Anzahl UNGELESENER Mails (IMAP UNSEEN), gecacht (Standard 2 min). None = Postfach
    nicht eingerichtet oder Fehler -> das Wallpaper zeigt dann schlicht „—"."""
    import time as _t
    if _t.time() - _UNREAD_CACHE["ts"] < max_age:
        return _UNREAD_CACHE["count"]
    cnt: int | None = None
    try:
        if enabled():
            cfg = _cfg()
            host = cfg.get("imap_host") or ((_preset() or ("", 0, ""))[2])
            user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
            if host and user and pw:
                with imaplib.IMAP4_SSL(host, int(cfg.get("imap_port") or 993)) as m:
                    m.login(user, pw)
                    m.select("INBOX", readonly=True)
                    _, data = m.search(None, "UNSEEN")
                    cnt = len((data[0] or b"").split())
    except Exception:  # noqa: BLE001 — nie raisen, nur „—" zeigen
        cnt = None
    _UNREAD_CACHE["ts"] = _t.time()
    _UNREAD_CACHE["count"] = cnt
    return cnt


def check(limit: int = 10) -> list[dict] | str:
    """Die juengsten Mails aus dem Posteingang (IMAP). Fehler -> Hinweis-String."""
    if not enabled():
        return "Email ist noch nicht eingerichtet (channels.email.enabled=false)."
    cfg = _cfg()
    host, port = cfg.get("imap_host") or ((_preset() or ("", 0, ""))[2]), int(cfg.get("imap_port") or 993)
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not host:
        return "IMAP ist nicht konfiguriert (channels.email.imap_host) — nur Senden moeglich."
    if not (user and pw):
        return "Postfach-Zugaenge fehlen — request_secret('SMTP_USER'/'SMTP_PASS', ...) anfragen."
    try:
        with imaplib.IMAP4_SSL(host, port) as m:
            m.login(user, pw)
            m.select("INBOX", readonly=True)
            _, data = m.search(None, "ALL")
            ids = (data[0] or b"").split()
            out = []
            for mid in reversed(ids[-limit:]):
                _, msg_data = m.fetch(mid, "(RFC822)")
                if msg_data and msg_data[0]:
                    out.append(_parse_message(msg_data[0][1]))
            return out
    except Exception as e:  # noqa: BLE001 — Fehler-String statt Raise (executor-Regel)
        return f"IMAP-Fehler: {e}"
