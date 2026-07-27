"""Pruefer (S2): selbst-geschriebene Akzeptanz-Checks + unabhaengige Bewertung.

Drei Schichten, bewusst in dieser Reihenfolge:
1. Kriterien: pro Task EINMAL generiert (billige Route), in tasks.acceptance gecacht —
   bei Retries werden dieselben Kriterien wiederverwendet (keine wandernden Torpfosten).
2. Harte Checks (0 Token): Ergebnis nicht leer, kein Degrade-Marker, Artefakt existiert,
   .py kompiliert, URL erreichbar. Schlaegt einer fehl -> sofort 'retry', Judge gespart.
3. LLM-Judge (Anti-Selbst-Beschoenigung): sieht NUR Kriterien + Ergebnis + Evidenz,
   NIE den Actor-Verlauf. Faellt der Judge aus -> fail-open ('pass', score NULL,
   verify_error-Event) — die Rueckkopplung darf den 24/7-Grind nie blockieren.
"""
from __future__ import annotations

import json
import re

from core.config import CONFIG
from core.kernel import events, llm_router

# Muss zum Text in act._degrade_text passen. Driftet der Wortlaut, verpasst der Check
# den Degrade nur (fail-open Richtung Judge) — kein Bruch.
_DEGRADE_MARKER = "⚠️ Ich bin bei einem Modell-/Netzwerk-Schritt"

_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")

_DEFAULT_CRITERIA: dict[str, list[dict]] = {
    "research": [
        {"text": "Beantwortet die Aufgabe konkret und nennt mindestens 2 nachpruefbare Quellen oder Belege"},
        {"text": "Endet mit einer klaren Schlussfolgerung oder Empfehlung, nicht nur Stichpunkten"},
    ],
    "produce": [
        {"text": "Nennt konkret die erstellten Artefakte mit Dateipfad"},
        {"text": "Das Ergebnis ist vollstaendig und direkt nutzbar — keine Platzhalter oder TODOs"},
    ],
    "publish": [
        {"text": "Nennt die konkrete Ziel-URL bzw. Plattform und bestaetigt die Veroeffentlichung"},
        {"text": "Der veroeffentlichte Inhalt entspricht der gestellten Aufgabe"},
    ],
}


def _cfg(key: str, default):
    o = CONFIG.get("outcomes") or {}
    return o.get(key, default) if isinstance(o, dict) else default


def _pass_score() -> int:
    return int(_cfg("pass_score", 70))


def max_quality_retries() -> int:
    return int(_cfg("max_quality_retries", 2))


def _verify_route() -> str:
    # Judge != Actor: der Denker (reason) benotet — Default haelt die Live-Config nach,
    # damit ein fehlender Config-Key den Richter nie still aufs Massen-Modell wirft.
    return str(_cfg("verifier_task_type", "reason"))


def generate_criteria(description: str, kind: str) -> list[dict]:
    """2–4 pruefbare Akzeptanzkriterien fuer einen Task. Bei JEDEM Fehler -> Default je kind."""
    fallback = _DEFAULT_CRITERIA.get(kind, _DEFAULT_CRITERIA["research"])
    system = (
        "Du schreibst Akzeptanzkriterien fuer die Arbeit eines autonomen Agenten. "
        "Antworte AUSSCHLIESSLICH mit einem JSON-Array aus 2 bis 4 kurzen Kriterien-Strings. "
        "Jedes Kriterium ist am ERGEBNIS-TEXT nachpruefbar (nicht am Prozess), konkret und binaer "
        'entscheidbar. Beispiel: ["Nennt mindestens 3 Quellen mit URL", "Enthaelt eine Preisspanne in EUR"]'
    )
    user = f"AUFGABE (Art: {kind}):\n{description[:1500]}\n\nNur das JSON-Array."
    try:
        res = llm_router.complete([{"role": "user", "content": user}], system=system,
                                  task_type=_verify_route(), escalate=False)
        m = re.search(r"\[.*\]", res["text"], re.DOTALL)
        items = json.loads(m.group(0)) if m else []
        criteria = [{"text": str(i)[:300]} for i in items if str(i).strip()][:4]
        return criteria if len(criteria) >= 2 else fallback
    except Exception as e:  # noqa: BLE001
        events.emit("verify_error", {"where": "generate_criteria", "error": str(e)[:300]})
        return fallback


