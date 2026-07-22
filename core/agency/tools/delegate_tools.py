"""Delegation (v1): Kira wird Dirigentin — Unteragenten nach RANG statt Modellname.

Raenge (Rang im Code, Modell in config models.routing — Modellwechsel = eine Zeile):
  reflex   -> routing.classify  (lokal, 0 EUR)      triviale Zuarbeit
  arbeiter -> routing.worker    (billig, Cents)     delegierte Teilaufgaben, Masse
  denker   -> routing.reason    (Mittelklasse)      Reasoning-Zuarbeit
  richter  -> escalation_model  (staerkstes Modell) seltene, finale Urteile

Ein Unteragent ist eine frische act()-Schleife mit eigener Session (sub-<parent>-<n>),
eigenem Schritt-Deckel und Kosten-Deckel. Er hat KEIN Gedaechtnis und darf NICHT
weiterdelegieren (Tiefen-Sperre) — nur Kira bleibt Kira. `delegate` ist ein einzelner,
synchroner Unteragent; `schwarm` (v2) faechert eine Liste ECHT PARALLEL auf (gedeckelter
Thread-Pool, da die act-Schleifen netzgebunden warten) und aggregiert die Ergebnisse —
mit einem eigenen Schwarm-Budget als Bremse (global bremst zusaetzlich governance).

Der Richter liest nie 'alle Akten': er bekommt ein Brief (Insights + Dossier) und
schreibt seine Kernerkenntnis in data/workspace/richter-dossier.md zurueck
(Lernen in Dateien, Hausprinzip).
"""
from __future__ import annotations

import concurrent.futures as _futures
import time as _time
import uuid

from core.config import CONFIG, DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write
from core.agency.tools.registry import tool

# P5: Rang -> (task_type, escalate) kommt aus der EINEN Rollen-Quelle (core/agency/rollen.py
# — dort stehen auch Toolset + Schritte je Etage, abfragbar fuer die Werkstatt).
# Nur ETAGEN sind delegierbar — "haupt" (unteragent=False) ist Kiras eigener Chat-Hut.
from core.agency import rollen as _rollen

_RANG = {r: (d["task_type"], d["escalate"]) for r, d in _rollen.ROLLEN.items()
         if d.get("unteragent", True)}

_DOSSIER = DATA_DIR / "workspace" / "richter-dossier.md"
_DOSSIER_CAP = 8000

# Fakten-Treue (gegen das Dazu-Dichten in der Uebergabe-Kette): jeder Unteragent
# liefert FAKT und VERMUTUNG getrennt — der Orchestrator darf nur FAKTEN verbauen.
_BERICHTSFORMAT = (
    "\n\nBERICHTSFORMAT (bindend): Trenne am Ende FAKT (mit Quelle) von VERMUTUNG. "
    "Fehlende Information heisst 'unbekannt' — NIE erfinden, NIE ausschmuecken.")

# Tiefen-Sperre: solange EINE Delegation ODER ein Schwarm laeuft, darf ein Unteragent
# nicht weiterdelegieren (keine Agenten-Pyramiden). Modul-Flag statt LLM-Disziplin —
# verlaesslich, auch wenn das Modell keine session_id mitgibt. Der Schwarm haelt das Flag
# fuer den GESAMTEN Parallel-Block (nicht je Unteragent) — sonst loeste der erste fertige
# Agent die Sperre, waehrend die anderen noch laufen. Darum toggelt _run_agent es NIE selbst.
_AKTIV = False


def _cfg() -> dict:
    d = CONFIG.get("agency", {}).get("delegate")
    return d if isinstance(d, dict) else {}


def _steps_for(rang: str) -> int:
    defaults = {r: d["schritte"] for r, d in _rollen.ROLLEN.items()
                if d.get("unteragent", True)}
    try:
        return int(_cfg().get("schritte", {}).get(rang, defaults[rang]))
    except Exception:  # noqa: BLE001
        return defaults.get(rang, 12)


def _kosten_deckel() -> float:
    try:
        return float(_cfg().get("max_kosten_eur", 1.0))
    except Exception:  # noqa: BLE001
        return 1.0


def _int_cfg(key: str, default: int) -> int:
    try:
        return int(_cfg().get(key, default))
    except Exception:  # noqa: BLE001
        return default


def _float_cfg(key: str, default: float) -> float:
    try:
        return float(_cfg().get(key, default))
    except Exception:  # noqa: BLE001
        return default


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


