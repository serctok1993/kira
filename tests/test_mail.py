"""S3.4: Mail-Konnektor + Gate-Regel — offline, kein Netz, Transport gefakt."""
from __future__ import annotations

from email.message import EmailMessage

from core.agency import approvals
from core.agency.connectors import mail
from core.agency.tools import mail_tools
from core.config import CONFIG
from core.governance import autonomy
from core.kernel import events


def _setup(monkeypatch, tmp_path, email_cfg=None):
    db = str(tmp_path / "state.db")
    for mod in (approvals, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(autonomy, "_PATH", tmp_path / "autonomy.json")
    autonomy.set_config(chains_off=True, hard_gate=["money", "email_stranger"])
    events.init_db()
    approvals.init_approvals()
    cfg = {"enabled": True, "provider": "smtp", "from_address": "kira@example.de",
           "own_addresses": ["nutzer@example.com"], "smtp_host": "smtp.example.de",
           "smtp_port": 587, "imap_host": "", "imap_port": 993}
    cfg.update(email_cfg or {})
    monkeypatch.setitem(CONFIG, "channels", {"email": cfg})


def test_is_stranger_matrix(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert not mail.is_stranger("nutzer@example.com")
    assert not mail.is_stranger("NUTZER@EXAMPLE.COM")  # case-insensitive
    assert not mail.is_stranger(" nutzer@example.com ")
    assert mail.is_stranger("fremd@firma.de")
    assert mail.is_stranger("")


def test_provider_selection(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"provider": "auto"})
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert mail.provider() == "smtp"
    monkeypatch.setenv("RESEND_API_KEY", "re_123")
    assert mail.provider() == "resend"
    _setup(monkeypatch, tmp_path, {"provider": "smtp"})  # Config erzwingt trotz Key
    assert mail.provider() == "smtp"


def test_parse_message_multipart_umlauts(monkeypatch, tmp_path):
    msg = EmailMessage()
    msg["From"] = "Müller <m@firma.de>"
    msg["Subject"] = "Größere Anfrage"
    msg["Date"] = "Thu, 02 Jul 2026 10:00:00 +0200"
    msg.set_content("Hallo Kira,\n\ndas ist der Text.\n" + "x" * 600)
    msg.add_alternative("<p>HTML-Teil</p>", subtype="html")

    out = mail._parse_message(bytes(msg))
    assert "Anfrage" in out["subject"] and "firma.de" in out["from"]
    assert out["snippet"].startswith("Hallo Kira, das ist der Text.")
    assert len(out["snippet"]) <= 400  # Truncation
    assert "HTML" not in out["snippet"]  # text/plain bevorzugt


def test_send_missing_credentials_hint(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASS", raising=False)
    out = mail.send("x@y.de", "Test", "Hallo")
    assert "request_secret" in out  # klarer Hinweis statt Exception

    _setup(monkeypatch, tmp_path, {"enabled": False})
    assert "nicht eingerichtet" in mail.send("x@y.de", "Test", "Hallo")


def test_check_without_imap_host(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert "IMAP ist nicht konfiguriert" in mail.check()


def test_email_send_stranger_blocks(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, s, b: sent.append(to) or "gesendet")

    out = mail_tools.email_send("fremd@firma.de", "Angebot", "Hallo...")
    assert "Wartet auf Partners Freigabe" in out
    assert sent == []  # NICHT gesendet
    pend = approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "email_stranger"


def test_email_send_own_address_flows_and_audits(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, s, b: sent.append(to) or "gesendet")

    out = mail_tools.email_send("nutzer@example.com", "Standup", "Heute...")
    assert out == "gesendet"
    assert sent == ["nutzer@example.com"]
    assert approvals.pending() == []
    audits = [e for e in events.recent(20) if e["type"] == "audit"]
    assert len(audits) == 1 and audits[0]["payload"]["target"] == "nutzer@example.com"
