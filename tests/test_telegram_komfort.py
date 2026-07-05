"""Telegram-Komfort: Push-Freigaben (proaktiv) + Steuerpult mit Knoepfen.

Push: neue Freigaben landen von selbst als ✅/❌-Karte im erlaubten Chat (kein /freigaben noetig).
Steuerpult: /steuer zeigt Status + Knoepfe (Heartbeat schalten, Aufgaben, Freigaben).
"""
from __future__ import annotations


class _Cap:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, **k):
        self.posts.append((url, json))

        class R:
            def json(self_):
                return {"ok": True}
        return R()


def _set_allowed(monkeypatch, chat_id):
    from core.config import CONFIG
    tel = dict(CONFIG.get("channels", {}).get("telegram", {}))
    tel["allowed_chat_id"] = chat_id
    ch = dict(CONFIG.get("channels", {}))
    ch["telegram"] = tel
    monkeypatch.setitem(CONFIG, "channels", ch)


# ---- Push-Freigaben --------------------------------------------------------------------

def test_push_schickt_nur_neue(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    _set_allowed(monkeypatch, 42)
    sent = []
    monkeypatch.setattr(tb, "_send_approval_card", lambda c, chat, appr: sent.append((chat, appr["id"])))
    tb._pushed_approvals.clear()
    monkeypatch.setattr(approvals, "pending", lambda: [{"id": "n1", "title": "A"}, {"id": "n2", "title": "B"}])

    tb._push_new_approvals(None)
    assert sent == [(42, "n1"), (42, "n2")]          # beide neu -> beide gepusht
    tb._push_new_approvals(None)
    assert sent == [(42, "n1"), (42, "n2")]          # zweite Runde: nichts Neues -> nichts nochmal
    tb._pushed_approvals.clear()


def test_push_ohne_chat_still(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    _set_allowed(monkeypatch, "")
    monkeypatch.setattr(approvals, "pending",
                        lambda: (_ for _ in ()).throw(AssertionError("nicht abfragen ohne Chat")))
    tb._push_new_approvals(None)                      # kein allowed_chat_id -> gar nichts


def test_push_deckelt_auf_fuenf(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    _set_allowed(monkeypatch, 7)
    sent = []
    monkeypatch.setattr(tb, "_send_approval_card", lambda c, chat, appr: sent.append(appr["id"]))
    tb._pushed_approvals.clear()
    monkeypatch.setattr(approvals, "pending", lambda: [{"id": f"x{i}", "title": "t"} for i in range(9)])
    tb._push_new_approvals(None)
    assert len(sent) == 5                             # max 5 pro Runde
    tb._push_new_approvals(None)
    assert len(sent) == 9                             # Rest in der naechsten Runde
    tb._pushed_approvals.clear()


def test_seed_markiert_bestehende(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    from core.agency import approvals
    tb._pushed_approvals.clear()
    monkeypatch.setattr(approvals, "init_approvals", lambda: None)
    monkeypatch.setattr(approvals, "pending", lambda: [{"id": "old1"}, {"id": "old2"}])
    tb._seed_pushed_approvals()
    assert tb._pushed_approvals == {"old1", "old2"}   # bestehende gelten als bekannt (kein Alt-Spam)
    tb._pushed_approvals.clear()


# ---- Steuerpult ------------------------------------------------------------------------

def test_panel_markup_spiegelt_heartbeat(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    import core.kernel.scheduler as sch
    monkeypatch.setattr(sch, "heartbeat_on", lambda: True)
    kb = tb._panel_markup()["inline_keyboard"]
    assert kb[0][0]["callback_data"] == "ctl:hb:off"   # laeuft -> Knopf bietet AUS
    monkeypatch.setattr(sch, "heartbeat_on", lambda: False)
    assert tb._panel_markup()["inline_keyboard"][0][0]["callback_data"] == "ctl:hb:on"


def test_steuer_befehl_sendet_panel(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    tb._handle_command(object(), 9, "/steuer")
    assert cap.posts and "sendMessage" in cap.posts[0][0]
    assert "Steuerpult" in cap.posts[0][1]["text"]
    assert "inline_keyboard" in cap.posts[0][1]["reply_markup"]


def test_ctl_heartbeat_schaltet_und_rendert(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    import core.kernel.scheduler as sch
    flipped = {}
    monkeypatch.setattr(sch, "set_heartbeat", lambda on: flipped.update(on=on))
    monkeypatch.setattr(sch, "heartbeat_on", lambda: True)
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    cq = {"id": "c", "data": "ctl:hb:on", "message": {"chat": {"id": 3}, "message_id": 8}}
    tb._handle_callback(None, cq)
    assert flipped == {"on": True}
    urls = [u for u, _ in cap.posts]
    assert any("answerCallbackQuery" in u for u in urls)
    assert any("editMessageText" in u for u in urls)   # Panel neu gerendert


def test_ctl_tasks_zeigt_aufgaben(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    monkeypatch.setattr(tb, "_tasks_text", lambda: "📋 Offene Aufgaben\n• test")
    sent = []
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append(txt))
    monkeypatch.setattr(tb, "_answer_cb", lambda *a, **k: None)
    tb._handle_callback(None, {"id": "c", "data": "ctl:tasks", "message": {"chat": {"id": 3}, "message_id": 8}})
    assert sent and "Offene Aufgaben" in sent[0]
