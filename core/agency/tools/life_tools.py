"""Lebens-Werkzeuge: Todos, Missionen, Ziele, Metriken (S5) — Kiras Coach-Griff.

Der groesste Einzelhebel aus der Erkundung: bisher konnte KEIN Werkzeug Todos
oder Ziele anlegen — damit kann Kira jetzt per Chat/Telegram (auch Sprachmemo)
erfassen, nachhalten und coachen. Lebens-Todos leben in mission='leben' und
sind fuer den Business-Heartbeat unsichtbar; Lebens-Ziele (domain='leben')
werden gecoacht, nie automatisch abgearbeitet.
"""
from __future__ import annotations

import datetime

from core.agency.tools.registry import tool

_LEBEN = "leben"


def _parse_due(due: str) -> str | None:
    """'heute'|'morgen'|'woche'|ISO-Datum -> ISO 'YYYY-MM-DD' oder None."""
    d = (due or "").strip().lower()
    today = datetime.date.today()
    if not d:
        return None
    if d == "heute":
        return today.isoformat()
    if d == "morgen":
        return (today + datetime.timedelta(days=1)).isoformat()
    if d == "woche":
        return (today + datetime.timedelta(days=6)).isoformat()
    try:
        return datetime.date.fromisoformat(d[:10]).isoformat()
    except ValueError:
        return None


@tool("todo_add",
      "Legt ein persoenliches Todo fuer Sergen an (Lebens-Board, NICHT die Business-Queue). "
      "Nutze es, wenn Sergen etwas erledigen will/soll — auch aus Sprachmemos heraus.",
      {"text": "das Todo, kurz und konkret",
       "due": "optional: heute | morgen | woche | YYYY-MM-DD",
       "prio": "optional: 1 (hoch) bis 5 (niedrig), Standard 3"})
def todo_add(text: str, due: str = "", prio: str = "3") -> str:
    from core.agency.missions import queue

    queue.init_queue()
    try:
        p = max(1, min(5, int(prio)))
    except ValueError:
        p = 3
    due_date = _parse_due(due)
    tid = queue.add(text.strip(), mission=_LEBEN, priority=p, due_date=due_date, kind="personal")
    when = f" (faellig {due_date})" if due_date else ""
    return f"Todo notiert (id {tid[:8]}){when}: {text.strip()[:100]}"


@tool("todo_list",
      "Zeigt Sergens persoenliche Todos vom Lebens-Board, gruppiert nach heute/Woche/spaeter.",
      {"scope": "optional: offen (Standard) | alle"})
def todo_list(scope: str = "offen") -> str:
    from core.agency.missions import queue

    queue.init_queue()
    board = queue.board(_LEBEN)
    lines: list[str] = []
    labels = [("today", "HEUTE"), ("week", "DIESE WOCHE"), ("later", "SPAETER"), ("deferred", "AUFGESCHOBEN")]
    if scope.strip().lower() == "alle":
        labels.append(("done", "ERLEDIGT"))
    for key, label in labels:
        items = board.get(key, [])
        if not items:
            continue
        lines.append(f"{label}:")
        for t in items[:10]:
            due = f" [{t['due_date']}]" if t.get("due_date") else ""
            lines.append(f"- ({t['id'][:8]}) {t['description'][:90]}{due}")
    return "\n".join(lines) or "Keine offenen Todos — freies Feld. 🙂"


@tool("todo_done",
      "Hakt ein persoenliches Todo ab (id oder 8-Zeichen-Kurzform aus todo_list).",
      {"todo_id": "die Todo-Id"})
def todo_done(todo_id: str) -> str:
    from core.agency.missions import queue

    queue.init_queue()
    tid = (todo_id or "").strip()
    match = [t for t in queue.all_tasks(_LEBEN, limit=500)
             if t["status"] in ("pending", "running") and t["id"].startswith(tid)]
    if len(match) != 1:
        return (f"Kein eindeutiges offenes Todo fuer id {tid!r} "
                f"({len(match)} Treffer — todo_list zeigt die Ids).")
    queue.update_task(match[0]["id"], status="done")
    return f"Abgehakt: {match[0]['description'][:90]} ✔"


@tool("objective_add",
      "Legt eine Mission oder ein Ziel an. domain 'leben' = persoenlich (wird gecoacht), "
      "'business' = wird vom 24/7-Heartbeat bearbeitet. kind: big (Lebens-Ziel/Jahres-Mission) | "
      "monthly | weekly.",
      {"title": "das Ziel, konkret formuliert",
       "kind": "big | monthly | weekly (Standard weekly)",
       "domain": "leben | business (Standard leben)",
       "target_date": "optional: YYYY-MM-DD"})
def objective_add(title: str, kind: str = "weekly", domain: str = "leben",
                  target_date: str = "") -> str:
    from core.agency.missions import objectives

    objectives.init_objectives()
    td = _parse_due(target_date)
    oid = objectives.add(title.strip(), kind=kind, domain=domain, target_date=td)
    o = next((x for x in objectives.list_all() if x["id"] == oid), {})
    return (f"Ziel angelegt (id {oid[:8]}): [{o.get('domain')}/{o.get('kind')}] {title.strip()[:90]}"
            + (f" bis {td}" if td else ""))


@tool("objective_list",
      "Zeigt Missionen/Ziele mit Fortschritt, Faelligkeit und id. domain optional filtern "
      "(leben | business); nur_aktiv=true blendet erledigte/pausierte aus.",
      {"domain": "optional: leben | business (leer = alle)",
       "nur_aktiv": "true|false (Standard false = auch erledigte zeigen)"})
