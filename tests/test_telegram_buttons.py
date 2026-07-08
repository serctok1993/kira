"""Telegram Inline-Buttons: Freigaben per ✅/❌-Knopf entscheiden.

/freigaben listet offene Freigaben als Karten mit Knoepfen; ein Klick entscheidet sie
(ueber die bestehende, idempotente approvals.decide) und aktualisiert die Nachricht.
"""
from __future__ import annotations


class _Cap:
    """Fake-HTTP-Client, der die POSTs mitschreibt."""
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, **k):
        self.posts.append((url, json))

        class R:
            def json(self_):
                return {"ok": True}
        return R()


def test_send_approval_card_baut_buttons(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    tb._send_approval_card(None, 5, {"id": "abc123", "title": "Mail senden",
                                     "detail": "an Firma X", "kind": "external"})
    assert cap.posts and "sendMessage" in cap.posts[0][0]
    payload = cap.posts[0][1]
    row = payload["reply_markup"]["inline_keyboard"][0]
    datas = [b["callback_data"] for b in row]
    assert "appr:ok:abc123" in datas and "appr:no:abc123" in datas
    assert "Mail senden" in payload["text"]


def test_callback_entscheidet_und_editiert(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    decided = {}
    monkeypatch.setattr(approvals, "decide",
                        lambda aid, ok, note=None: (decided.update(aid=aid, ok=ok), {"ok": True})[1])
    monkeypatch.setattr(approvals, "get",
                        lambda aid: {"id": aid, "title": "Mail senden", "kind": "email_stranger"})
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    cq = {"id": "cq1", "data": "appr:ok:deadbeef", "message": {"chat": {"id": 9}, "message_id": 42}}
    tb._handle_callback(None, cq)
    assert decided == {"aid": "deadbeef", "ok": True}
    urls = [u for u, _ in cap.posts]
    assert any("answerCallbackQuery" in u for u in urls)
    edit = [j for u, j in cap.posts if "editMessageText" in u]
    assert edit and "Freigegeben" in edit[0]["text"]
    assert "reply_markup" not in edit[0]        # Knoepfe verschwinden


def test_callback_ablehnen(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    got = {}
    monkeypatch.setattr(approvals, "decide", lambda aid, ok, note=None: (got.update(ok=ok), {"ok": True})[1])
    monkeypatch.setattr(approvals, "get", lambda aid: {"id": aid, "title": "X", "kind": "publish"})
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    tb._handle_callback(None, {"id": "c", "data": "appr:no:abcdef", "message": {"chat": {"id": 1}, "message_id": 2}})
    assert got == {"ok": False}                 # 'no' -> approved=False
    edit = [j for u, j in cap.posts if "editMessageText" in u][0]
    assert "Abgelehnt" in edit["text"]


def test_callback_info_eintrag_sagt_gelesen(monkeypatch):
    """Info-Eintraege (generic) werden nach dem Klick als 'Gelesen', nicht 'Freigegeben' markiert."""
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    monkeypatch.setattr(approvals, "decide", lambda aid, ok, note=None: {"ok": True})
    monkeypatch.setattr(approvals, "get", lambda aid: {"id": aid, "title": "Report", "kind": "generic"})
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    tb._handle_callback(None, {"id": "c", "data": "appr:ok:beef01", "message": {"chat": {"id": 1}, "message_id": 2}})
    edit = [j for u, j in cap.posts if "editMessageText" in u][0]
    assert "Gelesen" in edit["text"] and "Freigegeben" not in edit["text"]
    assert edit["text"].startswith("📋")


def test_callback_ignoriert_fremde_daten(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    monkeypatch.setattr(approvals, "decide",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("darf nicht entscheiden")))
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    tb._handle_callback(None, {"id": "cq", "data": "irgendwas:anderes", "message": {}})
    assert [u for u, _ in cap.posts] == [f"{tb.API}/answerCallbackQuery"]  # nur Raedchen stoppen


def test_dispatch_routet_callback(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    called = {}
    monkeypatch.setattr(tb, "_handle_callback", lambda client, cq: called.update(cq=cq))
    tb._dispatch(None, {"callback_query": {"id": "x", "data": "appr:ok:abc"}})
    assert called.get("cq", {}).get("id") == "x"


def test_freigaben_befehl_listet(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    monkeypatch.setattr(approvals, "pending", lambda: [{"id": "a1", "title": "X"}, {"id": "a2", "title": "Y"}])
    sent, cards = [], []
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append(txt))
    monkeypatch.setattr(tb, "_send_approval_card", lambda c, ch, appr: cards.append(appr["id"]))
    tb._handle_command(object(), 7, "/freigaben")
    assert any("2 offene" in s for s in sent)
    assert cards == ["a1", "a2"]


def test_freigaben_leer(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    monkeypatch.setattr(approvals, "pending", lambda: [])
    sent = []
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append(txt))
    tb._handle_command(object(), 7, "/freigaben")
    assert any("Keine offenen" in s for s in sent)
