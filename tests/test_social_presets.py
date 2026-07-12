"""Teil 2 Malen-nach-Zahlen: Gmail-Presets (nur App-Passwort noetig) + Bluesky.

Offline: SMTP/IMAP/httpx gefakt. Prueft die drei Versprechen:
  1. Bekannter Anbieter (Gmail & Co.) -> Hosts automatisch, config gewinnt.
  2. bluesky_post laeuft IMMER durchs publish-Gate (Freigabe-Inbox).
  3. des Nutzers GO fuehrt den Post deterministisch aus (approvals.decide).
"""
from __future__ import annotations

import json

from core.agency import approvals
from core.agency.connectors import bluesky, mail
from core.agency.tools import social_tools
from core.config import CONFIG
from core.governance import autonomy
from core.kernel import events


def _setup(monkeypatch, tmp_path, email_cfg=None, hard_gate=None):
    db = str(tmp_path / "state.db")
    for mod in (approvals, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(autonomy, "_PATH", tmp_path / "autonomy.json")
    autonomy.set_config(chains_off=True,
                        hard_gate=hard_gate or ["money", "email_stranger", "publish"])
    events.init_db()
    approvals.init_approvals()
    cfg = {"enabled": True, "provider": "smtp", "from_address": "kira@example.de",
           "own_addresses": ["nutzer@example.com"], "smtp_host": "",
           "smtp_port": 587, "imap_host": "", "imap_port": 993}
    cfg.update(email_cfg or {})
    monkeypatch.setitem(CONFIG, "channels", {"email": cfg})


# ---------- Gmail & Co.: Hosts automatisch ----------

def test_preset_known_and_unknown_domains(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "kira.tok@gmail.com")
    assert mail._preset() == ("smtp.gmail.com", 587, "imap.gmail.com")
    monkeypatch.setenv("SMTP_USER", "x@WEB.DE")  # case-insensitiv
    assert mail._preset() == ("smtp.web.de", 587, "imap.web.de")
    monkeypatch.setenv("SMTP_USER", "x@eigene-domain.de")
    assert mail._preset() is None
    monkeypatch.setenv("SMTP_USER", "kein-at-zeichen")
    assert mail._preset() is None


def test_preset_falls_back_to_from_address(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"from_address": "kira@gmx.de"})
    monkeypatch.delenv("SMTP_USER", raising=False)
    assert mail._preset() == ("mail.gmx.net", 587, "imap.gmx.net")


