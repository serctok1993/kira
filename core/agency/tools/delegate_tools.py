"""Delegation (v1): Kira wird Dirigentin — Unteragenten nach RANG statt Modellname.

Raenge (Rang im Code, Modell in config models.routing — Modellwechsel = eine Zeile):
  reflex   -> routing.classify  (lokal, 0 EUR)      triviale Zuarbeit
  arbeiter -> routing.worker    (billig, Cents)     delegierte Teilaufgaben, Masse
  denker   -> routing.reason    (Mittelklasse)      Reasoning-Zuarbeit
  richter  -> escalation_model  (staerkstes Modell) seltene, finale Urteile

Ein Unteragent ist eine frische act()-Schleife mit eigener Session (sub-<parent>-<n>),
eigenem Schritt-Deckel und Kosten-Deckel. Er hat KEIN Gedaechtnis und darf NICHT
weiterdelegieren (Tiefen-Sperre) — nur Kira bleibt Kira. v1 ist bewusst sequenziell.

Der Richter liest nie 'alle Akten': er bekommt ein Brief (Insights + Dossier) und
schreibt seine Kernerkenntnis in data/workspace/richter-dossier.md zurueck
(Lernen in Dateien, Hausprinzip).
"""
from __future__ import annotations

import uuid

from core.config import CONFIG, DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write
from core.agency.tools.registry import tool

# Rang -> (task_type fuer resolve_model, escalate). Neue routing-Keys brauchen
# KEINE Code-Aenderung (resolve_model faellt sonst auf default zurueck).
_RANG = {
    "reflex":   ("classify", False),
    "arbeiter": ("worker", False),
    "denker":   ("reason", False),
    "richter":  ("reason", True),   # escalate -> escalation_model (der Richter)
}

_DOSSIER = DATA_DIR / "workspace" / "richter-dossier.md"
_DOSSIER_CAP = 8000

# Fakten-Treue (gegen das Dazu-Dichten in der Uebergabe-Kette): jeder Unteragent
# liefert FAKT und VERMUTUNG getrennt — der Orchestrator darf nur FAKTEN verbauen.
_BERICHTSFORMAT = (
    "\n\nBERICHTSFORMAT (bindend): Trenne am Ende FAKT (mit Quelle) von VERMUTUNG. "
    "Fehlende Information heisst 'unbekannt' — NIE erfinden, NIE ausschmuecken.")

# Tiefen-Sperre: solange eine Delegation laeuft (v1 = synchron), darf der Unteragent
# nicht weiterdelegieren. Modul-Flag statt LLM-Disziplin — verlaesslich, auch wenn das
# Modell keine session_id mitgibt.
_AKTIV = False


def _cfg() -> dict:
    d = CONFIG.get("agency", {}).get("delegate")
    return d if isinstance(d, dict) else {}


def _steps_for(rang: str) -> int:
    defaults = {"reflex": 6, "arbeiter": 12, "denker": 20, "richter": 12}
    try:
        return int(_cfg().get("schritte", {}).get(rang, defaults[rang]))
    except Exception:  # noqa: BLE001
        return defaults.get(rang, 12)


def _kosten_deckel() -> float:
    try:
        return float(_cfg().get("max_kosten_eur", 1.0))
    except Exception:  # noqa: BLE001
        return 1.0


def _richter_brief() -> str:
    """Vorbereitetes Brief fuer den Richter: Insights + Dossier statt 'alle Akten'."""
    parts: list[str] = []
    try:
        from core.agency import insights

        b = insights.render_brief(days=14, max_chars=500)
        if b:
            parts.append(b)
    except Exception:  # noqa: BLE001
        pass
    try:
        if _DOSSIER.exists():
            parts.append("DEIN DOSSIER (deine frueheren Kernerkenntnisse):\n"
                         + _DOSSIER.read_text(encoding="utf-8")[-3000:])
    except Exception:  # noqa: BLE001
        pass
    return "\n\n".join(parts)


def _dossier_nachtragen(urteil: str) -> None:
    """Kernerkenntnis ans Richter-Dossier anhaengen (gekappt, atomar)."""
    try:
        import time as _t

        kern = urteil.strip()[-500:]
        alt = _DOSSIER.read_text(encoding="utf-8") if _DOSSIER.exists() else "# Richter-Dossier\n"
        neu = alt + f"\n## {_t.strftime('%Y-%m-%d %H:%M')}\n{kern}\n"
        if len(neu) > _DOSSIER_CAP:  # aelteste Eintraege raus, Kopfzeile behalten
            neu = "# Richter-Dossier\n…(gekappt)…\n" + neu[-_DOSSIER_CAP:]
        atomic_write(_DOSSIER, neu)
    except Exception:  # noqa: BLE001
        pass


def _sub_session(session_id: str | None) -> str:
    parent = (session_id or "solo").replace("sub-", "")[:8]
    return f"sub-{parent}-{uuid.uuid4().hex[:4]}"