def ensure_criteria(task: dict) -> list[dict]:
    """Kriterien lazy laden: gecacht in tasks.acceptance, sonst generieren + cachen."""
    raw = task.get("acceptance")
    if raw:
        try:
            crit = json.loads(raw)
            if isinstance(crit, list) and crit:
                return crit
        except Exception:  # noqa: BLE001
            pass  # kaputter Cache -> neu generieren
    crit = generate_criteria(task.get("description", ""), task.get("kind") or "research")
    try:
        from core.agency.missions import queue
        queue.update_task(task["id"], acceptance=json.dumps(crit, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass  # Cachen ist Komfort, kein Muss
    events.emit("task_criteria", {"id": task.get("id"), "criteria": [c["text"] for c in crit]})
    return crit


def _url_reachable(url: str) -> tuple[bool, str]:
    """Modul-global, damit Tests es monkeypatchen koennen (kein Netz in pytest)."""
    try:
        import httpx

        r = httpx.get(url, timeout=10, follow_redirects=True)
        return (r.status_code < 400, f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return (False, str(e)[:200])


def deterministic_checks(task: dict, result_text: str) -> list[dict]:
    """Harte, tokenfreie Checks. source='det'."""
    checks: list[dict] = []
    text = (result_text or "").strip()

    checks.append({"text": "Ergebnis ist substanziell (>= 50 Zeichen)", "ok": len(text) >= 50,
                   "evidence": f"{len(text)} Zeichen", "source": "det"})
    checks.append({"text": "Kein Modell-Ausfall (Degrade-Abbruch)", "ok": _DEGRADE_MARKER not in text,
                   "evidence": "Degrade-Marker gefunden" if _DEGRADE_MARKER in text else "ok",
                   "source": "det"})

    kind = task.get("kind") or "research"
    artifact = task.get("artifact_path")
    if kind == "produce" and artifact:
        from pathlib import Path

        p = Path(artifact)
        exists = p.is_file() and p.stat().st_size > 0
        checks.append({"text": f"Artefakt {artifact} existiert und ist nicht leer", "ok": exists,
                       "evidence": f"{p.stat().st_size} Bytes" if exists else "fehlt oder leer",
                       "source": "det"})
        if exists and p.suffix == ".py":
            import py_compile

            try:
                py_compile.compile(str(p), doraise=True)
                checks.append({"text": "Python-Artefakt kompiliert", "ok": True, "evidence": "py_compile ok",
                               "source": "det"})
            except Exception as e:  # noqa: BLE001
                checks.append({"text": "Python-Artefakt kompiliert", "ok": False,
                               "evidence": str(e)[:200], "source": "det"})
    if kind == "publish":
        m = _URL_RE.search(text)
        if m:
            ok, why = _url_reachable(m.group(0))
            checks.append({"text": f"Genannte URL erreichbar: {m.group(0)[:120]}", "ok": ok,
                           "evidence": why, "source": "det"})
        else:
            checks.append({"text": "Ergebnis nennt eine konkrete URL", "ok": False,
                           "evidence": "keine URL im Ergebnis", "source": "det"})
    return checks


def klartext(feedback: str) -> str:
    """Pruefer-Feedback in einen Satz uebersetzen, den ein Mensch versteht.

    Das `feedback` hat zwei Leser: den naechsten Versuch (braucht die harte Technik)
    und den Nutzer (braucht einen Satz). Live-Befund 27.07.: beim Nutzer landete
    woertlich "Harte Checks fehlgeschlagen: Ergebnis ist substanziell (>= 50 Zeichen)
    (0 Zeichen)" — eine Assertion, kein Satz. Das Judge-Feedback (freier Text vom
    Pruefmodell) ist meist schon verstaendlich und wird unveraendert durchgereicht."""
    f = (feedback or "").strip()
    if not f:
        return "Kein Prueferbefund vorhanden."
    if not f.startswith("Harte Checks fehlgeschlagen:"):
        return f
    rest = f.split(":", 1)[1]
    saetze = []
    for teil in rest.split(";"):
        t = teil.strip()
        if "substanziell" in t:
            saetze.append("Sie hat gar kein Ergebnis geliefert.")
        elif "Degrade" in t or "Modell-Ausfall" in t:
            saetze.append("Das Modell ist mitten in der Arbeit ausgefallen.")
        elif "Artefakt" in t and "kompiliert" in t:
            saetze.append("Der erzeugte Code laesst sich nicht ausfuehren.")
        elif "Artefakt" in t:
            saetze.append("Die Datei, die dabei entstehen sollte, wurde nicht angelegt.")
        elif "URL" in t:
            saetze.append("Der genannte Link funktioniert nicht.")
        elif t:
            saetze.append(t)
    return " ".join(saetze) or f


def _judge(criteria: list[dict], result_text: str, evidence_lines: list[str]) -> dict:
    """Unabhaengiger LLM-Pruefer. Sieht NUR Kriterien + Ergebnis + Evidenz."""
    crit_lines = "\n".join(f"{i}. {c['text']}" for i, c in enumerate(criteria, 1))
    user = (
        "Pruefe das ERGEBNIS eines Agenten-Tasks streng gegen die AKZEPTANZKRITERIEN.\n\n"
        f"AKZEPTANZKRITERIEN:\n{crit_lines}\n\n"
        f"ERGEBNIS:\n{(result_text or '')[:3500]}\n\n"
        f"HARTE EVIDENZ (bereits automatisch geprueft):\n" + "\n".join(evidence_lines) + "\n\n"
        'Antworte AUSSCHLIESSLICH mit JSON: {"criteria":[{"ok":true,"why":"..."}],'
        '"score":0-100,"verdict":"pass|retry","feedback":"was der naechste Versuch KONKRET anders machen soll"}'
    )
    system = (
        "Du bist ein strenger, unabhaengiger Pruefer. Du bewertest NUR das vorgelegte Ergebnis "
        "gegen die Kriterien — hoeflich formulierte Behauptungen ohne Substanz bestehen NICHT. "
        "Antworte strikt als JSON, nichts anderes."
    )
    res = llm_router.complete([{"role": "user", "content": user}], system=system,
                              task_type=_verify_route(), escalate=False)
    m = re.search(r"\{.*\}", res["text"], re.DOTALL)
    data = json.loads(m.group(0))
    score = max(0, min(100, int(data.get("score", 0))))
    return {
        "score": score,
        "feedback": str(data.get("feedback", ""))[:1000],
        "criteria_results": data.get("criteria", []),
        "cost_usd": float(res.get("cost_usd") or 0.0),
    }


def verify(task: dict, criteria: list[dict], result_text: str) -> dict:
    """Gesamturteil: harte Checks zuerst (Fail-fast), dann Judge. Fail-open bei Judge-Ausfall.

    -> {"score": int|None, "verdict": "pass"|"retry", "checks": [...], "feedback": str, "cost_usd": float}
    """
    checks = deterministic_checks(task, result_text)
    hard_fails = [c for c in checks if not c["ok"]]
    if hard_fails:
        feedback = "Harte Checks fehlgeschlagen: " + "; ".join(
            f"{c['text']} ({c['evidence']})" for c in hard_fails)
        # Kein Substanz-Ergebnis geliefert -> 10; geliefert, aber harter Check kaputt -> 40.
        substance_failed = any("substanziell" in c["text"] for c in hard_fails)
        return {"score": 10 if substance_failed else 40, "verdict": "retry",
                "checks": checks, "feedback": feedback[:1000], "cost_usd": 0.0}

    evidence = [f"- {c['text']}: OK ({c['evidence']})" for c in checks]
    try:
        j = _judge(criteria, result_text, evidence)
    except Exception as e:  # noqa: BLE001
        events.emit("verify_error", {"where": "judge", "task_id": task.get("id"), "error": str(e)[:300]})
        return {"score": None, "verdict": "pass", "checks": checks,
                "feedback": "", "cost_usd": 0.0}  # fail-open: Grind nie blockieren

    for i, cr in enumerate(j["criteria_results"][: len(criteria)]):
        checks.append({"text": criteria[i]["text"], "ok": bool(cr.get("ok")),
                       "evidence": str(cr.get("why", ""))[:200], "source": "llm"})
    verdict = "pass" if j["score"] >= _pass_score() else "retry"
    return {"score": j["score"], "verdict": verdict, "checks": checks,
            "feedback": j["feedback"], "cost_usd": j["cost_usd"]}
