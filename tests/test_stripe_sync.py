"""S3.6: Stripe-Einnahmen-Sync — offline, HTTP gefakt, Dedupe + Zuordnung."""
from __future__ import annotations

from core.agency import ventures
from core.agency.connectors import stripe_sync
from core.kernel import events


def _setup(monkeypatch, tmp_path, charges):
    db = str(tmp_path / "state.db")
    for mod in (ventures, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "rk_test_123")
    monkeypatch.setattr(stripe_sync, "_fetch_charges", lambda limit=50: charges)


def _charge(cid, amount_cents, status="succeeded", paid=True, venture_id=None, refunded=False):
    return {"id": cid, "amount": amount_cents, "status": status, "paid": paid,
            "refunded": refunded, "description": f"Zahlung {cid}",
            "metadata": ({"venture_id": venture_id} if venture_id else {})}


def test_sync_books_and_maps(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [])
    vid = ventures.add("Shop", status="live")
    charges = [
        _charge("ch_1", 4900, venture_id=vid),          # zugeordnet
        _charge("ch_2", 1500),                          # ohne Zuordnung -> Sammel-Venture
        _charge("ch_3", 900, status="failed"),          # nicht erfolgreich -> ignorieren
        _charge("ch_4", 2000, refunded=True),           # erstattet -> ignorieren
        _charge("ch_5", 1000, venture_id="gibtsnicht"),  # kaputte Zuordnung -> Sammel-Venture
    ]
    monkeypatch.setattr(stripe_sync, "_fetch_charges", lambda limit=50: charges)

    res = stripe_sync.sync()
    assert res["booked"] == 3 and res["total_eur"] == 74.0  # 49 + 15 + 10

    assert ventures.balance(vid) == 49.0
    fallback = next(v for v in ventures.list_all() if v["name"] == "Unzugeordnet")
    assert ventures.balance(fallback["id"]) == 25.0
    assert any(e["type"] == "stripe_income" for e in events.recent(10))


def test_sync_is_idempotent(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [_charge("ch_x", 5000)])
    assert stripe_sync.sync()["booked"] == 1
    # Zweiter Lauf mit denselben Charges: ref-Dedupe -> nichts doppelt
    res = stripe_sync.sync()
    assert res["booked"] == 0
    fallback = next(v for v in ventures.list_all() if v["name"] == "Unzugeordnet")
    assert ventures.balance(fallback["id"]) == 50.0


def test_fallback_venture_created_once(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [_charge("a", 100), _charge("b", 200)])
    stripe_sync.sync()
    names = [v["name"] for v in ventures.list_all()]
    assert names.count("Unzugeordnet") == 1


def test_missing_key_returns_hint(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    res = stripe_sync.sync()
    assert res["booked"] == 0 and "request_secret" in res["note"]


def test_fetch_error_is_soft(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [])

    def boom(limit=50):
        raise RuntimeError("API down")

    monkeypatch.setattr(stripe_sync, "_fetch_charges", boom)
    res = stripe_sync.sync()
    assert res["booked"] == 0 and "API down" in res["error"]
    assert any(e["type"] == "stripe_sync_error" for e in events.recent(10))
