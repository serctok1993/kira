"""Phase 3 "Kommunikation": Mail-Threading (reply), email_reply-Gate + deterministisches
Nachziehen, verbessertes email_check, Bluesky-Stats — offline, Transport gefakt."""
from __future__ import annotations

import json

from email.message import EmailMessage

from core.agency import approvals
from core.agency.connectors import bluesky, mail
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


# ---------- Threading-Bausteine (pur, offline) ------------------------------------------

def test_reply_subject_idempotent():
    assert mail.reply_subject("Angebot") == "Re: Angebot"
    assert mail.reply_subject("Re: Angebot") == "Re: Angebot"      # nie 'Re: Re:'
    assert mail.reply_subject("RE: Angebot") == "RE: Angebot"
    assert mail.reply_subject("re: angebot") == "re: angebot"


def test_thread_headers_normalisieren_spitzklammern():
    assert mail._thread_headers("") == {}
    for roh in ("abc@mail.example", "<abc@mail.example>"):
        h = mail._thread_headers(roh)
        assert h == {"In-Reply-To": "<abc@mail.example>", "References": "<abc@mail.example>"}


def test_build_message_traegt_threading_header():
    msg = mail.build_message("kira@example.de", "max@firma.de", "Re: Hi", "Text",
                             {"In-Reply-To": "<a@b>", "References": "<a@b>"})
    assert msg["In-Reply-To"] == "<a@b>" and msg["References"] == "<a@b>"
    assert msg["Subject"] == "Re: Hi" and msg["To"] == "max@firma.de"


def test_reply_setzt_re_und_header(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(mail, "send",
                        lambda to, s, b, headers=None: captured.update(
                            {"to": to, "subject": s, "headers": headers}) or "ok")
    assert mail.reply("max@firma.de", "Angebot", "Hallo", in_reply_to="m1@firma.de") == "ok"
    assert captured["subject"] == "Re: Angebot"
    assert captured["headers"]["In-Reply-To"] == "<m1@firma.de>"
    # ohne message_id: normale Mail mit Re:-Betreff, keine Threading-Header
    mail.reply("max@firma.de", "Angebot", "Hallo")
    assert captured["headers"] == {}


def test_parse_message_liefert_message_id_und_to():
    msg = EmailMessage()
    msg["From"] = "Max <max@firma.de>"
    msg["To"] = "kira@example.de"
    msg["Subject"] = "Angebot"
    msg["Date"] = "Fri, 10 Jul 2026 10:00:00 +0200"
    msg["Message-ID"] = "<m1@firma.de>"
    msg.set_content("Hallo Kira")
    out = mail._parse_message(bytes(msg))
    assert out["message_id"] == "<m1@firma.de>"
    assert out["to"] == "kira@example.de"


# ---------- email_check: nummerierte Liste + Lehr-Beispiel -------------------------------

def test_email_check_nummeriert_mit_reply_beispiel(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(mail, "check", lambda n=10: [
        {"from": "Max <max@firma.de>", "to": "kira@example.de", "subject": "Angebot",
         "date": "Fri, 10 Jul 2026", "snippet": "Hallo Kira", "message_id": "<m1@firma.de>"}])
    out = mail_tools.email_check()
    assert out.startswith("1)")
    assert "message_id: <m1@firma.de>" in out
    assert "ACT email_reply" in out                       # Lehr-Beispiel als Schlusszeile


# ---------- email_reply: Gate + deterministisches Nachziehen -----------------------------

def test_email_reply_fremd_stoppt_am_gate(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(mail, "reply", lambda *a, **k: sent.append(a) or "gesendet")
    out = mail_tools.email_reply(an="fremd@firma.de", betreff="Angebot",
                                 text="Hallo ...", message_id="<m1@firma.de>")
    assert "Freigabe" in out and sent == []               # NICHT gesendet
    pend = approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "email_stranger"
    detail = json.loads(pend[0]["detail"])
    assert detail["in_reply_to"] == "<m1@firma.de>"       # Threading ueberlebt das Gate


def test_email_reply_freigabe_zieht_reply_nach(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    mail_tools.email_reply(an="fremd@firma.de", betreff="Angebot",
                           text="Hallo ...", message_id="m1@firma.de")
    aid = approvals.pending()[0]["id"]
    captured = {}
    monkeypatch.setattr(mail, "reply",
                        lambda to, s, b, in_reply_to="": captured.update(
                            {"to": to, "mid": in_reply_to}) or "gesendet")
    res = approvals.decide(aid, True)
    assert res["ok"] and res["applied"]["email_sent"] is True
    assert captured["to"] == "fremd@firma.de" and captured["mid"] == "m1@firma.de"


def test_email_reply_eigene_adresse_laeuft_frei(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(mail, "reply", lambda *a, **k: "gesendet")
    out = mail_tools.email_reply(an="nutzer@example.com", betreff="Hi", text="Hallo")
    assert out == "gesendet"
    assert approvals.pending() == []


def test_email_reply_lehrt_bei_fehlenden_args():
    assert "ACT email_reply" in mail_tools.email_reply(an="", text="")


# ---------- Standup-Post-Hinweis ----------------------------------------------------------

def test_mail_block_still_und_aktiv(monkeypatch, tmp_path):
    from core.agency.missions import standup

    _setup(monkeypatch, tmp_path, {"enabled": False})
    assert standup._mail_block() == ""                    # Postfach aus -> still
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(mail, "unread_count", lambda max_age=120.0: 3)
    out = standup._mail_block()
    assert "3 ungelesene" in out and "email_reply" in out
    monkeypatch.setattr(mail, "unread_count", lambda max_age=120.0: 0)
    assert standup._mail_block() == ""                    # nichts Neues -> kein Rauschen


# ---------- /api/mails --------------------------------------------------------------------

def test_api_mails_hint_ohne_postfach(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import core.api.server as s

    _setup(monkeypatch, tmp_path, {"enabled": False})
    d = TestClient(s.app).get("/api/mails").json()
    assert d["mails"] == [] and "hint" in d


# ---------- Bluesky-Stats (oeffentliche API, gemockt) -------------------------------------

def test_bluesky_profile_stats_gemockt(monkeypatch):
    import httpx

    monkeypatch.setenv("BLUESKY_HANDLE", "beispiel.bsky.social")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"followersCount": 42, "followsCount": 7, "postsCount": 3}

    monkeypatch.setattr(httpx, "get", lambda url, params=None, timeout=None: _Resp())
    assert bluesky.profile_stats() == {"followers": 42, "follows": 7, "posts": 3}


def test_bluesky_stats_ohne_handle_still(monkeypatch):
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    assert bluesky.profile_stats() == {}


# ---------- Manifest ----------------------------------------------------------------------

def test_email_reply_im_manifest():
    import core.agency.tools.builtin  # noqa: F401

    from core.agency.tools import registry

    assert registry.get("email_reply") is not None
    assert "- email_reply (" in registry.manifest()
    schema = next(s for s in registry.tool_schemas()
                  if s["function"]["name"] == "email_reply")
    # message_id ist optional (Registry-Konvention), an/betreff/text sind Pflicht
    assert set(schema["function"]["parameters"]["required"]) == {"an", "betreff", "text"}
