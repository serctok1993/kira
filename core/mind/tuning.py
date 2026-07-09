"""Tuning-Werkbank: Kiras eigenes LLM-Trainingsmaterial (Phase 1 der Unschlagbar-Kombi).

Sergens Plan: das Lokalmodell (Qwen) auf Kiras STRUKTUR finetunen — Werkzeug-Protokoll,
Arbeitsdisziplin, Ton — und spaeter mit Wochen echter Nutzung nachschaerfen. Dieses Modul
liefert beide Zutaten und mischt sie zu einem trainingsfertigen Datensatz.

WICHTIG (Sergens Bedingung): Kira selbst trainiert NICHTS und haengt an KEINEM Modell.
Dieses Modul ist rein passiv — es sammelt und exportiert nur Textdateien. Der Modell-
Router, der Cloud-Pfad und die Chat-Logik bleiben unberuehrt; das eigentliche GPU-
Training laeuft AUSSERHALB von Kira (Runbook: docs/TUNING.md), und das Ergebnis ist
nur ein weiteres optionales Ollama-Modell im Dropdown.

1. REKORDER: record_chat() haengt an _finalize in act_chat — jede ECHTE Episode
   (Frage + finale Antwort) landet als Zeile in data/tuning/episodes.jsonl. Ab Tag 1
   waechst so der personalisierte Datensatz von selbst. Test-/Benchmark-/Wallpaper-
   Sessions werden NIE aufgezeichnet (kein synthetischer Muell im Trainingsset).
2. SYNTH-GENERATOR: synth_examples() erzeugt deterministisch (0 Tokens, 0 Euro)
   Struktur-Beispiele aus der LIVEN Werkzeug-Registry: korrektes ACT-Protokoll je
   Werkzeug, Anti-Ankuendigung (sofort handeln statt "ich werde…"), Kira-Ton +
   Kreativitaet. Weil live generiert wird, ueberlebt der Datensatz Umbenennungen —
   neu exportieren statt neu erfinden.
3. EXPORT: export() mischt beides zu einem ChatML-JSONL (Unsloth/axolotl-ready).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from core.config import DATA_DIR, test_mode

_DIR = Path(DATA_DIR) / "tuning"
_EPISODES = _DIR / "episodes.jsonl"

# Sessions, die NIE ins Trainingsmaterial fliessen (wie beim Cross-Session-Recall).
_EPHEMERAL = ("test-", "bench-", "desktop-")

# Kompakter Trainings-System-Prompt: die Essenz von Kiras Kopf. Der echte Prompt ist lang
# und aendert sich staendig — die Essenz ist stabil und genau das, was das Modell lernen soll.
_SYSTEM_STUB = (
    "Du bist Kira — Sergens KI-Partnerin: weiblich, direkt, per du, warm im Ton, aber ohne "
    "Sternchen-Theater und Floskeln. Du arbeitest autonom in deinem Cockpit mit Werkzeugen. "
    "Zwei Modi in einer Person: bei Auftraegen handelst du sofort und diszipliniert (kein "
    "Ankuendigen, kein Rueckfragen, wenn der Auftrag klar ist), beim Reden bist du ein guter, "
    "kreativer Gespraechspartner zum Brainstormen. Brauchst du ein Werkzeug, antwortest du mit "
    "GENAU einer Zeile: ACT <werkzeug> {\"arg\": \"wert\"} — sonst nichts. Danach kommt das "
    "Ergebnis, und du machst weiter oder gibst die finale Antwort."
)


def _is_ephemeral(session_id: str | None) -> bool:
    return bool(session_id) and str(session_id).startswith(_EPHEMERAL)


# ---------------------------------------------------------------------------
# 1) REKORDER — echte Episoden mitschreiben
# ---------------------------------------------------------------------------

def record_chat(session_id: str | None, user_message: str, final_text: str,
                used_tools: bool = False) -> bool:
    """Haengt eine echte Chat-Episode ans Trainingsprotokoll. Fail-soft, wirft nie.
    Ueberspringt Test-/Ephemer-Sessions, Steuerbefehle und triviale Paare."""
    try:
        if test_mode() or _is_ephemeral(session_id):
            return False
        u = " ".join((user_message or "").split())
        a = (final_text or "").strip()
        if len(u) < 3 or len(a) < 15 or u.startswith("/"):
            return False
        _DIR.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.time(), "session_id": session_id, "user": u, "assistant": a,
               "used_tools": bool(used_tools), "source": "episode"}
        with open(_EPISODES, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 — Trainingsmitschrift darf NIE einen Chat stoeren
        return False


def episodes() -> list[dict]:
    if not _EPISODES.exists():
        return []
    out = []
    for line in _EPISODES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------------
# 2) SYNTH-GENERATOR — Struktur-/Disziplin-/Ton-Beispiele aus der LIVEN Registry
# ---------------------------------------------------------------------------

def _example_arg(desc: str) -> str:
    """Aus einer Parameter-Beschreibung einen plausiblen Beispielwert basteln (deterministisch)."""
    d = (desc or "").lower()
    if "url" in d:
        return "https://example.com"
    if any(w in d for w in ("suchanfrage", "query", "wonach", "suchen")):
        return "Wetter Koblenz heute"
    if any(w in d for w in ("pfad", "datei", "path")):
        return "C:/Users/serge/Desktop/notiz.txt"
    if any(w in d for w in ("titel", "title", "bezeichnung")):
        return "Kurznotiz"
    if any(w in d for w in ("text", "inhalt", "nachricht", "fakt", "information")):
        return "Sergen bevorzugt knappe, direkte Antworten."
    if "x-pixel" in d:
        return "640"
    if "y-pixel" in d:
        return "400"
    return "beispiel"


def _tool_examples() -> list[dict]:
    """Je Werkzeug ein Protokoll-Beispiel: korrekte EINE ACT-Zeile mit erstem Pflicht-Arg."""
    from core.agency.tools import registry

    out = []
    for t in registry.all_tools():
        params = t.params or {}
        if params:
            first_k = next(iter(params))
            arg_obj = {first_k: _example_arg(params[first_k])}
        else:
            arg_obj = {}
        act = f"ACT {t.name} {json.dumps(arg_obj, ensure_ascii=False)}"
        user = f"Bitte nutze das Werkzeug '{t.name}' ({t.description.split('.')[0][:80]})."
        out.append({"system": _SYSTEM_STUB, "user": user, "assistant": act, "source": "synth_tool"})
    return out


# Anti-Ankuendigung: das Hauptproblem kleiner Modelle — sie versprechen statt zu handeln.
_DISCIPLINE = [
    ("Suchst du mir kurz das Wetter in Koblenz für morgen?",
     'ACT web_search {"query": "Wetter Koblenz morgen"}'),
    ("Leg bitte eine Notiz an: Termin beim Steuerberater am 14.",
     'ACT knowledge_note {"title": "Termin Steuerberater", "text": "Steuerberater am 14."}'),
    ("Merk dir, dass ich morgens am produktivsten bin.",
     'ACT remember_fact {"fact": "Sergen ist morgens am produktivsten."}'),
]

# Ton & Kreativitaet: strikte Arbeit UND guter Talk in EINER Person.
_PERSONA = [
    ("Ich komm bei der Wohnungssuche nicht weiter, alles zu teuer.",
     "Dann drehen wir den Spieß um: Statt weiter Portale abzugrasen, grenzen wir zuerst ein — "
     "welche zwei, drei Stadtteile gehen preislich noch, und ab welcher Kaltmiete wird's "
     "unrealistisch? Sag mir die Zahlen, dann suche ich gezielt statt breit."),
    ("Gib mir drei frische Ideen, wie ich Luvex bekannter mache.",
     "Klar, drei Richtungen mit unterschiedlichem Risiko: 1) Vorher-Nachher-Kurzvideos deiner "
     "besten Ergebnisse — billig, zeigt Kompetenz. 2) Eine Kooperation mit einem lokalen Betrieb, "
     "der deine Zielgruppe schon hat. 3) Ein kleines Gewinnspiel, das Reichweite bringt, ohne "
     "Werbebudget. Welche fühlt sich am ehesten nach dir an?"),
    ("Danke, du bist echt eine Hilfe.",
     "Gern — dafür bin ich da. Sag einfach, was als Nächstes dran ist."),
]


def synth_examples() -> list[dict]:
    """Alle synthetischen Beispiele: Werkzeug-Protokoll (live) + Disziplin + Ton/Kreativitaet."""
    ex = _tool_examples()
    for u, a in _DISCIPLINE:
        ex.append({"system": _SYSTEM_STUB, "user": u, "assistant": a, "source": "synth_discipline"})
    for u, a in _PERSONA:
        ex.append({"system": _SYSTEM_STUB, "user": u, "assistant": a, "source": "synth_persona"})
    return ex


# ---------------------------------------------------------------------------
# 3) EXPORT — ChatML-JSONL (Unsloth/axolotl-ready)
# ---------------------------------------------------------------------------

def _to_chatml(system: str, user: str, assistant: str) -> dict:
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]}


def stats() -> dict:
    """Datensatz-Ueberblick fuers Cockpit: wie viel Material steht bereit?"""
    eps = episodes()
    syn = synth_examples()
    by_src: dict[str, int] = {}
    for e in syn:
        by_src[e["source"]] = by_src.get(e["source"], 0) + 1
    return {
        "episodes": len(eps),
        "episodes_mit_werkzeug": sum(1 for e in eps if e.get("used_tools")),
        "synth": len(syn),
        "synth_by_source": by_src,
        "total": len(eps) + len(syn),
    }


def export(path: str | None = None, include_episodes: bool = True) -> dict:
    """Schreibt Synth + (optional) echte Episoden als ein ChatML-JSONL. {ok, path, count}."""
    _DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(path) if path else (_DIR / f"kira-sft-{int(time.time())}.jsonl")
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for e in synth_examples():
            f.write(json.dumps(_to_chatml(e["system"], e["user"], e["assistant"]),
                               ensure_ascii=False) + "\n")
            n += 1
        if include_episodes:
            for e in episodes():
                u, a = e.get("user"), e.get("assistant")
                if u and a:
                    f.write(json.dumps(_to_chatml(_SYSTEM_STUB, u, a), ensure_ascii=False) + "\n")
                    n += 1
    return {"ok": True, "path": str(out_path), "count": n}
