"""Venture-Werkzeuge: Kiras Unternehmer-Griff auf ihre Standbeine (S3).

Ausgaben laufen IMMER ueber treasury.record_spend (Budget-Autoritaet + Ledger in
einem Schritt); Einnahmen bucht ventures.book direkt. Werkzeuge liefern Strings,
nie Exceptions (executor-Retry-Regel).
"""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("venture_add",
      "Legt ein neues Venture (Einkommens-Projekt) an: Name, Hypothese ('wer zahlt wofuer?'), "
      "optional Meilenstein in EUR. Nutze Ventures fuer alles, was Geld einbringen soll.",
      {"name": "kurzer Name des Standbeins",
       "hypothesis": "eine Zeile: wer zahlt wofuer, warum jetzt",
       "milestone_eur": "optional: Umsatz-Meilenstein in EUR (Zahl)"})
def venture_add(name: str, hypothesis: str = "", milestone_eur: str = "") -> str:
    from core.agency import ventures

    try:
        ms = float(milestone_eur) if str(milestone_eur).strip() else None
    except ValueError:
        ms = None
    vid = ventures.add(name, hypothesis=hypothesis, milestone_eur=ms)
    leaf = ventures.ensure_vault_leaf(name, vid)  # idempotent — Ast wurde in add() schon angelegt
    zusatz = ""
    if leaf.get("created"):
        zusatz = (f". Stammbaum-Ast angelegt: gedaechtnis/stammbaum/business/{ventures._slug(name)}.md "
                  "(??? -Felder fuellt die taegliche Logbuch-Frage; frag bei Bedarf gezielt nach)")
    return (f"Venture angelegt: {name} (id {vid[:8]}, Status idea"
            + (f", Meilenstein {ms:.0f} EUR" if ms else "") + ")" + zusatz)


@tool("venture_list",
      "Zeigt alle Ventures mit Status, Kasse (Einnahmen/Ausgaben) und Meilenstein-Fortschritt.",
      {})
def venture_list() -> str:
    from core.agency import ventures

    rows = ventures.summary()
    if not rows:
        return "Noch keine Ventures. Lege mit venture_add dein erstes Standbein an."
    lines = []
    for v in rows:
        ms = (f" | Meilenstein: {v['milestone_progress']}% von {v['milestone_eur']:.0f} EUR"
              if v.get("milestone_eur") else "")
        lines.append(f"- {v['name']} [{v['status']}] (id {v['id'][:8]}): "
                     f"+{v['income_eur']:.2f} / -{v['expenses_eur']:.2f} = {v['balance_eur']:.2f} EUR{ms}"
                     + (f"\n  Hypothese: {v['hypothesis']}" if v.get("hypothesis") else ""))
    return "\n".join(lines)


@tool("venture_update",
      "Aendert ein Venture: status (idea|building|live|scaling|paused|dead), hypothesis, "
      "milestone_eur oder notes.",
      {"venture_id": "die Venture-Id (auch 8-Zeichen-Kurzform)",
       "field": "status | hypothesis | milestone_eur | notes | name",
       "value": "der neue Wert"})
def venture_update(venture_id: str, field: str, value: str) -> str:
    from core.agency import ventures

    v = _resolve(ventures, venture_id)
    if not v:
        return f"Kein Venture mit id {venture_id} gefunden (venture_list zeigt alle)."
    if field == "milestone_eur":
        try:
            value = float(value)
        except ValueError:
            return f"milestone_eur braucht eine Zahl, nicht {value!r}."
    ok = ventures.update(v["id"], **{field: value})
    return f"{v['name']}: {field} -> {value}" if ok else f"Feld {field!r} ist nicht aenderbar."


@tool("ledger_book",
      "Bucht Geld ins Konto-Buch eines Ventures. direction 'in' = Einnahme (direkt gebucht), "
      "'out' = Ausgabe (laeuft ueber das Budget: erst can_spend, dann record_spend + Ledger).",
      {"venture_id": "die Venture-Id (auch Kurzform)",
       "direction": "in | out",
       "amount_eur": "Betrag in EUR (Zahl)",
       "note": "wofuer (eine Zeile)"})
def ledger_book(venture_id: str, direction: str, amount_eur: str, note: str = "") -> str:
    from core.agency import ventures
    from core.governance import treasury

    v = _resolve(ventures, venture_id)
    if not v:
        return f"Kein Venture mit id {venture_id} gefunden."
    try:
        amount = float(amount_eur)
    except ValueError:
        return f"amount_eur braucht eine Zahl, nicht {amount_eur!r}."
    if amount <= 0:
        return "Betrag muss > 0 sein."

    if direction == "out":
        ok, why = treasury.can_spend(amount)
        if not ok:
            return f"Budget-Stopp: {why}"
        treasury.record_spend(amount, note or f"Ausgabe {v['name']}", category="venture", venture_id=v["id"])
        return f"Ausgabe gebucht: -{amount:.2f} EUR bei {v['name']} (Kasse: {ventures.balance(v['id']):.2f} EUR)"
    if direction == "in":
        ventures.book(v["id"], "in", amount, category="venture", note=note)
        return f"Einnahme gebucht: +{amount:.2f} EUR bei {v['name']} (Kasse: {ventures.balance(v['id']):.2f} EUR)"
    return f"direction muss 'in' oder 'out' sein, nicht {direction!r}."


def _resolve(ventures_mod, vid: str) -> dict | None:
    """Volle Id oder 8-Zeichen-Kurzform aufloesen."""
    vid = (vid or "").strip()
    v = ventures_mod.get(vid)
    if v:
        return v
    matches = [x for x in ventures_mod.list_all(include_dead=True) if x["id"].startswith(vid)]
    return matches[0] if len(matches) == 1 else None


@tool("project_note",
      "Legt eine DAUERANWEISUNG von Sergen ins Projekt-Gedaechtnis (Briefing) eines Ventures ab — "
      "z.B. 'haeng bei Kaltakquise immer unseren Website-Link an'. Sie fliesst danach in JEDEN "
      "Task dieses Projekts ein. project = Name-Teil oder Id; ist es mehrdeutig, bekommst du "
      "eine Rueckfrage-Liste zurueck: frag Sergen kurz, welches Projekt gemeint ist.",
      {"project": "Venture-Name (Teil reicht) oder Id/Kurzform",
       "note": "die Daueranweisung, eine klare Zeile"})
def project_note(project: str, note: str) -> str:
    from core.agency import ventures

    note = (note or "").strip()
    if not note:
        return "Keine Anweisung uebergeben — note ist leer."
    token = (project or "").strip()
    cands = ventures.list_all()
    hits = [v for v in cands if v["id"].startswith(token)] if token else []
    if not hits and token:
        low = token.lower()
        hits = [v for v in cands if low in (v.get("name") or "").lower()]
    if len(hits) == 1:
        v = hits[0]
        ventures.append_briefing(v["id"], note)
        return (f"Notiert im Projekt-Gedaechtnis von '{v['name']}': {note[:120]} — "
                f"gilt ab jetzt fuer jeden Task dieses Projekts.")
    if len(hits) > 1:
        names = ", ".join(v["name"] for v in hits[:5])
        return (f"MEHRDEUTIG: '{token}' passt auf mehrere Projekte ({names}). "
                f"Frag Sergen kurz, welches gemeint ist, und ruf project_note erneut auf.")
    names = ", ".join(v["name"] for v in cands[:6]) or "(noch keine Projekte angelegt)"
    return (f"KEIN TREFFER fuer '{token}'. Vorhandene Projekte: {names}. "
            f"Frag Sergen kurz, welches gemeint ist.")
