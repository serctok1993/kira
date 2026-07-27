"""Telegram-Werkbank: ehrliche Freigabe-Karten (Aktion/Anfrage/Info), /tagewerk,
/kalibrierung, Steuerpult — alles offline, reine Renderer."""
from __future__ import annotations

from core.agency.connectors import telegram_bot as tb


# ---------- Karten-Taxonomie: der Knopf sagt, was er WIRKLICH tut ----------

def test_karte_aktion_email():
    text, kb = tb._approval_card({"id": "a1", "kind": "email_stranger",
                                  "title": "E-Mail an x@firma.de", "detail": "{}"})
    assert "🔔" in text and "SOFORT" in text
    row = kb["inline_keyboard"][0]
    assert row[0]["text"] == "✅ Senden" and row[0]["callback_data"] == "appr:ok:a1"
    assert row[1]["text"] == "❌ Nicht senden" and row[1]["callback_data"] == "appr:no:a1"


def test_karte_aktion_publish():
    text, kb = tb._approval_card({"id": "b2", "kind": "publish", "title": "Bluesky-Post"})
    assert "postet SOFORT" in text
    assert kb["inline_keyboard"][0][0]["text"] == "✅ Posten"


def test_karte_anfrage_money_sagt_kein_geld():
    text, kb = tb._approval_card({"id": "c3", "kind": "money", "title": "Domain kaufen"})
    assert "💶" in text and "KEIN Geld" in text
    assert kb["inline_keyboard"][0][0]["text"] == "✅ Erlauben"


def test_karte_info_generic():
    """Praxis-Fund: Report/Steckt-fest sind KEINE Freigaben — Karte sagt das jetzt."""
    text, kb = tb._approval_card({"id": "d4", "kind": "generic",
                                  "title": "Selbstkalibrierungs-Report (7 Tage)"})
    assert "📋" in text and "Zur Kenntnis" in text
    assert "aendert nichts automatisch" in text
    row = kb["inline_keyboard"][0]
    assert row[0]["text"] == "✔ Gelesen" and row[1]["text"] == "🗑 Verwerfen"
    assert "Freigabe noetig" not in text


def test_karte_detail_wird_gekappt_und_escaped():
    text, _ = tb._approval_card({"id": "e5", "kind": "generic", "title": "T",
                                 "detail": "<script>" + "x" * 700})
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert len(text) < 800


# ---------- _tg_html: Whitelist-Tags bleiben, Rest wird escaped ----------

def test_tg_html_whitelist_und_escape():
    out = tb._tg_html("💜 <b>Denken an</b> — <code>/denken aus</code> & 1<2 <script>böse</script>")
    assert "<b>Denken an</b>" in out and "<code>/denken aus</code>" in out
    assert "&lt;script&gt;" in out and "&amp;" in out
    assert tb._tg_html("**fett** und `code`") == "<b>fett</b> und <code>code</code>"


# ---------- /tagewerk + /kalibrierung Renderer ----------

def test_tagewerk_text(monkeypatch):
    from core.agency import tagewerk
    monkeypatch.setattr(tagewerk, "heute", lambda: {
        "tasks": {"done": 3, "failed": 1, "avg_score": 82.0},
        "mails": {"anzahl": 2, "an": ["kunde@x.de", "b@y.de"]},
        "skills": {"anzahl": 1, "namen": ["Impressum"]},
        "crons": {"anzahl": 4, "labels": ["Briefing"]},
        "selbstverbesserung": {"ticks": 2, "code_edits": ["core/x.py"]},
        "diagnose": {"ok": True}, "lektionen": 1,
        "freigaben_offen": 2, "kosten_heute_usd": 0.42})
    t = tb._tagewerk_text()
    # "Tasks" war Denglisch, "Ø 82.0" eine interne Pruefernote ohne Skala (Fund 27.07.).
    assert "Mein Tag" in t and "3 Aufgaben erledigt" in t and "1 nicht geschafft" in t
    assert "Ø" not in t
    assert "kunde@x.de" in t and "Impressum" in t and "Briefing" in t
    assert "2 Freigaben warten" in t and "0.42 $" in t


def test_tagewerk_text_faellt_weich(monkeypatch):
    from core.agency import tagewerk
    monkeypatch.setattr(tagewerk, "heute", lambda: (_ for _ in ()).throw(RuntimeError("db weg")))
    assert "nicht abrufbar" in tb._tagewerk_text()


def test_kalibrierung_text(monkeypatch):
    from core.agency import calibration
    monkeypatch.setattr(calibration, "render", lambda days=7: "SELBSTKALIBRIERUNG (Test)")
    t = tb._kalibrierung_text()
    assert "Selbstkalibrierung" in t and "SELBSTKALIBRIERUNG (Test)" in t


# ---------- Menue + Panel ----------

def test_botmenu_hat_neue_befehle():
    cmds = [c for c, _ in tb._BOT_COMMANDS]
    assert "tagewerk" in cmds and "kalibrierung" in cmds
    assert cmds.index("status") < cmds.index("tagewerk")  # Überblick zuerst


def test_panel_hat_tagewerk_knopf():
    kb = tb._panel_markup()["inline_keyboard"]
    flat = [b["callback_data"] for row in kb for b in row]
    assert "ctl:tagewerk" in flat and "ctl:freigaben" in flat
