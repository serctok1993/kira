"""Uebergabe-Preflight: EIN gruener Blick vor dem Start.

Baut auf doctor.check() auf (Modelle/Zugaenge/Abhaengigkeiten) und ergaenzt die
handover-spezifischen Signale: Laufen die aktivierten MCP-Server wirklich? Ist die
Wissensbasis befuellt? Ist ein Cloud-Modell erreichbar? Liefert eine Checkliste mit
klaren Zustaenden — damit ein fehlender Zugang VOR dem Arbeiten auffaellt, nicht
mittendrin. Wirft nie, kostet 0 Tokens.

Zustaende je Punkt:
  ok      — passt
  warn    — laeuft, aber eingeschraenkt (z.B. alles auf Lokal-Fallback)
  todo    — Sergen sollte etwas tun (kein Blocker, z.B. Wissensbasis leer)
  blocker — muss vor dem Start behoben werden
"""
from __future__ import annotations

from core.kernel import doctor


def _item(label: str, state: str, detail: str = "") -> dict:
    return {"label": label, "state": state, "detail": detail}


def check() -> dict:
    """Handover-Checkliste. {items: [...], ready: bool, blockers: int, todos: int}."""
    rep = doctor.check(test_call=False)
    items: list[dict] = []

    # --- Modell erreichbar ---
    routing = rep.get("routing") or {}
    all_local = bool(routing) and all(v.get("fallback") for v in routing.values())
    if not routing:
        items.append(_item("Modell-Routing", "blocker", "Routing nicht auswertbar."))
    elif all_local and not rep.get("ollama"):
        items.append(_item("Modell erreichbar", "blocker",
                           "Alle Routen auf Lokal-Fallback UND Ollama ist tot — kein Modell verfuegbar."))
    elif all_local:
        items.append(_item("Modell erreichbar", "warn",
                           "Laeuft komplett lokal (Ollama) — kein Cloud-Key aktiv. Fuer volle Qualitaet einen Schluessel unter Zugaenge setzen."))
    else:
        items.append(_item("Modell erreichbar", "ok", "Cloud-Modell aktiv."))

    # --- Abhaengigkeiten (harte Imports) ---
    imports = rep.get("imports") or {}
    kaputt = [m for m, ok in imports.items() if not ok and m in ("fastapi", "mcp", "playwright", "python_multipart")]
    if kaputt:
        items.append(_item("Abhaengigkeiten", "blocker", f"Fehlt/kaputt: {', '.join(kaputt)} — 'uv sync'."))
    else:
        items.append(_item("Abhaengigkeiten", "ok", "Kern-Pakete geladen."))

    # --- MCP-Voraussetzung + laufende Server ---
    if not rep.get("npx"):
        items.append(_item("MCP-Laufzeit (npx/node)", "warn",
                           "npx fehlt — MCP-Server koennen nicht starten. Node.js installieren."))
    else:
        items.append(_item("MCP-Laufzeit (npx/node)", "ok", "node & npx vorhanden."))
    try:
        from core.agency.mcp import registry_bridge

        st = registry_bridge.server_status()
        aktiviert = {n: s for n, s in st.items() if s.get("enabled")}
        tot = [n for n, s in aktiviert.items() if not s.get("running")]
        if not st:
            items.append(_item("MCP-Server", "todo",
                               "Noch keiner angeschlossen — im MCP-Universum aus dem Katalog waehlen (optional)."))
        elif tot:
            items.append(_item("MCP-Server", "warn",
                               f"Aktiviert, aber nicht gestartet: {', '.join(tot)} (Zugang/Setup pruefen)."))
        else:
            items.append(_item("MCP-Server", "ok", f"{len(aktiviert)} aktiv und laufend."))
    except Exception as e:  # noqa: BLE001
        items.append(_item("MCP-Server", "warn", f"Status nicht lesbar: {str(e)[:80]}"))

    # --- Wissensbasis befuellt ---
    try:
        from core.mind import knowledge

        docs = knowledge.list_docs(limit=1)
        if docs:
            items.append(_item("Wissensbasis", "ok", "Dokumente vorhanden."))
        else:
            items.append(_item("Wissensbasis", "todo",
                               "Noch leer — Projekt-Unterlagen unter Wissen hochladen (optional, aber hilft ab Tag 1)."))
    except Exception as e:  # noqa: BLE001
        items.append(_item("Wissensbasis", "warn", f"nicht lesbar: {str(e)[:80]}"))

    # --- Ollama/Embeddings (semantisches Gedaechtnis) ---
    if rep.get("ollama"):
        items.append(_item("Embeddings (Ollama)", "ok", "erreichbar — semantisches Erinnern aktiv."))
    else:
        items.append(_item("Embeddings (Ollama)", "warn",
                           "Ollama-Port 11434 tot — Gedaechtnis faellt auf Stichwortsuche zurueck."))

    # --- Plattenplatz ---
    free = rep.get("disk_free_gb")
    if isinstance(free, (int, float)) and free < 5:
        items.append(_item("Plattenplatz", "warn", f"nur {free} GB frei."))

    blockers = sum(1 for i in items if i["state"] == "blocker")
    todos = sum(1 for i in items if i["state"] == "todo")
    return {"items": items, "ready": blockers == 0, "blockers": blockers, "todos": todos,
            "warns": sum(1 for i in items if i["state"] == "warn")}