def test_smtp_auto_host_gmail(monkeypatch, tmp_path):
    """Kern des Versprechens: nur Adresse + App-Passwort, Host kommt von selbst."""
    _setup(monkeypatch, tmp_path, {"from_address": ""})
    monkeypatch.setenv("SMTP_USER", "kira.tok@gmail.com")
    monkeypatch.setenv("SMTP_PASS", "app-passwort")
    used = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            used["host"], used["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, u, p):
            used["login"] = u

        def send_message(self, msg):
            used["to"] = msg["To"]

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    out = mail._send_smtp("ziel@firma.de", "Test", "Hallo")
    assert out.startswith("Gesendet an ziel@firma.de")
    assert used["host"] == "smtp.gmail.com" and used["port"] == 587
    assert used["login"] == "kira.tok@gmail.com" and used["to"] == "ziel@firma.de"


def test_smtp_config_host_wins_over_preset(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"smtp_host": "mail.eigener-server.de", "smtp_port": 465})
    monkeypatch.setenv("SMTP_USER", "kira.tok@gmail.com")
    monkeypatch.setenv("SMTP_PASS", "pw")
    used = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            used["host"], used["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def send_message(self, msg):
            pass

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    mail._send_smtp("x@y.de", "T", "B")
    assert used["host"] == "mail.eigener-server.de" and used["port"] == 465


def test_smtp_hint_mentions_auto_hosts(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASS", raising=False)
    out = mail._send_smtp("x@y.de", "T", "B")
    assert "App-Passwort" in out and "automatisch" in out


def test_imap_preset_fallback(monkeypatch, tmp_path):
    """check() findet den IMAP-Host automatisch, wenn die Adresse bekannt ist."""
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("SMTP_USER", "kira.tok@gmail.com")
    monkeypatch.setenv("SMTP_PASS", "pw")
    used = {}

    class FakeIMAP:
        def __init__(self, host, port):
            used["host"], used["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            pass

        def select(self, box, readonly=True):
            pass

        def search(self, charset, query):
            return "OK", [b""]

        def fetch(self, mid, spec):
            return "OK", []

    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", FakeIMAP)
    out = mail.check(limit=3)
    assert out == []  # leerer Posteingang, aber verbunden
    assert used["host"] == "imap.gmail.com" and used["port"] == 993


def test_imap_still_hints_without_preset(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)  # from_address example.de -> kein Preset
    monkeypatch.delenv("SMTP_USER", raising=False)
    assert "IMAP ist nicht konfiguriert" in mail.check()


# ---------- Bluesky-Connector ----------

def test_bluesky_firewall_dry_run(monkeypatch):
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    out = bluesky.post("Hallo Welt")
    assert "[TESTMODUS]" in out and "NICHT gesendet" in out


def test_bluesky_missing_secrets_hint(monkeypatch):
    monkeypatch.delenv("KIRA_NO_OUTBOUND", raising=False)
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    assert not bluesky.configured()
    out = bluesky.post("Hallo")
    assert "request_secret" in out and "App-Passwort" in out


def test_bluesky_post_success_and_cap(monkeypatch):
    monkeypatch.delenv("KIRA_NO_OUTBOUND", raising=False)
    monkeypatch.setenv("BLUESKY_HANDLE", "beispiel.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "app-pw")
    assert bluesky.configured()
    calls = []

    class FakeResp:
        def __init__(self, data):
            self._d = data
            self.status_code = 200
            self.text = ""

        def json(self):
            return self._d

    def fake_post(url, **kw):
        calls.append((url, kw))
        if url.endswith("createSession"):
            return FakeResp({"accessJwt": "jwt123", "did": "did:plc:abc"})
        return FakeResp({"uri": "at://did:plc:abc/app.bsky.feed.post/xyz"})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    out = bluesky.post("x" * 400)  # ueber dem Limit -> gekappt
    assert out.startswith("Gepostet auf Bluesky (300 Zeichen)")
    assert "at://" in out
    record = calls[1][1]["json"]["record"]
    assert record["$type"] == "app.bsky.feed.post"
    assert len(record["text"]) == 300
    assert calls[1][1]["headers"]["Authorization"] == "Bearer jwt123"


def test_bluesky_login_failure_is_string(monkeypatch):
    monkeypatch.delenv("KIRA_NO_OUTBOUND", raising=False)
    monkeypatch.setenv("BLUESKY_HANDLE", "beispiel.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "falsch")

    class FakeResp:
        status_code = 401
        text = "AuthFactorTokenRequired"

        def json(self):
            return {}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())
    out = bluesky.post("Hallo")
    assert "Bluesky-Login fehlgeschlagen (401)" in out


def test_bluesky_empty_text(monkeypatch):
    monkeypatch.delenv("KIRA_NO_OUTBOUND", raising=False)
    monkeypatch.setenv("BLUESKY_HANDLE", "h")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "p")
    assert "Leerer Post" in bluesky.post("   ")


# ---------- publish-Gate + Freigabe-Re-Dispatch ----------

def test_bluesky_post_tool_waits_for_approval(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    posted = []
    monkeypatch.setattr(bluesky, "post", lambda t: posted.append(t) or "ok")

    out = social_tools.bluesky_post("Kira ist live! #ai")
    assert "Wartet auf Partners Freigabe" in out
    assert posted == []  # NICHT gepostet
    pend = approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "publish"
    payload = json.loads(pend[0]["detail"])
    assert payload["platform"] == "bluesky"
    assert payload["text"] == "Kira ist live! #ai"


def test_decide_publish_executes_post(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    posted = []
    monkeypatch.setattr(bluesky, "post", lambda t: posted.append(t) or "Gepostet auf Bluesky (17 Zeichen). at://x")

    social_tools.bluesky_post("Kira ist live! #ai")
    aid = approvals.pending()[0]["id"]
    res = approvals.decide(aid, approved=True, note="GO")
    assert res["ok"] and res["status"] == "approved"
    assert res["applied"]["posted"] is True
    assert posted == ["Kira ist live! #ai"]  # GO hat wirklich gesendet


def test_decide_publish_reject_posts_nothing(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    posted = []
    monkeypatch.setattr(bluesky, "post", lambda t: posted.append(t) or "ok")

    social_tools.bluesky_post("Entwurf")
    aid = approvals.pending()[0]["id"]
    res = approvals.decide(aid, approved=False, note="nein")
    assert res["ok"] and res["status"] == "rejected"
    assert posted == [] and res["applied"] is None


def test_bluesky_tool_dry_run_behind_firewall(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    out = social_tools.bluesky_post("Test")
    assert "[TESTMODUS]" in out
    assert approvals.pending() == []  # nicht mal ein Inbox-Eintrag


def test_hard_gate_default_contains_publish():
    assert "publish" in autonomy._DEFAULT["hard_gate"]


def test_publish_needs_approval_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(autonomy, "_PATH", tmp_path / "keine-datei.json")
    assert autonomy.needs_approval("publish")
    assert autonomy.needs_approval("email_stranger")
    assert not autonomy.needs_approval("generic")


def test_suggested_secrets_include_mail_and_bluesky():
    from core.api import server
    s = server.api_secrets()
    for key in ("SMTP_USER", "SMTP_PASS", "BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"):
        assert key in s["suggested"]
