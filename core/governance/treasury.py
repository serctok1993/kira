"""Treasury: Budget-Bewusstsein.

Trackt Ausgaben (LLM-Kosten + protokollierte Aussen-Ausgaben) gegen die Tages- und
Monatslimits aus config.yaml. Quelle ist der Event-Store: `llm_call.cost_usd`
(Cloud-Eskalationen) + `spend`-Events (Geld nach aussen). EUR/USD werden hier
vereinfachend gleichgesetzt — fuer ein privates Setup ausreichend.
"""
from __future__ import annotations

import datetime
import sqlite3

from core.config import CONFIG, DB_PATH
from core.kernel import events


def _budget() -> dict:
    return CONFIG.get("governance", {}).get("budget", {})


def _spent_since(ts_start: float) -> float:
    """Summe aller Ausgaben seit ts_start — als SQL-Aggregat ueber die GANZE
    events-Tabelle (S6.2). Vorher lief das ueber events.recent(5000): unter
    24/7-Last rutschten Monatsanfangs-Events aus dem Fenster und der Monats-
    Spend wurde still zu NIEDRIG gezaehlt — die Budget-Bremse griff zu spaet."""
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute("PRAGMA busy_timeout=5000")  # Budget-Lesung nie an Schreib-Lock scheitern
            row = c.execute(
                "SELECT "
                " COALESCE(SUM(CASE WHEN type='llm_call' "
                "   THEN COALESCE(json_extract(payload,'$.cost_usd'),0) ELSE 0 END),0),"
                " COALESCE(SUM(CASE WHEN type='spend' "
                "   THEN COALESCE(json_extract(payload,'$.amount'),0) ELSE 0 END),0) "
                "FROM events WHERE ts >= ?", (ts_start,),
            ).fetchone()
        return float(row[0] or 0.0) + float(row[1] or 0.0)
    except Exception:  # noqa: BLE001 — Fallback: alter (ungenauer) Fenster-Scan
        total = 0.0
        for e in events.recent(5000):
            if e["ts"] < ts_start:
                continue
            if e["type"] == "llm_call":
                total += float(e["payload"].get("cost_usd") or 0.0)
            elif e["type"] == "spend":
                total += float(e["payload"].get("amount") or 0.0)
        return total


def today_spend() -> float:
    start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return _spent_since(start)


def month_spend() -> float:
    start = datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    return _spent_since(start)


def status() -> dict:
    b = _budget()
    d, m = today_spend(), month_spend()
    dl, ml = b.get("daily_eur"), b.get("monthly_eur")
    return {
        "day_spent": round(d, 4),
        "day_limit": dl,
        "day_remaining": (round(dl - d, 4) if dl is not None else None),
        "month_spent": round(m, 4),
        "month_limit": ml,
        "month_remaining": (round(ml - m, 4) if ml is not None else None),
    }


def can_spend(amount: float) -> tuple[bool, str]:
    """Darf Kira gerade `amount` ausgeben? (Vor jeder Aussen-Geldaktion fragen.)"""
    b = _budget()
    dl, ml = b.get("daily_eur"), b.get("monthly_eur")
    if dl is not None and today_spend() + amount > dl:
        return False, f"Tagesbudget {dl} EUR wuerde ueberschritten."
    if ml is not None and month_spend() + amount > ml:
        return False, f"Monatsbudget {ml} EUR wuerde ueberschritten."
    return True, "ok"


def record_spend(amount: float, reason: str, category: str = "misc",
                 venture_id: str | None = None) -> str:
    """Eine getaetigte Ausgabe verbuchen (z.B. Ads, API, Tools).

    Der EINZIGE Schreibpfad fuer Ausgaben: das spend-Event traegt das globale Budget,
    venture_id bucht dieselbe Ausgabe zusaetzlich ins Venture-Konto-Buch (Projekt-Sicht).
    Das Ledger emittiert nur venture_book — hier nicht mitgezaehlt, kein Doppelzaehlen."""
    if venture_id:
        try:
            from core.agency import ventures

            ventures.book(venture_id, "out", float(amount), category=category, note=reason)
        except Exception as e:  # noqa: BLE001 — Buchhaltungs-Sicht darf die Ausgabe nie blockieren
            events.emit("venture_book_error", {"venture_id": venture_id, "error": str(e)[:200]})
    return events.emit("spend", {"amount": float(amount), "reason": reason,
                                 "category": category, "venture_id": venture_id})
