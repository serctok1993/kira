"""Standup-Kontext: der strukturierte Lagebericht fuer Briefings und Coach (S5).

build_context() ist ein reiner Daten-Read (KEIN LLM-Call, ~2500 Zeichen Cap):
Leben-Board, Ziele nach Domaene, Ventures-Kasse, offene Freigaben, Tagesstand,
Metriken, Fokus. Cron-Prompts nutzen den Platzhalter {{standup}} (cron.run_job
expandiert ihn) — so lesen Morgen-Briefing, Abend-Review und Coach-Check echte
Boards statt zu raten.
"""
from __future__ import annotations

import datetime
import json
import time

from core.config import ROOT, feature_on
from core.kernel import events

_CAP = 3000  # S6.2: +500 fuer die ERKENNTNISSE-Sektion (Outcome-Rueckkopplung)


def _focus() -> str:
    try:
        d = json.loads((ROOT / "data" / "focus.json").read_text(encoding="utf-8"))
        return (d.get("focus") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _today_numbers() -> dict:
    start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    done = fails = 0
    for e in events.recent(500):
        if e["ts"] < start:
            continue
        if e["type"] == "mission_task_done":
            done += 1
        elif e["type"] in ("mission_task_failed", "task_failed_final"):
            fails += 1
    try:
        from core.governance import treasury

        spend = round(treasury.today_spend(), 2)
    except Exception:  # noqa: BLE001
        spend = None
    return {"done": done, "fails": fails, "spend": spend}


def _fmt_obj(o: dict) -> str:
    tail = f" (bis {o['target_date']})" if o.get("target_date") else ""
    return f"- [{o['kind']}] {o['title']} — {o['progress']}%{tail}"


def _news_block(max_items: int = 8) -> str:
    """Gemerkte Themen-News fuers Briefing (Titel + Link). Leert den Monitor-Puffer.

    Frischer Check vorab (ignoriert das Intervall, meldet NICHT spontan) — so bringt
    das Briefing auch das Neueste. Faellt still aus, wenn nichts anliegt.
    """
    try:
        from core.agency.connectors import news_monitor

        try:
            news_monitor.run_all(force=True, notify=False)
        except Exception:  # noqa: BLE001
            pass
        items = news_monitor.drain_pending(max_items)
        if not items:
            return ""
        lines = ["NEUES AUS DEINEN THEMEN (bring es in eigenen Worten, MIT Link):"]
        for it in items:
            link = f" ({it['link']})" if it.get("link") else ""
            lines.append(f"- [{it.get('label', '')}] {it.get('title', '')[:110]}{link}")
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return ""


def _stammbaum_question(heute: str = "") -> str:
    """EINE Logbuch-Frage pro Tag: sucht ???-Luecken im Stammbaum und rotiert per Datum.

    Kein LLM, 0 EUR. Verschwindet von selbst, wenn alle Luecken gefuellt sind.
    heute: Datum als String fuer die Rotation (Standard: heutiges Datum) — testbar."""
    try:
        import hashlib

        base = ROOT / "gedaechtnis" / "stammbaum"
        if not base.exists():
            return ""
        luecken: list[tuple[str, str]] = []  # (datei-relativ, feldzeile)
        for p in sorted(base.rglob("*.md")):
            if "_VORLAGE" in p.name:
                continue
            try:
                for zeile in p.read_text(encoding="utf-8").splitlines():
                    z = zeile.strip()
                    if z.startswith("-") and z.endswith("???"):
                        luecken.append((str(p.relative_to(ROOT)), z.lstrip("- ").rstrip(": ?").strip()))
            except Exception:  # noqa: BLE001
                continue
        if not luecken:
            return ""
        heute = heute or time.strftime("%Y-%m-%d")
        idx = int(hashlib.md5(heute.encode()).hexdigest(), 16) % len(luecken)
        datei, feld = luecken[idx]
        return ("LOGBUCH-FRAGE (stelle Sergen GENAU EINE Frage, beilaeufig und warm — "
                f"kein Verhoer): Frag nach '{feld}' und trage die Antwort mit edit_datei "
                f"in {datei} ein (??? ersetzen). Insgesamt noch {len(luecken)} Luecken offen.")
    except Exception:  # noqa: BLE001 — das Briefing darf daran nie scheitern
        return ""


_TERMIN_FELDER = ("geburtstag", "jahrestag", "hochzeitstag", "jubilaeum", "jubiläum")


def _termin_radar(heute: datetime.date | None = None, vorlauf_tage: int = 8) -> str:
    """Sergens Kernwunsch (08.07.): Erinnerungen ANWENDEN statt nur ablegen.

    Liest Datums-Felder aus dem Stammbaum (kein LLM, 0 EUR):
      - Jahrestage ('- geburtstag: 01.07.[1993]') -> naechstes Vorkommen im Vorlauf
      - einmalige Termine mit vollem Datum ('- vertrag endet: 15.07.2026') -> im Vorlauf
    Faellige landen im Briefing mit klarer Anweisung, sie VON SELBST anzusprechen."""
    import re as _re

    try:
        base = ROOT / "gedaechtnis" / "stammbaum"
        if not base.exists():
            return ""
        heute = heute or datetime.date.today()
        funde: list[tuple[int, str]] = []  # (tage_bis, zeile)
        pat = _re.compile(r"^-\s*([^:]{2,60}):\s*.*?(\d{1,2})\.(\d{1,2})\.(\d{4})?\s*$")
        for p in sorted(base.rglob("*.md")):
            if "_VORLAGE" in p.name:
                continue
            wer = p.stem.replace("-", " ").replace("_", " ").title()
            try:
                zeilen = p.read_text(encoding="utf-8").splitlines()
            except Exception:  # noqa: BLE001
                continue
            for z in zeilen:
                m = pat.match(z.strip())
                if not m:
                    continue
                feld = m.group(1).strip().lower()
                try:
                    tag, monat = int(m.group(2)), int(m.group(3))
                    jahr = int(m.group(4)) if m.group(4) else None
                    jaehrlich = any(k in feld for k in _TERMIN_FELDER)
                    if jaehrlich:
                        naechster = datetime.date(heute.year, monat, tag)
                        if naechster < heute:
                            naechster = datetime.date(heute.year + 1, monat, tag)
                        extra = f" (wird {heute.year - jahr})" if (jahr and "geburtstag" in feld) else ""
                    elif jahr:
                        naechster = datetime.date(jahr, monat, tag)
                        extra = ""
                    else:
                        continue  # einmaliger Termin ohne Jahr -> nicht deutbar
                    diff = (naechster - heute).days
                    if 0 <= diff <= vorlauf_tage:
                        wann = "HEUTE" if diff == 0 else ("morgen" if diff == 1 else f"in {diff} Tagen")
                        funde.append((diff, f"- {wer}: {feld} am {naechster.strftime('%d.%m.')} — {wann}{extra}"))
                except (ValueError, TypeError):
                    continue
        if not funde:
            return ""
        funde.sort()
        return ("TERMIN-RADAR (aus dem Stammbaum — sprich es VON DIR AUS an, warm und "
                "rechtzeitig; nicht warten, bis Sergen fragt):\n"
                + "\n".join(z for _, z in funde[:6]))
    except Exception:  # noqa: BLE001 — das Briefing darf daran nie scheitern
        return ""


def build_context(scope: str = "morgen") -> str:
    """Der Lagebericht. scope ist informativ (morgen|abend|coach) — Inhalt identisch."""
    from core.agency.missions import metrics, objectives, queue

    objectives.init_objectives()
    queue.init_queue()
    parts: list[str] = [f"=== LAGEBERICHT ({scope}, {time.strftime('%d.%m.%Y %H:%M')}) ==="]

    focus = _focus()
    if focus:
        parts.append(f"FOKUS von Sergen: {focus}")

    # Leben: Todos heute/Woche + Ziele
    board = queue.board("leben")
    heute = board.get("today", [])
    woche = board.get("week", [])
    parts.append(f"LEBEN — Todos: {len(heute)} heute, {len(woche)} diese Woche, "
                 f"{len(board.get('later', []))} spaeter")
    for t in heute[:5]:
        parts.append(f"- HEUTE: {t['description'][:90]}")
    for t in woche[:4]:
        parts.append(f"- Woche: {t['description'][:90]}")
    leben_ziele = objectives.list_active(domain="leben")
    if leben_ziele:
        parts.append("LEBEN — Missionen/Ziele:")
        parts.extend(_fmt_obj(o) for o in leben_ziele[:6])

    # Business: Ziele-Kopf + Ventures — nur wenn das Feature an ist (S12), sonst
    # briefed Kira ueber abgeschaltete Bausteine.
    if feature_on("business"):
        biz = objectives.list_active(domain="business")
        if biz:
            parts.append("BUSINESS — aktive Ziele:")
            parts.extend(_fmt_obj(o) for o in biz[:4])
        try:
            from core.agency import ventures

            vs = ventures.summary()
            if vs:
                parts.append("VENTURES:")
                for v in vs[:5]:
                    ms = f", Meilenstein {v['milestone_progress']}%" if v.get("milestone_progress") is not None else ""
                    parts.append(f"- {v['name']} [{v['status']}]: Kasse {v['balance_eur']:.2f} EUR{ms}")
        except Exception:  # noqa: BLE001
            pass

    # Offen fuer Sergen + Tagesstand
    try:
        from core.agency import approvals

        pend = approvals.pending()
        if pend:
            parts.append(f"WARTET AUF SERGEN ({len(pend)}):")
            parts.extend(f"- {p['title'][:90]}" for p in pend[:3])
    except Exception:  # noqa: BLE001
        pass
    nums = _today_numbers()
    spend = f", {nums['spend']} EUR ausgegeben" if nums.get("spend") is not None else ""
    parts.append(f"HEUTE: {nums['done']} Aufgaben erledigt, {nums['fails']} gescheitert{spend}")

    # Erkenntnisse aus dem Outcome-Ledger (S6.2) — was zuletzt funktionierte und was nicht
    try:
        from core.agency import insights

        brief = insights.render_brief(days=7, max_chars=400)
        if brief:
            parts.append(brief)
    except Exception:  # noqa: BLE001
        pass

    # Metriken (Coach-Futter)
    try:
        ms = metrics.latest()
        if ms:
            parts.append("METRIKEN:")
            for m in ms[:6]:
                delta = f" ({'+' if m['delta'] > 0 else ''}{m['delta']} seit letztem Mal)" if m.get("delta") is not None else ""
                parts.append(f"- {m['name']}: {m['value']}{delta}")
    except Exception:  # noqa: BLE001
        pass

    text = "\n".join(parts)[:_CAP]
    # News NACH dem Cap anhaengen, damit Themen + Links nie weggeschnitten werden.
    news = _news_block()
    if news:
        text = f"{text}\n\n{news}"
    # Termin-Radar: faellige Geburtstage/Termine aus dem Stammbaum (post-cap, nie beschnitten).
    termine = _termin_radar()
    if termine:
        text = f"{text}\n\n{termine}"
    # Das hungrige Logbuch: EINE Stammbaum-Luecke pro Tag erfragen (ebenfalls post-cap).
    frage = _stammbaum_question()
    if frage:
        text = f"{text}\n\n{frage}"
    return text
