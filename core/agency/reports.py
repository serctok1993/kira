"""Report-Hierarchie (Phase 2): Tag -> Woche -> Monat, deterministisch (0 LLM-Token).

Der Tagesreport EXISTIERT (tagewerk.heute() + Telegram 21:30). Hier kommen dazu:
- wochenreport(): montags fuer die Vorwoche -> Vault reports/wochenreport-<jjjj>-w<kw>.md
- monatsreport(): am 1. fuer den Vormonat  -> Vault reports/monatsreport-<jjjj>-<mm>.md
Beide mit PRIORITAETEN-Sektion (offene P1/P2-Todos vom Life-Board). Faelligkeit wird
IN der Funktion geprueft; der Erledigt-Merker je KW/Monat laeuft ueber maintenance
(Keys wreport_/mreport_ mit praktisch unendlichem Intervall = genau 1x je Label).
rollup() ist der Runner-Einstieg (alle 6h angestossen, schreibt nur wenn faellig).
"""
from __future__ import annotations

import datetime

from core import identity as _id
from core.kernel import events

_EINMAL = 10 * 365 * 86400  # "genau einmal je Label" via maintenance.maybe_run


def _ts(d: datetime.date) -> float:
    return datetime.datetime.combine(d, datetime.time.min).timestamp()


def _tagewerk_block(start: datetime.date, ende: datetime.date) -> list[str]:
    from core.agency import tagewerk

    z = tagewerk.zeitraum(_ts(start), _ts(ende))
    t = z["tasks"]
    score = f" (Score-Schnitt {t['avg_score']})" if t.get("avg_score") is not None else ""
    out = [f"- Aufgaben: {t['done']} erledigt, {t['failed']} gescheitert{score}",
           f"- Mails raus: {z['mails']['anzahl']}",
           f"- Routinen gelaufen: {z['crons']['anzahl']}",
           f"- Selbstverbesserung: {z['selbstverbesserung']['ticks']} Ticks, "
           f"{len(z['selbstverbesserung']['code_edits'])} Code-Aenderungen",
           f"- Gelernt: {z['lektionen']} Lektionen, {z['skills']['anzahl']} Skills"]
    return out


def _prioritaeten_block(titel: str) -> list[str]:
    """Offene P1/P2-Todos vom Life-Board — was als Naechstes zaehlt."""
    try:
        from core.agency.missions import queue

        wichtig = [t for t in queue.pending("leben", limit=40)
                   if int(t.get("priority") or 3) <= 2]
    except Exception:  # noqa: BLE001
        wichtig = []
    out = [f"## PRIORITAETEN — {titel}", ""]
    if wichtig:
        out += [f"- P{t['priority']}: {t['description'][:120]}" for t in wichtig[:8]]
    else:
        out += [f"- (keine offenen P1/P2-Todos — Prioritaeten setzt {_id.user_name()} im Cockpit)"]
    return out


def _termine_block(tage: int) -> list[str]:
    try:
        from core.agency import termine

        kommend = termine.list_upcoming(tage)
    except Exception:  # noqa: BLE001
        kommend = []
    if not kommend:
        return []
    out = ["## TERMINE", ""]
    for e in kommend[:10]:
        zeit = f" {e['zeit']}" if e.get("zeit") else ""
        out.append(f"- {e['datum']}{zeit}: {e['titel']}")
    out.append("")
    return out


def _schreiben(titel: str, zeilen: list[str]) -> dict | None:
    from core.agency import vault_notes

    res = vault_notes.write_note(titel, "\n".join(zeilen), ordner="reports")
    return {"pfad": res.get("path", "")} if res.get("ok") else None


def wochenreport(heute: datetime.date | None = None, force: bool = False) -> dict | None:
    """Montags fuer die Vorwoche (Mo-So); force=True erzwingt (Test/manuell)."""
    from core.agency.missions import maintenance

    heute = heute or datetime.date.today()
    if not force and heute.weekday() != 0:
        return None
    start = heute - datetime.timedelta(days=7 if heute.weekday() == 0 else heute.weekday() + 7)
    ende = start + datetime.timedelta(days=7)
    iso = start.isocalendar()
    label = f"{iso[0]}-W{iso[1]:02d}"
    if not force and not maintenance.maybe_run(f"wreport_{label}", interval_s=_EINMAL):
        return None

    zeilen = [f"Zeitraum: {start.strftime('%d.%m.')} - "
              f"{(ende - datetime.timedelta(days=1)).strftime('%d.%m.%Y')}", "",
              "## WAS LIEF", ""]
    zeilen += _tagewerk_block(start, ende)
    zeilen.append("")
    zeilen += _termine_block(7)
    zeilen += _prioritaeten_block("kommende Woche")
    res = _schreiben(f"Wochenreport {label}", zeilen)
    if not res:
        return None
    out = {"art": "Wochenreport", "label": label, **res}
    events.emit("report_written", out)
    return out


def monatsreport(heute: datetime.date | None = None, force: bool = False) -> dict | None:
    """Am Monatsersten fuer den Vormonat; verlinkt die Wochenreports des Monats."""
    from core.agency.missions import maintenance

    heute = heute or datetime.date.today()
    if not force and heute.day != 1:
        return None
    ende = heute.replace(day=1)
    start = (ende - datetime.timedelta(days=1)).replace(day=1)
    label = f"{start.year}-{start.month:02d}"
    if not force and not maintenance.maybe_run(f"mreport_{label}", interval_s=_EINMAL):
        return None

    zeilen = [f"Zeitraum: {start.strftime('%d.%m.')} - "
              f"{(ende - datetime.timedelta(days=1)).strftime('%d.%m.%Y')}", "",
              "## WAS LIEF", ""]
    zeilen += _tagewerk_block(start, ende)
    zeilen.append("")
    # Wochenreports des Monats verlinken (Obsidian-[[...]] — der Graph verbindet sie)
    try:
        from core.agency import vault_notes

        ordner = vault_notes.vault_root() / "reports"
        wochen = sorted(p.stem for p in ordner.glob("wochenreport-*.md")
                        if p.stat().st_mtime >= _ts(start) - 8 * 86400)
    except Exception:  # noqa: BLE001
        wochen = []
    if wochen:
        zeilen += ["## WOCHEN IM DETAIL", ""] + [f"- [[{w}]]" for w in wochen[-6:]] + [""]
    zeilen += _termine_block(31)
    zeilen += _prioritaeten_block("kommender Monat")
    res = _schreiben(f"Monatsreport {label}", zeilen)
    if not res:
        return None
    out = {"art": "Monatsreport", "label": label, **res}
    events.emit("report_written", out)
    return out


def rollup() -> list[dict]:
    """Runner-Einstieg: prueft Woche + Monat, schreibt nur Faelliges. Fail-soft je Report."""
    out: list[dict] = []
    for fn in (wochenreport, monatsreport):
        try:
            r = fn()
            if r:
                out.append(r)
        except Exception as e:  # noqa: BLE001 — ein kaputter Report darf den Tick nie brechen
            events.emit("report_error", {"error": str(e)[:200]})
    return out
