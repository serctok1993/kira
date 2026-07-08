"""Selbstkalibrierung (B-025): wie oft muss das System nachhelfen — pro Modell.

Deterministische Aggregation ueber die events-Tabelle (kein LLM, 0 Euro):
  - llm_call:                Anrufe, Fallback-/Eskalations-Quote, Kosten, Latenz je Modell
  - llm_call_error/-timeout: Fehlerquote je Modell
  - nudge:                   wie oft act.py ein Modell anstupsen musste (Ankuendiger statt Macher)
  - model_fallback:          welche Rolle wie oft auf lokal ausweicht (fehlender Key/Budget)
  - task_retry/task_scored:  Wiederholungen + Pass-Rate je Strategie (standard/eskaliert/wechsel)

report() liefert die Zahlen, render() den lesbaren Block mit Empfehlungen,
propose() legt ihn woechentlich als Vorschlag in die Freigabe-Inbox — Sergen zieht
Modell-Rollen dann datenbasiert nach statt nach Gefuehl.
"""
from __future__ import annotations

import time

from core.kernel import events

_TYPES = ("llm_call", "llm_call_error", "llm_call_timeout", "nudge",
          "model_fallback", "task_retry", "task_scored", "task_failed_final")

# Schwellen fuer Empfehlungen: erst ab MIN_CALLS pro Modell wird geurteilt —
# drei Anrufe sind Rauschen, keine Rate.
MIN_CALLS = 10


def _empty() -> dict:
    return {"calls": 0, "fell_back": 0, "escalated": 0, "errors": 0, "nudges": 0,
            "cost_usd": 0.0, "latency_sum": 0.0, "latency_n": 0}


def report(days: int = 7) -> dict:
    since = time.time() - days * 86400
    per: dict[str, dict] = {}
    strategies: dict[str, dict] = {}
    fallbacks: dict[str, int] = {}
    retries = failed = 0
    for ev in events.rows_since(_TYPES, since):
        t, p = ev["type"], ev["payload"]
        m = str(p.get("model") or "")
        if t == "llm_call" and m:
            g = per.setdefault(m, _empty())
            g["calls"] += 1
            g["fell_back"] += 1 if p.get("fell_back") else 0
            g["escalated"] += 1 if p.get("escalated") else 0
            g["cost_usd"] += float(p.get("cost_usd") or 0)
            lat = float(p.get("latency_s") or 0)
            if lat:
                g["latency_sum"] += lat
                g["latency_n"] += 1
        elif t in ("llm_call_error", "llm_call_timeout") and m:
            per.setdefault(m, _empty())["errors"] += 1
        elif t == "nudge" and m:
            per.setdefault(m, _empty())["nudges"] += 1
        elif t == "model_fallback":
            key = f"{p.get('task_type', '?')} wollte {p.get('wanted', '?')}"
            fallbacks[key] = fallbacks.get(key, 0) + 1
        elif t == "task_retry":
            retries += 1
        elif t == "task_failed_final":
            failed += 1
        elif t == "task_scored":
            s = str(p.get("strategy") or "")
            if s:
                g = strategies.setdefault(s, {"attempts": 0, "passed": 0})
                g["attempts"] += 1
                g["passed"] += 1 if str(p.get("verdict")) == "pass" else 0
    models = []
    for m, g in sorted(per.items(), key=lambda x: -x[1]["calls"]):
        calls, total = g["calls"], g["calls"] + g["errors"]
        models.append({
            "model": m, "calls": calls, "errors": g["errors"], "nudges": g["nudges"],
            "escalated": g["escalated"],
            "fallback_rate": round(g["fell_back"] / calls, 3) if calls else None,
            "error_rate": round(g["errors"] / total, 3) if total else None,
            "nudge_rate": round(g["nudges"] / calls, 3) if calls else None,
            "avg_latency_s": round(g["latency_sum"] / g["latency_n"], 1) if g["latency_n"] else None,
            "cost_usd": round(g["cost_usd"], 4),
        })
    for s, g in strategies.items():
        g["pass_rate"] = round(g["passed"] / g["attempts"], 3) if g["attempts"] else None
    return {"days": days, "models": models, "strategies": strategies, "fallbacks": fallbacks,
            "task_retries": retries, "tasks_failed": failed,
            "total_calls": sum(x["calls"] for x in models)}


