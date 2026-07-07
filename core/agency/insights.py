"""Insights: liest den Outcome-Ledger und macht daraus Verhaltens-Aenderung (S6.2).

Bisher war der Ledger write-only: Scores/Feedback/Kosten wurden pro Task-Versuch
gesammelt, aber NICHTS las sie zurueck — Kira wurde fleissiger, nicht besser.
Dieses Modul aggregiert die Versuche (reines SQL, kein LLM, deterministisch):

- fail_patterns():  Pass-Rate / Durchschnitts-Score / Kosten-pro-Erfolg je Task-Art
                    und je Ziel + wiederkehrende Kritik-Themen aus dem Pruefer-Feedback
- strategy_stats(): Pass-Rate je Strategie (standard/eskaliert/strategiewechsel)
                    — beantwortet: lohnt sich Eskalation?
- render_brief():   kompakter deutscher ERKENNTNISSE-Block, geht in Planner-Prompt
                    und Standup-Lagebericht (die eigentliche Rueckkopplung)
- weekly_lessons(): destilliert 1-3 Lektionen ins Gedaechtnis (Curator entdoppelt)
"""
from __future__ import annotations

import re
import sqlite3
import time

from core.config import DB_PATH
from core.kernel import events


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")  # Nebenlaeufigkeit: bis 5s warten statt sofort locken
    return conn


# Fuellwoerter, die im Pruefer-Feedback nichts ueber das Muster aussagen.
_STOP = {
    "der", "die", "das", "und", "oder", "nicht", "kein", "keine", "keinen", "mit", "fuer",
    "von", "im", "in", "am", "an", "auf", "zu", "zur", "zum", "ist", "sind", "war", "wird",
    "werden", "wurde", "wurden", "es", "ein", "eine", "einen", "einem", "einer", "dem",
    "den", "des", "bei", "als", "auch", "aus", "um", "noch", "nur", "sollte", "soll",
    "sollten", "muss", "mehr", "sich", "sein", "seine", "ihre", "aber", "sehr", "hat",
    "haben", "dass", "task", "aufgabe", "ergebnis", "versuch", "the", "and", "was",
    "wie", "man", "ohne", "statt", "diese", "dieser", "dieses", "wurde",
}


def _rows(days: int) -> list[tuple]:
    cutoff = time.time() - days * 86400
    with _conn() as c:
        try:
            return c.execute(
                "SELECT o.verdict, o.score, o.cost_usd, o.feedback, o.strategy, "
                "       t.kind, t.objective_id "
                "FROM outcomes o LEFT JOIN tasks t ON t.id = o.task_id "
                "WHERE o.ts >= ?", (cutoff,)
            ).fetchall()
        except sqlite3.OperationalError:  # Tabellen existieren noch nicht
            return []


def _objective_titles() -> dict:
    with _conn() as c:
        try:
            return dict(c.execute("SELECT id, title FROM objectives").fetchall())
        except sqlite3.OperationalError:
            return {}


def _agg(rows: list[tuple], key_idx: int) -> list[dict]:
    """Aggregiert Versuche nach einem Schluessel (kind oder objective_id)."""
    groups: dict[str, dict] = {}
    for verdict, score, cost, _fb, _strat, kind, oid in rows:
        key = kind if key_idx == 5 else oid
        if not key:
            continue
        g = groups.setdefault(key, {"key": key, "attempts": 0, "passed": 0,
                                    "cost_usd": 0.0, "scores": []})
        g["attempts"] += 1
        g["passed"] += 1 if verdict == "pass" else 0
        g["cost_usd"] += float(cost or 0.0)
        if score is not None:
            g["scores"].append(score)
    out = []
    for g in groups.values():
        out.append({
            "key": g["key"],
            "attempts": g["attempts"],
            "passed": g["passed"],
            "pass_rate": round(g["passed"] / g["attempts"], 3),
            "avg_score": round(sum(g["scores"]) / len(g["scores"]), 1) if g["scores"] else None,
            "cost_per_success": round(g["cost_usd"] / g["passed"], 4) if g["passed"] else None,
            "cost_usd": round(g["cost_usd"], 4),
        })
    return sorted(out, key=lambda x: (x["pass_rate"], -(x["attempts"])))  # schwaechste zuerst


