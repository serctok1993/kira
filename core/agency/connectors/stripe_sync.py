"""Stripe-Einnahmen-Sync: erfolgreiche Zahlungen -> Venture-Konto-Buch (S3).

Rein LESEND (kein Geld wird bewegt — dafuer ist das money-Gate zustaendig).
Laeuft periodisch im Runner-Loop (maintenance.maybe_run 'stripe_sync').

Zuordnung: Kira setzt beim Anlegen von Produkten/Payment-Links die Stripe-
metadata 'venture_id'; Zahlungen ohne (gueltige) Zuordnung landen im Sammel-
Venture 'Unzugeordnet'. Dedupe ueber venture_ledger.ref (UNIQUE) — derselbe
Charge wird nie doppelt gebucht. Betraege: Stripe liefert Cents; EUR/USD
werden wie im Treasury vereinfachend gleichgesetzt.
"""
from __future__ import annotations

import os

from core.agency import ventures
from core.kernel import events

_FALLBACK_NAME = "Unzugeordnet"


def _fetch_charges(limit: int = 50) -> list[dict]:
    """Juengste Charges von der Stripe-API (modul-global -> in Tests fakebar)."""
    import httpx

    key = os.getenv("STRIPE_SECRET_KEY") or ""
    r = httpx.get("https://api.stripe.com/v1/charges",
                  params={"limit": limit}, auth=(key, ""), timeout=20)
    r.raise_for_status()
    return r.json().get("data", [])


def _fallback_venture() -> str:
    for v in ventures.list_all(include_dead=True):
        if v["name"] == _FALLBACK_NAME:
            return v["id"]
    return ventures.add(_FALLBACK_NAME, status="live",
                        hypothesis="Sammelbecken fuer Stripe-Einnahmen ohne Venture-Zuordnung")


def sync(limit: int = 50) -> dict:
    """Neue erfolgreiche Zahlungen ins Ledger buchen. Idempotent (ref-Dedupe)."""
    if not os.getenv("STRIPE_SECRET_KEY"):
        return {"note": "STRIPE_SECRET_KEY fehlt — request_secret('STRIPE_SECRET_KEY', ...) anfragen.",
                "booked": 0, "total_eur": 0.0}
    try:
        charges = _fetch_charges(limit)
    except Exception as e:  # noqa: BLE001
        events.emit("stripe_sync_error", {"error": str(e)[:300]})
        return {"error": str(e)[:200], "booked": 0, "total_eur": 0.0}

    booked, total = 0, 0.0
    for ch in charges:
        if ch.get("status") != "succeeded" or not ch.get("paid") or ch.get("refunded"):
            continue
        amount = float(ch.get("amount") or 0) / 100.0  # Cents -> EUR
        if amount <= 0:
            continue
        vid = (ch.get("metadata") or {}).get("venture_id") or ""
        if not vid or ventures.get(vid) is None:
            vid = _fallback_venture()
        lid = ventures.book(vid, "in", amount, category="stripe",
                            note=(ch.get("description") or "Stripe-Zahlung")[:200],
                            ref=f"stripe_{ch.get('id')}")
        if lid:  # "" = ref schon gebucht (Dedupe)
            booked += 1
            total += amount

    if booked:
        events.emit("stripe_income", {"booked": booked, "total_eur": round(total, 2)})
    return {"booked": booked, "total_eur": round(total, 2), "checked": len(charges)}
