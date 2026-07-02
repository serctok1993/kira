"""Wissens-Werkzeuge: Kiras Griff in Sergens Archiv (S5).

Werkzeug-basierter Abruf statt Prompt-Injektion (Kontext-Diaet): Kira sucht
gezielt, wenn eine Frage Sergens Dokumente/gefuettertes Wissen betrifft.
"""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("knowledge_search",
      "Durchsucht Sergens Wissens-Archiv (hochgeladene Dokumente, Notizen, gefuettertes Wissen). "
      "Nutze es bei Fragen zu seinen Unterlagen, Projekten oder frueher gefuettertem Wissen.",
      {"query": "wonach suchen", "k": "optional: wie viele Treffer (Standard 5)"})
def knowledge_search(query: str, k: str = "5") -> str:
    from core.mind import knowledge

    try:
        n = max(1, min(10, int(k)))
    except ValueError:
        n = 5
    hits = knowledge.search(query, k=n)
    if not hits:
        return "Nichts gefunden im Archiv. (knowledge_list zeigt, was ueberhaupt drin ist.)"
    out = []
    for h in hits:
        head = f"[{h['title']} · Abschnitt {h['chunk_no'] + 1}]"
        out.append(f"{head}\n{h['text'][:700]}")
    return "\n\n".join(out)


@tool("knowledge_list", "Zeigt, welche Dokumente/Notizen in Sergens Wissens-Archiv liegen.", {})
def knowledge_list() -> str:
    from core.mind import knowledge

    docs = knowledge.list_docs(limit=40)
    if not docs:
        return "Archiv ist noch leer. Sergen kann im Cockpit (Wissen) hochladen oder dir Dateien per Telegram schicken."
    total = sum(d.get("chunks") or 0 for d in docs)
    lines = [f"{len(docs)} Dokumente, {total} Abschnitte:"]
    for d in docs:
        kb = round((d.get("bytes") or 0) / 1024)
        lines.append(f"- ({d['id'][:8]}) {d['title'][:70]} [{d['source']}, {kb} KB, {d['chunks']} Abschnitte]")
    return "\n".join(lines)


@tool("knowledge_note",
      "Legt eine Notiz/Wissen dauerhaft in Sergens Archiv ab (fuer Groesseres — kleine Fakten "
      "gehoeren in remember_fact).",
      {"title": "kurzer Titel", "text": "der Inhalt"})
def knowledge_note(title: str, text: str) -> str:
    from core.mind import knowledge

    res = knowledge.ingest_text(title, text, source="note")
    if not res.get("ok"):
        return f"Konnte nicht ablegen: {res.get('error')}"
    if res.get("duplicate"):
        return f"Kenne ich schon (Duplikat von: {res.get('title')})."
    return f"Im Archiv abgelegt: {title[:80]} ({res['chunks']} Abschnitte)."
