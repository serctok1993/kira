"""Widget-System (Werkbank PR 8): Kira liefert CONFIG, nie Code.

Widgets sind kleine Zusatz-Kacheln im Cockpit (z.B. Follower-Statistik), die
Kira selbst anlegen kann — als deklarative JSON-Datei in data/widgets/, NIE als
Code. Das Cockpit rendert sie mit drei festen, sicheren Renderern:

  metric — aktueller Wert einer Kennzahl + Sparkline (Quelle: /api/metrics)
  chart  — Balkenverlauf einer Kennzahl (Quelle: /api/metrics)
  list   — Liste aus einem WHITELISTETEN Endpunkt (z.B. digest.tasks_done)

Slots: zentrale | projekt | serc. Alles wird beim Laden UND beim Speichern
validiert; unbekannte Typen/Slots/Endpunkte fliegen raus. Kein eval, kein HTML
aus der Config — Titel & Werte werden im Frontend esc()-gesichert.
"""
from __future__ import annotations

import json
import re

from core.config import DATA_DIR

DIR = DATA_DIR / "widgets"
TYPES = ("metric", "chart", "list")
SLOTS = ("zentrale", "projekt", "serc")
# Nur lesende, unkritische Endpunkte — die einzige Tuer der list-Widgets.
LIST_ENDPOINTS = ("/api/digest", "/api/tagewerk", "/api/status", "/api/evolution")

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
_METRIC = re.compile(r"^[a-z0-9_.\-]{1,40}$")
_KEY = re.compile(r"^[a-z0-9_]{1,40}$")

# Erste Kachel zum Anfassen, solange noch nichts angelegt wurde (Sergens
# Beispiel aus dem Redesign-Auftrag). Verschwindet, sobald data/widgets existiert.
DEMO = {"id": "demo-follower", "title": "📈 Follower", "type": "metric",
        "slot": "zentrale", "metric": "follower", "demo": True}


def validate(cfg: dict) -> str:
    """Config pruefen — gibt '' zurueck oder den Fehler in Klartext."""
    if not isinstance(cfg, dict):
        return "Config muss ein Objekt sein"
    if not _ID.match(str(cfg.get("id") or "")):
        return "id: 2-40 Zeichen, nur a-z 0-9 und Bindestrich"
    title = str(cfg.get("title") or "")
    if not 1 <= len(title) <= 60:
        return "title: 1-60 Zeichen"
    typ = str(cfg.get("type") or "")
    if typ not in TYPES:
        return f"type muss eins sein von: {', '.join(TYPES)}"
    if str(cfg.get("slot") or "") not in SLOTS:
        return f"slot muss eins sein von: {', '.join(SLOTS)}"
    if typ in ("metric", "chart"):
        # gleiche Normalisierung wie _clean — 'Follower' ist ok und wird 'follower'
        if not _METRIC.match(str(cfg.get("metric") or "").strip().lower()):
            return "metric: Name der Kennzahl fehlt (a-z 0-9 _ . -)"
    if typ == "list":
        if str(cfg.get("endpoint") or "") not in LIST_ENDPOINTS:
            return f"endpoint muss whitelisted sein: {', '.join(LIST_ENDPOINTS)}"
        if not _KEY.match(str(cfg.get("key") or "")):
            return "key: Feldname im Endpunkt fehlt (a-z 0-9 _)"
    try:
        days = int(cfg.get("days", 30))
        limit = int(cfg.get("limit", 5))
    except (TypeError, ValueError):
        return "days/limit muessen Zahlen sein"
    if not (1 <= days <= 365 and 1 <= limit <= 10):
        return "days: 1-365, limit: 1-10"
    return ""


def _clean(cfg: dict) -> dict:
    """Nur bekannte Felder uebernehmen — nichts Fremdes schleppt sich in die Datei."""
    out = {"id": str(cfg["id"]), "title": str(cfg["title"]).strip(),
           "type": str(cfg["type"]), "slot": str(cfg["slot"])}
    if out["type"] in ("metric", "chart"):
        out["metric"] = str(cfg["metric"]).strip().lower()
        out["days"] = int(cfg.get("days", 30))
    if out["type"] == "list":
        out["endpoint"] = str(cfg["endpoint"])
        out["key"] = str(cfg["key"])
        out["limit"] = int(cfg.get("limit", 5))
    return out


def list_all() -> list[dict]:
    """Alle gueltigen Widgets (Demo, solange noch nie eines angelegt/geloescht wurde)."""
    if not DIR.exists():
        return [dict(DEMO)]
    out = []
    for p in sorted(DIR.glob("*.json")):
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if validate(cfg) == "":
                out.append(_clean(cfg))
        except Exception:  # noqa: BLE001 — kaputte Datei blockiert nicht den Rest
            continue
    return out


def save(cfg: dict) -> dict:
    err = validate(cfg)
    if err:
        return {"ok": False, "error": err}
    DIR.mkdir(parents=True, exist_ok=True)
    clean = _clean(cfg)
    (DIR / f"{clean['id']}.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "id": clean["id"]}


def delete(wid: str) -> bool:
    """Widget entfernen. Loeschen der Demo legt nur den (leeren) Ordner an —
    damit ist sie dauerhaft weg, ohne Sonderzustand."""
    if not _ID.match(str(wid or "")):
        return False
    DIR.mkdir(parents=True, exist_ok=True)
    p = DIR / f"{wid}.json"
    if p.exists():
        p.unlink()
        return True
    return wid == DEMO["id"]
