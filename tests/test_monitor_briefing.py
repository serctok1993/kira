"""News-Monitor: still puffern statt spontan pingen; Briefing holt die News (S11.6).

Hintergrund: Der Monitor lief in run_forever mit notify=True hartcodiert und meldete
Neues zur Unzeit als rohen Dump. Neu: er MERKT sich Neues nur (Puffer), spontanes
Pingen haengt am Flag config monitor.spontaneous_notify (Standard aus), und das
Briefing (standup) leert den Puffer und bringt Themen + Links in Kiras Stimme.
"""
from __future__ import annotations


def _feed_watch() -> dict:
    # last_checked gesetzt -> kein first_run, damit Neues als "neu" zaehlt
    return {"id": "w1", "kind": "feed", "value": "http://x", "label": "Testfeed",
            "interval_min": 60, "last_checked": 1.0, "seen": []}


def test_monitor_buffers_silently_when_notify_off(tmp_path, monkeypatch):
    from core.agency.connectors import news_monitor as nm

    monkeypatch.setattr(nm, "WATCHES", tmp_path / "watches.json")
    monkeypatch.setattr(nm, "PENDING", tmp_path / "pending.json")
    nm._save([_feed_watch()])
    monkeypatch.setattr(nm, "_feed_items", lambda url: [
        {"id": "a", "title": "Schlagzeile A", "link": "http://a"},
        {"id": "b", "title": "Schlagzeile B", "link": "http://b"},
    ])
    pinged: list[str] = []
    monkeypatch.setattr(nm, "_notify", lambda text: pinged.append(text))

    res = nm.run_all(force=True, notify=False)

    assert res["checked"] == 1
    assert pinged == []  # KEIN spontanes Telegram-Pingen
    pend = nm._load_pending()
    assert len(pend) == 2
    assert {p["link"] for p in pend} == {"http://a", "http://b"}


def test_monitor_notify_true_still_pings(tmp_path, monkeypatch):
    from core.agency.connectors import news_monitor as nm

    monkeypatch.setattr(nm, "WATCHES", tmp_path / "watches.json")
    monkeypatch.setattr(nm, "PENDING", tmp_path / "pending.json")
    nm._save([_feed_watch()])
    monkeypatch.setattr(nm, "_feed_items", lambda url: [{"id": "a", "title": "A", "link": "http://a"}])
    monkeypatch.setattr(nm, "_summarize", lambda label, new: "- A")
    pinged: list[str] = []
    monkeypatch.setattr(nm, "_notify", lambda text: pinged.append(text))

    nm.run_all(force=True, notify=True)

    assert len(pinged) == 1 and "Testfeed" in pinged[0]


def test_drain_pending_returns_and_clears(tmp_path, monkeypatch):
    from core.agency.connectors import news_monitor as nm

    monkeypatch.setattr(nm, "PENDING", tmp_path / "pending.json")
    nm._add_pending([
        {"label": "Tech", "title": "Neu 1", "link": "http://1", "ts": 1.0},
        {"label": "Tech", "title": "Neu 2", "link": "http://2", "ts": 2.0},
    ])
    nm._add_pending([{"label": "Tech", "title": "Neu 1", "link": "http://1", "ts": 3.0}])  # Dublette

    drained = nm.drain_pending()

    assert len(drained) == 2  # dedupliziert
    assert nm._load_pending() == []  # Puffer geleert


def test_standup_news_block_pulls_and_clears(tmp_path, monkeypatch):
    from core.agency.connectors import news_monitor as nm
    from core.agency.missions import standup

    monkeypatch.setattr(nm, "WATCHES", tmp_path / "watches.json")  # keine watches -> run_all no-op
    monkeypatch.setattr(nm, "PENDING", tmp_path / "pending.json")
    nm._add_pending([{"label": "KI", "title": "Neues Modell X", "link": "http://x", "ts": 1.0}])

    block = standup._news_block()

    assert "NEUES AUS DEINEN THEMEN" in block
    assert "Neues Modell X" in block and "http://x" in block
    assert nm._load_pending() == []  # Briefing hat den Puffer geleert
