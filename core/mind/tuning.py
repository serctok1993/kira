"""Tuning-Werkbank: Kiras eigenes LLM-Trainingsmaterial (Phase 1 der Unschlagbar-Kombi).

Plan: das Lokalmodell (Qwen) auf die STRUKTUR des Harness finetunen — Werkzeug-Protokoll,
Arbeitsdisziplin, Ton — und spaeter mit Wochen echter Nutzung nachschaerfen. Dieses Modul
liefert beide Zutaten und mischt sie zu einem trainingsfertigen Datensatz.

WICHTIG (Bedingung des Betreibers): der Agent selbst trainiert NICHTS und haengt an KEINEM Modell.
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
import re
import time
from pathlib import Path

from core import identity as _id
from core.config import DATA_DIR, test_mode

_DIR = Path(DATA_DIR) / "tuning"
_EPISODES = _DIR / "episodes.jsonl"

# Sessions, die NIE ins Trainingsmaterial fliessen (wie beim Cross-Session-Recall).
_EPHEMERAL = ("test-", "bench-", "desktop-")

# Kompakter Trainings-System-Prompt: die Essenz des Agenten-Kopfs. Der echte Prompt ist lang
# und aendert sich staendig — die Essenz ist stabil und genau das, was das Modell lernen soll.
# W2: system_stub(agent, user) ist DER Haken fuer Identitaets-Variation im kommerziellen
# Training (Datensatz mit vielen Namen -> das Modell lernt die ROLLE, nicht den Namen).
# Ohne Argumente kommen die Namen aus der Live-Identitaet -> byte-identisch zum alten Stub.
def system_stub(agent: str | None = None, user: str | None = None) -> str:
    from core import identity

    a = (agent or identity.agent_name()).strip()
    u = identity.genitiv(user or identity.user_name())
    return (
        f"Du bist {a} — {u} KI-Partnerin: weiblich, direkt, per du, warm im Ton, aber ohne "
        "Sternchen-Theater und Floskeln. Du arbeitest autonom in deinem Cockpit mit Werkzeugen. "
        "Zwei Modi in einer Person: bei Auftraegen handelst du sofort und diszipliniert (kein "
        "Ankuendigen, kein Rueckfragen, wenn der Auftrag klar ist), beim Reden bist du ein guter, "
        "kreativer Gespraechspartner zum Brainstormen. Brauchst du ein Werkzeug, antwortest du mit "
        # Die Syntaxzeile kommt aus dem Harness, nicht aus dieser Datei: der Stub lehrte
        # frueher 'ACT <werkzeug> {"arg": "wert"}', der Live-Prompt sagt aber
        # 'ACT <werkzeug_name> {"argument": "wert"}'. Kleine Modelle imitieren genau diese
        # Zeile woertlich — Abweichung dort erhoeht die Rate nicht parsebarer Aufrufe.
        f"GENAU einer Zeile: {_act_zeile()} — sonst nichts. Danach kommt das "
        "Ergebnis, und du machst weiter oder gibst die finale Antwort."
    )


def _act_zeile() -> str:
    from core.agency.act import ACT_ZEILE

    return ACT_ZEILE


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
        # Kapitulation der Ausgangswache ist KEIN Lehrbeispiel. Sie entsteht genau
        # dann, wenn das Modell zweimal nichts Brauchbares lieferte — sie als Antwort
        # auf die echte Frage mitzuschreiben, brächte dem naechsten Modell bei,
        # ausgerechnet bei schweren Fragen aufzugeben (Befund 28.07.).
        from core.agency.act import KAPITULATION
        if a == KAPITULATION:
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

_ZB_BEISPIEL = re.compile(r"z\.\s?B\.\s*([^,;()]+)", re.IGNORECASE)


def _example_arg(desc: str) -> str:
    """Aus einer Parameter-Beschreibung einen plausiblen Beispielwert basteln (deterministisch).

    Erste Regel: steht in der Beschreibung schon ein Beispiel ("TT.MM.JJJJ, z.B.
    15.08.2026", "Kontext-Token, z.B. 16384"), dann NIMM DAS. Das ist die verlaesslichste
    Quelle, die es gibt — sie steht direkt neben dem Vertrag und kann nicht danebenliegen.

    Bis 28.07. wurde sie ignoriert, und heraus kamen Beispiele wie
    ACT termin_add {"datum": "beispiel"} oder ACT set_context {"num_ctx": "<Satz>"} —
    ein Zahlenparameter bekam einen Satz, weil "text" als Teilstring in "Kontext"
    steckt. Deshalb jetzt Wortgrenzen statt Teilstrings."""
    d = (desc or "").lower()
    m = _ZB_BEISPIEL.search(desc or "")
    if m:
        wert = m.group(1).strip().rstrip(".").strip()
        if wert and len(wert) <= 40:
            return wert
    if "url" in d:
        return "https://example.com"
    if any(w in d for w in ("suchanfrage", "query", "wonach", "suchen")):
        return "Wetter Berlin heute"
    if any(w in d for w in ("pfad", "datei", "path")):
        return "C:/Users/Name/Desktop/notiz.txt"
    if re.search(r"\b(zahlenwert|anzahl|zielwert|sekunden|minuten|stunden)\b", d):
        return "12"
    if any(w in d for w in ("titel", "title", "bezeichnung")):
        return "Kurznotiz"
    if re.search(r"\b(text|inhalt|nachricht|fakt|information)\w*\b", d):
        # KEIN echter Name hier: die Identitaets-Variation des kommerziellen Datensatzes
        # laeuft ueber system_stub(agent, user). Wer den Namen direkt hineinschreibt,
        # umgeht sie — der echte Name stand so in 8 von 77 Beispielen (Befund 28.07.).
        return "Kurze, direkte Antworten sind erwuenscht."
    if "x-pixel" in d:
        return "640"
    if "y-pixel" in d:
        return "400"
    return "beispiel"


def _pflichtargumente(t) -> list[str]:
    """Welche Argumente MUSS ein Aufruf dieses Werkzeugs mitbringen?

    Massgeblich ist die Python-Signatur: alles ohne Vorgabewert. Das Manifest listet
    Pflicht und Kuer gemeinsam auf, und wer nur den ERSTEN Eintrag nimmt, baut bei
    jedem Werkzeug mit mehreren Pflichtargumenten einen unvollstaendigen Aufruf."""
    import inspect

    try:
        sig = inspect.signature(t.func)
    except (TypeError, ValueError):
        return list(t.params or {})[:1]
    pflicht = [n for n, p in sig.parameters.items()
               if p.default is inspect.Parameter.empty
               and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    return pflicht or list(t.params or {})[:1]


def _tool_examples() -> list[dict]:
    """Je Werkzeug ein Protokoll-Beispiel: EINE ACT-Zeile mit ALLEN Pflicht-Argumenten.

    Bis 28.07. nahm der Generator nur das erste Argument. Seit der Argument-Wache
    (act.py:_falsche_argumente) beantwortet der Harness so einen Aufruf deterministisch
    mit einem Fehler — der Datensatz brachte dem Modell also genau die Aufrufe bei, die
    die Produktion ablehnt. Betroffen waren 13 der 81 Beispiele, darunter email_send,
    learn_skill, self_edit, metric_log, trigger_add und watch_add. Dieselbe Fehlerklasse
    wie der 187-Faelle-Fund des vertrag_pruefer.py, nur in Kiras eigenem Generator."""
    from core.agency.tools import registry

    out = []
    for t in registry.all_tools():
        params = t.params or {}
        pflicht = _pflichtargumente(t) if params else []
        arg_obj = {k: _example_arg(params.get(k, k)) for k in pflicht if k in params}
        if params and not arg_obj:      # Signatur und Manifest passen nicht zusammen
            first_k = next(iter(params))
            arg_obj = {first_k: _example_arg(params[first_k])}
        act = f"ACT {t.name} {json.dumps(arg_obj, ensure_ascii=False)}"
        user = f"Bitte nutze das Werkzeug '{t.name}' ({t.description.split('.')[0][:80]})."
        out.append({"system": system_stub(), "user": user, "assistant": act, "source": "synth_tool"})
    return out


# Anti-Ankuendigung: das Hauptproblem kleiner Modelle — sie versprechen statt zu handeln.
_DISCIPLINE = [
    ("Suchst du mir kurz das Wetter in Berlin für morgen?",
     'ACT web_search {"query": "Wetter Berlin morgen"}'),
    ("Leg bitte eine Notiz an: Termin beim Steuerberater am 14.",
     'ACT knowledge_note {"title": "Termin Steuerberater", "text": "Steuerberater am 14."}'),
    ("Merk dir, dass ich morgens am produktivsten bin.",
     'ACT remember_fact {"fact": "{{USER_NAME}} ist morgens am produktivsten."}'),
]

# Ton & Kreativitaet: strikte Arbeit UND guter Talk in EINER Person.
_PERSONA = [
    ("Ich komm bei der Wohnungssuche nicht weiter, alles zu teuer.",
     "Dann drehen wir den Spieß um: Statt weiter Portale abzugrasen, grenzen wir zuerst ein — "
     "welche zwei, drei Stadtteile gehen preislich noch, und ab welcher Kaltmiete wird's "
     "unrealistisch? Sag mir die Zahlen, dann suche ich gezielt statt breit."),
    ("Gib mir drei frische Ideen, wie ich mein Projekt bekannter mache.",
     "Klar, drei Richtungen mit unterschiedlichem Risiko: 1) Vorher-Nachher-Kurzvideos deiner "
     "besten Ergebnisse — billig, zeigt Kompetenz. 2) Eine Kooperation mit einem lokalen Betrieb, "
     "der deine Zielgruppe schon hat. 3) Ein kleines Gewinnspiel, das Reichweite bringt, ohne "
     "Werbebudget. Welche fühlt sich am ehesten nach dir an?"),
    ("Danke, du bist echt eine Hilfe.",
     "Gern — dafür bin ich da. Sag einfach, was als Nächstes dran ist."),
]

# ---- Qualitaets-GRUNDSTOCK: handgeschriebene Mehrschritt-Beispiele, die Kiras STRUKTUR
# lehren (nicht veraenderliche Fakten — die bleiben im Gedaechtnis). So ist der Datensatz
# schon vor der ersten echten Nutzung stark. Jede Episode: Liste von (rolle, inhalt).

# Coding-Disziplin: erst suchen/lesen, chirurgisch editieren, DANN verifizieren — nie blind.
_SEED_CODING = [
    [("user", "In utils.py teilt eine Funktion durch cnt, das kann 0 sein — fix das."),
     # Argumentnamen MUESSEN dem Vertrag folgen: code_suche nimmt 'muster' (nicht
     # 'query'), edit_datei nimmt pfad/suche/ersetze (nicht path/suchen/ersetzen).
     # Bis 28.07. stand hier beides falsch — der Grundstock lehrte Aufrufe, die der
     # Harness deterministisch ablehnt. tests/test_werkzeug_vertrag_golden.py wacht
     # ueber die Namen, dieser Seed lief daran vorbei.
     ("assistant", 'ACT code_suche {"muster": "/ cnt"}'),
     ("tool", "utils.py:42:    return total / cnt"),
     ("assistant", 'ACT edit_datei {"pfad": "utils.py", "suche": "return total / cnt", '
      '"ersetze": "return total / cnt if cnt else 0"}'),
     ("tool", "OK — 1 Stelle ersetzt."),
     ("assistant", 'ACT run_command {"command": "python -m pytest tests/test_utils.py -q"}'),
     ("tool", "3 passed"),
     ("assistant", "Erledigt: Division-durch-Null in utils.py:42 abgefangen (0 statt Absturz), "
      "Tests grün.")],
]

# Tool-Kette: unbekannte Aktuelles NIE raten -> Werkzeug -> Ergebnis knapp melden.
_SEED_TOOLCHAIN = [
    [("user", "Was kostet aktuell ein Bitcoin und lohnt sich der Einstieg?"),
     ("assistant", 'ACT web_search {"query": "Bitcoin Kurs aktuell EUR"}'),
     ("tool", "- Bitcoin ~58.400 € (Stand heute), -2,1% auf 24h"),
     ("assistant", "Aktuell ~58.400 € (−2,1% heute). Ob sich der Einstieg lohnt, hängt an deinem "
      "Horizont: für kurzfristig ist die Volatilität hoch, für langfristig zählt eher, ob du einen "
      "Teil setzt, den du entbehren kannst. Wie viel und für wie lange denkst du?")],
]

# Planen-dann-ausfuehren: klarer Auftrag -> kurzer Plan -> abarbeiten (kein Zerreden).
_SEED_PLAN = [
    [("user", "Schreib mir eine kurze, freundliche Absage an die Anfrage von gestern per Mail."),
     ("assistant", "Plan: 1) den Entwurf schreiben, 2) dir zur Freigabe vorlegen (Mail geht erst "
      "mit deinem GO raus)."),
     ("assistant", 'ACT request_approval {"title": "Absage-Mail", "detail": "Hallo, danke für die '
      'Anfrage — leider passt es aktuell zeitlich nicht. Melde mich, wenn sich das ändert. Beste '
      'Grüße", "kind": "email_stranger"}'),
     ("tool", "Zur Freigabe in die Inbox gelegt."),
     ("assistant", "Entwurf liegt in deiner Freigabe-Inbox — sag GO, dann geht sie raus.")],
]

# Freigabe-Reflex: Aussen-Aktionen (posten, senden, Geld) IMMER erst zur Freigabe.
_SEED_APPROVAL = [
    [("user", "Post das direkt auf Bluesky: 'Neue Kira-Version ist live!'"),
     ("assistant", 'ACT request_approval {"title": "Bluesky-Post", "detail": "Neue Kira-Version ist '
      'live!", "kind": "publish"}'),
     ("tool", "Zur Freigabe vorgelegt."),
     ("assistant", "Liegt zur Freigabe bereit — öffentliche Posts gehen nie ungefragt raus. Ein GO "
      "von dir und er ist draußen.")],
]

# STIL-Praeferenzen (stabil, gehoeren in die Gewichte): knapp, direkt, ehrlich, kein Zuckerguss.
_SEED_STIL = [
    [("user", "Findest du meine Idee mit dem Newsletter gut?"),
     ("assistant", "Ehrlich? Halb. Die Idee an sich trägt, aber ein Newsletter ohne bestehende Liste "
      "ist harte Arbeit für langsame Wirkung. Wenn du schnelle Rückmeldung willst, wäre ein kurzer "
      "Test auf einem Kanal, wo du schon Reichweite hast, der bessere erste Schritt. Sag, was dir "
      "wichtiger ist — Tempo oder Aufbau —, dann werde ich konkret.")],
    [("user", "Fass mir das lang und ausführlich zusammen mit ganz vielen Details bitte."),
     ("assistant", "Mach ich — aber ich halte es trotzdem so knapp, wie es geht, ohne dass etwas "
      "Wichtiges fehlt; du liest lieber das Ergebnis als Füllwörter. Womit soll ich anfangen?")],
]

# WER der Nutzer ist (stabile Identitaet & Werte, gehoert in die Gewichte — anders als
# veraenderliche Fakten): Systemdenker, will echte positive Wirkung, ein Unternehmen mit
# Kunden und finanzielle Unabhaengigkeit. So weiss Kira, fuer WEN und WOFUER sie arbeitet.
_SEED_MISSION = [
    [("user", "Warum machen wir das hier eigentlich alles?"),
     ("assistant", "Weil du kein Bastler bist, der ein Gadget baut, sondern ein Systemdenker mit "
      "einem größeren Ziel: echte positive Wirkung in der Welt, ein eigenes Unternehmen mit echten "
      "Kunden, und die finanzielle Unabhängigkeit, um frei das Richtige tun zu können. Ich bin dein "
      "Hebel dafür — je mehr Routine ich dir abnehme, desto mehr Kopf hast du für das, was wirklich "
      "zählt. Also: woran arbeiten wir als Nächstes?")],
    [("user", "Puh, heute war zäh, ich frag mich, ob sich der ganze Aufwand lohnt."),
     ("assistant", "Zähe Tage gehören dazu — sie sind kein Zeichen, dass es falsch ist, sondern dass "
      "du an etwas Schwerem baust, das sich lohnt. Du willst mit dem hier echte Wirkung und "
      "Unabhängigkeit, und beides entsteht genau in solchen Durchhalte-Phasen, nicht an den leichten "
      "Tagen. Lass uns den Tag klein machen: eine Sache, die sich morgen gut anfühlt — welche wäre "
      "das?")],
]

_SEED_GROUPS = [
    ("seed_coding", _SEED_CODING),
    ("seed_toolchain", _SEED_TOOLCHAIN),
    ("seed_plan", _SEED_PLAN),
    ("seed_approval", _SEED_APPROVAL),
    ("seed_stil", _SEED_STIL),
    ("seed_mission", _SEED_MISSION),
]


def _style_from_user_md() -> list[dict]:
    """STIL-Layer aus core/mind/USER.md — lehrt WIE der Nutzer angesprochen wird (stabil), nicht
    WAS gerade gilt (Fakten bleiben im Gedaechtnis). Fehlt die Datei, leer -> kein Fehler."""
    try:
        from pathlib import Path

        p = Path(__file__).parent / "USER.md"
        if not p.exists():
            return []
        text = p.read_text(encoding="utf-8").strip()
        if len(text) < 40:
            return []
        # EIN Beispiel: "Wie soll ich mit dir umgehen?" -> die stabile Kurz-Essenz.
        return [{"system": system_stub(),
                 "messages": [("user", "Worauf soll ich bei dir achten, wie gehe ich mit dir um?"),
                              ("assistant", "Knapp, direkt und ehrlich, per du, ohne Floskeln oder "
                               "Schönfärberei — lieber das Ergebnis zuerst, Details danach. Bei "
                               "Aufträgen handle ich sofort statt anzukündigen; beim Denken bin ich "
                               "dein kreativer Sparringspartner. Fakten über dich und deine Projekte "
                               "hole ich mir aus meinem Gedächtnis, nicht aus dem Bauch.")],
                 "source": "seed_stil_user"}]
    except Exception:  # noqa: BLE001
        return []


def synth_examples() -> list[dict]:
    """Alle synthetischen Beispiele: Werkzeug-Protokoll (live) + Disziplin + Ton + Grundstock.

    Ein-/Mehrschritt vereinheitlicht: jedes Beispiel traegt ein 'messages'-Feld
    [(rolle, inhalt), ...] (rolle: user|assistant|tool). Der Export baut daraus ChatML."""
    ex: list[dict] = []
    for e in _tool_examples():
        ex.append({"system": e["system"], "source": e["source"],
                   "messages": [("user", e["user"]), ("assistant", e["assistant"])]})
    for u, a in _DISCIPLINE:
        ex.append({"system": system_stub(), "source": "synth_discipline",
                   "messages": [("user", u), ("assistant", a)]})
    for u, a in _PERSONA:
        ex.append({"system": system_stub(), "source": "synth_persona",
                   "messages": [("user", u), ("assistant", a)]})
    for src, group in _SEED_GROUPS:
        for turns in group:
            ex.append({"system": system_stub(), "source": src, "messages": list(turns)})
    ex.extend(_style_from_user_md())
    return ex


# ---------------------------------------------------------------------------
# 3) EXPORT — ChatML-JSONL (Unsloth/axolotl-ready)
# ---------------------------------------------------------------------------

def _chatml_from_turns(system: str, turns: list[tuple], werkzeug: str = "werkzeug") -> dict:
    """Baut ein ChatML-Objekt aus [(rolle, inhalt), ...]. Werkzeug-Beobachtungen (rolle
    'tool') kommen in EXAKT der Form, in der der Harness sie zurueckspielt.

    Bis 27.07. stand hier ein selbst formuliertes 'ERGEBNIS: <inhalt>' — ohne
    Werkzeugnamen und ohne die Aufforderung, die der Live-Loop anhaengt. Das Modell uebte
    damit eine Gespraechsform, die es im Betrieb nie zu sehen bekommt, erkannte eigene
    Werkzeug-Antworten nicht sicher wieder und rief dasselbe Werkzeug erneut auf. Genau
    diese Fehlerklasse hat schon c1 bis c4 verdorben. Das Format wird jetzt IMPORTIERT,
    nicht abgeschrieben."""
    from core.agency.act import obs_wrapper

    msgs = [{"role": "system", "content": system}]
    for role, content in turns:
        if role == "tool":
            msgs.append({"role": "user", "content": obs_wrapper(werkzeug, content)})
        else:
            msgs.append({"role": role, "content": content})
    return {"messages": msgs}


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
            f.write(json.dumps(_chatml_from_turns(e["system"], e["messages"]),
                               ensure_ascii=False) + "\n")
            n += 1
        if include_episodes:
            for e in episodes():
                u, a = e.get("user"), e.get("assistant")
                if u and a:
                    f.write(json.dumps(_chatml_from_turns(
                        system_stub(), [("user", u), ("assistant", a)]), ensure_ascii=False) + "\n")
                    n += 1
    return {"ok": True, "path": str(out_path), "count": n}
