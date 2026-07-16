"""Auftrags-Store (P1, Working-Modus): der Plan lebt im HARNESS, nicht im Kontextfenster.

EIN aktiver Auftrag (data/auftrag.json): Ziel, nummerierte Schritte mit Status,
optionale Huerde. Der Chat-Prompt bekommt den Plan bei JEDEM Zug kompakt ans
PROMPT-ENDE (Werkstatt-Messung: +11 Punkte vs. Anfang) — das Modell muss nur
den NAECHSTEN offenen Schritt perfekt machen. "Malen nach Zahlen."

Kein aktiver Auftrag = leerer Prompt-Block = byte-identischer Prompt
(dasselbe Muster wie ARBEITSWEISE.md; der P6-Golden-Test bleibt gruen).
"""
from __future__ import annotations

import json
import time

from core.config import ROOT
from core.kernel import events

_PATH = ROOT / "data" / "auftrag.json"

STATI = ("offen", "laeuft", "fertig", "verworfen")
_MAX_SCHRITTE = 20


def _melden(typ: str, payload: dict) -> None:
    """Live-Ops-Beleg — Telemetrie darf den Store NIE brechen (W0-Geist)."""
    try:
        events.emit(typ, payload)
    except Exception:  # noqa: BLE001
        pass


def get() -> dict:
    """Aktiver Auftrag oder {} — raist nie."""
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if d.get("ziel") else {}
    except Exception:  # noqa: BLE001
        return {}


def _speichern(d: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def set_plan(ziel: str, schritte: list[str]) -> dict:
    """Neuen Auftrag anlegen (ersetzt einen bestehenden bewusst — Pruefung macht das Tool)."""
    d = {"ziel": (ziel or "").strip()[:300],
         "schritte": [{"nr": i + 1, "text": s.strip()[:300], "status": "offen"}
                      for i, s in enumerate(schritte[:_MAX_SCHRITTE]) if s.strip()],
         "huerde": "", "ts": time.time()}
    _speichern(d)
    _melden("auftrag_plan", {"ziel": d["ziel"], "schritte": len(d["schritte"])})
    return d


def update(nr: int, status: str, notiz: str = "") -> tuple[dict | None, str]:
    """Schritt-Status setzen; status='huerde' notiert die Huerde am Auftrag.
    Liefert (auftrag, '') oder (None, lehrender Fehler)."""
    d = get()
    if not d:
        return None, "Kein aktiver Auftrag. Lege zuerst einen an: todo_plan(ziel, schritte)."
    treffer = next((s for s in d["schritte"] if s["nr"] == nr), None)
    if treffer is None:
        gueltig = ", ".join(str(s["nr"]) for s in d["schritte"])
        return None, f"Schritt {nr} gibt es nicht. Gueltige Nummern: {gueltig}."
    if status == "huerde":
        if not (notiz or "").strip():
            return None, ("Eine Huerde braucht die notiz: was blockiert konkret? "
                          "Beispiel: todo_update(2, \"huerde\", \"API-Key fehlt\").")
        d["huerde"] = notiz.strip()[:300]
    elif status in STATI:
        treffer["status"] = status
        if notiz.strip():
            treffer["notiz"] = notiz.strip()[:200]
        if status in ("fertig", "verworfen") and d.get("huerde"):
            d["huerde"] = ""                      # Huerde gilt als ueberwunden
    else:
        return None, (f"Unbekannter Status '{status}'. Erlaubt: "
                      f"{', '.join(STATI)} oder 'huerde' (mit notiz).")
    d["ts"] = time.time()
    _speichern(d)
    _melden("auftrag_update", {"nr": nr, "status": status, "notiz": (notiz or "")[:120]})
    return d, ""


def clear() -> None:
    _speichern({"ziel": "", "schritte": [], "huerde": "", "ts": time.time()})
    _melden("auftrag_clear", {})


def _zeile(s: dict) -> str:
    mark = {"offen": "[ ]", "laeuft": "[>]", "fertig": "[x]", "verworfen": "[-]"}[s["status"]]
    notiz = f"  ({s['notiz']})" if s.get("notiz") else ""
    return f"{mark} {s['nr']}. {s['text']}{notiz}"


def klartext() -> str:
    """Der Plan als lesbarer Block — fuer plan_list, Tool-Rueckgaben und die UI."""
    d = get()
    if not d:
        return "(kein aktiver Auftrag)"
    zeilen = [f"Ziel: {d['ziel']}"] + [_zeile(s) for s in d["schritte"]]
    if d.get("huerde"):
        zeilen.append(f"! Huerde: {d['huerde']}")
    offen = [s for s in d["schritte"] if s["status"] in ("offen", "laeuft")]
    if offen:
        zeilen.append(f"-> Naechster Schritt: Nr. {offen[0]['nr']}")
    else:
        zeilen.append("-> Alle Schritte erledigt — Auftrag abschliessbar.")
    return "\n".join(zeilen)


def prompt_block() -> str:
    """Der Plan fuers PROMPT-ENDE — '' ohne aktiven Auftrag (= byte-identischer Prompt)."""
    d = get()
    if not d:
        return ""
    return ("\n\n# DEIN AKTIVER AUFTRAG (der Harness fuehrt die Liste — erledige NUR den "
            "naechsten offenen Schritt, dann todo_update(nr, \"fertig\"))\n" + klartext())