def objective_list(domain: str = "", nur_aktiv: str = "") -> str:
    from core.agency.missions import objectives

    objectives.init_objectives()
    aktiv = str(nur_aktiv).strip().lower() in ("true", "1", "ja", "yes")
    dom = (domain or "").strip().lower() or None
    ziele = (objectives.list_active(domain=dom) if aktiv
             else [o for o in objectives.list_all() if not dom or o.get("domain") == dom])
    if not ziele:
        return "(keine Ziele)" + (f" in domain '{dom}'" if dom else "")
    lines = []
    for o in ziele:
        frist = f", faellig {o['target_date']}" if o.get("target_date") else ""
        aufgaben = f", {o['tasks_done']}/{o['tasks_total']} Tasks" if o.get("tasks_total") else ""
        lines.append(f"- [{o['domain']}/{o['kind']}] {o['title'][:80]} — {o['progress']}% "
                     f"({o['status']}{frist}{aufgaben}) (id {o['id'][:8]})")
    return "\n".join(lines)


@tool("metric_log",
      "Loggt einen Messwert fuer Sergens Lebens-Metriken (Gewicht, Training, Schlaf ...). "
      "Beispiel: metric_log('gewicht', '91.4').",
      {"name": "Name der Metrik (z.B. gewicht)",
       "value": "der Zahlenwert",
       "note": "optional: kurze Notiz"})
def metric_log(name: str, value: str, note: str = "") -> str:
    from core.agency.missions import metrics

    try:
        v = float(str(value).replace(",", "."))
    except ValueError:
        return f"value braucht eine Zahl, nicht {value!r}."
    metrics.log(name, v, note=note or None)
    s = metrics.series(name, days=365)
    delta = ""
    if len(s) >= 2:
        d = round(s[-1]["value"] - s[-2]["value"], 2)
        delta = f" ({'+' if d > 0 else ''}{d} seit letztem Eintrag)"
    return f"Notiert: {name.strip().lower()} = {v}{delta}"


@tool("metric_list",
      "Zeigt Sergens Metriken: letzter Wert, Trend, Anzahl Eintraege.",
      {"name": "optional: nur diese Metrik (mit Verlauf)",
       "days": "optional: Zeitraum in Tagen (Standard 30)"})
def metric_list(name: str = "", days: str = "30") -> str:
    from core.agency.missions import metrics

    try:
        d = max(1, int(days))
    except ValueError:
        d = 30
    if name.strip():
        s = metrics.series(name, days=d)
        if not s:
            return f"Keine Eintraege fuer {name.strip().lower()!r} in {d} Tagen."
        first, last = s[0]["value"], s[-1]["value"]
        delta = round(last - first, 2)
        lines = [f"{name.strip().lower()}: {len(s)} Eintraege, {first} -> {last} "
                 f"({'+' if delta > 0 else ''}{delta} in {d} Tagen)"]
        for e in s[-8:]:
            import time as _t
            lines.append(f"- {_t.strftime('%d.%m.', _t.localtime(e['ts']))} {e['value']}"
                         + (f" ({e['note']})" if e.get("note") else ""))
        return "\n".join(lines)
    latest = metrics.latest()
    if not latest:
        return "Noch keine Metriken. Mit metric_log('gewicht', '91.4') faengst du an."
    return "\n".join(
        f"- {m['name']}: {m['value']}"
        + (f" ({'+' if m['delta'] > 0 else ''}{m['delta']})" if m.get("delta") is not None else "")
        + f" [{m['count']} Eintraege]"
        for m in latest)


@tool("metric_ziel",
      "Macht aus einer Kennzahl ein sichtbares Ziel im Dashboard: setzt Zielwert/Einheit/Emoji "
      "und heftet sie optional in die Zentrale. So gestaltest du das Ziele-Dashboard selbst. "
      "Beispiel: metric_ziel('follower', ziel='10000', einheit='Abos', emoji='📈', zentrale='ja'). "
      "zentrale='nein' nimmt sie wieder aus der Zentrale.",
      {"name": "Name der Kennzahl (z.B. follower)",
       "ziel": "optional: Zielwert als Zahl",
       "einheit": "optional: Einheit (z.B. Abos, kg, €)",
       "emoji": "optional: ein Emoji fuers Kaertchen",
       "zentrale": "optional: 'ja' anheften / 'nein' loesen"})
def metric_ziel(name: str, ziel: str = "", einheit: str = "",
                emoji: str = "", zentrale: str = "") -> str:
    from core.agency.missions import metrics

    name = (name or "").strip()
    if not name:
        return "Welche Kennzahl? z.B. metric_ziel('follower', ziel='10000', zentrale='ja')."
    target = None
    if str(ziel).strip() != "":
        try:
            target = float(str(ziel).replace(",", ".").strip())
        except ValueError:
            return f"'{ziel}' ist keine Zahl fuer den Zielwert."
    unit = einheit.strip() if einheit and einheit.strip() else None
    em = emoji.strip() if emoji and emoji.strip() else None
    pin = None
    z = (zentrale or "").strip().lower()
    if z in ("ja", "an", "true", "1", "yes", "zeigen", "on"):
        pin = True
    elif z in ("nein", "aus", "false", "0", "no", "off"):
        pin = False
    metrics.set_meta(name, pinned=pin, target=target, unit=unit, emoji=em)
    parts = [f"Ziele-Dashboard aktualisiert: '{name.lower()}'"]
    if target is not None:
        parts.append(f"Zielwert {target}" + (f" {unit}" if unit else ""))
    if pin is True:
        parts.append("in der Zentrale angeheftet")
    elif pin is False:
        parts.append("aus der Zentrale geloest")
    if metrics.get_meta(name)["target"] and not metrics.series(name, days=3650):
        parts.append("(noch kein Wert — logg einen mit metric_log)")
    return " · ".join(parts) + "."
