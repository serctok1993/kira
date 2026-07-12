"""Telegram-Werkbank 2: /fokus, todo-Schnellzugriff mit Abhak-Knoepfen, Abend-Resuemee.
Alles offline — Queue/Fokus auf tmp, Telegram-Client gefakt."""
from __future__ import annotations

import time

from core.agency import fokus
from core.agency.connectors import telegram_bot as tb
from core.kernel import events


class _Cap:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, **k):
        self.posts.append((url, json))

        class R:
            def json(self_):
                return {"ok": True, "result": {"message_id": 1}}
        return R()


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setattr(fokus, "_PATH", tmp_path / "focus.json")


# ---------- Fokus: ein Speicher, zwei Bedienwege ----------

def test_fokus_setzen_lesen_loeschen(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    cleared = []
    from core.agency.missions import queue
    monkeypatch.setattr(queue, "init_queue", lambda: None)
    monkeypatch.setattr(queue, "clear", lambda mission: cleared.append(mission))

    assert fokus.set_focus("MESSE-Leads", via="telegram") == "MESSE-Leads"
    assert fokus.get()["focus"] == "MESSE-Leads"
    assert cleared  # Queue geleert -> naechster Tick plant um den Fokus herum
    assert any(e["type"] == "focus_set" and e["payload"]["via"] == "telegram"
               for e in events.recent(5))
    fokus.set_focus("")
    assert fokus.get()["focus"] == ""


def test_fokus_befehl(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    from core.agency.missions import queue
    monkeypatch.setattr(queue, "init_queue", lambda: None)
    monkeypatch.setattr(queue, "clear", lambda mission: None)
    sent = []
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append(txt))

    tb._handle_command(object(), 7, "/fokus MESSE-Landingpage fertig machen")
    assert "Fokus gesetzt" in sent[-1]
    assert fokus.get()["focus"] == "MESSE-Landingpage fertig machen"
    tb._handle_command(object(), 7, "/fokus")
    assert "MESSE-Landingpage" in sent[-1]
    tb._handle_command(object(), 7, "/fokus -")
    assert "geloescht" in sent[-1] and fokus.get()["focus"] == ""


def test_api_direktive_nutzt_fokus_modul(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient
    import core.api.server as s
    from core.agency.missions import queue
    monkeypatch.setattr(queue, "init_queue", lambda: None)
    monkeypatch.setattr(queue, "clear", lambda mission: None)
    cl = TestClient(s.app)
    r = cl.post("/api/direktive", json={"focus": "Bewerbung raus"}).json()
    assert r["ok"] and r["focus"] == "Bewerbung raus"
    assert cl.get("/api/direktive").json()["focus"] == "Bewerbung raus"


# ---------- Todos: Schnellzugriff + Abhak-Knoepfe ----------

def _fake_board(monkeypatch, items_today=None, items_week=None):
    from core.agency.missions import queue
    monkeypatch.setattr(queue, "init_queue", lambda: None)
    monkeypatch.setattr(queue, "board", lambda mission: {
        "today": items_today or [], "week": items_week or [], "later": [], "deferred": []})


def test_todo_overview_mit_knoepfen(monkeypatch):
    _fake_board(monkeypatch,
                items_today=[{"id": "aabbccdd1122", "description": "Reifen wechseln", "due_date": "2026-07-08"}],
                items_week=[{"id": "eeff00112233", "description": "Angebot MESSE", "due_date": None}])
    text, kb = tb._todo_overview()
    assert "Reifen wechseln" in text and "HEUTE" in text and "WOCHE" in text
    datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert "todo:done:aabbccdd" in datas and "todo:done:eeff0011" in datas


def test_todo_overview_leer(monkeypatch):
    _fake_board(monkeypatch)
    text, kb = tb._todo_overview()
    assert "Keine offenen Todos" in text and kb is None


def test_todo_fastpath_legt_an(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    from core.agency.tools import life_tools
    added = []
    monkeypatch.setattr(life_tools, "todo_add",
                        lambda text, due="", prio="3": added.append(text) or f"Todo notiert: {text}")
    sent = []
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append(txt))
    monkeypatch.setattr(tb, "_cfg", lambda: {"allowed_chat_id": 7})
    tb._handle(object(), {"message": {"chat": {"id": 7}, "text": "todo: Reifen wechseln"}})
    assert added == ["Reifen wechseln"]
    assert "Todo notiert" in sent[-1]


def test_todo_done_callback_hakt_ab_und_aktualisiert(monkeypatch):
    from core.agency.tools import life_tools
    done = []
    monkeypatch.setattr(life_tools, "todo_done", lambda tid: done.append(tid) or "Abgehakt ✔")
    _fake_board(monkeypatch)  # danach leer
    cap = _Cap()
    monkeypatch.setattr(tb, "_ctrl", lambda: cap)
    tb._handle_callback(None, {"id": "cq", "data": "todo:done:aabbccdd",
                               "message": {"chat": {"id": 7}, "message_id": 5}})
    assert done == ["aabbccdd"]
    edits = [j for u, j in cap.posts if "editMessageText" in u]
    assert edits and "Keine offenen Todos" in edits[0]["text"]


# ---------- Abend-Resuemee ----------

def test_resuemee_due_logik(monkeypatch, tmp_path):
    monkeypatch.setattr(tb, "_RESUEMEE_FILE", tmp_path / "resuemee.json")
    monkeypatch.setattr(tb, "_cfg", lambda: {"tagewerk_zeit": "21:30"})
    frueh = time.struct_time((2026, 7, 8, 20, 59, 0, 2, 189, 1))
    spaet = time.struct_time((2026, 7, 8, 21, 31, 0, 2, 189, 1))
    assert not tb._resuemee_due(frueh)          # noch nicht so weit
    assert tb._resuemee_due(spaet)              # faellig, noch nicht gesendet
    import json
    (tmp_path / "resuemee.json").write_text(json.dumps({"date": time.strftime("%Y-%m-%d", spaet)}))
    assert not tb._resuemee_due(spaet)          # heute schon gesendet
    monkeypatch.setattr(tb, "_cfg", lambda: {"tagewerk_zeit": ""})
    assert not tb._resuemee_due(spaet)          # abgeschaltet


def test_resuemee_sendet_einmal(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(tb, "_RESUEMEE_FILE", tmp_path / "resuemee.json")
    monkeypatch.setattr(tb, "_cfg", lambda: {"allowed_chat_id": 7, "tagewerk_zeit": "00:00"})
    monkeypatch.setattr(tb, "_tagewerk_text", lambda: "Tagewerk-Stub")
    sent = []
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append((ch, txt)))
    tb._maybe_evening_resuemee(object())
    tb._maybe_evening_resuemee(object())        # zweiter Lauf am selben Tag: still
    assert len(sent) == 1 and sent[0][0] == 7
    assert "Feierabend-Blick" in sent[0][1] and "Tagewerk-Stub" in sent[0][1]


# ---------- Menue ----------

def test_botmenu_hat_todo_und_fokus():
    cmds = [c for c, _ in tb._BOT_COMMANDS]
    assert "todo" in cmds and "fokus" in cmds
