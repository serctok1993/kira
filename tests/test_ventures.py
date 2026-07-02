"""S3.1: Ventures + Konto-Buch — offline, Temp-DB, deterministisch."""
from __future__ import annotations

import sqlite3

from core.agency import ventures
from core.agency.missions import objectives
from core.governance import treasury
from core.kernel import events


def _use_tmp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (ventures, objectives, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    return db


def test_init_idempotent(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    ventures.init_ventures()
    ventures.init_ventures()


def test_add_get_update_list(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    vid = ventures.add("QS-SEO", hypothesis="Transportfirmen zahlen fuer Sichtbarkeit", milestone_eur=500)
    v = ventures.get(vid)
    assert v["name"] == "QS-SEO" and v["status"] == "idea" and v["milestone_eur"] == 500

    assert ventures.update(vid, status="live", notes="gestartet")
    assert ventures.get(vid)["status"] == "live"
    assert not ventures.update(vid, id="hack")  # nicht erlaubtes Feld
    ventures.update(vid, status="quatsch")      # ungueltiger Status wird verworfen
    assert ventures.get(vid)["status"] == "live"

    dead = ventures.add("Tot", status="dead")
    assert dead not in [v["id"] for v in ventures.list_all()]
    assert dead in [v["id"] for v in ventures.list_all(include_dead=True)]


def test_book_balance_and_dedupe(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    vid = ventures.add("Shop")
    ventures.book(vid, "in", 100.0, note="Erste Zahlung", ref="stripe_ch_1")
    ventures.book(vid, "out", 30.0, note="Domain")
    assert ventures.balance(vid) == 70.0

    # Dedupe: gleiche externe Referenz wird still verworfen (Sync-Idempotenz)
    assert ventures.book(vid, "in", 100.0, ref="stripe_ch_1") == ""
    assert ventures.balance(vid) == 70.0
    # aber: beliebig viele manuelle Buchungen ohne ref
    ventures.book(vid, "out", 10.0)
    ventures.book(vid, "out", 10.0)
    assert ventures.balance(vid) == 50.0

    rows = ventures.ledger(vid)
    assert len(rows) == 4

    try:
        ventures.book(vid, "sideways", 5.0)
        raise AssertionError("direction-Validierung fehlt")
    except ValueError:
        pass


def test_summary_milestone_progress(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    vid = ventures.add("SaaS", milestone_eur=200)
    ventures.book(vid, "in", 50.0)
    ventures.book(vid, "out", 20.0)
    ohne = ventures.add("Ohne Meilenstein")

    s = {v["id"]: v for v in ventures.summary()}
    assert s[vid]["income_eur"] == 50.0 and s[vid]["expenses_eur"] == 20.0
    assert s[vid]["balance_eur"] == 30.0
    assert s[vid]["milestone_progress"] == 25  # 50 von 200 (Fortschritt = Einnahmen, nicht Kasse)
    assert s[ohne]["milestone_progress"] is None


def test_no_double_counting_with_treasury(monkeypatch, tmp_path):
    """DER Geld-Wahrheits-Test: eine Ausgabe = 1 spend-Event (Budget) + 1 Ledger-Zeile (Venture)."""
    _use_tmp_db(monkeypatch, tmp_path)
    vid = ventures.add("Testbein")

    treasury.record_spend(5.0, "Domain gekauft", category="venture", venture_id=vid)

    spends = [e for e in events.recent(50) if e["type"] == "spend"]
    books = [e for e in events.recent(50) if e["type"] == "venture_book"]
    assert len(spends) == 1 and spends[0]["payload"]["venture_id"] == vid
    assert len(books) == 1
    assert len(ventures.ledger(vid)) == 1
    assert ventures.balance(vid) == -5.0
    assert treasury.today_spend() == 5.0  # NUR das spend-Event zaehlt, nicht venture_book

    # record_spend ohne venture_id: kein Ledger-Eintrag, Budget trotzdem belastet
    treasury.record_spend(2.0, "API-Guthaben")
    assert treasury.today_spend() == 7.0
    assert len(ventures.ledger(vid)) == 1


def test_objectives_venture_link_and_migration(monkeypatch, tmp_path):
    db = _use_tmp_db(monkeypatch, tmp_path)
    # Alt-Schema OHNE venture_id anlegen -> init ruestet nach
    with sqlite3.connect(db) as c:
        c.execute(
            """
            CREATE TABLE objectives (
                id TEXT PRIMARY KEY, ts REAL NOT NULL, kind TEXT DEFAULT 'weekly',
                title TEXT NOT NULL, parent_id TEXT, status TEXT DEFAULT 'active',
                progress INTEGER, target_date TEXT, notes TEXT, updated_ts REAL
            )
            """
        )
    objectives.init_objectives()
    vid = ventures.add("Standbein")
    oid = objectives.add("Landingpage live", venture_id=vid)
    objs = {o["id"]: o for o in objectives.list_all()}
    assert objs[oid]["venture_id"] == vid
    assert objectives.update(oid, venture_id=None)