def _run_agent(auftrag: str, rang: str, session_id: str | None, schritte: str = "") -> dict:
    """Fuehrt EINEN Unteragenten aus (frische act-Schleife) und gibt sein Ergebnis strukturiert
    zurueck: {sid, rang, text, ok}. Setzt bewusst NICHT das _AKTIV-Flag — die Tiefen-Sperre
    haelt der Aufrufer (delegate: je Call, schwarm: fuer den ganzen Parallel-Block). So bleibt
    die Sperre auch bei parallelen Agenten dicht (kein zu fruehes finally). Thread-sicher:
    frische Session-ID je Agent, keine gemeinsamen Zustands-Mutationen."""
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
    try:
        from core.agency.act import act  # lazy: act.py importiert builtin (Zirkularitaet)

        # P5: der Unteragent sieht NUR das Toolset seines Rangs (rollen.py)
        res = act(prompt, session_id=sid, max_steps=max_steps, escalate=escalate,
                  task_type=task_type, rolle=rang)
        text = (res.get("text") or "").strip() or "(kein Ergebnis)"
    except Exception as e:  # noqa: BLE001 — Werkzeuge liefern Strings, raisen nie
        events.emit("delegate_error", {"sub": sid, "error": str(e)[:200]}, session_id=session_id)
        return {"sid": sid, "rang": rang, "text": f"Delegation fehlgeschlagen ({rang}): {e}", "ok": False}

    if rang == "richter":
        _dossier_nachtragen(text)
    events.emit("delegate_done", {"rang": rang, "sub": sid, "chars": len(text)},
                session_id=session_id)
    return {"sid": sid, "rang": rang, "text": text, "ok": True}


def _delegiere(auftrag: str, rang: str, session_id: str | None, schritte: str = "") -> str:
    """EIN synchroner Unteragent (das delegate-Werkzeug). Haelt _AKTIV fuer die Dauer und
    misst die Kosten dieser einen Delegation (global bremst zusaetzlich governance)."""
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

    _AKTIV = True
    try:
        r = _run_agent(auftrag, rang, session_id, schritte)
        # P5 spawn-and-retry-once (grok-Muster): scheitert der Rang HART (Exception im
        # Unteragenten), GENAU EIN neuer Versuch eine Etage hoeher — danach ist Schluss.
        if not r["ok"]:
            hoeher = _rollen.eskalation(rang)
            if hoeher:
                events.emit("delegate_retry", {"von": rang, "nach": hoeher, "sub": r["sid"]},
                            session_id=session_id)
                r = _run_agent(auftrag, hoeher, session_id, schritte)
                if r["ok"]:
                    r["rang"] = f"{hoeher} (eskaliert von {rang})"
    finally:
        _AKTIV = False

    kosten = ""
    try:
        from core.governance import treasury

        if start_spend is not None:
            diff = treasury.today_spend() - start_spend
            kosten = f" | Kosten ~{diff:.3f} EUR"
            if diff > _kosten_deckel():
                events.emit("delegate_over_budget", {"sub": r["sid"], "eur": round(diff, 3)},
                            session_id=session_id)
                kosten += f" (UEBER Deckel {_kosten_deckel():.2f} EUR — naechstes Mal kleiner delegieren)"
    except Exception:  # noqa: BLE001
        pass

    return f"[{r['rang']} · {r['sid']}{kosten}]\n{r['text']}"


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


def _schwarm_budget_reached(start_spend: float | None, budget: float) -> bool:
    """Hat DIESER Schwarm sein Euro-Budget schon verbraucht? -> keine neuen Agenten mehr
    starten. Weiche Decke (laufende Agenten enden noch); die harte Tages-Bremse haelt
    governance in jedem einzelnen LLM-Call. So kann kein Massen-Schwarm den Tag sprengen."""
    if start_spend is None or budget <= 0:
        return False
    try:
        from core.governance import treasury

        return (treasury.today_spend() - start_spend) > budget
    except Exception:  # noqa: BLE001
        return False


@tool("schwarm",
      "Faechert einen Auftrag ECHT PARALLEL ueber eine LISTE auf: pro Zeile ein Unteragent, "
      "alle laufen gleichzeitig (gedeckelter Pool), Ergebnisse kommen nummeriert + mit "
      "Kurz-Bilanz (fertig/Fehler/Kosten/Dauer) zurueck. Fuer gleichfoermige Massenarbeit "
      "(z.B. 50 Friseure recherchieren, jeder findet 5 Leads). In der Vorlage steht {item} "
      "als Platzhalter fuer das jeweilige Listen-Element.",
      {"auftrag_vorlage": "Auftrag mit {item}-Platzhalter, z.B. 'Recherchiere kurz: {item}'",
       "liste": "die Items, EINE pro Zeile",
       "rang": "optional: Rang der Arbeiter (Standard arbeiter)",
       "session_id": "optional: wird automatisch gesetzt"})