def _hints(rep: dict) -> list[str]:
    """Empfehlungen aus den Raten — bewusst simple, pruefbare Heuristiken."""
    hints: list[str] = []
    for m in rep["models"]:
        if m["calls"] < MIN_CALLS:
            continue
        name = m["model"]
        if (m["nudge_rate"] or 0) > 0.2:
            hints.append(f"'{name}' kuendigt oft nur an ({m['nudges']}x gestupst bei {m['calls']} "
                         f"Anrufen) — Rolle pruefen: haerterer Prompt oder anderes Modell.")
        if (m["fallback_rate"] or 0) > 0.2:
            hints.append(f"'{name}' faellt oft auf lokal zurueck ({round(m['fallback_rate'] * 100)}%) "
                         f"— API-Key/Budget pruefen.")
        if (m["error_rate"] or 0) > 0.15:
            hints.append(f"'{name}' hat eine hohe Fehlerquote ({round(m['error_rate'] * 100)}%) "
                         f"— Anbieter-Status/Timeouts pruefen.")
    st = rep["strategies"]
    esc, std = st.get("strategiewechsel"), st.get("standard")
    if esc and std and esc["attempts"] >= 2 and (esc["pass_rate"] or 0) > (std["pass_rate"] or 0) + 0.15:
        hints.append("Strategiewechsel schlaegt Standard deutlich — bei zaehen Aufgaben frueher wechseln.")
    if rep["tasks_failed"] >= 3:
        hints.append(f"{rep['tasks_failed']} Auftraege endgueltig gescheitert — Muster in den "
                     f"Erkenntnissen (Kira-Tab) ansehen.")
    return hints


def render(days: int = 7, rep: dict | None = None) -> str:
    rep = rep or report(days)
    if not rep["total_calls"]:
        return f"Keine LLM-Anrufe in den letzten {days} Tagen — nichts zu kalibrieren."
    lines = [f"SELBSTKALIBRIERUNG (letzte {days} Tage, {rep['total_calls']} LLM-Anrufe):"]
    for m in rep["models"][:8]:
        parts = [f"{m['calls']} Anrufe"]
        if m["nudges"]:
            parts.append(f"{m['nudges']}x gestupst")
        if m["errors"]:
            parts.append(f"{m['errors']} Fehler")
        if m["fallback_rate"]:
            parts.append(f"{round(m['fallback_rate'] * 100)}% Fallback")
        if m["avg_latency_s"] is not None:
            parts.append(f"~{m['avg_latency_s']}s")
        if m["cost_usd"]:
            parts.append(f"{m['cost_usd']:.2f} USD")
        lines.append(f"- {m['model']}: " + " · ".join(parts))
    for s, g in rep["strategies"].items():
        lines.append(f"- Strategie '{s}': {g['passed']}/{g['attempts']} bestanden")
    if rep["task_retries"]:
        lines.append(f"- Auftrags-Wiederholungen: {rep['task_retries']}"
                     + (f" · endgueltig gescheitert: {rep['tasks_failed']}" if rep["tasks_failed"] else ""))
    for k, n in sorted(rep["fallbacks"].items(), key=lambda x: -x[1])[:4]:
        lines.append(f"- Fallback-Grund: {k} ({n}x, Key fehlte)")
    hints = _hints(rep)
    if hints:
        lines.append("")
        lines.append("EMPFEHLUNGEN:")
        lines.extend(f"- {h}" for h in hints)
    return "\n".join(lines)


def propose(days: int = 7, min_calls: int = 25) -> str | None:
    """Report als Vorschlag in die Freigabe-Inbox (woechentlich via maintenance).
    None, wenn zu wenig Daten — ein leerer Report waere Inbox-Laerm."""
    rep = report(days)
    if rep["total_calls"] < min_calls:
        return None
    from core.agency import approvals

    aid = approvals.create(
        title=f"Selbstkalibrierungs-Report ({days} Tage, {rep['total_calls']} Anrufe)",
        kind="generic", detail=render(days, rep), source="kira")
    events.emit("calibration_report", {"approval_id": aid, "calls": rep["total_calls"],
                                       "hints": len(_hints(rep))})
    return aid