def feedback_themes(days: int = 14, k: int = 3) -> list[str]:
    """Wiederkehrende Woerter aus dem Pruefer-Feedback NICHT-bestandener Versuche."""
    counts: dict[str, int] = {}
    for verdict, _s, _c, fb, *_ in _rows(days):
        if verdict == "pass" or not fb:
            continue
        for w in re.findall(r"[a-zA-Zäöüß]{4,}", fb.lower()):
            if w not in _STOP:
                counts[w] = counts.get(w, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    return [w for w, n in ranked[:k] if n >= 2]


def fail_patterns(days: int = 14) -> dict:
    """Muster-Aggregat: je Task-Art und je Ziel, schwaechste zuerst."""
    rows = _rows(days)
    titles = _objective_titles()
    by_obj = _agg(rows, key_idx=6)
    for g in by_obj:
        g["title"] = titles.get(g["key"], g["key"])
    return {
        "days": days,
        "attempts": len(rows),
        "by_kind": _agg(rows, key_idx=5),
        "by_objective": by_obj,
        "themes": feedback_themes(days),
    }


def strategy_stats(days: int = 14) -> dict:
    """Pass-Rate je Strategie: zeigt, ob Eskalation/Strategiewechsel sich lohnt."""
    stats: dict[str, dict] = {}
    for verdict, _s, _c, _fb, strat, _k, _o in _rows(days):
        if not strat:
            continue
        g = stats.setdefault(strat, {"attempts": 0, "passed": 0})
        g["attempts"] += 1
        g["passed"] += 1 if verdict == "pass" else 0
    return {s: {"attempts": g["attempts"], "passed": g["passed"],
                "pass_rate": round(g["passed"] / g["attempts"], 3)}
            for s, g in stats.items()}


def render_brief(days: int = 14, max_chars: int = 900) -> str:
    """Kompakter ERKENNTNISSE-Block fuer Planner-Prompt und Standup. Leer ohne Daten."""
    from core.agency import outcomes

    pat = fail_patterns(days)
    if not pat["attempts"]:
        return ""
    st = outcomes.stats(days)
    lines = [f"ERKENNTNISSE AUS BISHERIGEN ERGEBNISSEN (letzte {days} Tage, {pat['attempts']} Versuche):"]
    pr = f"{round(st['pass_rate'] * 100)}%" if st.get("pass_rate") is not None else "?"
    avg = st.get("avg_score")
    lines.append(f"- Pass-Rate {pr}" + (f" · Durchschnitts-Score {avg}" if avg is not None else ""))
    weak_kind = next((g for g in pat["by_kind"] if g["attempts"] >= 3 and g["pass_rate"] < 0.7), None)
    if weak_kind:
        lines.append(f"- Schwaechste Task-Art: '{weak_kind['key']}' "
                     f"({weak_kind['passed']}/{weak_kind['attempts']} bestanden"
                     + (f", Kosten/Erfolg {weak_kind['cost_per_success']} USD" if weak_kind["cost_per_success"] else "")
                     + ") — solche Aufgaben kleiner und praeziser formulieren")
    weak_obj = next((g for g in pat["by_objective"] if g["attempts"] >= 3 and g["pass_rate"] < 0.5), None)
    if weak_obj:
        lines.append(f"- Zaehes Ziel: '{str(weak_obj['title'])[:60]}' "
                     f"({weak_obj['passed']}/{weak_obj['attempts']} bestanden) — Ansatz ueberdenken")
    if pat["themes"]:
        lines.append("- Wiederkehrende Pruefer-Kritik: " + ", ".join(pat["themes"]))
    strat = strategy_stats(days)
    esc, std = strat.get("strategiewechsel"), strat.get("standard")
    if esc and std and esc["attempts"] >= 2 and esc["pass_rate"] > std["pass_rate"] + 0.15:
        lines.append("- Strategiewechsel zahlt sich aus: bei Zaehem frueh den Ansatz wechseln")
    return "\n".join(lines)[:max_chars]


def weekly_lessons(days: int = 7) -> list[str]:
    """Destilliert die Wochen-Muster in 1-3 Lektionen furs Gedaechtnis (Curator entdoppelt)."""
    from core.mind.memory import store as memory

    pat = fail_patterns(days)
    lessons: list[str] = []
    if not pat["attempts"]:
        return lessons
    for g in pat["by_kind"]:
        if g["attempts"] >= 3 and g["pass_rate"] < 0.5:
            theme = f" Haeufige Kritik: {', '.join(pat['themes'])}." if pat["themes"] else ""
            lessons.append(f"Task-Art '{g['key']}' scheitert oft ({g['passed']}/{g['attempts']} "
                           f"bestanden).{theme} Solche Aufgaben kleiner schneiden und Kriterien "
                           f"vorab klarziehen.")
            break
    strat = strategy_stats(days)
    esc, std = strat.get("strategiewechsel"), strat.get("standard")
    if esc and std and esc["attempts"] >= 2 and esc["pass_rate"] > std["pass_rate"] + 0.15:
        lessons.append("Wenn ein Task zweimal am Pruefer scheitert, lohnt ein grundlegender "
                       "Strategiewechsel mehr als Nachbessern am selben Ansatz.")
    expensive = next((g for g in pat["by_kind"]
                      if g["cost_per_success"] and g["cost_per_success"] > 0.5), None)
    if expensive:
        lessons.append(f"Task-Art '{expensive['key']}' ist teuer pro Erfolg "
                       f"({expensive['cost_per_success']} USD) — billigere lokale Vorarbeit "
                       f"erledigen, bevor Cloud-Modelle rechnen.")
    for text in lessons[:3]:
        try:
            memory.remember(text, role="self", kind="lesson")
        except Exception as e:  # noqa: BLE001
            events.emit("insights_error", {"error": str(e)[:200]})
    if lessons:
        events.emit("insights_weekly", {"lessons": len(lessons[:3]), "attempts": pat["attempts"]})
    return lessons[:3]


def stalled_objectives(days: int = 5) -> list[dict]:
    """Aktive Business-Ziele ohne erledigten Task seit `days` Tagen (S6.3).

    Zu junge Ziele (juenger als `days`) bekommen noch kein Urteil. Ergebnis
    traegt idle_days fuer den Freigabe-Eintrag ('Ziel steckt fest')."""
    from core.agency.missions import objectives

    now = time.time()
    cutoff = now - days * 86400
    out: list[dict] = []
    for o in objectives.list_active(domain="business"):
        if float(o.get("ts") or now) > cutoff:
            continue  # zu jung fuer ein Stall-Urteil
        la = objectives.last_activity(o["id"])
        if la is None or la < cutoff:
            idle = (now - la) / 86400 if la else (now - float(o["ts"])) / 86400
            out.append({**o, "last_activity": la, "idle_days": round(idle, 1)})
    return out