def _delegiere(auftrag: str, rang: str, session_id: str | None, schritte: str = "") -> str:
    global _AKTIV
    rang = (rang or "arbeiter").strip().lower()
    if rang not in _RANG:
        return f"Unbekannter Rang '{rang}'. Verfuegbar: {', '.join(_RANG)}."
    # Tiefen-Sperre: Unteragenten delegieren nicht weiter (keine Agenten-Pyramiden).
    if _AKTIV or (session_id or "").startswith("sub-"):
        return "Delegation verweigert: Du bist selbst ein Unteragent — erledige den Auftrag direkt."
    # Kosten-Deckel je Delegation: vorher Stand merken, global bremst weiterhin governance.
    try:
        from core.governance import treasury

        start_spend = treasury.today_spend()
    except Exception:  # noqa: BLE001
        start_spend = None

    task_type, escalate = _RANG[rang]
    try:
        max_steps = int(schritte) if str(schritte).strip() else _steps_for(rang)
    except Exception:  # noqa: BLE001
        max_steps = _steps_for(rang)
    max_steps = max(1, min(max_steps, 40))

    prompt = auftrag.strip() + _BERICHTSFORMAT
    if rang == "richter":
        brief = _richter_brief()
        if brief:
            prompt = f"{brief}\n\n---\nDEIN URTEILSAUFTRAG:\n{prompt}"

    sid = _sub_session(session_id)
    events.emit("delegate_start", {"rang": rang, "auftrag": auftrag[:160], "sub": sid},
                session_id=session_id)
    _AKTIV = True
    try:
        from core.agency.act import act  # lazy: act.py importiert builtin (Zirkularitaet)

        res = act(prompt, session_id=sid, max_steps=max_steps, escalate=escalate, task_type=task_type)
        text = (res.get("text") or "").strip() or "(kein Ergebnis)"
    except Exception as e:  # noqa: BLE001 — Werkzeuge liefern Strings, raisen nie
        events.emit("delegate_error", {"sub": sid, "error": str(e)[:200]}, session_id=session_id)
        return f"Delegation fehlgeschlagen ({rang}): {e}"
    finally:
        _AKTIV = False

    kosten = ""
    try:
        from core.governance import treasury

        if start_spend is not None:
            diff = treasury.today_spend() - start_spend
            kosten = f" | Kosten ~{diff:.3f} EUR"
            if diff > _kosten_deckel():
                events.emit("delegate_over_budget", {"sub": sid, "eur": round(diff, 3)},
                            session_id=session_id)
                kosten += f" (UEBER Deckel {_kosten_deckel():.2f} EUR — naechstes Mal kleiner delegieren)"
    except Exception:  # noqa: BLE001
        pass

    if rang == "richter":
        _dossier_nachtragen(text)
    events.emit("delegate_done", {"rang": rang, "sub": sid, "chars": len(text)},
                session_id=session_id)
    return f"[{rang} · {sid}{kosten}]\n{text}"


@tool("delegate",
      "Delegiert EINEN Auftrag an einen Unteragenten nach RANG: reflex (lokal 0 EUR, trivial) | "
      "arbeiter (billig, Standard) | denker (Reasoning) | richter (staerkstes Modell, NUR finale "
      "Urteile - selten benutzen!). Der Unteragent hat frischen Kontext und eigene Werkzeuge; "
      "gib ihm ALLES Noetige im Auftrag mit.",
      {"auftrag": "der vollstaendige, in sich geschlossene Auftrag",
       "rang": "optional: reflex|arbeiter|denker|richter (Standard arbeiter)",
       "schritte": "optional: max. Werkzeug-Runden des Unteragenten",
       "session_id": "optional: wird automatisch gesetzt"})
def delegate(auftrag: str, rang: str = "arbeiter", schritte: str = "", session_id: str = "") -> str:
    return _delegiere(auftrag, rang, session_id or None, schritte)


@tool("schwarm",
      "Faechert einen Auftrag ueber eine LISTE auf: pro Zeile ein Unteragent (Rang arbeiter), "
      "Ergebnisse nummeriert zurueck. Fuer gleichfoermige Massenarbeit (z.B. 5 Leads recherchieren). "
      "In der Vorlage steht {item} als Platzhalter.",
      {"auftrag_vorlage": "Auftrag mit {item}-Platzhalter, z.B. 'Recherchiere kurz: {item}'",
       "liste": "die Items, EINE pro Zeile",
       "rang": "optional: Rang der Arbeiter (Standard arbeiter)",
       "session_id": "optional: wird automatisch gesetzt"})
def schwarm(auftrag_vorlage: str, liste: str, rang: str = "arbeiter", session_id: str = "") -> str:
    if _AKTIV or (session_id or "").startswith("sub-"):
        return "Schwarm verweigert: Du bist selbst ein Unteragent."
    items = [ln.strip() for ln in (liste or "").splitlines() if ln.strip()]
    if not items:
        return "Schwarm ohne Liste — gib die Items eine pro Zeile an."
    try:
        cap = int(_cfg().get("schwarm_max", 8))
    except Exception:  # noqa: BLE001
        cap = 8
    uebrig = len(items) - cap
    items = items[:cap]
    out = []
    for i, item in enumerate(items, 1):
        auftrag = auftrag_vorlage.replace("{item}", item) if "{item}" in auftrag_vorlage \
            else f"{auftrag_vorlage}\n\nITEM: {item}"
        out.append(f"### {i}/{len(items)} — {item[:60]}\n" + _delegiere(auftrag, rang, session_id or None))
    if uebrig > 0:
        out.append(f"(… {uebrig} weitere Items uebersprungen — schwarm_max={cap}; in Wellen arbeiten.)")
    return "\n\n".join(out)