def _items_aus(liste) -> list[str]:
    """Nacht-Fund 22.07.: Modelle geben die Liste natuerlich als JSON-Array — das
    crashte roh ("'list' object has no attribute 'splitlines'"). Durchreichen statt
    belehren: echte Listen werden angenommen, Strings weiter zeilenweise."""
    if isinstance(liste, (list, tuple)):
        return [str(x).strip() for x in liste if str(x).strip()]
    return [ln.strip() for ln in str(liste or "").splitlines() if ln.strip()]


def schwarm(auftrag_vorlage: str, liste: str, rang: str = "arbeiter", session_id: str = "") -> str:
    global _AKTIV
    if _AKTIV or (session_id or "").startswith("sub-"):
        return "Schwarm verweigert: Du bist selbst ein Unteragent."
    rang = (rang or "arbeiter").strip().lower()
    if rang not in _RANG:
        return f"Unbekannter Rang '{rang}'. Verfuegbar: {', '.join(_RANG)}."
    items = _items_aus(liste)
    if not items:
        return "Schwarm ohne Liste — gib die Items eine pro Zeile an."

    cap = _int_cfg("schwarm_max", 50)
    parallel = max(1, _int_cfg("schwarm_parallel", 6))
    budget = _float_cfg("schwarm_budget_eur", 5.0)
    uebrig = len(items) - cap
    items = items[:cap]

    def _auftrag_for(item: str) -> str:
        return (auftrag_vorlage.replace("{item}", item) if "{item}" in auftrag_vorlage
                else f"{auftrag_vorlage}\n\nITEM: {item}")

    try:
        from core.governance import treasury

        start_spend = treasury.today_spend()
    except Exception:  # noqa: BLE001
        start_spend = None

    events.emit("schwarm_start", {"items": len(items), "parallel": parallel, "rang": rang,
                                  "budget_eur": budget}, session_id=session_id)
    t0 = _time.time()

    def _work(item: str) -> dict:
        # Budget-Bremse am Agenten-Start: der gedeckelte Pool startet spaetere Agenten erst,
        # wenn fruehere fertig sind -> sie sehen den akkumulierten Verbrauch und stoppen sauber.
        if _schwarm_budget_reached(start_spend, budget):
            return {"text": f"(uebersprungen — Schwarm-Budget {budget:.2f} EUR erreicht)",
                    "ok": False, "skipped": True}
        return _run_agent(_auftrag_for(item), rang, session_id or None)

    # Tiefen-Sperre fuer den GESAMTEN Parallel-Block halten (nicht je Agent) — sonst loeste
    # der erste fertige Agent die Sperre, waehrend die anderen noch laufen.
    _AKTIV = True
    try:
        with _futures.ThreadPoolExecutor(max_workers=parallel) as ex:
            results = list(ex.map(_work, items))  # map -> Ergebnisse in Listen-Reihenfolge
    finally:
        _AKTIV = False

    fertig = sum(1 for r in results if r.get("ok"))
    skipped = sum(1 for r in results if r.get("skipped"))
    fehler = len(results) - fertig - skipped
    dauer = _time.time() - t0
    kosten = ""
    if start_spend is not None:
        try:
            from core.governance import treasury

            kosten = f" · ~{treasury.today_spend() - start_spend:.3f} EUR"
        except Exception:  # noqa: BLE001
            pass

    events.emit("schwarm_done", {"items": len(items), "fertig": fertig, "fehler": fehler,
                                 "skipped": skipped, "dauer_s": round(dauer, 1)},
                session_id=session_id)

    head = (f"🐝 Schwarm: {len(items)} Agenten parallel · {fertig} fertig"
            + (f" · {fehler} Fehler" if fehler else "")
            + (f" · {skipped} budget-gestoppt" if skipped else "")
            + kosten + f" · {dauer:.0f}s")
    out = [head]
    for i, (item, r) in enumerate(zip(items, results), 1):
        out.append(f"### {i}/{len(items)} — {item[:60]}\n{r['text']}")
    if uebrig > 0:
        out.append(f"(… {uebrig} weitere Items uebersprungen — schwarm_max={cap}; in Wellen arbeiten.)")
    return "\n\n".join(out)
