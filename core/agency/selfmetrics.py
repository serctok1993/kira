"""Selbstmessung: ein dauerhafter Zeitreihen-Punkt pro Woche — damit DRIFT sichtbar wird.

outcomes.stats(7) liefert nur das aktuelle Fenster (jetzt). Sobald der Motor 24/7 laeuft,
braucht der Nutzer (und Kira selbst) den VERLAUF: wird der Harness ueber die Wochen besser oder
schlechter, und was kostet er? Dieser Schnappschuss liest NUR bereits protokollierte Daten
(Outcome-Ledger) — 0 Token, 0 EUR, kein Modell-Aufruf, deterministisch (DeepSeek-tauglich).
Kein Benchmark-Lauf: der teure GLM-Referenz-Benchmark bleibt des Nutzers Knopf im Cockpit.

Eine Zeile je Schnappschuss in data/selfmetrics.jsonl — waechst langsam, nie geloescht.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _path() -> Path:
    from core import config

    return Path(config.DATA_DIR) / "selfmetrics.jsonl"


def snapshot(days: int = 7) -> dict:
    """Baut einen Messpunkt aus dem Outcome-Ledger und haengt ihn an die Zeitreihe an."""
    from core.agency import outcomes

    st = outcomes.stats(days)
    point = {
        "ts": time.time(),
        "window_days": days,
        "attempts": st.get("attempts", 0),
        "passed": st.get("passed", 0),
        "pass_rate": st.get("pass_rate"),
        "avg_score": st.get("avg_score"),
        "cost_usd": st.get("cost_usd", 0.0),
    }
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(point, ensure_ascii=False) + "\n")
    return point


def history(limit: int = 26) -> list[dict]:
    """Die juengsten Messpunkte (neueste zuletzt) — fuers Cockpit / den Trend."""
    p = _path()
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001 — eine kaputte Zeile darf die Reihe nicht killen
            continue
    return out[-int(limit):] if limit else out


def trend() -> dict:
    """Vergleicht den letzten mit dem vorletzten Punkt — Richtung der Pass-Rate."""
    h = history(limit=2)
    if len(h) < 2:
        return {"direction": "flat", "delta": 0.0, "points": len(h)}
    a = h[-2].get("pass_rate") or 0.0
    b = h[-1].get("pass_rate") or 0.0
    delta = round(b - a, 3)
    direction = "up" if delta > 0.02 else "down" if delta < -0.02 else "flat"
    return {"direction": direction, "delta": delta, "points": len(h)}
