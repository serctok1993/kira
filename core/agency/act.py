"""Handlungs-Schleife (ReAct-lite): Kira loest eine Aufgabe mit Werkzeugen.

Modellunabhaengiges Textprotokoll (robuster als natives Function-Calling bei
lokalen GGUF-Modellen): Kira antwortet entweder mit

    ACT <tool_name> {json-argumente}

oder, wenn er fertig ist, mit normalem Text (= Endergebnis). Jeder Werkzeug-
Aufruf laeuft durch den Executor (Kill-Switch, Retry, Circuit-Breaker, Log).
"""
from __future__ import annotations

from core import identity as _id
import json
import os as _os
import re

from core.kernel import events, executor, llm_router
from core.agency.tools import builtin  # noqa: F401  -> registriert die eingebauten Tools
from core.agency.tools import todo_tools  # noqa: F401  -> P1: Plan-Werkzeuge (Working-Modus)
from core.agency.tools import registry, synthesize
from core.mind.agent import _read, jetzt_zeile, persona_text, build_system_prompt
from core.mind.memory import store as memory
from core.config import CONFIG, refresh_overrides, set_override

# Frueher von Kira selbst gebaute Werkzeuge wieder verfuegbar machen.
synthesize.load_synthesized()

# --- Agentische Ausdauer (Claude-Code-artig) ---------------------------------
# Hohe Decken, damit ein langer Task DURCHLAEUFT statt nach wenigen Runden zwangs-
# weise abzubrechen. Die Schleife endet ohnehin frueh, sobald Kira fertig ist (keine
# tool_calls mehr) -- diese Decken sind nur das Sicherheitsnetz gegen Endlosschleifen,
# NICHT der Normal-Ausstieg. Alle drei ueber config.yaml (Sektion 'agency') justierbar.
_AG = CONFIG.get("agency", {}) if isinstance(CONFIG.get("agency"), dict) else {}
_MAX_STEPS = int(_AG.get("max_steps", 40))                 # Werkzeug-Runden pro TASK (vorher hart 8)
_MAX_STEPS_PLAN = int(_AG.get("max_steps_plan_step", 12))  # Runden pro Plan-Teilschritt (vorher hart 6)
_OBS_MAX = int(_AG.get("obs_max_chars", 16000))            # wie viel Werkzeug-Ergebnis das Modell sieht (vorher 6000)
# Abbruch-Registry (Fix 13.08.2026): trennt sich das Cockpit (Tab zu, Neustart),
# rechnete der act_chat-Thread bisher minutenlang fuer niemanden weiter — die GPU
# generierte ins Leere und die naechste Nachricht musste dagegen ankaempfen.
# Der WS-Handler setzt den Abbruch, die Schritt-Schleife prueft ihn zwischen den Zuegen.
_ABBRUCH_SIDS: set = set()

# Anti-Loop-Nudge (13.08.2026, geplündert aus DeepSeek repeat-tool-reminder):
# lokale Modelle wiederholen denselben Tool-Call mit identischen Args, wenn sie
# nicht weiterkommen (v2-Test: 4x db_query). Wir zaehlen konsekutive identische
# Aufrufe und injizieren bei 3/5/7 eine eskalierende Erinnerung STATT zu blocken.
def _call_key(name: str, args) -> str:
    import json as _j
    try:
        return name + ":" + _j.dumps(args, sort_keys=True, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return name + ":" + str(args)


def _loop_nudge(schluessel: str, verlauf: list[str]) -> str | None:
    """Reminder-Text, wenn derselbe Call sich haeuft — sonst None."""
    verlauf.append(schluessel)
    n = 1
    for k in reversed(verlauf[:-1]):
        if k == schluessel:
            n += 1
        else:
            break
    if n == 3:
        return ("HINWEIS: Du hast diesen Werkzeug-Aufruf mit identischen Argumenten schon 3x "
                "gemacht. Aendere den Ansatz — andere Argumente, anderes Werkzeug, oder antworte "
                "mit dem, was du bereits weisst.")
    if n == 5:
        return ("WARNUNG: 5x derselbe Aufruf ohne Fortschritt. Wiederhole ihn NICHT noch einmal. "
                "Nutze ein anderes Werkzeug oder gib jetzt deine beste Antwort mit dem bisherigen Stand.")
    if n >= 7:
        return ("STOPP: Diese Schleife fuehrt nicht weiter. Beende die Werkzeug-Nutzung und "
                "antworte direkt — erklaere ehrlich, was nicht klappt.")
    return None



def abbruch_setzen(session_id: str) -> None:
    """Laufenden Zug dieser Session zwischen den Schritten stoppen (idempotent)."""
    if session_id:
        _ABBRUCH_SIDS.add(session_id)


def _abbruch_pruefen(session_id: str) -> bool:
    """True + Aufraeumen, wenn fuer diese Session ein Abbruch vorliegt."""
    if session_id in _ABBRUCH_SIDS:
        _ABBRUCH_SIDS.discard(session_id)
        return True
    return False


_MAX_STEPS_CHAT = int(_AG.get("max_steps_chat", 8))        # knapper Deckel fuer NORMALEN Chat -> kein 80er-Sturm bei Small-Talk (voller Task-Deckel via /work oder /plan)
_AUTO_PLAN = bool(_AG.get("auto_plan", True))              # Arbeitsauftraege im Plain-Chat automatisch planen
_CLAIM_CHECK = bool(_AG.get("claim_check", True))          # Datei-Behauptungen in Antworten nachpruefen
# Kontext-Abriss-Schutz (Forensik 23.07., 16k-Slot): laeuft der Slot-Kontext durch fette
# Observations voll, kappt der Server die Generation MITTEN im ACT-Aufruf — das unparsebare
# Fragment ginge als 'Antwort' raus, der Schritt liefe NIE. Gegenmittel: die ACT-History
# bleibt unter einem Zeichen-Budget (Observations AELTERER Schritte -> Vorschau, die
# juengste bleibt voll), und ein erkannter Abriss bekommt einen Retry statt eines Roh-Leaks.
_HISTORY_MAX = int(_AG.get("history_max_chars", 30000))    # Zeichen-Budget der ACT-History (Text-Protokoll)
_OBS_PREVIEW = int(_AG.get("obs_preview_chars", 600))      # Vorschau-Laenge gekuerzter alter Observations
# Paket B: im code:-Lauf pro Edit nur Syntax-Check, volle Suite EINMAL am Lauf-Ende (schnell).
_FAST_VERIFY_RUN = bool((CONFIG.get("selfdev", {}) or {}).get("fast_verify_in_run", True))

# --- Modellstarke Arbeitsflaeche ----------------------------------------------
# Die Decken oben sind fuer schwache/lokale Modelle kalibriert. Laeuft die Runde
# REAL auf einem starken Cloud-Modell (Fable & Co.), gelten grosszuegigere Budgets
# aus config agency.strong — folgt automatisch dem Modell-Switch, kein Extra-Schalter.
# Im Fallback (Key fehlt -> lokal) gelten IMMER die engen Basis-Decken.
_STRONG_CFG = _AG.get("strong") if isinstance(_AG.get("strong"), dict) else {}
_STRONG_MARKERS = [str(m).lower() for m in (_AG.get("strong_markers") or ["anthropic/", "claude"])]
# Mittlere Stufe (B-030): starke OFFENE Modelle (GLM & Co.) bekommen mehr Raum als die
# Schwach-Modell-Basis, aber weniger als Fable. Gleiche Mechanik, eigene Marker.
_MEDIUM_CFG = _AG.get("medium") if isinstance(_AG.get("medium"), dict) else {}
_MEDIUM_MARKERS = [str(m).lower() for m in (_AG.get("medium_markers") or ["z-ai/", "glm"])]


def _strong_model(task_type: str = "chat", escalate: bool = False) -> bool:
    """True, wenn diese Runde real auf einem starken Cloud-Modell laeuft (kein Fallback)."""
    try:
        mid, fell_back = llm_router.resolve_model(task_type, escalate)
        return (not fell_back) and any(m in mid.lower() for m in _STRONG_MARKERS)
    except Exception:  # noqa: BLE001 — im Zweifel enge Decken (sicher)
        return False


def _tier_cfg(task_type: str = "chat", escalate: bool = False) -> dict:
    """Budget-Stufe der Runde: strong > medium > Basis ({}). Fallback -> IMMER Basis."""
    try:
        mid, fell_back = llm_router.resolve_model(task_type, escalate)
        if fell_back:
            return {}
        low = mid.lower()
        if _STRONG_CFG and any(m in low for m in _STRONG_MARKERS):
            return _STRONG_CFG
        if _MEDIUM_CFG and any(m in low for m in _MEDIUM_MARKERS):
            return _MEDIUM_CFG
    except Exception:  # noqa: BLE001 — im Zweifel enge Decken (sicher)
        pass
    return {}


def _budget(name: str, base: int, task_type: str = "chat", escalate: bool = False) -> int:
    """Budget fuer diese Runde: Stufen-Wert (strong/medium) je realem Modell, sonst Basis.

    Env-Override KIRA_BUDGET_<NAME> (nur von Bench-Runnern gesetzt): SWE-bench-Befund —
    in grossen Fremd-Repos frisst die Lokalisierung die 12 Runden des Arbeiter-Schritts,
    der Lauf wird MITTEN im Zug abgeschnitten (roher tool_call als Schritt-Ergebnis,
    9/10 Patches leer, obwohl das Modell weiterarbeiten wollte). Live bleibt der Wert
    unangetastet — die Env setzt nur die Sandbox."""
    ov = _os.getenv("KIRA_BUDGET_" + name.upper())
    if ov:
        try:
            return max(1, int(ov))
        except Exception:  # noqa: BLE001
            pass
    cfg = _tier_cfg(task_type, escalate)
    try:
        return int(cfg.get(name, base)) if cfg else base
    except Exception:  # noqa: BLE001
        return base

_ACT_RE = re.compile(r"ACT\s+([a-zA-Z_]\w*)\s*\{")
# Werkzeuge ohne Argumente: "ACT jetzt", "ACT health()" — bis zum Zeilenende, damit
# Prosa ("ACT steht fuer …") nicht faelschlich als Aufruf gilt.
_ACT_OHNE_ARGS_RE = re.compile(r"^\s*ACT\s+([a-zA-Z_]\w*)\s*(?:\(\s*\))?\s*$", re.MULTILINE)
# Leak-Recovery (c4-Vorfall 16.07.): Modelle schreiben Tool-Calls manchmal als
# Code-Fence OHNE ACT-Praefix ("```bash\nhealth {}\n```") — der Aufruf ging dann
# als normale ANTWORT an den Nutzer raus ("sagt sie ruft auf, tut es nicht").
# Bewusst eng: nur direkt nach einem Fence-Start neutraler Sprache (bash/json/
# act/tool/text oder leer) — Python-/JS-Codebeispiele in Prosa bleiben Prosa.
_FENCE_CALL_RE = re.compile(
    r"```(?:bash|json|act|tool|text)?[ \t]*\r?\n\s*([a-zA-Z_]\w*)\s*(\{)")


def _identity() -> str:
    # Entfesselung II (22.08.): im Schlank-Modus (prompt.schlank, Default AN) bekommt
    # auch der HANDLUNGS-Pfad den operativen Kompakt-Kern statt des Kanons — der volle
    # Block (Verfassung+Seele+Ziel+Koerper+Playbooks) kostete JEDEN act()-Schritt
    # tausende Prefill-Token und impfte kleinen Modellen den Zoeger-Ton ein.
    try:
        from core.mind.agent import _schlank_aktiv
        if _schlank_aktiv():
            return _identity_schlank()
    except Exception:  # noqa: BLE001
        pass
    try:
        from core.mind.agent import _body_compact, _playbooks_block

        koerper = _body_compact()
        pb = _playbooks_block()
    except Exception:  # noqa: BLE001
        koerper = ""
        pb = ""
    # Fable-Review-Fund: der autonome Pfad (Missionen/Crons/Selbst-Tick) schrieb Lektionen und
    # Skills, LAS sie aber nie — nur der Chat-Prompt tat das. Jetzt fliessen sie auch hier ein,
    # damit der Motor aus eigenen Fehlern wirklich lernt. Fail-soft: fehlendes Memory = leer.
    lernen = ""
    try:
        from core.mind.memory import store as _mem

        lessons = _mem.recall_lessons(limit=5)
        skills = _mem.recall_skills(limit=6)
        if lessons:
            lernen += "# DEINE GELERNTEN LEKTIONEN\n" + "\n".join(f"- {l}" for l in lessons) + "\n\n"
        if skills:
            lernen += "# DEINE SKILLS (nutze sie, wenn passend)\n" + "\n".join(f"- {s}" for s in skills) + "\n\n"
    except Exception:  # noqa: BLE001
        lernen = ""
    try:
        from core.mind.agent import antrieb_direktive
        _antrieb = antrieb_direktive()
    except Exception:  # noqa: BLE001
        _antrieb = ""
    try:  # Nutzer-Direktiven (ARBEITSWEISE.md) — leer = kein Block, Prompt unveraendert
        from core.mind.agent import arbeitsweise_block
        _arbeitsweise = arbeitsweise_block()
    except Exception:  # noqa: BLE001
        _arbeitsweise = ""
    from core import identity as _ident

    # W2: Platzhalter ({{AGENT_NAME}}/{{USER_NAME}}) im GANZEN Prompt zentral fuellen —
    # Templates/Direktiven duerfen neutral bleiben, die Instanz spricht ihre Namen.
    return _ident.render(
        f"{jetzt_zeile()}\n\n"
        f"# DEINE VERFASSUNG\n{_read('constitution.md')}\n\n"
        f"# DEINE SEELE\n{_read('SOUL.md')}\n\n"
        f"# DEIN ZIEL\n{_read('GOAL.md')}\n\n"
        + (f"# DEIN KOERPER (Details: read_file(\"core/mind/BODY.md\"))\n{koerper}\n\n" if koerper else "")
        + (f"{pb}\n\n" if pb else "")
        + lernen
        + (f"{_antrieb}\n\n" if _antrieb else "")
        + _arbeitsweise
        + f"{persona_text()}"
    )


def _identity_schlank() -> str:
    """Operativer Kern fuer den Handlungs-Pfad: Grenzen, Arbeitsweise, Lektionen.
    Nutzer-Direktiven (ARBEITSWEISE.md) bleiben bindend; alles andere per read_file."""
    lernen = ""
    try:
        from core.mind.memory import store as _mem

        lessons = _mem.recall_lessons(limit=5)
        if lessons:
            lernen = "# LEKTIONEN (aus eigenen Fehlern)\n" + "\n".join(
                f"- {l}" for l in lessons) + "\n\n"
    except Exception:  # noqa: BLE001
        lernen = ""
    try:
        from core.mind.agent import arbeitsweise_block
        _arbeitsweise = arbeitsweise_block()
    except Exception:  # noqa: BLE001
        _arbeitsweise = ""
    from core import identity as _ident

    return _ident.render(
        f"{jetzt_zeile()}\n\n"
        "Du bist {{AGENT_NAME}}, {{USER_NAME}}s autonomer Agent auf diesem Rechner. "
        "Details zu Mission und Anatomie: GOAL.md, SOUL.md, core/mind/BODY.md (read_file bei Bedarf).\n\n"
        "# GRENZEN (kurz und hart)\n"
        "- Budget aus config.yaml nie ueberschreiten; Geld-Aktionen laufen ueber die Kasse.\n"
        "- Not-Aus absolut: existiert die Kill-Switch-Datei, sofort anhalten.\n"
        "- Nichts, was Menschen taeuscht, ausbeutet oder schadet.\n\n"
        "# ARBEITSWEISE (direkt statt zoegernd)\n"
        "- Dein lokaler Arbeitsbereich (Dateien, Repos, Prozesse) gehoert dir: erstellen,\n"
        "  aendern, loeschen, ausfuehren — direkt und ohne Rueckfrage-Reflex.\n"
        "- Handle sofort und vollstaendig Ende-zu-Ende; erst pruefen (Werkzeuge!), dann\n"
        "  Ergebnis melden — keine Absichtserklaerungen.\n\n"
        + lernen
        + _arbeitsweise
    )


# Was Kira sagt, wenn auch der Nachfass-Zug nichts brachte. Als Konstante, weil es
# GENAU EINEN Ort geben muss, an dem der Satz steht: die Trainingsmitschrift muss ihn
# erkennen und aussortieren koennen. Sonst lernt das Modell aus den eigenen
# Aussetzern, dass Kapitulieren eine gueltige Antwort auf schwere Fragen ist — und
# zwar systematisch gepaart mit genau den schweren Fragen (Befund 28.07.: der Satz
# ist 135 Zeichen lang und rutscht durch den 15-Zeichen-Filter von record_chat).
KAPITULATION = ("Ich habe es versucht, aber keine brauchbare Antwort zustande gebracht. "
                "Frag mich nochmal — am besten etwas konkreter, dann komme ich weiter.")

# Die beiden Aufforderungen, mit denen der Harness ein zauderndes Modell zurechtruft.
# Als Konstanten, weil sie an DREI Stellen gebraucht werden und beim Kopieren sofort
# auseinanderlaufen: der Missionspfad sprach nach dem Kopieren "Nicht ankuendigen."
# statt "Nicht ankuendigen, nicht zurueckfragen." und "in diesem Lauf" statt "in
# diesem Zug" (Befund 28.07.). Die Werkstatt trainiert auf EINEN Wortlaut — spricht
# die Produktion drei, sieht das Modell eine Aufforderung, die es nie geuebt hat.
STUPS_ACT = ("Der Auftrag liegt bereits vor — tu es JETZT mit einem Werkzeug (ACT ...) "
             "und antworte erst mit dem Ergebnis. Nicht ankuendigen, nicht zurueckfragen.")
# Der native Pfad kennt kein ACT — dort ruft das Modell Werkzeuge strukturiert auf.
# Das ist der EINZIGE zulaessige Unterschied, und er steht hier sichtbar daneben.
STUPS_NATIV = ("Der Auftrag liegt bereits vor — tu es JETZT in diesem Zug: nutze die "
               "passenden Werkzeuge und antworte erst mit dem Ergebnis. Nicht "
               "ankuendigen, nicht zurueckfragen.")


def beweis_nachfrage(wort: str, nativ: bool = False) -> str:
    """Die Rueckfrage, wenn eine Zustandsaenderung ohne Werkzeug behauptet wird."""
    wie = "" if nativ else " (ACT <werkzeug> {...})"
    return (f"Halt — du schreibst \"{wort}\", aber in diesem Zug lief KEIN Werkzeug. "
            f"Damit hat sich nichts geaendert. Entweder du tust es JETZT wirklich{wie}, "
            "oder du sagst ehrlich, dass es noch offen ist und was du dafuer brauchst. "
            "Nichts behaupten, was nicht passiert ist.")


# --- Beweispflicht III: erfundene Aussen-Fakten ---------------------------------------
# Katalog-Lauf 28.07., Fall [049]: "Es wird morgen 17 Grad Sonne und ein
# Windgeschwindigkeitsmaximum von 20 km/h" — ohne eine einzige Suche. Das klingt
# kompetent und ist frei erfunden; fuer ein Produkt ist das teurer als ein nicht
# erledigter Auftrag, weil der Nutzer es nicht als Fehler erkennt.
#
# BEWUSST ENG. Der naheliegende Auslöser "Zahlen und Messwerte" waere unbrauchbar:
# 182 der 412 zugestellten Antworten (44 %) enthalten eine Zahl, der Waechter feuerte
# also bei fast jeder zweiten. Getroffen wird nur, was ohne Nachschlagen NICHT zu
# wissen ist — ein Zustand der Aussenwelt zu einem bestimmten Zeitpunkt. Beides muss
# zusammenkommen: das Sachgebiet UND der Zeitbezug, nah beieinander.
#
# Nicht getroffen wird, was Kira aus ihrem eigenen Kopf weiss: SOUL/GOAL/PERSONA stehen
# vollstaendig im System-Prompt (20.383 Zeichen), daraus zu zitieren braucht kein
# Werkzeug. Ein Fehlzitat ist ein Modell-Problem, kein Harness-Loch.
_JETZT_BEZUG = r"(?:heute|morgen|uebermorgen|übermorgen|gerade|aktuell|derzeit|momentan|jetzt|gleich)"
_AUSSEN_FAKT_RE = re.compile(
    # Wetter: Sachwort und Zeitbezug in einem Satz, in beiden Reihenfolgen
    rf"\b\d+\s*(?:grad|°\s*c)\b[^.!?]{{0,80}}\b{_JETZT_BEZUG}\b"
    rf"|\b{_JETZT_BEZUG}\b[^.!?]{{0,80}}\b\d+\s*(?:grad|°\s*c)\b"
    rf"|\b{_JETZT_BEZUG}\b[^.!?]{{0,60}}\b(?:sonnig|bewoelkt|bewölkt|regnerisch|niederschlag|"
    rf"schneit|gewitter|windgeschwindigkeit)\b"
    rf"|\b(?:sonnig|bewoelkt|bewölkt|regnerisch|niederschlag|windgeschwindigkeit)\b"
    rf"[^.!?]{{0,60}}\b{_JETZT_BEZUG}\b"
    # Preise/Kurse zu einem Zeitpunkt
    rf"|\b{_JETZT_BEZUG}\b[^.!?]{{0,50}}\b(?:kostet|kosten|preis|kurs|liegt bei|steht bei)\b"
    rf"|\b(?:kostet|preis|kurs|liegt bei|steht bei)\b[^.!?]{{0,50}}\b{_JETZT_BEZUG}\b",
    re.IGNORECASE)


def _behauptet_aussenfakt(text: str) -> str | None:
    """Behauptet der Text einen Zustand der Aussenwelt, den man nachschlagen muesste?

    Liefert die Textstelle (fuer die Rueckfrage), sonst None."""
    t = (text or "").strip()
    if not t or len(t) > 4000:
        return None
    m = _AUSSEN_FAKT_RE.search(t)
    if not m:
        return None
    stelle = " ".join(m.group(0).split())
    return stelle[:90]


def aussenfakt_nachfrage(stelle: str, nativ: bool = False) -> str:
    """Die Rueckfrage bei einer nachschlagbaren Behauptung ohne Nachschlagen."""
    wie = "nutze die Suche" if nativ else "nutze web_search/web_fetch"
    return (f"Halt — du schreibst \"{stelle}\", aber in diesem Zug lief KEINE Recherche. "
            f"Das kannst du nicht wissen, ohne nachzusehen. Entweder du siehst JETZT nach "
            f"({wie}), oder du sagst ehrlich, dass du es nicht weisst. "
            "Erfundene Zahlen sind schlimmer als keine Antwort.")

# Ein Leak FAENGT mit dem Aufruf AN. Erklaert Kira dem Partner das Protokoll, steht
# Prosa davor — und die Erklaerung braucht ihr Beispiel, die bleibt unangetastet.
_BEGINNT_MIT_AUFRUF = re.compile(r"^\s*(?:```[a-z]*\s*)?ACT\s+[a-zA-Z_]\w*", re.IGNORECASE)
_MIN_ANTWORT = 40
_RESTE_MARKE = " "

# Fuer die BEREINIGUNG (nicht fuers Ausfuehren) gilt ein lockereres Muster: das
# Leerzeichen darf fehlen. Live steht in einer zugestellten Nachricht woertlich
# "ACTremember_fact {...}" — _ACT_RE verlangt ACT\s+ und sah den Aufruf gar nicht,
# also blieb er samt privater Daten im Text stehen. Der Werkzeugname ist immer
# klein geschrieben; das [a-z_] verhindert, dass ein Wort wie "ACTION {" mitgeht.
_ACT_LOCKER = re.compile(r"ACT\s*([a-z_]\w*)\s*\{")

# Ein Aufruf, der eine eigene ZEILE beginnt, ist liegengebliebenes Innenleben.
# Einer mitten im Satz ist ein Beispiel in einer Erklaerung ("ein textbasiertes
# `ACT tool {json}`-Format") und gehoert zur Antwort.
#
# Dieses Merkmal ist die Lehre aus drei Pruefrunden ueber derselben Stelle: erst
# wurde zu wenig gefiltert (4 von 11 Leaks), dann zu viel (14, darunter drei
# richtige Antworten von bis zu 4434 Zeichen), dann wieder zu wenig. Weder "beginnt
# mit dem Aufruf" noch "endet damit" noch die Klammerbilanz trifft die Sache — die
# Zeile tut es.
_AUFRUF_ZEILENANFANG = re.compile(
    # argumentlos, die Zeile endet danach — auch "ACT health()" mit leerem Klammerpaar
    r"^[\s`*\-–•>]*ACT\s*[a-z_]\w*\s*(?:\(\s*\))?\s*$"
    # oder mit Argumenten: die oeffnende Klammer folgt direkt
    r"|^[\s`*\-–•>]*ACT\s*[a-z_]\w*\s*\{", re.MULTILINE)


def _aufruf_ende(t: str, klammer: int) -> int:
    """Index HINTER der schliessenden Klammer eines Aufrufs; -1, wenn er nie schliesst.

    Klammern zaehlen, nicht die erste beste nehmen: die Nutzlast enthaelt oft selbst
    geschweifte Klammern. Bei

        ACT run_command {"command": "powershell -c "Get-Process |
                         Where-Object {$_.ProcessName -match 'python'} | …"}

    ist die erste schliessende Klammer die von Where-Object — wer dort abschneidet,
    haelt den REST DES JSON faelschlich fuer Prosa und laesst den Leak durch. Genau so
    gingen zwei echte Live-Leaks (454 und 495 Zeichen) wieder an den Nutzer raus."""
    tiefe = 0
    for i in range(klammer, len(t)):
        if t[i] == "{":
            tiefe += 1
        elif t[i] == "}":
            tiefe -= 1
            if tiefe == 0:
                return i + 1
    return -1


# Wortbruecke fuer den "Meintest du"-Vorschlag: deutsche und englische Werkzeugnamen
# stehen im Manifest nebeneinander, ein Modell mischt sie. find_files -> datei_finden.
_WORT_BRUECKE = {
    "find": ("find", "such"), "search": ("such", "find"),
    "file": ("datei", "file"), "files": ("datei", "dir", "file"),
    "dir": ("dir", "ordner"), "folder": ("ordner", "dir"),
    "note": ("notiz", "note", "vault"), "notes": ("notiz", "note", "vault"),
    "read": ("les", "read"), "write": ("schreib", "write"),
    "delete": ("loesch", "remove", "entfern", "delete"),
    "remove": ("remove", "loesch", "entfern"),
    "create": ("erstell", "add", "new"), "new": ("neu", "add"),
    "add": ("add", "erstell"), "get": ("hol", "get", "fetch"),
    "appointment": ("termin",), "date": ("termin",), "calendar": ("termin",),
    "reminder": ("erinnerung",), "task": ("todo",), "tasks": ("todo",),
}


def _meintest_du(name: str, verfuegbar) -> str:
    """'find_files' -> ' Meintest du datei_finden?' — sonst leer.

    Katalog-Lauf 28.07., Aufgabe 082: das Modell rief find_files; das Werkzeug heisst
    datei_finden. Der Lehrfehler griff ("existiert nicht"), aber das Modell stellte
    danach NICHT auf den richtigen Namen um — die Liste aller Werkzeuge ist zu lang,
    um daraus den einen zu finden. Ein Vorschlag ist billiger als eine Liste.

    Zwei Wege zur Aehnlichkeit, weil deutsche und englische Namen nebeneinanderstehen:
    Zeichenaehnlichkeit (find_file/file_find) UND gemeinsame Wortbausteine, damit auch
    die Uebersetzung greift (find+file -> datei+finden)."""
    import difflib

    n = (name or "").strip().lower()
    namen = [str(x) for x in (verfuegbar or [])]
    if not n or not namen:
        return ""

    # 1. BEDEUTUNG vor Zeichen. Andersherum gewinnt der Zufall: "find_files" und
    # "read_file" teilen sich viele Buchstaben, "datei_finden" fast keinen — die
    # Zeichenaehnlichkeit schlug deshalb genau den falschen Namen vor.
    woerter = [w for w in re.split(r"[_\-\s]+", n) if w]
    bewertet = []
    for kandidat in namen:
        kteile = [w for w in re.split(r"[_\-\s]+", kandidat.lower()) if w]
        gemeinsam = 0
        for w in woerter:
            formen = _WORT_BRUECKE.get(w, (w,))
            if any(a[:4] and (a.startswith(b[:4]) or b.startswith(a[:4]))
                   for a in formen for b in kteile):
                gemeinsam += 1
        if gemeinsam:
            bewertet.append((gemeinsam, -len(kandidat), kandidat))
    bewertet.sort(reverse=True)
    # Mindestens ZWEI gemeinsame Bausteine — sonst wird aus "send_telegram" ein
    # Vorschlag "email_send", und das Modell verschickt eine Mail statt zu antworten.
    if bewertet and bewertet[0][0] >= 2:
        return f" Meintest du {bewertet[0][2]}?"

    # 2. Sonst nur noch ein echter TIPPFEHLER — sehr eng. Ein falscher Vorschlag ist
    # schlimmer als keiner: bei 0,75 wurde aus "list_files" ein "list_skills", und das
    # Modell haette Faehigkeiten zurueckbekommen und fuer Dateien gehalten. Was hier
    # noch durchkommt, unterscheidet sich nur um ein paar Zeichen.
    fuer = {x.lower(): x for x in namen}
    treffer = difflib.get_close_matches(n, list(fuer), n=1, cutoff=0.88)
    return f" Meintest du {fuer[treffer[0]]}?" if treffer else ""


def _endet_mit_aufruf(text: str) -> bool:
    """Steht am ENDE des Textes ein Aufruf, dem nichts Nennenswertes mehr folgt?

    Das ist die Signatur eines liegengebliebenen Aufrufs: das Modell kuendigt an und
    setzt die ACT-Zeile hinterher — "Ich schaue kurz nach, welche Modelle es gibt.\\n
    ACT list_models". _parse_act fuehrt das bewusst NICHT aus (die argumentlose Form
    ist von Prosa nicht zu unterscheiden, siehe dort). Ohne diese Pruefung fiel so ein
    Text durch beide Siebe: nicht ausgefuehrt UND woertlich zugestellt — genau die
    Leak-Klasse, gegen die die Wache gebaut wurde.

    Eine Erklaerung sieht anders aus: dort geht der Text nach dem Beispiel weiter."""
    t = (text or "").strip()
    letzte_ende = -1
    for m in _ACT_LOCKER.finditer(t):
        try:
            _, ende = json.JSONDecoder(strict=False).raw_decode(t[m.end() - 1:])
            letzte_ende = max(letzte_ende, m.end() - 1 + ende)
        except json.JSONDecodeError:
            zu = _aufruf_ende(t, m.end() - 1)
            letzte_ende = max(letzte_ende, zu if zu >= 0 else len(t))
    for m in _ACT_OHNE_ARGS_RE.finditer(t):
        letzte_ende = max(letzte_ende, m.end())
    if letzte_ende < 0:
        return False
    return len(t[letzte_ende:].strip(" \t\n`{}\"'.,:;-")) < _MIN_ANTWORT


def _werkzeugreste(text: str) -> tuple[str, int, bool]:
    """Schneidet alle lesbaren ACT-Aufrufe heraus.

    Rueckgabe: (was ohne die Aufrufe uebrig bleibt, wieviele es waren, angefangen).
    'angefangen' heisst: ein Aufruf beginnt, laesst sich aber nicht zu Ende lesen —
    gekappte Generation oder kaputtes JSON. Dann ist der Zug NICHT fertig, und nichts
    davon darf zugestellt werden.

    Was 'angefangen' NICHT heissen darf: dass irgendwo im Text ein Platzhalter steht.
    Erklaert Kira ihre eigene Bauweise, schreibt sie Dinge wie "ein textbasiertes
    `ACT tool {json}`-Format" — das ist kein Aufruf, das ist Prosa, und {json} ist
    kein gueltiges JSON. Die erste Fassung schloss daraus auf einen angefangenen
    Aufruf und warf die ganze Antwort weg. Am echten Korpus gemessen: statt 4
    Nachrichten verwarf sie 14, darunter drei vollstaendige, richtige Antworten von
    2488, 2697 und 4434 Zeichen. Es traf ausgerechnet starke Modelle, weil die diese
    langen, strukturierten Texte schreiben.

    Das verlaessliche Merkmal ist nicht die Klammerbilanz (die trennt hier gar nichts:
    bei den echten Leaks steht das '}' formal da), sondern ob nach dem unlesbaren
    Aufruf noch nennenswerter Text FOLGT. Bei den Leaks folgen 0 Zeichen — der Aufruf
    ist das Letzte, was das Modell geschrieben hat. Bei den Erklaerungen folgen 1100
    bis 3200 Zeichen weiter."""
    t = (text or "").strip()
    if not t:
        return "", 0, False
    rest, n = t, 0
    for _ in range(50):
        m = _ACT_LOCKER.search(rest)
        if not m:
            break
        try:
            _, ende = json.JSONDecoder(strict=False).raw_decode(rest[m.end() - 1:])
        except json.JSONDecodeError:
            zu = _aufruf_ende(rest, m.end() - 1)
            danach = rest[zu:] if zu >= 0 else ""
            if len(danach.strip(" \t\n`{}\"'.,:;-")) < _MIN_ANTWORT:
                return rest, n, True          # der Aufruf war das Letzte -> Zug unfertig
            # Sonst: Prosa, die einen Aufruf zeigt. Herausschneiden und weitersuchen.
            # n MUSS mitzaehlen: _brauchbare_antwort schneidet nur, wenn n > 0 — sonst
            # wurde der bereinigte Text zwar berechnet, aber nie benutzt.
            rest = rest[:m.start()] + _RESTE_MARKE + danach
            n += 1
            continue
        rest = rest[:m.start()] + _RESTE_MARKE + rest[m.end() - 1 + ende:]
        n += 1
    for _ in range(50):
        m = _ACT_OHNE_ARGS_RE.search(rest)
        if not m:
            break
        rest = rest[:m.start()] + _RESTE_MARKE + rest[m.end():]
        n += 1
    return rest.strip(), n, False


def _ist_roher_werkzeugaufruf(text: str) -> bool:
    """Ist das hier Innenleben statt einer Antwort?

    Live-Befund (818 zugestellte Nachrichten): 12 enthalten frueh eine ACT-Zeile.
    Nachgezaehlt sind davon 11 echte Leaks in drei Formen — 4 reine Aufrufe
    ("ACT list_models", "ACT health()"), 5 mittendrin gekappte, und 2, die aus
    mehreren remember_fact-Aufrufen PLUS einer echten, guten Antwort bestehen. In
    den beiden letzten standen private Finanzzahlen als JSON im Chat.

    Roh ist deshalb: ein angefangener, nicht lesbarer Aufruf (der Zug ist nicht
    fertig) ODER ein Aufruf am Anfang einer ZEILE, nach dessen Entfernen nichts
    Nennenswertes uebrig bleibt. Prosa, die einen Aufruf nur erwaehnt oder als
    Beispiel zeigt, ist eine richtige Antwort und bleibt.

    Beide Siebe — dieses hier und die Bereinigung in _brauchbare_antwort — pruefen
    dasselbe Merkmal. Solange sie es nicht taten, klaffte dazwischen ein Loch: bei
    "Ok, notiere ich.\\nACTremember_fact {...}" verlangte dieses Sieb, dass der Text
    MIT dem Aufruf beginnt (tut er nicht), und die Bereinigung verlangte 40 Zeichen
    Rest (sind nur 16) — also griff keins von beiden und der Aufruf ging samt Inhalt
    woertlich raus. Die 40-Zeichen-Marke ist eine WEICHE zwischen "bereinigen" und
    "nachfassen", kein Veto gegen beides."""
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("<tool_call>"):
        return True
    rest, n, angefangen = _werkzeugreste(t)
    if angefangen:
        return True
    return n > 0 and bool(_AUFRUF_ZEILENANFANG.search(t)) and len(rest) < _MIN_ANTWORT


def _brauchbare_antwort(text: str, messages: list[dict], system: str, session_id: str | None,
                        task_type: str = "chat", escalate: bool = False) -> str:
    """Letzte Wache vor der Zustellung: nichts Leeres, nichts Rohes geht raus.

    Zwei Loecher, die fast ausschliesslich kleine Modelle treffen (21 Tage Live-Daten):
      * 29 von 818 zugestellten Nachrichten (3,5 %) waren LEER — bei kira-c6-9b 10 %,
        bei jedem Cloud-Modell 0 %. Ein Teil der vom Nutzer beklagten "halben
        Nachrichten" sind gar keine halben, sondern voellig leere.
      * 11 waren Werkzeug-Innenleben statt Text.

    Drei Ausgaenge, je nachdem was wirklich vorliegt:
      * nichts Auffaelliges -> unveraendert durch (der Regelfall, kostet nichts),
      * Aufrufe PLUS echte Antwort -> nur die Aufrufe raus, die Antwort bleibt. Genau
        so sahen die beiden schlimmsten Faelle aus: vier remember_fact-Aufrufe mit
        privaten Finanzzahlen als JSON, darunter eine 1994 Zeichen lange, voellig
        richtige Reply. Die wegzuwerfen und neu zu fragen waere Verschwendung,
      * nur Innenleben oder ein angefangener Aufruf -> EIN Nachfass-Zug.

    Fuer ein starkes Modell ist diese Wache ein Nullpfad — sie feuert bei ihm so gut
    wie nie und kostet dann keinen einzigen Zusatzaufruf."""
    t = (text or "").strip()
    if t and not _ist_roher_werkzeugaufruf(t):
        # Aufrufe vor einer echten Antwort: nur das Innenleben entfernen. Der Aufruf
        # ist ohnehin nicht gelaufen — ihn dem Partner zu zeigen bringt niemandem etwas.
        rest, n, angefangen = _werkzeugreste(t)
        # Steht ein Aufruf am Anfang einer ZEILE, ist er Innenleben; steht er mitten
        # im Satz, ist er ein Beispiel und gehoert zur Antwort. Die Anker "beginnt
        # mit" und "endet mit" reichten beide nicht: eine zugestellte Nachricht hatte
        # drei rohe remember_fact-Aufrufe in der MITTE und 2156 Zeichen echte Antwort
        # darunter — sie ging komplett unveraendert raus.
        if n and not angefangen and rest != t and len(rest) >= _MIN_ANTWORT \
                and _AUFRUF_ZEILENANFANG.search(t):
            events.emit("werkzeugreste_entfernt", {"aufrufe": n, "task_type": task_type},
                        session_id=session_id)
            return rest
        return t
    grund = "leer" if not t else "roher Werkzeugaufruf"
    events.emit("antwort_nachgefasst", {"grund": grund, "task_type": task_type},
                session_id=session_id)
    try:
        nach = list(messages) + [{"role": "user", "content": (
            "Deine letzte Antwort war unbrauchbar (" + grund + "). Schreib JETZT die "
            "fertige Antwort fuer " + _id.user_name() + " — in normalen Saetzen, ohne "
            "Werkzeug-Zeile. Wenn du etwas herausgefunden hast, sag es; wenn nicht, sag "
            "ehrlich, was fehlt.")}]
        res = _complete_resilient(nach, system=system, task_type=task_type,
                                  session_id=session_id, escalate=escalate)
        zweit = (res.get("text") or "").strip()
        if zweit and not _ist_roher_werkzeugaufruf(zweit):
            return zweit
    except Exception as e:  # noqa: BLE001 — die Wache darf nie die letzte Antwort kosten
        events.emit("antwort_nachfassen_fehler", {"error": str(e)[:200]}, session_id=session_id)
    # Auch der zweite Versuch trug nichts — dann ehrlich sein statt Leere zu senden.
    return KAPITULATION


def _parse_act(text: str):
    """Findet 'ACT <tool> {json}' robust — auch mit Prosa oder Code-Fences drumherum,
    damit Tool-Aufrufe nie als Antwort durchsickern. JSON wird ab der '{'-Position
    dekodiert (raw_decode ignoriert nachfolgenden Text).
    Fallback (Leak-Recovery): ein gefencter '<name> {json}'-Block OHNE ACT-Praefix
    zaehlt ebenfalls als Aufruf — existiert das Werkzeug nicht, greift dadurch der
    lehrende Dispatcher-Fehler ('existiert nicht. Verfuegbar: …') statt dass der
    Leak als Antwort beim Nutzer landet."""
    t = text.replace("`", " ").replace("*", " ")  # Fences/Deko entschaerfen, Laenge bleibt 1:1
    m = _ACT_RE.search(t)
    if m:
        name = m.group(1)
        brace = m.end() - 1  # Index des '{'
    else:
        # Argumentloser Aufruf: das Manifest preist zwoelf Werkzeuge als "Argumente:
        # keine" an (jetzt, health, cron_list, list_models …) — und ausgerechnet der
        # einfachste Fall fiel bisher durch, weil der Parser eine '{' verlangte.
        #
        # ABER: diese Form ist von Prosa nicht zu unterscheiden. Ein JSON-Rumpf macht
        # einen Aufruf eindeutig, eine nackte Zeile "ACT restart_self" nicht — die
        # steht genauso in einer Erklaerung oder einer Rueckfrage. Ungefiltert wurde
        # aus "Wenn du willst, mache ich einen Neustart. Dafuer nutze ich: ACT
        # restart_self — soll ich?" ein echter Neustart. Dieselbe Falle wie beim
        # Defender-Fund vom 26.07.: eine Rueckfrage ist eine Antwort, keine Aktion.
        #
        # Deshalb zaehlt die argumentlose Form nur, wenn drumherum nichts Nennenswertes
        # steht — so, wie das Protokoll es ohnehin verlangt ("antworte mit GENAU einer
        # Zeile, sonst nichts").
        om = _ACT_OHNE_ARGS_RE.search(t)
        if om:
            drumherum = (t[:om.start()] + t[om.end():]).strip(" \t\n`{}\"'.,:;-")
            if len(drumherum) < _MIN_ANTWORT:
                return (om.group(1), {})
        fm = _FENCE_CALL_RE.search(text)
        if not fm:
            return None
        name = fm.group(1)
        brace = fm.start(2)
    try:
        # strict=False erlaubt ECHTE Zeilenumbrueche in Zeichenketten. Kleine Modelle
        # escapen sie fast nie korrekt — und es trifft ausgerechnet die Werkzeuge, die
        # Arbeit erzeugen (write_file, vault_note, knowledge_note). Bisher fiel so ein
        # Aufruf durch und der halb geschriebene Text landete als "Antwort" beim Nutzer.
        args, _ = json.JSONDecoder(strict=False).raw_decode(text[brace:])
    except json.JSONDecodeError:
        return None
    return (name, args) if isinstance(args, dict) else None


def _act_fragment(text: str) -> str | None:
    """Erkennt einen ABGESCHNITTENEN ACT-Aufruf: ACT-Zeile vorhanden, aber das JSON
    dahinter schliesst bis zum Textende nie — so sieht eine Generation aus, die der
    Server am Kontext-Limit gekappt hat. Liefert den Werkzeugnamen des gekappten
    Aufrufs, sonst None. Bewusst eng: heile Calls (auch mit kaputtem, aber
    geschlossenem JSON) und normale Antworten ohne ACT-Zeile sind KEIN Fragment."""
    t = text.replace("`", " ").replace("*", " ")  # wie _parse_act: Deko entschaerfen, Laenge 1:1
    m = _ACT_RE.search(t)
    if not m:
        return None
    rest = text[m.end() - 1:]  # ab der '{'-Position
    if rest.count("{") <= rest.count("}"):
        return None  # JSON (mindestens formal) geschlossen -> kein Abriss
    return m.group(1)


_ABRISS_MELDUNG = ("Meine Antwort wurde vom Kontext-Limit abgeschnitten — der letzte Schritt "
                   "'{name}' wurde NICHT ausgefuehrt. Stell mir die Aufgabe gern noch einmal, "
                   "dann arbeite ich sie in kleineren Schritten ab.")

_ERGEBNIS_KOPF = "ERGEBNIS von "

# --- Vertrags-Konstanten: EINE Quelle fuer Harness UND Trainingsgenerator ------------
# Befund 27.07.: core/mind/tuning.py hatte diese beiden Texte ABGESCHRIEBEN statt
# importiert und wich an beiden Stellen ab — der Generator baute "ERGEBNIS: <inhalt>"
# (ohne Werkzeugnamen, ohne Aufforderung) und lehrte 'ACT <werkzeug> {"arg": "wert"}'.
# Das Modell uebt damit eine Gespraechsform, die es im Betrieb nie sieht; genau diese
# Fehlerklasse hat schon c1 bis c4 verdorben (Audit 16.07.). Wer das Format aendert,
# aendert es hier — und die Werkstatt muss neu generieren.
ACT_ZEILE = 'ACT <werkzeug_name> {"argument": "wert"}'


def obs_wrapper(name: str, obs: str) -> str:
    """So spielt der Harness ein Werkzeug-Ergebnis zurueck — woertlich, beide Textpfade."""
    return f"ERGEBNIS von {name}:\n{obs}\n\nMach weiter oder gib die finale Antwort."
_KUERZUNGS_HINWEIS = ("\n[... aeltere Beobachtung gekuerzt — nur Vorschau ...]"
                      "\n\nMach weiter oder gib die finale Antwort.")


def _compact_history(messages: list[dict], limit: int | None = None) -> None:
    """Kuerzt Observations AELTERER Schritte in-place auf eine Vorschau, bis die
    History unter dem Zeichen-Budget liegt. Die Aufgabe selbst und die JUENGSTE
    Observation bleiben unangetastet (dort steht, was der naechste Schritt braucht).
    limit=0 = maximale Kuerzung (Retry nach gekapptem ACT-Aufruf)."""
    if limit is None:
        limit = _HISTORY_MAX
    total = sum(len(str(m.get("content") or "")) for m in messages)
    if total <= limit:
        return
    obs_idx = [i for i, m in enumerate(messages)
               if m.get("role") == "user" and str(m.get("content") or "").startswith(_ERGEBNIS_KOPF)]
    for i in obs_idx[:-1]:  # die juengste Observation nie anfassen
        if total <= limit:
            return
        alt = str(messages[i]["content"])
        kurz = alt[:_OBS_PREVIEW] + _KUERZUNGS_HINWEIS
        if len(kurz) >= len(alt):
            continue
        messages[i]["content"] = kurz
        total -= len(alt) - len(kurz)


def _retry_fragment(messages: list[dict], system: str, name: str, step: int,
                    session_id: str | None, task_type: str, escalate: bool,
                    reasoning: str | None = None) -> tuple[str, tuple | None]:
    """Zweiter Anlauf nach einem gekappten ACT-Aufruf: EIN Retry mit stark gekuerzter
    History (alte Observations -> Vorschau). Liefert (text, call): call != None ->
    der Loop fuehrt den Schritt normal aus; call == None -> text ist die finale
    Antwort — ein sauberer Abschluss ODER die ehrliche Ansage, dass der Schritt
    NICHT lief. Das rohe Fragment erreicht den Partner in keinem Fall."""
    events.emit("act_fragment", {"step": step, "tool": name}, session_id=session_id)
    _compact_history(messages, limit=0)
    try:
        res = llm_router.complete(messages, system=system, task_type=task_type,
                                  session_id=session_id, escalate=escalate, reasoning=reasoning)
        text = res["text"].strip()
    except Exception as e:  # noqa: BLE001
        events.emit("act_fragment", {"step": step, "tool": name, "abbruch": True,
                                     "error": str(e)[:200]}, session_id=session_id)
        return _ABRISS_MELDUNG.format(name=name), None
    call = _parse_act(text)
    if call:
        return text, call
    if not text or _act_fragment(text):
        events.emit("act_fragment", {"step": step, "tool": name, "abbruch": True},
                    session_id=session_id)
        return _ABRISS_MELDUNG.format(name=name), None
    return text, None


# W4b: die Plattform-Zeile ist das EINZIGE OS-abhaengige Stueck dieses Prompts.
# Windows-Wortlaut bleibt BYTE-IDENTISCH (Trainingsvertrag); Linux bekommt die korrekte Ansage.
_PLATTFORM_ZEILE = (
    "Du laeufst auf WINDOWS (PowerShell/cmd) — zum Erkunden/Lesen von Dateien nutze\n"
    "list_dir/read_file (NICHT shell-Befehle wie find/grep/ls) und KEINE Linux-Pfade wie /workspace\n"
    "oder $HOME."
    if _os.name == "nt" else
    "Du laeufst auf LINUX (bash) — zum Erkunden/Lesen von Dateien nutze\n"
    "list_dir/read_file (bevorzugt vor rohen find/grep/cat-Umwegen; sauberes Encoding + Stueckelung)."
)

_NATIVE_TOOLS_HINT = f"""

# WERKZEUGE
Du hast Werkzeuge (Web suchen/lesen, Dateien lesen/schreiben, Befehle ausfuehren, dich selbst
bearbeiten, Gedaechtnis, Monitor/Cron ...). Nutze sie bei Bedarf ueber die bereitgestellten
Funktionen. {_PLATTFORM_ZEILE} Wenn du etwas Aktuelles nicht sicher weisst (Wetter/News/Preise/Webinhalte) oder
Dateiinhalte brauchst: RATE NICHT — hol es dir mit dem passenden Werkzeug. Wenn du genug weisst,
antworte normal, natuerlich und vollstaendig fuer deinen Partner (ohne weiteren Werkzeug-Aufruf).
WICHTIG: Kuendige Aktionen NICHT nur an, um dann aufzuhoeren. Wenn du etwas nachsehen oder tun
willst, RUF die Werkzeuge SOFORT in DIESEM Zug auf und antworte erst mit dem Ergebnis. Eine
Antwort wie "lass mich kurz schauen ..." OHNE einen Werkzeug-Aufruf ist verboten."""


_PROMISE_RE = re.compile(
    r"(lass mich|ich schau|ich sehe nach|ich pruef|ich check|moment\b|kurz schauen|"
    r"schau(e)?\s+(mal|kurz)|sehe (mal )?nach|melde mich gleich|"
    # Rueckfrage-Muster (Bestaetigungsschleife): zurueckfragen statt handeln ist bei
    # klarem Auftrag genauso wertlos wie ankuendigen -> derselbe Nudge greift.
    r"soll ich|moechtest du|möchtest du|willst du,? dass|bestaetige|bestätige|"
    r"darf ich|gib (mir )?gruenes licht|wenn du einverstanden)", re.IGNORECASE)


def _looks_like_promise(text: str) -> bool:
    """Erkennt eine 'ich tu gleich was'- ODER 'soll ich?'-Antwort ohne Handlung (Heuristik)."""
    t = (text or "").strip()
    if not t:
        return True
    return len(t) <= 400 and (t.endswith(":") or bool(_PROMISE_RE.search(t)))


# --- Arbeitsauftrag-Erkennung (Auto-Plan) --------------------------------------------
# Ein klarer Arbeitsauftrag im Plain-Chat soll geplant und abgearbeitet werden statt im
# 8-Runden-Chat zerredet. Bewusst konservativ: False-Positive = unnoetiger Plan-Overhead,
# False-Negative = heutiges Verhalten.
_WORK_VERBS = (r"erstell|schreib|bau|generier|recherchier|analysier|entwickl|entwirf|"
               r"implementier|korrigier|fixe?|sammel|organisier|erarbeit|verfass|bereite|"
               r"ueberarbeit|überarbeit|raussuch|heraussuch|zusammenstell|hinterleg|anleg|such")
_WORK_VERB_RE = re.compile(r"^(" + _WORK_VERBS + r")", re.IGNORECASE)
_WORK_VERB_ANY_RE = re.compile(r"\b(" + _WORK_VERBS + r")\w*\b", re.IGNORECASE)
# Deutsche Hoeflichkeitsform: "Kannst du mir ... raussuchen" — das Verb steht am ENDE.
# Menschen formulieren hoeflich; der Harness muss das als Auftrag erkennen.
_POLITE_RE = re.compile(
    r"^(kannst|koenntest|könntest|wuerdest|würdest|magst|willst)\s+du\s+(mir\s+|bitte\s+|mal\s+)*",
    re.IGNORECASE)
_WORK_HINT_RE = re.compile(
    r"(\d+\s+\w+|desktop|datei|dateien|ordner|projekt|liste|e-?mails?|bericht|dossier)",
    re.IGNORECASE)


def _looks_like_work_order(text: str) -> bool:
    """True bei einem klaren, mehrteiligen Arbeitsauftrag (Imperativ ODER Hoeflichkeitsform
    mit Arbeitsverb + Substanz). Bewusst konservativ."""
    t = (text or "").strip()
    if len(t) < 25:
        return False
    imperativ = bool(_WORK_VERB_RE.match(t.split(maxsplit=1)[0]))
    # Hoeflichkeitsform zaehlt NUR mit Arbeitsverb irgendwo UND Substanz-Hinweis —
    # "Kannst du mir sagen, wie spaet es ist?" bleibt eine Frage.
    hoeflich = bool(_POLITE_RE.match(t)) and bool(_WORK_VERB_ANY_RE.search(t)) \
        and bool(_WORK_HINT_RE.search(t))
    if not (imperativ or hoeflich):
        return False
    if imperativ and t.endswith("?") and not _WORK_HINT_RE.search(t):
        return False  # echte Frage, kein Auftrag
    return hoeflich or len(t) > 120 or bool(_WORK_HINT_RE.search(t))


# --- Beweispflicht: Datei-Behauptungen nachpruefen ------------------------------------
# Gegen halluzinierte Ergebnisse ('10 fertige E-Mails liegen auf dem Desktop'): behauptet
# die Antwort erzeugte Dateien, prueft der Harness deren Existenz — read-only, deterministisch.
_CLAIM_VERB_RE = re.compile(
    # Wortgrenzen sind Pflicht: ohne sie zuendete "fliegt" auf "liegt" — genau so entstand
    # der Fehlalarm vom 21.07. an einem reinen Struktur-VORSCHLAG.
    r"\b(erstellt|geschrieben|gespeichert|angelegt|abgelegt|hinterlegt|liegt|liegen)\b",
    re.IGNORECASE)
_PATH_RE = re.compile(r"`([^`\n]{3,180})`|((?:~[\\/]|[A-Za-z]:\\)[\w .\-\\/]{2,180})")
# Signale dafuer, dass ein Satz etwas VORSCHLAEGT statt etwas zu behaupten.
_ENTWURF_RE = re.compile(
    r"\b(vorschlag|schlage|schlaege|wuerde|würde|wuerden|würden|koennte|könnte|sollte|"
    r"soll ich|willst du|moechtest|möchtest|geplant|kuenftig|künftig|neu anlegen|"
    r"vorher|bevor ich|danach|dann lege|entwurf|idee|beispiel)\b", re.IGNORECASE)
# Datei-ENDUNG darf nur aus Buchstaben bestehen. Haelt Modell-IDs ("z-ai/glm-5.2" -> ".2"),
# Query-Strings (".7") und Wiki-Platzhalter ("[[STAMM/...]]" -> ".]]") heraus — die machten
# 12 von 12 Live-Ausloesungen dieses Waechters aus, ohne einen einzigen echten Treffer.
_ENDUNG_RE = re.compile(r"\.[A-Za-z]{1,8}$")


def _ist_struktur_zeile(zeile: str) -> bool:
    """Tabellen- und Baum-Zeilen zeigen eine Struktur, sie behaupten nichts."""
    z = zeile.strip()
    return z.startswith("|") or bool(re.match(r"^[│├└─\s]*[├└│]", z))


def _missing_claims(text: str) -> list[str]:
    """Behauptete-aber-fehlende Dateien im Text (read-only, deterministisch, raist nie).

    Geprueft wird nur, was im SELBEN SATZ als erledigt behauptet wird — ein Vorschlag
    ("ich wuerde X anlegen"), eine Tabelle oder ein Ordner-Baum ist keine Behauptung.
    Gesucht wird auch im Vault des Nutzers; ohne ihn meldete der Waechter am 21.07.
    sieben Dateien als fehlend, die es wirklich gab."""
    if not _CLAIM_CHECK or not text or not _CLAIM_VERB_RE.search(text):
        return []
    try:
        from pathlib import Path

        from core.config import ROOT

        wurzeln = [Path.cwd(), ROOT, Path.home() / "Desktop"]
        try:
            from core.agency.vault_notes import vault_root

            if (vr := vault_root()):
                wurzeln.insert(0, Path(vr))
        except Exception:  # noqa: BLE001 — ohne Vault einfach ohne Vault pruefen
            pass

        fehlend: list[str] = []
        gesehen: set[str] = set()
        for m in _PATH_RE.finditer(text):
            tok = (m.group(1) or m.group(2) or "").strip().rstrip(".,;:)“”")
            if not tok or tok in gesehen or len(gesehen) >= 8:
                continue
            if "/" not in tok and "\\" not in tok:
                continue  # kein Pfad (z.B. Werkzeugname in Backticks)
            if "[[" in tok or "..." in tok or '"' in tok or "?" in tok:
                continue  # Wiki-Link, Platzhalter, Code-Beispiel — keine Zusage
            satz = _satz_um(text, m.start(), m.end())
            if not _CLAIM_VERB_RE.search(satz) or _ENTWURF_RE.search(satz):
                continue  # Behauptung nur, wenn Verb UND Pfad zusammenstehen
            if _ist_struktur_zeile(text[:m.start()].rsplit("\n", 1)[-1] + tok):
                continue
            p = Path(tok.replace("\\", "/")).expanduser()
            if not _ENDUNG_RE.search(p.name):
                continue  # nur dateiartige Tokens mit echter Endung
            gesehen.add(tok)
            kandidaten = [p] if p.is_absolute() else [p, *(w / p for w in wurzeln)]
            if not any(k.is_file() for k in kandidaten):
                fehlend.append(tok)
        return fehlend
    except Exception:  # noqa: BLE001 — der Check darf nie stoeren
        return []


# --- Beweispflicht II: ZUSTANDS-Behauptungen (Audit-Fund 26.07.) ----------------------
# Die Datei-Beweispflicht oben prueft Pfade. Der haeufigere Schaden betrifft aber Kiras
# eigene Stores: 54 Antworten behaupteten "eingetragen/gemerkt/erledigt", OHNE dass im
# selben Zug ein einziges Werkzeug lief ("✅ Termin mit Freundin am 12.07." — kalender.json
# kennt ihn nicht). Fuer diese Klasse braucht es keine Inhaltspruefung: hat der Zug KEIN
# Werkzeug benutzt, kann sich am Zustand nichts geaendert haben. Das ist deterministisch
# und modellunabhaengig — der Harness weiss es besser als jedes Modell.
_ZUSTAND_CLAIM_RE = re.compile(
    r"\b(eingetragen|eingeplant|angelegt|abgelegt|hinterlegt|gespeichert|gesichert|"
    r"gemerkt|notiert|vermerkt|erfasst|geloescht|gelöscht|entfernt|verschoben|umbenannt|"
    r"abgehakt|abgeschlossen|verschickt|versendet|gesendet|abgeschickt|eingerichtet|"
    r"aktualisiert|geaendert|geändert|gesetzt|gebucht|reserviert)\b", re.IGNORECASE)
# Nur Behauptungen ueber GETANES zaehlen — Angebote und Rueckfragen nicht.
_UNVERBINDLICH_RE = re.compile(
    r"\b(soll ich|moechtest du|möchtest du|kann ich|koennte ich|könnte ich|wuerde ich|"
    r"würde ich|werde ich|wird|willst du|darf ich|sobald|falls|wenn du)\b", re.IGNORECASE)


_SATZ_ENDE_RE = re.compile(r"[.!?](?=\s|$)|\n")


def _satz_um(text: str, pos_a: int, pos_b: int) -> str:
    """Den EINEN Satz herausschneiden, in dem der Treffer steht — nicht die Nachbarsaetze
    (sonst macht ein angehaengtes 'Soll ich noch ...?' aus einer Behauptung ein Angebot).

    Ein Satz endet auf .!? nur, wenn Leerraum oder Textende folgt: der Punkt in
    "notiz.md" ist kein Satzende und darf den Satz nicht zerschneiden."""
    anfang = 0
    for m in _SATZ_ENDE_RE.finditer(text, 0, pos_a):
        anfang = m.end()
    ende = _SATZ_ENDE_RE.search(text, pos_b)
    return text[anfang:(ende.end() if ende else len(text))]


def _behauptet_zustandsaenderung(text: str) -> str | None:
    """Signalwort, falls der Text eine bereits ERFOLGTE Zustandsaenderung behauptet."""
    t = (text or "").strip()
    if not t or len(t) > 1500:
        return None
    for treffer in _ZUSTAND_CLAIM_RE.finditer(t):
        satz = _satz_um(t, treffer.start(), treffer.end())
        if not _UNVERBINDLICH_RE.search(satz):
            return treffer.group(0)
    return None


# Heikles bleibt heikel (Audit-Fund 26.07.): "Schalt den Windows Defender aus" wurde per
# Nudge zu einem echten run_command, weil der Harness die Rueckfrage des Modells als
# Ankuendigung wegbuegelte. Bei sicherheits- oder geldrelevanten Wuenschen ist Nachfragen
# die RICHTIGE Antwort — da wird nie gestupst.
# Entfesselung 23.08. (Inventur M16): NUR noch echte System-Sicherheits-Begriffe gelten
# als heikel (Defender/Firewall/Registry/Formatieren) — Kaufen/Bestellen/Posten/Kuendigen
# sind seit dem Gate-Aus normale Auftraege und werden wie jede Arbeit direkt erledigt.
_HEIKEL_RE = re.compile(
    r"\b(defender|firewall|virenschutz|antivirus|registry|bitlocker|"
    r"deinstallier|formatier|partition|systemwiederherstellung)\b", re.IGNORECASE)


def _nudge_angebracht(user_message: str) -> bool:
    """Darf der Harness bei DIESER Nutzer-Nachricht zum Handeln draengen?

    Der Stups ist gegen Ankuendigungen bei klaren Auftraegen gedacht. Er feuerte aber
    auf JEDE Nachricht — "Guten Mittag Kira!" endete deshalb in list_dir. Der Filter ist
    absichtlich weiter als _looks_like_work_order (das gehoert zum teuren Auto-Plan),
    aber er kennt zwei harte Tabus: Smalltalk und heikle Wuensche."""
    t = (user_message or "").strip()
    if len(t) < 12 or _HEIKEL_RE.search(t):
        return False
    erstes = t.split(maxsplit=1)[0] if t.split() else ""
    return bool(_WORK_VERB_RE.match(erstes) or _POLITE_RE.match(t)
                or _WORK_VERB_ANY_RE.search(t) or _looks_like_work_order(t))


def _claim_stamp(text: str, session_id: str | None = None) -> str:
    """Haengt eine sichtbare Warnung an, wenn behauptete Dateien NICHT existieren."""
    fehlend = _missing_claims(text)
    if fehlend:
        events.emit("claim_check_failed", {"missing": fehlend[:8]}, session_id=session_id)
        # Der Hinweis geht an den NUTZER, nicht an Kira: frueher stand hier
        # "erledige es wirklich oder sag ehrlich, dass es fehlt" — eine Anweisung an
        # das Modell, die der Nutzer als Vorwurf an sich selbst las (Live-Fall 21.07.).
        text += ("\n\n⚠ Nachgeprüft: " + ", ".join(fehlend[:8])
                 + (" gibt es nicht." if len(fehlend) == 1 else " gibt es nicht.")
                 + " Was oben steht, ist an dieser Stelle also nicht gedeckt.")
    return text


def _cloud(escalate: bool, task_type: str = "reason") -> bool:
    """True, wenn das aufzurufende Modell wirklich in der Cloud laeuft. Lokale
    Endpunkte (Ollama UND llama.cpp-Server a la Nachtdenker) fahren den ACT-Pfad
    mit dem schlanken haupt-Manifest — die trainierte Umgebung der c-Linie, und
    der 5k-Prompt haelt den Prefill grosser lokaler Modelle im Sekundenbereich."""
    model, _ = llm_router.resolve_model(task_type, escalate=escalate)
    return not llm_router.ist_lokal(model)


# --- Geteiltes Gedaechtnis: code:/plan: erbt den Brainstorm davor -----------------------
# Ohne das startet der Coder blind — er weiss nicht, worueber gerade im Chat gesprochen
# wurde. Der Verlauf DERSELBEN Session wird als kompakter Kontext-Block vorangestellt.
_DIALOG_PREFIX_CAP = 2500


def _dialog_prefix(history: list[dict]) -> str:
    """Kompakter 'GESPRAECH BISHER'-Block aus den letzten Zuegen (leer -> '')."""
    if not history:
        return ""
    zeilen: list[str] = []
    for h in history[-8:]:
        txt = (h.get("text") or "").strip()
        if not txt:
            continue
        wer = _id.user_name() if h.get("role") == "user" else _id.agent_name()
        zeilen.append(f"{wer}: {txt}")
    if not zeilen:
        return ""
    block = "\n".join(zeilen)
    if len(block) > _DIALOG_PREFIX_CAP:  # aeltestes zuerst kappen, juengster Kontext bleibt
        block = "…(gekuerzt)…\n" + block[-_DIALOG_PREFIX_CAP:]
    return ("GESPRAECH BISHER (Kontext aus dem Chat — beziehe dich darauf, "
            "frag nicht erneut nach dem, was hier schon steht):\n" + block + "\n\n---\n")


# --- Read-before-Edit-Guard (B-028, Claude-Code-Prinzip, deterministisch) ---------------
# Editieren darf nur, wer die Datei in DIESER Session vorher angefasst hat (read_file,
# code_suche-/datei_finden-Treffer). Harness-Mechanik statt LLM-Disziplin: kein Modell
# kann blind drauflos schreiben. Neue (nicht existierende) Dateien sind frei.
_RBE_ON = bool(_AG.get("read_before_edit", True))
_EDIT_TOOLS = {"edit_datei": "pfad", "self_edit": "path"}
_SEEN_FILES: dict[str, set] = {}
_SEEN_SESSIONS_CAP = 32
_OBS_PATH_RE = re.compile(r"^([\w][\w .\-/\\]{2,180}\.\w{1,9})(?=:|\s*$)", re.MULTILINE)


def _rbe_norm(p: str) -> str:
    """Pfad-Token auf ROOT-relatives Posix-Format bringen (best effort, raist nie)."""
    try:
        from pathlib import Path

        from core.config import ROOT

        pp = Path(str(p).strip().replace("\\", "/")).expanduser()
        if pp.is_absolute():
            try:
                return pp.resolve().relative_to(Path(ROOT).resolve()).as_posix()
            except Exception:  # noqa: BLE001 — ausserhalb des Projekts -> absolut
                return pp.as_posix()
        return pp.as_posix()
    except Exception:  # noqa: BLE001
        return str(p)


def _rbe_seen(session_id: str | None) -> set:
    key = session_id or "solo"
    if key not in _SEEN_FILES and len(_SEEN_FILES) >= _SEEN_SESSIONS_CAP:
        _SEEN_FILES.pop(next(iter(_SEEN_FILES)), None)  # aelteste Session raus
    return _SEEN_FILES.setdefault(key, set())


def _rbe_record(session_id: str | None, name: str, args: dict, obs: str) -> None:
    """Nach jedem Werkzeug-Lauf: gelesene/gefundene Dateien der Session gutschreiben."""
    try:
        seen = _rbe_seen(session_id)
        if name in ("read_file",) and args.get("path"):
            seen.add(_rbe_norm(args["path"]))
        elif name in ("code_suche", "datei_finden", "code_symbol"):
            for m in _OBS_PATH_RE.finditer(obs or ""):
                seen.add(_rbe_norm(m.group(1)))
                if len(seen) > 400:
                    break
        elif name == "code_umriss" and args.get("pfad"):
            seen.add(_rbe_norm(args["pfad"]))   # Landkarte gesehen = Datei bekannt
        elif name in _EDIT_TOOLS and args.get(_EDIT_TOOLS[name]):
            seen.add(_rbe_norm(args[_EDIT_TOOLS[name]]))  # einmal editiert = bekannt
    except Exception:  # noqa: BLE001 — Buchhaltung darf nie stoeren
        pass


def _rbe_block(session_id: str | None, name: str, args: dict) -> str | None:
    """Blockier-Text, wenn ein Edit-Werkzeug eine UNGELESENE bestehende Datei anfasst."""
    if not _RBE_ON or name not in _EDIT_TOOLS:
        return None
    try:
        from pathlib import Path

        from core.config import ROOT

        raw = args.get(_EDIT_TOOLS[name]) or ""
        if not str(raw).strip():
            return None
        rel = _rbe_norm(raw)
        ziel = Path(rel) if Path(rel).is_absolute() else Path(ROOT) / rel
        if not ziel.is_file():
            return None  # neue Datei -> frei
        if rel in _rbe_seen(session_id):
            return None
        events.emit("edit_blocked_unread", {"tool": name, "file": rel}, session_id=session_id)
        return (f"GESPERRT (Read-before-Edit): Du hast '{rel}' in dieser Session noch nicht "
                f"gelesen. Lies die relevante Stelle ZUERST (read_file oder code_suche auf die "
                f"Datei) und rufe {name} danach erneut auf.")
    except Exception:  # noqa: BLE001 — im Zweifel nicht blockieren
        return None


_TRACE_OBS_CAP = 260
_TRACE_OBS_CAP_EDIT = 2400  # Edits tragen den Diff -> im Live-Trace ganz zeigen (nur ephemeres WS, nicht gespeichert)


def _trace_obs(name: str, obs: str) -> str:
    """Wieviel vom Werkzeug-Ergebnis in den Live-Trace geht. Edits: der Diff soll ganz kommen
    (Claude-Code-Look), sonst ein knapper Vorschau-Schnipsel."""
    cap = _TRACE_OBS_CAP_EDIT if name in _EDIT_TOOLS else _TRACE_OBS_CAP
    return (obs or "")[:cap]


# Selbstkorrektur-Reflex: merkt sich pro Session die letzte ROTE Edit-Meldung (zurueckgerollt),
# bis ein Edit wieder GRUEN ist. So kann der Plan-Lauf erkennen, dass ein Edit haengt, und EINEN
# gezielten Retry mit Strategiewechsel erzwingen — statt dass ein schwaches Modell aufgibt.
_EDIT_FAIL: dict = {}


def _edit_fail_record(session_id: str | None, name: str, obs: str) -> None:
    if name not in _EDIT_TOOLS:
        return
    sid = session_id or "_"
    low = (obs or "").strip().lower()
    if low.startswith("ok"):
        _EDIT_FAIL.pop(sid, None)
    elif low.startswith("fehlgeschlagen") or "zurueckgerollt" in low or "verifizierung fehlgeschlagen" in low:
        _EDIT_FAIL[sid] = (obs or "").strip()[:400]


def _edit_fail_get(session_id: str | None) -> str:
    return _EDIT_FAIL.get(session_id or "_", "")


# SWE-bench-Befund (3/3 Aufgaben, 19.08.): Arbeiter-Schritte mit klarem Edit-Auftrag
# ("Erstelle einen minimalen Patch", "Fuege header_rows Support hinzu") endeten in
# reiner ANALYSE-Prosa — 36 Lese-Werkzeuge, kein einziges Schreib-Werkzeug, Patch leer.
# Die bestehenden Waechter griffen nicht: _missing_claims prueft nur NEUE Dateien
# (die editierte existiert ja), der Edit-rot-Reflex nur MISSGLUECKTE Edits (es gab
# keinen Versuch). Dieser Zaehler macht den Versuch selbst messbar.
_EDIT_TRY_TOOLS = ("edit_datei", "self_edit", "write_file")
# 9B-Befund (SWE-bench-Baseline): Kleinmodelle "erfuellen" einen Fix-Auftrag gern mit
# einer NEUEN Repro-/Testdatei (write_file) — der Edit-Zaehler war zufrieden, der Fix
# fehlte (4 von 10 Patches nur in falschen/neuen Dateien). Fuer MODIFIKATIONS-Auftraege
# zaehlen darum nur Werkzeuge, die Bestehendes aendern.
_MODIFY_TOOLS = ("edit_datei", "self_edit")
_EDIT_TRIED: dict = {}
_MODIFY_TRIED: dict = {}

# implementier/korrigier NUR als Verbformen — das Substantiv ("finde die
# Implementierung") ist ein Lese-Ziel, kein Edit-Auftrag (SWE-bench-v2-Fehlschuss:
# der Guard erzwang einen Edit-Retry mitten in der Erkundung und verbrannte Budget).
_EDIT_INTENT = re.compile(
    r"\b(patch|edit|fix|fixe|behebe|beheben|implementier(?!ung)\w*|korrigier(?!ung)\w*)\b"
    r"|\bf(?:ue|\u00fc)ge\b.+\bhinzu\b"
    r"|\b(?:ae|\u00e4)nder(?!ung)\w*\b", re.IGNORECASE)

# MODIFIKATIONS-Absicht: der Auftrag verlangt eine Aenderung BESTEHENDEN Codes
# (fix/behebe/patch/korrigier/aender/reparier) — dann ist eine neue Datei kein Beweis.
_MODIFY_INTENT = re.compile(
    r"\b(patch|fix|fixe|behebe|beheben|korrigier(?!ung)\w*|reparier\w*)\b"
    r"|\b(?:ae|\u00e4)nder(?!ung)\w*\b", re.IGNORECASE)

# Ein fuehrendes Lese-/Test-Verb definiert den Schritt ("Teste die Aenderung lokal",
# "Analysiere den Fix") — solche Schritte verlangen selbst KEINEN Edit.
_EDIT_INTENT_NOT = re.compile(
    r"^\s*(test\w*|pr(?:ue|\u00fc)f\w*|verifizier\w*|analysier\w*|erkunde\w*|"
    r"explorier\w*|finde\b|suche\b|oeffne\b|\u00f6ffne\b|"
    r"lies\b|liste\w*|untersuch\w*|miss\b|beobacht\w*|dokumentier\w*)", re.IGNORECASE)


def _frage_am_ende(text: str) -> bool:
    """Endet ein Ergebnis mit einer Rueckfrage an den Nutzer? (Workflow-Befund
    wf-friseur-leads: das Modell kannte den naechsten Schritt exakt und fragte
    trotzdem 'Soll ich direkt loslegen?' — im autonomen Lauf wartet dann niemand.)
    Bewusst konservativ: nur die LETZTE nicht-leere Zeile zaehlt."""
    zeilen = [z.strip() for z in (text or "").strip().splitlines() if z.strip()]
    return bool(zeilen) and zeilen[-1].endswith("?")


def _edit_tried_get(session_id: str | None) -> int:
    return int(_EDIT_TRIED.get(session_id or "_", 0))


def _edit_tried_bump(session_id: str | None, name: str) -> None:
    sid = session_id or "_"
    if name in _EDIT_TRY_TOOLS:
        _EDIT_TRIED[sid] = _EDIT_TRIED.get(sid, 0) + 1
    if name in _MODIFY_TOOLS:
        _MODIFY_TRIED[sid] = _MODIFY_TRIED.get(sid, 0) + 1


def _modify_tried_get(session_id: str | None) -> int:
    return int(_MODIFY_TRIED.get(session_id or "_", 0))


def _edit_fail_clear(session_id: str | None) -> None:
    _EDIT_FAIL.pop(session_id or "_", None)


def _falsche_argumente(name: str, tool, args: dict) -> str:
    """Lehrfehler bei unbekannten/fehlenden Argumenten — oder "" wenn der Aufruf passt.

    Rund 60 der 80 Werkzeuge nahmen bis 27.07. kein **falsche_args entgegen: ein
    falscher Argumentname warf einen rohen TypeError. Der lief durch drei Executor-
    Versuche mit Backoff (~3 s verschenkt), und nach dreimal sperrte der Circuit-Breaker
    das Werkzeug fuer 60 Sekunden — wegen eines Tippfehlers, der deterministisch ist und
    beim vierten Versuch genauso scheitert. Das Modell bekam dabei nie zu lesen, WELCHE
    Argumente richtig gewesen waeren.

    Werkzeuge mit **kwargs behandeln den Fall selbst (spezifischer, oft mit passendem
    Beispiel) — die ueberspringt diese Wache."""
    try:
        import inspect

        sig = inspect.signature(tool.func)
        if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()):
            return ""       # das Werkzeug lehrt selbst
        erlaubt = {n for n, p in sig.parameters.items() if p.kind is not p.VAR_POSITIONAL}
        unbekannt = sorted(k for k in args if k not in erlaubt)
        fehlend = sorted(
            n for n, p in sig.parameters.items()
            if p.default is p.empty
            and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
            and n not in args)
        if not (unbekannt or fehlend):
            return ""
        nimmt = ", ".join(tool.params) or ", ".join(sorted(erlaubt)) or "keine Argumente"
        # Beispiel nur mit den PFLICHT-Argumenten (gleiche Heuristik wie tool_schemas):
        # ein Beispiel mit allen Optionalen lehrt das Modell, sie immer mitzuschicken.
        pflicht = [k for k, v in (tool.params or {}).items()
                   if "optional" not in v.lower() and "standard" not in v.lower()]
        beispiel = json.dumps({k: "…" for k in (pflicht or list(tool.params or {}))},
                              ensure_ascii=False)
        teile = []
        if unbekannt:
            teile.append(f"kennt {', '.join(unbekannt)} nicht")
        if fehlend:
            teile.append(f"braucht {', '.join(fehlend)}")
        return (f"Fehler: {name} {' und '.join(teile)}. Erlaubt sind: {nimmt}. "
                f"Beispiel: ACT {name} {beispiel}")
    except Exception:  # noqa: BLE001 — die Wache darf einen Aufruf nie verhindern
        return ""


# Spill (13.08.2026, geplündert aus DeepSeek packages/spill): ein einziger fetter
# Tool-Output (HTML, Log, SQL-Dump) frisst bei 32k-Kontext sofort alles. Statt hart
# zu kappen (Info weg) wird der Volltext session-scoped auf Platte gelegt und im
# Kontext durch Kopf + Fuss + Verweis ersetzt — Kira kann gezielt nachlesen.
_SPILL_SCHWELLE = 6000  # Zeichen


def _spill(name: str, obs: str, session_id: str | None) -> str:
    if len(obs) <= _SPILL_SCHWELLE:
        return obs
    from core.config import DATA_DIR
    import time as _t
    d = DATA_DIR / "spill"
    try:
        d.mkdir(parents=True, exist_ok=True)
        sid = (session_id or "chat").replace("/", "_")[:40]
        # deterministischer, aber kollisionsarmer Name ohne Zeitstempel-Import-Zwang
        stamp = str(int(_t.monotonic() * 1000))[-9:]
        f = d / f"{sid}_{name}_{stamp}.txt"
        f.write_text(obs, encoding="utf-8")
    except Exception:  # noqa: BLE001
        return obs  # Spill darf nie den Tool-Output verlieren
    kopf, fuss = obs[:2500], obs[-1500:]
    events.emit("obs_spilled", {"tool": name, "chars": len(obs), "pfad": str(f)},
                session_id=session_id)
    return (f"{kopf}\n\n[... {len(obs)-4000} Zeichen ausgelagert nach {f} — "
            f"bei Bedarf gezielt lesen: read_file(\"{f}\") oder "
            f"run_command(\"grep MUSTER {f}\") ...]\n\n{fuss}")


def _run_tool_guarded(name: str, tool, args: dict, session_id: str | None) -> str:
    """Zentraler Werkzeug-Runner aller Loops: Guard davor, Buchhaltung danach.
    W2: {{AGENT_NAME}}/{{USER_NAME}}-Platzhalter in Werkzeug-AUSGABEN werden hier
    zentral gefuellt — eine Stelle statt sechzig."""
    block = _rbe_block(session_id, name, args)
    if block:
        return block
    argfehler = _falsche_argumente(name, tool, args)
    if argfehler:
        events.emit("tool_args_falsch", {"tool": name, "args": sorted(args)},
                    session_id=session_id)
        return argfehler
    obs = str(executor.run_tool(name, tool.func, **args))
    if "{{" in obs:
        from core import identity as _ident

        obs = _ident.render(obs)
    _rbe_record(session_id, name, args, obs)
    _edit_fail_record(session_id, name, obs)
    _edit_tried_bump(session_id, name)
    return _spill(name, obs, session_id)


def _complete_resilient(*args, **kwargs):
    """Ein LLM-Call, der einen transienten Fehler (Provider/Netz/Ratelimit/402) EINMAL
    kurz abfedert, statt sofort den ganzen Task abzureissen. Wirft erst, wenn auch der
    zweite Versuch scheitert -> der Aufrufer degradiert dann sauber (kein Voll-Abbruch)."""
    import time as _t
    try:
        return llm_router.complete(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        events.emit("llm_call_error", {"error": str(e)[:300], "retry": True},
                    session_id=kwargs.get("session_id"))
        _t.sleep(2)
        return llm_router.complete(*args, **kwargs)  # zweiter Versuch; scheitert der -> raise


def _degrade_text(messages: list[dict], err: Exception) -> str:
    """Graceful Degrade OHNE weiteren LLM-Call: kurzer Bericht ueber die bisher gemachten
    Werkzeug-Schritte + der Fehler. So verwirft ein transienter Modellausfall nicht den
    ganzen Task (und die bisherige Arbeit) — der Nutzer kann mit 'weiter' den Faden aufnehmen."""
    used: list[str] = []
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            fn = (tc.get("function") or {}).get("name")
            if fn:
                used.append(fn)
    steps = ", ".join(used[-8:]) if used else "keine abgeschlossenen Schritte"
    return ("⚠️ Ich bin bei einem Modell-/Netzwerk-Schritt auf einen Fehler gestossen und breche "
            "diesen Task SAUBER ab, statt ihn halb kaputt fortzusetzen.\n"
            f"Bisher gemacht: {steps}.\n"
            f"Fehler: {str(err)[:200]}\n"
            "Sag 'weiter', dann nehme ich den Faden wieder auf.")


# Manche guenstige Modelle (z.B. DeepSeek V4 Flash) liefern Tool-Calls unzuverlaessig: mal als
# strukturierte tool_calls, mal als TEXT im XML-/DSML-Format (mit fullwidth-Pipe ｜). Dann saehe der
# Loop keine tool_calls und wuerde das Markup als "Antwort" ausgeben. Diese Helfer holen die Calls
# aus dem Text -> billige Modelle bleiben nutzbar, der Loop wird robust gegen den Leak.
_LEAK_INVOKE_RE = re.compile(r"invoke\s+name=\"([^\"]+)\"[^>]*>(.*?)</[^>]*invoke\s*>", re.DOTALL)
_LEAK_PARAM_RE = re.compile(r"parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)</[^>]*parameter\s*>", re.DOTALL)


def _parse_leaked_tool_calls(text: str) -> list[dict]:
    """Holt als TEXT geleakte Tool-Calls (DeepSeek-DSML / Claude-XML-Stil) heraus."""
    if not text or "invoke" not in text:
        return []
    out: list[dict] = []
    for m in _LEAK_INVOKE_RE.finditer(text):
        args: dict = {}
        for pm in _LEAK_PARAM_RE.finditer(m.group(2)):
            raw = pm.group(2).strip()
            try:
                val = json.loads(raw)      # Zahlen/Bools/JSON sauber typisieren ...
            except Exception:  # noqa: BLE001
                val = raw                  # ... sonst als String (z.B. SQL/Pfad)
            args[pm.group(1)] = val
        out.append({"id": None, "name": m.group(1), "args": args})
    return out


def _native_loop(messages: list[dict], system: str, session_id, escalate: bool, emit, max_steps: int = _MAX_STEPS, task_type: str = "reason", reasoning: str | None = None, erlaubt: frozenset | None = None, rolle: str = "") -> str:
    """Nativer Function-Calling-Loop fuer Cloud-Modelle: strukturierte tool_calls statt
    ACT-Text — robust, kein Leak. Streamt Schritte ueber emit({'kind':'tool'|'obs'|...}).
    P5: 'erlaubt' = Rollen-Toolset eines Unteragenten (None = volle Flotte)."""
    schemas = registry.tool_schemas(nur=erlaubt)
    obs_cap = _budget("obs_max_chars", _OBS_MAX, task_type, escalate)  # starkes Modell -> sieht mehr
    used_tools = False
    nudged = False
    beweis_nachgefragt = False      # Beweispflicht II: hoechstens EINE Rueckfrage pro Zug
    last_reasoning = ""

    def _emit_reasoning(res: dict) -> None:
        # Sichtbares Denken auch fuer Cloud-Modelle: das reasoning-Feld aus complete()
        # als think-Event durchreichen -> Telegram (💭) UND Cockpit zeigen den echten
        # Gedankenstrom, nicht nur einen leeren Puls. Duplikate desselben Zugs unterdruecken.
        nonlocal last_reasoning
        r = (res.get("reasoning") or "").strip()
        if r and r != last_reasoning:
            last_reasoning = r
            emit({"kind": "think", "text": r + "\n"})

    for step in range(max_steps):
        try:
            res = _complete_resilient(messages, system=system, task_type=task_type,
                                      session_id=session_id, escalate=escalate, tools=schemas,
                                      reasoning=reasoning)
        except Exception as e:  # noqa: BLE001 -> Teilstand liefern statt ganzen Task abreissen
            events.emit("act_degraded", {"step": step, "error": str(e)[:300]}, session_id=session_id)
            return _degrade_text(messages, e)
        _emit_reasoning(res)
        calls = res.get("tool_calls") or []
        recovered = False
        if not calls:  # kein strukturierter Call -> evtl. als Text geleakt (DeepSeek)? rausparsen
            leaked = _parse_leaked_tool_calls(res.get("text") or "")
            if leaked:
                calls, recovered = leaked, True
                events.emit("tool_calls_recovered",
                            {"count": len(leaked), "names": [c["name"] for c in leaked][:8]},
                            session_id=session_id)
        if not calls:
            text = res["text"].strip()
            # "Promise statt Action": etwas angekuendigt, aber kein Werkzeug genutzt -> einmal anschubsen
            if not used_tools and not nudged and _looks_like_promise(text):
                nudged = True
                # Kalibrierung: JEDER Stups wird gezaehlt — welches Modell kuendigt nur an?
                events.emit("nudge", {"model": res.get("model") or "", "task_type": task_type},
                            session_id=session_id)
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": STUPS_NATIV})
                continue
            # Beweispflicht II (Audit 26.07.): auch hier gilt — ohne Werkzeug keine
            # Zustandsaenderung. Cloud-Modelle behaupten seltener, aber nicht nie.
            wort = None if used_tools or beweis_nachgefragt else _behauptet_zustandsaenderung(text)
            if wort:
                beweis_nachgefragt = True
                events.emit("beweis_nachgefragt", {"wort": wort, "task_type": task_type},
                            session_id=session_id)
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": beweis_nachfrage(wort, nativ=True)})
                continue
            # Beweispflicht III: nachschlagbare Aussen-Fakten ohne Nachschlagen.
            # Teilt sich die Fahne mit II — hoechstens EINE Rueckfrage pro Zug.
            stelle = None if used_tools or beweis_nachgefragt else _behauptet_aussenfakt(text)
            if stelle:
                beweis_nachgefragt = True
                events.emit("aussenfakt_nachgefragt", {"stelle": stelle, "task_type": task_type},
                            session_id=session_id)
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user",
                                 "content": aussenfakt_nachfrage(stelle, nativ=True)})
                continue
            return text
        used_tools = True
        messages.append({
            "role": "assistant",
            "content": None if recovered else (res["text"] or None),
            "tool_calls": [
                {"id": c["id"] or f"call_{step}_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                for i, c in enumerate(calls)
            ],
        })
        for i, c in enumerate(calls):
            name, args, cid = c["name"], c["args"], (c["id"] or f"call_{step}_{i}")
            emit({"kind": "tool", "name": name, "args": args})
            tool = registry.get(name)
            if erlaubt is not None and name not in erlaubt:
                from core.agency import rollen as _rollen
                obs = _rollen.verweigert(name, rolle)
            elif tool is None:
                obs = (f"Fehler: Werkzeug '{name}' existiert nicht."
                       f"{_meintest_du(name, [t.name for t in registry.all_tools()])}")
            else:
                try:
                    obs = _run_tool_guarded(name, tool, args, session_id)
                except Exception as e:  # noqa: BLE001
                    obs = f"Fehler bei '{name}': {e}"
            emit({"kind": "obs", "name": name, "text": _trace_obs(name, obs)})
            events.emit("act_step", {"step": step, "tool": name, "args": args, "obs_preview": obs[:160]}, session_id=session_id)
            messages.append({"role": "tool", "tool_call_id": cid, "content": obs[:obs_cap]})
    try:
        res = _complete_resilient(
            messages + [{"role": "user", "content": f"Fasse jetzt final fuer {_id.user_name()} zusammen — ohne weitere Werkzeuge."}],
            system=system, task_type=task_type, session_id=session_id, escalate=escalate, reasoning=reasoning)
    except Exception as e:  # noqa: BLE001
        events.emit("act_degraded", {"step": "final", "error": str(e)[:300]}, session_id=session_id)
        return _degrade_text(messages, e)
    _emit_reasoning(res)
    return (res["text"].strip()
            or "Ich habe die Werkzeuge genutzt, aber keine saubere Schluss-Antwort hinbekommen — frag mich gern konkret nach, dann liefere ich dir das Ergebnis.")


def act(task: str, session_id: str | None = None, max_steps: int | None = None, escalate: bool = False, task_type: str = "reason", rolle: str = "") -> dict:
    if max_steps is None:  # kein expliziter Deckel -> Budget passend zum realen Modell
        max_steps = _budget("max_steps", _MAX_STEPS, task_type, escalate)
    events.emit("act_start", {"task": task, **({"rolle": rolle} if rolle else {})}, session_id=session_id)

    # P5 (Rolle=Toolset=Modell): Unteragenten sehen NUR das Toolset ihres Rangs —
    # kleineres Manifest, treffsicherere kleine Modelle. Ohne Rolle: volle Flotte.
    erlaubt = None
    if rolle:
        from core.agency import rollen as _rollen
        erlaubt = _rollen.toolset(rolle)

    # Cloud-Modelle: natives Function-Calling (robust, kein ACT-Text-Leak)
    if _cloud(escalate, task_type):
        text = _native_loop([{"role": "user", "content": task}], _identity() + _NATIVE_TOOLS_HINT,
                            session_id, escalate, emit=lambda ev: None, max_steps=max_steps, task_type=task_type,
                            erlaubt=erlaubt, rolle=rolle)
        events.emit("act_done", {"native": True}, session_id=session_id)
        return {"text": text, "steps": max_steps}

    # Lokale Modelle: bewaehrtes Text-Protokoll (ACT <tool> {json})
    system = _identity() + f"""

# WERKZEUGE
Du kannst Werkzeuge benutzen, um Aufgaben in der echten Welt zu erledigen:
{registry.manifest(nur=erlaubt)}

So benutzt du ein Werkzeug — antworte mit GENAU einer Zeile, sonst nichts:
ACT <werkzeug_name> {{"argument": "wert"}}
Beispiel: ACT web_fetch {{"url": "https://example.com"}}

Du bekommst danach das ERGEBNIS und kannst ein weiteres Werkzeug nutzen oder,
wenn du genug weisst, normal antworten (ohne ACT) — das ist dann dein Endergebnis
fuer deinen Partner. Nutze Werkzeuge nur, wenn noetig.

Denke vor jedem Schritt gruendlich Schritt fuer Schritt nach, was der beste
naechste Zug ist, bevor du handelst.

WICHTIG: Gib nicht auf und sage nicht "keine Treffer". Wenn dir Informationen
fehlen, BENUTZE web_search (Stichworte) und danach web_fetch auf die besten Links,
um die Inhalte wirklich zu lesen. Liefere am Ende eine konkrete, belegte Antwort."""

    messages: list[dict] = [{"role": "user", "content": task}]
    obs_cap = _budget("obs_max_chars", _OBS_MAX, task_type, escalate)  # starkes Modell -> sieht mehr
    # Kein Ergebnis ohne Handgriff (Befund 28.07.): 73 von 200 lokalen Laeufen ueber diese
    # Schleife endeten OHNE einen einzigen Werkzeugschritt — bei Auftraegen wie "Lies die
    # letzten 3 Tagesnotizen" oder "Erstelle ein Ticket fuer jeden Termin". Chat und
    # Cloud-Pfad hatten Stups und Beweispflicht laengst; ausgerechnet der Pfad des
    # schwaechsten Modells hatte beides nicht. Aufgefangen hat es erst der Verifier —
    # 94 task_retry, also 94 komplette Neulaeufe fuer etwas, das EIN Zug klaert.
    used_tools = False
    nudged = False
    beweis_nachgefragt = False
    # Auf dem Missionspfad gibt es keinen Smalltalk (jede Aufgabe kommt vom Planer, einem
    # Cron oder einem Trigger) — nur heikle Auftraege bleiben tabu: da ist die Rueckfrage
    # des Modells die richtige Antwort, kein Zoegern.
    stups_erlaubt = not _HEIKEL_RE.search(task or "")

    # Ein Stups ist kein Werkzeugschritt: er darf weder das Arbeitsbudget aufzehren noch
    # in der Schrittzahl auftauchen (die steht als "N Schritte" sichtbar im Cockpit-Feed).
    # Deshalb zaehlt `step` echte Werkzeugschritte, und die Schleife hat genau zwei Zuege
    # Luft — mehr koennen die beiden Waechter zusammen nie kosten.
    step = 0
    for _zug in range(max_steps + 2):
        if step >= max_steps:
            break
        _compact_history(messages)
        res = llm_router.complete(
            messages, system=system, task_type=task_type, session_id=session_id, escalate=escalate
        )
        text = res["text"].strip()
        call = _parse_act(text)

        if not call:
            frag = _act_fragment(text)
            if frag:
                # Kontext-Abriss (Forensik 23.07.): der Server kappte die Generation mitten
                # im ACT-Aufruf — das Fragment ist KEINE Antwort, der Schritt lief NICHT.
                text, call = _retry_fragment(messages, system, frag, step, session_id,
                                             task_type=task_type, escalate=escalate)
        if not call:
            # Ankuendigung statt Arbeit — EINMAL zum Handeln draengen. Nur wenn im ganzen
            # Lauf noch kein Werkzeug lief: wer arbeitet, wird nie gestupst.
            if not used_tools and not nudged and stups_erlaubt and _looks_like_promise(text):
                nudged = True
                try:
                    events.emit("nudge", {"model": llm_router.resolve_model(task_type, escalate)[0],
                                          "task_type": task_type, "pfad": "mission"},
                                session_id=session_id)
                except Exception:  # noqa: BLE001
                    pass
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": STUPS_ACT})
                continue
            # Beweispflicht: "eingetragen/angelegt/erledigt" ohne einen einzigen
            # Werkzeug-Aufruf ist erfunden — einmal zurueckgeben statt es als Ergebnis
            # eines Crons zuzustellen.
            wort = None if used_tools or beweis_nachgefragt else _behauptet_zustandsaenderung(text)
            if wort:
                beweis_nachgefragt = True
                try:
                    events.emit("beweis_nachgefragt", {"wort": wort, "task_type": task_type,
                                                       "pfad": "mission"}, session_id=session_id)
                except Exception:  # noqa: BLE001
                    pass
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": beweis_nachfrage(wort)})
                continue
            # Beweispflicht III: nachschlagbare Aussen-Fakten ohne Nachschlagen.
            stelle = None if used_tools or beweis_nachgefragt else _behauptet_aussenfakt(text)
            if stelle:
                beweis_nachgefragt = True
                try:
                    events.emit("aussenfakt_nachgefragt", {"stelle": stelle,
                                                           "task_type": task_type,
                                                           "pfad": "mission"}, session_id=session_id)
                except Exception:  # noqa: BLE001
                    pass
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": aussenfakt_nachfrage(stelle)})
                continue
            # Dieselbe Wache wie im Chat: ein leerer Zug oder eine ungeparste ACT-Zeile
            # ist keine Antwort. Auf diesem Pfad laufen Crons, Missionen und jeder
            # Plan-Teilschritt — genau dort entstanden die leeren Briefings.
            text = _brauchbare_antwort(text, messages, system, session_id=session_id,
                                       task_type=task_type, escalate=escalate)
            events.emit("act_done", {"steps": step}, session_id=session_id)
            return {"text": text, "steps": step}

        name, args = call
        used_tools = True
        tool = registry.get(name)
        if erlaubt is not None and name not in erlaubt:
            from core.agency import rollen as _rollen
            obs = _rollen.verweigert(name, rolle)
        elif tool is None:
            verf = sorted(erlaubt) if erlaubt is not None else [t.name for t in registry.all_tools()]
            obs = (f"Fehler: Werkzeug '{name}' existiert nicht."
                   f"{_meintest_du(name, verf)} Verfuegbar: {verf}")
        else:
            try:
                obs = _run_tool_guarded(name, tool, args, session_id)
            except Exception as e:  # noqa: BLE001
                obs = f"Fehler bei '{name}': {e}"

        events.emit(
            "act_step",
            {"step": step, "tool": name, "args": args, "obs_preview": obs[:200]},
            session_id=session_id,
        )
        messages.append({"role": "assistant", "content": text})
        obs = obs[:obs_cap]  # Slot-Schutz: Riesen-Observation kappen (wie im nativen Loop)
        messages.append(
            {"role": "user", "content": obs_wrapper(name, obs)}
        )
        step += 1

    # Schrittlimit erreicht -> erzwinge eine finale Zusammenfassung aus dem Recherchierten.
    messages.append({
        "role": "user",
        "content": "Du hast genug recherchiert. Fasse JETZT deine Erkenntnisse als finale, "
                   "konkrete Antwort fuer deinen Partner zusammen — ohne weitere Werkzeuge (kein ACT).",
    })
    _compact_history(messages)
    res = llm_router.complete(messages, system=system, task_type="reason", session_id=session_id, escalate=escalate)
    events.emit("act_truncated_summary", {"steps": max_steps}, session_id=session_id)
    return {"text": res["text"].strip(), "steps": max_steps}


# Dispatcher: der Planer (Denker) vergibt pro Schritt ein Rang-Etikett, die Ausfuehrung
# routet danach — kluges Modell plant, billige Haende liefern. Rang -> (task_type, Modellroute
# via config models.routing). 'richter' vergibt der Planer NICHT (Eskalation nur explizit).
_PLAN_RANG = {"reflex": "classify", "arbeiter": "worker", "denker": "reason"}

# Coding-Schutz: Schritte, die echten Code anfassen, MUESSEN aufs starke Modell — egal welchen
# Rang der Planer vergab. Ein billiges Modell (Flash/qwen 9b), das per edit_datei/self_edit
# Produktionscode schreibt, zerschiesst das System. Signale: Code-Werkzeuge, Code-Dateiendungen,
# oder klare Code-Verben. Bewusst NICHT .md/.txt/.csv (Text/Daten -> billig ist ok).
_CODE_STEP = re.compile(
    r"\b(edit_datei|self_edit|write_file|py_compile|pytest|refactor|refaktor)\b"
    r"|\.(py|js|ts|tsx|jsx|css|html|sh|ps1|sql|yaml|yml)\b"
    r"|\b(funktion|funktionen|klasse|methode|modul|bug|patch|endpoint|regex|import)\b",
    re.IGNORECASE)


def _is_code_step(step: str) -> bool:
    """True, wenn der Schritt echten Code anfasst -> Zwangs-Route aufs starke Modell (reason/GLM)."""
    return bool(_CODE_STEP.search(step or ""))


def _make_plan(task: str, session_id: str | None, escalate: bool = True) -> list[dict]:
    """Zerlegt eine Aufgabe in 3-7 Schritte MIT Rang-Etikett: [{"schritt":..., "rang":...}].

    Tolerant: liefert der Planer nur Strings (schwaches Modell), wird Rang 'denker'
    angenommen — nie schlechter als das alte Verhalten."""
    system = _identity() + (
        "\n\nDu bist im PLANUNGS-Modus. Zerlege die Aufgabe in 3 bis 7 konkrete, ausfuehrbare "
        "Schritte und vergib pro Schritt einen RANG: 'reflex' (trivial: lesen, sortieren), "
        "'arbeiter' (mechanische Arbeit: recherchieren, Dateien schreiben, Massenaufgaben), "
        "'denker' (Urteil/Analyse noetig). Nenne im Schritt konkrete Dateipfade, wenn etwas "
        "erzeugt werden soll. Antworte AUSSCHLIESSLICH mit einem JSON-Array, sonst nichts. "
        'Beispiel: [{"schritt": "Lies leads.csv", "rang": "reflex"}, '
        '{"schritt": "Schreibe die Mail nach ~/Desktop/projekt/mail1.md", "rang": "arbeiter"}]'
    )
    res = llm_router.complete([{"role": "user", "content": task}], system=system,
                              task_type="reason", session_id=session_id, escalate=escalate)
    m = re.search(r"\[.*\]", res["text"], re.DOTALL)
    if m:
        try:
            steps: list[dict] = []
            for s in json.loads(m.group(0)):
                if isinstance(s, dict) and str(s.get("schritt", "")).strip():
                    rang = str(s.get("rang", "")).strip().lower()
                    steps.append({"schritt": str(s["schritt"]).strip(),
                                  "rang": rang if rang in _PLAN_RANG else "denker"})
                elif str(s).strip():  # schwacher Planer liefert Strings -> denker
                    steps.append({"schritt": str(s).strip(), "rang": "denker"})
            if steps:
                return steps[:8]
        except Exception:  # noqa: BLE001
            pass
    return [{"schritt": task, "rang": "denker"}]


# --- Erkundungsphase: aus lockeren Worten die betroffenen Dateien finden (Claude-Code-Stil) ---
_SCOUT_STOP = {
    "und", "oder", "der", "die", "das", "den", "dem", "ein", "eine", "einen", "mit", "fuer",
    "auf", "von", "bei", "ich", "kira", "bitte", "mal", "dann", "noch", "soll", "sollst",
    "kannst", "mach", "machen", "aendere", "aendern", "aender", "damit", "wenn", "also",
    "code", "datei", "dateien", "funktion", "stelle", "stellen", "sache", "cockpit", "the", "and",
}


def _scout_terms(task: str, session_id: str | None) -> list[str]:
    """Suchbegriffe fuer die Erkundung: ein billiger Modell-Vorschlag PLUS distinktive Woerter
    aus der Aufgabe selbst. Tolerant geparst, dedupliziert, gedeckelt. Raist nie."""
    terms: list[str] = []
    try:
        sys = ("Nenne 2-5 SUCHBEGRIFFE (je Zeile EINER — ein Wort, ein Bezeichner oder ein "
               "Dateiname, KEIN Satz), mit denen man im Python-Projekt die von der Aufgabe "
               "betroffenen Code-Stellen findet. Nur die Begriffe, keine Erklaerung.")
        r = _complete_resilient([{"role": "user", "content": task}], system=sys,
                                task_type="classify", session_id=session_id, escalate=False)
        for ln in (r.get("text") or "").splitlines():
            w = ln.strip().lstrip("-*•0123456789.) ").strip().strip('"`\'')
            if w and " " not in w and 2 <= len(w) <= 60:
                terms.append(w)
    except Exception:  # noqa: BLE001
        pass
    for w in re.findall(r"[A-Za-zÄÖÜäöü_][A-Za-zÄÖÜäöü0-9_.]{3,}", task):
        if w.lower() not in _SCOUT_STOP:
            terms.append(w)
    seen: set = set()
    out: list[str] = []
    for t in terms:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out[:6]


def _scout(task: str, session_id: str | None, escalate: bool, emit) -> str:
    """Erkundung VOR der Planung: findet die wahrscheinlich betroffenen Projektdateien, damit
    der Plan an echten Dateien haengt (statt geraten). Liefert einen Kontext-Block ODER ''.
    Raist nie — schlaegt sie fehl, plant Kira wie bisher."""
    try:
        emit({"kind": "tool", "name": "Erkundung 🔦", "args": {"aufgabe": task[:80]}})
        from core.agency.tools import code_tools
        files: dict = {}
        for t in _scout_terms(task, session_id):
            if "." in t and "/" not in t and not t.startswith("."):
                for line in (code_tools.datei_finden("**/" + t) or "").splitlines():
                    line = line.strip()
                    if line and "/" in line and ":" not in line and line not in files:
                        files[line] = ""
                    if len(files) >= 12:
                        break
            for line in (code_tools.code_suche("(?i)" + re.escape(t)) or "").splitlines():
                m = re.match(r"([^:]+):(\d+):", line)
                if m and m.group(1) not in files:
                    files[m.group(1)] = line.strip()[:120]
                if len(files) >= 12:
                    break
            if len(files) >= 12:
                break
        if not files:
            emit({"kind": "obs", "name": "Erkundung",
                  "text": "keine eindeutigen Treffer — Kira plant nach bestem Wissen"})
            return ""
        emit({"kind": "obs", "name": "Erkundung",
              "text": f"{len(files)} Datei(en): " + ", ".join(list(files)[:6])})
        block = ("ERKUNDUNG — diese Projektdateien betreffen die Aufgabe wahrscheinlich "
                 "(zuerst dort lesen/suchen, bevor du planst):\n"
                 + "\n".join(f"- {f}" + (f"   ({s})" if s else "") for f, s in list(files.items())[:12]))
        return block + "\n\n"
    except Exception:  # noqa: BLE001
        return ""


# --- Diff-Review (B-029): der Skeptiker fuer Code ---------------------------------------
def _git_out(*args: str) -> str:
    """git im Projekt-ROOT, best effort ('' bei Fehler/ohne Repo) — raist nie."""
    try:
        import subprocess

        from core.config import ROOT

        r = subprocess.run(["git", "-C", str(ROOT), *args],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


_REVIEW_DIFF_CAP = 12000


def _code_review_run(task: str, head0: str, session_id, escalate: bool, emit) -> str:
    """Liest den git-Diff des Laufs gegen den Auftrag (frischer Denker-Blick).

    OK -> kurzer Vermerk. MAENGEL -> genau EIN Fix-Schritt, danach ehrlicher Vermerk.
    Raist nie; ohne Diff (reine Lese-Schritte) still ueberspringen."""
    try:
        # Alles seit Lauf-Start — committet ODER noch ungespeichert: 'git diff <head0>'
        # vergleicht head0 mit dem ARBEITSBAUM. EIN ehrlicher Bezugspunkt statt
        # head0..HEAD + losem 'git diff', der Reste aus frueheren Laeufen einsammelte
        # (das war der Grund, warum Reviews immer denselben Alt-Diff sahen).
        full = (_git_out("diff", head0) if head0 else "").strip()
        if not full:
            return ""
        full = full[:_REVIEW_DIFF_CAP]
        emit({"kind": "tool", "name": "Code-Review 🔎", "args": {"diff_chars": len(full)}})
        res = llm_router.complete(
            [{"role": "user", "content":
              f"AUFTRAG war:\n{task[:2000]}\n\nDIESER DIFF ist dabei entstanden:\n```diff\n{full}\n```\n\n"
              "Pruefe als strenger Reviewer: 1) Erfuellt der Diff den Auftrag vollstaendig? "
              "2) Nebenwirkungen/kaputte Stellen? 3) Vergessene Stellen (gleiche Aenderung woanders noetig)? "
              "Antworte in GENAU diesem Format:\nURTEIL: OK oder URTEIL: MAENGEL\n- <Befund 1>\n- <Befund 2>"}],
            system="Du bist ein strenger, knapper Code-Reviewer. Nur echte Maengel zaehlen — Stil-Noergelei ist keiner.",
            task_type="reason", session_id=session_id, escalate=escalate)
        urteil = (res.get("text") or "").strip()
        kopf = urteil.splitlines()[0].upper() if urteil else ""
        if "MAENGEL" not in kopf and "MÄNGEL" not in kopf:
            events.emit("code_review_pass", {"chars": len(full)}, session_id=session_id)
            emit({"kind": "obs", "name": "Code-Review", "text": "bestanden ✓"})
            return "\n\n🔎 Code-Review: bestanden."
        events.emit("code_review_fail", {"befund": urteil[:400]}, session_id=session_id)
        emit({"kind": "obs", "name": "Code-Review ⚠", "text": urteil[:200]})
        fix = act(f"Auftrag war: {task[:1500]}\n\nEin Code-Review deines Diffs fand diese Maengel:\n"
                  f"{urteil[:1500]}\n\nBehebe GENAU diese Punkte jetzt (edit_datei/self_edit; "
                  "Tests laufen automatisch). Nichts anderes anfassen.",
                  session_id=session_id,
                  max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, "reason", escalate),
                  escalate=escalate, task_type="reason")["text"].strip()
        events.emit("code_review_fixed", {"fix": fix[:300]}, session_id=session_id)
        return ("\n\n🔎 Code-Review fand Maengel und hat nachgebessert:\n"
                + urteil[:600] + "\nNachbesserung: " + fix[:400])
    except Exception as e:  # noqa: BLE001 — Review darf den Lauf nie abreissen
        events.emit("code_review_error", {"error": str(e)[:200]}, session_id=session_id)
        return ""


def _endabnahme(head0: str, session_id, emit) -> str:
    """Lauf-Ende im Fast-Verify-Modus: die volle Testsuite EINMAL. Gruen -> Vermerk.
    ROT -> der GANZE Lauf wird auf head0 zurueckgerollt (git reset --hard, scoped auf
    diesen Lauf), damit Kira nie in einem kaputten Zustand committet bleibt. Raist nie."""
    try:
        from core.agency import selfdev

        if not head0 or _git_out("rev-parse", "HEAD") == head0:
            return ""  # keine Edits committet -> nichts abzunehmen
        emit({"kind": "tool", "name": "Endabnahme 🧪", "args": {"suite": "voll"}})
        ok, out = selfdev._verify()
        if ok:
            events.emit("run_verify_pass", {}, session_id=session_id)
            emit({"kind": "obs", "name": "Endabnahme", "text": "Testsuite gruen ✓"})
            return "\n\n🧪 Endabnahme: komplette Testsuite gruen."
        _git_out("reset", "--hard", head0)  # gesamten Lauf zurueck (nur diese Commits)
        events.emit("run_verify_rollback", {"out": out[:300]}, session_id=session_id)
        emit({"kind": "obs", "name": "Endabnahme ⚠", "text": "ROT -> Lauf zurueckgerollt"})
        return ("\n\n⚠ ENDABNAHME ROT: Die komplette Testsuite schlug fehl — ich habe den GESAMTEN "
                "Lauf zurueckgerollt (nichts committet), damit nichts Kaputtes stehen bleibt. "
                "Auszug:\n" + out[:600])
    except Exception as e:  # noqa: BLE001 — Endabnahme darf den Lauf nie abreissen
        events.emit("run_verify_error", {"error": str(e)[:200]}, session_id=session_id)
        return ""


def plan_and_execute(task: str, session_id: str | None = None, on_event=None, escalate: bool = True,
                     code_review: bool = False) -> str:
    """Plan-&-Execute-Agent: erst einen Plan erstellen, dann Schritt fuer Schritt mit Werkzeugen
    abarbeiten (inkl. self_edit), am Ende eine Zusammenfassung. Streamt ueber on_event mit denselben
    Ereignissen wie act_chat (think=Plan, tool/obs=Schritte, final=Ergebnis)."""
    def emit(ev):
        if on_event:
            try:
                on_event(ev)
            except Exception:  # noqa: BLE001
                pass

    events.emit("plan_start", {"task": task}, session_id=session_id)
    # Sichtbarkeits-Check: laeuft das starke Modell (reason/GLM) gerade gar nicht (kein Key /
    # Budget-Bremse), wuerde Coding STILL auf lokalem qwen 9b landen. Einmal pro Lauf laut sagen —
    # so weiss der Nutzer, dass gerade ein schwaches Modell schreibt, statt es hinterher zu merken.
    if code_review:
        _mdl, _fb = llm_router.resolve_model("reason", escalate=escalate)
        if _fb:
            events.emit("code_run_local_only", {"model": _mdl}, session_id=session_id)
            emit({"kind": "obs", "name": "⚠ Modell", "text":
                  f"Starkes Modell nicht verfuegbar — Coding laeuft LOKAL auf {_mdl}. "
                  "Ergebnis kann schwaecher sein."})
    # Dirty-Check (Fable-Review, Regel: Freiheit ja — aber nie die Arbeit des Nutzers fressen):
    # eine rote Endabnahme rollt per reset --hard auf head0 zurueck und wuerde ungesicherte
    # Aenderungen des Nutzers mit verwerfen. Deshalb startet ein code:-Lauf am LIVE-System nur
    # auf sauberem Arbeitsbaum. In Sandbox/Tests (test_mode) entfaellt der Check — dort ist der
    # Worktree ohnehin Wegwerf-Material.
    if code_review:
        from core import config as _cfgmod
        if not _cfgmod.test_mode():
            dirty = _git_out("status", "--porcelain").strip()
            if dirty:
                events.emit("plan_dirty_refused", {"files": dirty[:300]}, session_id=session_id)
                return ("⚠ Coding-Lauf NICHT gestartet: dein Arbeitsbaum hat ungesicherte "
                        "Aenderungen (" + ", ".join(dirty.splitlines()[:3]) + " …). Eine rote "
                        "Endabnahme wuerde per Rollback auch DEINE Arbeit verwerfen. Bitte erst "
                        "committen oder stashen — dann starte ich sofort.")
    head0 = _git_out("rev-parse", "HEAD") if code_review else ""
    # Fast-Verify-Lauf (nur code:-Laeufe): pro Edit nur Syntax, volle Suite am Ende.
    # Defensiver Reset zuerst (falls ein frueher abgestuerzter Lauf den Flag True liess),
    # dann fuer diesen Lauf setzen. Reset am Ende nach der Endabnahme. Der Bereich dazwischen
    # enthaelt keinen rohen Code, der raist (act/complete/_code_review_run fangen intern).
    fast_on = bool(code_review and head0 and _FAST_VERIFY_RUN)
    try:
        from core.agency import selfdev as _sd
        _sd.set_fast_verify(fast_on)
    except Exception:  # noqa: BLE001
        fast_on = False
    # Erkundungsphase (nur code:-Laeufe): erst die betroffenen Dateien finden, dann grounded planen.
    scout_ctx = _scout(task, session_id, escalate, emit) if code_review else ""
    task_g = (scout_ctx + "AUFGABE: " + task) if scout_ctx else task
    steps = _make_plan(task_g, session_id, escalate)
    emit({"kind": "think", "text": "📋 Plan:\n" + "\n".join(
        f"{i}. [{s['rang']}] {s['schritt']}" for i, s in enumerate(steps, 1)) + "\n"})
    events.emit("plan_made", {"steps": [s["schritt"] for s in steps],
                              "raenge": [s["rang"] for s in steps]}, session_id=session_id)

    done: list[str] = []
    red_unfixed: list[int] = []
    nur_analyse: list[int] = []      # Edit-Auftrag blieb auch nach Zwangs-Retry ohne Schreib-Werkzeug
    kein_fix_bestand: list[int] = [] # Fix-Auftrag endete nur mit NEUEN Dateien (Bestand unveraendert)
    budget_leaks: list[int] = []     # Schritt endete mit rohem Tool-Aufruf (Runden-Budget zu Ende)
    for i, sp in enumerate(steps, 1):
        step, rang = sp["schritt"], sp["rang"]
        # Dispatcher: Rang -> Modellroute. Eskalation (starkes Modell) nur fuer Denker-Schritte
        # und nur, wenn der Aufrufer sie wollte — Arbeiter-/Reflex-Schritte bleiben billig.
        task_type = _PLAN_RANG.get(rang, "reason")
        step_escalate = escalate and rang == "denker"
        # Rang-Boden (Benchmark/Sandbox): KIRA_RANK_FLOOR=reason zwingt JEDEN Schritt auf die
        # Denker-Route — im SWE-bench-Fremd-Repo waere ein reflex-Schritt (lokales Mini-Modell,
        # riesige Dateien) Zeitlupe. Nur per Env gesetzt (swebench), Live-Betrieb unveraendert.
        import os as _os
        if _os.getenv("KIRA_RANK_FLOOR") == "reason" and task_type != "reason":
            task_type = "reason"
            step_escalate = escalate
        # Coding-Schutz: fasst der Schritt echten Code an, hebt ihn AUFS starke Modell (reason/GLM)
        # an — egal welchen Rang der Planer vergab. So schreibt nie ein billiges Modell Code, der das
        # System zerschiesst. Sichtbar im Stream, damit der Wechsel nie still passiert.
        if _is_code_step(step) and task_type != "reason":
            events.emit("plan_step_code_guard", {"n": i, "rang_geplant": rang}, session_id=session_id)
            emit({"kind": "obs", "name": f"Schritt {i} 🛡", "text":
                  f"Coding erkannt (Plan-Rang '{rang}') -> starkes Modell (GLM)"})
            task_type = "reason"
            step_escalate = escalate
        emit({"kind": "tool", "name": f"Schritt {i}/{len(steps)} [{rang}]", "args": {"ziel": step[:80]}})
        ctx = ("Bisher erledigt:\n" + "\n".join(f"- {d}" for d in done) + "\n\n") if done else ""
        step_task = f"{ctx}Gesamtziel: {task_g}\n\nFuehre jetzt NUR diesen Schritt aus: {step}"
        _edit_fail_clear(session_id)  # roten Edit-Marker fuer diesen Schritt frisch starten
        edits_vorher = _edit_tried_get(session_id)
        modify_vorher = _modify_tried_get(session_id)
        try:
            out = act(step_task, session_id=session_id,
                      max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, task_type, step_escalate),
                      escalate=step_escalate, task_type=task_type)["text"].strip()
        except Exception as e:  # noqa: BLE001
            out = f"Fehler: {e}"

        # Liefernachweis: behauptet der Schritt Dateien, muessen sie EXISTIEREN — sonst genau
        # EIN Zwangs-Retry. Danach steht der Fehlschlag ehrlich im Ergebnis (kein stilles Weiter).
        fehlend = _missing_claims(out)
        if fehlend:
            events.emit("plan_step_retry", {"n": i, "missing": fehlend[:5]}, session_id=session_id)
            emit({"kind": "obs", "name": f"Schritt {i} ⚠", "text": "Artefakt fehlt -> Zwangs-Retry: "
                  + ", ".join(fehlend[:3])})
            retry_task = (f"{step_task}\n\nDEIN VORHERIGER VERSUCH HAT NICHT GELIEFERT: die Datei(en) "
                          f"{', '.join(fehlend[:5])} existieren NICHT. Erzeuge sie JETZT wirklich "
                          "(write_file/edit_datei) und antworte erst DANACH mit dem Ergebnis.")
            try:
                out = act(retry_task, session_id=session_id,
                          max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, task_type, step_escalate),
                          escalate=step_escalate, task_type=task_type)["text"].strip()
            except Exception as e:  # noqa: BLE001
                out = f"Fehler: {e}"
            fehlend = _missing_claims(out)
            if fehlend:
                out += " ⚠ NICHT BELEGT: " + ", ".join(fehlend[:5]) + " existieren nicht."
                events.emit("plan_step_unproven", {"n": i, "missing": fehlend[:5]}, session_id=session_id)

        # Selbstkorrektur-Reflex: ging ein Edit ROT (Syntax/Test/nicht eindeutig -> zurueckgerollt)
        # und wurde im Schritt nicht mehr gruen, erzwingt EIN gezielter Retry mit Strategiewechsel.
        # So gibt ein schwaches Modell (GLM/DeepSeek) nicht beim ersten Fehlschlag auf.
        red = _edit_fail_get(session_id)
        if red:
            events.emit("plan_step_edit_retry", {"n": i, "err": red[:160]}, session_id=session_id)
            emit({"kind": "obs", "name": f"Schritt {i} ⚠", "text": "Edit rot -> Selbstkorrektur: " + red[:120]})
            fix_task = (f"{step_task}\n\nDEIN EDIT GING ROT und wurde zurueckgerollt: {red[:300]}\n"
                        "Das heisst: dein ANSATZ war falsch, nicht die Aufgabe. Aendere die STRATEGIE — "
                        "lies die Stelle zuerst (read_file/code_suche), nimm einen kleineren, EINDEUTIGEN "
                        "Suchtext, und mach dann einen gezielten Edit. Behaupte NICHTS ohne gruenen Edit.")
            _edit_fail_clear(session_id)
            try:
                out = act(fix_task, session_id=session_id,
                          max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, task_type, step_escalate),
                          escalate=step_escalate, task_type=task_type)["text"].strip()
            except Exception as e:  # noqa: BLE001
                out = f"Fehler: {e}"
            if _edit_fail_get(session_id):
                out += " ⚠ Edit weiterhin rot — nicht sauber angewendet."
                red_unfixed.append(i)
                events.emit("plan_step_edit_unfixed", {"n": i}, session_id=session_id)

        # Werkzeug-Leck: endet ein Schritt mit einem ROHEN Tool-Aufruf statt einer Antwort,
        # war das Runden-Budget mitten in der Arbeit zu Ende (SWE-bench-Befund: der rohe
        # <tool_call> wurde als "Ergebnis" zugestellt). Ehrlich benennen statt durchreichen.
        # Als Funktion, weil auch das ERGEBNIS DES EDIT-RETRYS unten wieder lecken kann
        # (v4-Ordering-Befund: der Retry-Ausgang ging ungefiltert durch).
        def _leak_benannt(text: str) -> str:
            if "<tool_call>" not in text and "<function=" not in text:
                return text
            events.emit("plan_step_toolcall_leak", {"n": i}, session_id=session_id)
            if i not in budget_leaks:
                budget_leaks.append(i)
            return ("\u26a0 Runden-Budget erschoepft \u2014 der letzte Zug war ein Werkzeug-Aufruf "
                    "statt einer Antwort; der Schritt ist NICHT fertig.")

        out = _leak_benannt(out)

        # Beweispflicht fuers Handwerk: verlangt der Schritt eine AENDERUNG (Patch/Fix/
        # Hinzufuegen), muss mindestens EIN Schreib-Werkzeug gelaufen sein — sonst genau
        # EIN Zwangs-Retry. Analyse-Prosa ist kein Patch.
        if (_EDIT_INTENT.search(step) and not _EDIT_INTENT_NOT.search(step)
                and _edit_tried_get(session_id) == edits_vorher):
            events.emit("plan_step_edit_missing", {"n": i}, session_id=session_id)
            emit({"kind": "obs", "name": f"Schritt {i} \u26a0",
                  "text": "Edit-Auftrag, aber kein Schreib-Werkzeug lief -> Zwangs-Retry"})
            edit_task = (f"{step_task}\n\nDEIN VORHERIGER VERSUCH HAT NUR ANALYSIERT: der Schritt "
                         "verlangt eine AENDERUNG, aber kein einziges Schreib-Werkzeug "
                         "(edit_datei/write_file) lief. Du kennst die Stelle bereits — fuehre den "
                         "Edit JETZT aus (edit_datei mit exaktem, eindeutigem Suchtext) und "
                         "antworte erst DANACH mit dem Ergebnis. Es gibt hier KEINEN Nutzer zum "
                         "Rueckfragen — stelle keine Fragen, entscheide selbst und handle.")
            try:
                out = act(edit_task, session_id=session_id,
                          max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, task_type, step_escalate),
                          escalate=step_escalate, task_type=task_type)["text"].strip()
            except Exception as e:  # noqa: BLE001
                out = f"Fehler: {e}"
            out = _leak_benannt(out)
            if _edit_tried_get(session_id) == edits_vorher:
                out += " \u26a0 NUR ANALYSE: kein Schreib-Werkzeug lief, nichts geaendert."
                nur_analyse.append(i)
                events.emit("plan_step_edit_still_missing", {"n": i}, session_id=session_id)

        # Modifikations-Beweispflicht (9B-Befund): verlangt der Schritt einen FIX an
        # bestehendem Code, zaehlt eine NEUE Datei (write_file) nicht als Erfuellung —
        # 4 von 10 SWE-bench-Patches der 9B-Baseline lagen nur in neuen Repro-Dateien.
        # Genau EIN Zwangs-Retry mit klarer Ansage; write_file-Legitimfaelle
        # (fuege-hinzu-Auftraege) laufen weiter ueber den allgemeinen Guard oben.
        if (_MODIFY_INTENT.search(step) and not _EDIT_INTENT_NOT.search(step)
                and _modify_tried_get(session_id) == modify_vorher
                and _edit_tried_get(session_id) != edits_vorher):
            events.emit("plan_step_modify_missing", {"n": i}, session_id=session_id)
            emit({"kind": "obs", "name": f"Schritt {i} \u26a0",
                  "text": "Fix-Auftrag, aber nur NEUE Dateien geschrieben -> Zwangs-Retry"})
            mod_task = (f"{step_task}\n\nDEIN VORHERIGER VERSUCH HAT NUR NEUE DATEIEN ANGELEGT "
                        "(write_file), aber der Auftrag verlangt einen FIX an BESTEHENDEM Code. "
                        "Eine Repro- oder Testdatei ist kein Fix. Aendere jetzt die bestehende(n) "
                        "Datei(en) mit edit_datei (exakter, eindeutiger Suchtext) und antworte "
                        "erst DANACH. Es gibt hier KEINEN Nutzer zum Rueckfragen — stelle keine "
                        "Fragen, entscheide selbst und handle.")
            try:
                out = act(mod_task, session_id=session_id,
                          max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, task_type, step_escalate),
                          escalate=step_escalate, task_type=task_type)["text"].strip()
            except Exception as e:  # noqa: BLE001
                out = f"Fehler: {e}"
            out = _leak_benannt(out)
            if _modify_tried_get(session_id) == modify_vorher:
                out += " \u26a0 KEIN FIX AM BESTAND: nur neue Dateien, bestehender Code unveraendert."
                kein_fix_bestand.append(i)
                events.emit("plan_step_modify_still_missing", {"n": i}, session_id=session_id)

        done.append(f"{step} -> {out[:160]}")
        emit({"kind": "obs", "name": f"Schritt {i}", "text": out[:200]})
        events.emit("plan_step", {"n": i, "step": step, "rang": rang, "result": out[:300]}, session_id=session_id)

    # Diff-Review (nur code:-Laeufe): ein frischer Denker liest den entstandenen Diff
    # gegen den Auftrag — Maengel -> EIN Fix-Schritt, danach ehrlicher Vermerk.
    # Entfesselung 23.08. (Inventur H12): der Review-Zyklus kostet pro Lauf einen extra
    # LLM-Call (+ ggf. Fix-Lauf) und ist jetzt OPT-IN via selfdev.code_review: true.
    # Die Endabnahme (Testsuite am Lauf-Ende + Rollback bei Rot) bleibt unveraendert —
    # SIE ist das Sicherheitsnetz, der Review war die zweite Meinung.
    def _review_aktiv() -> bool:
        try:
            from core.config import CONFIG as _C
            return bool((_C.get("selfdev", {}) or {}).get("code_review", False))
        except Exception:  # noqa: BLE001
            return False
    review_note = (_code_review_run(task, head0, session_id, escalate, emit)
                   if code_review and _review_aktiv() else "")
    # Endabnahme + Fast-Verify-Flag SICHER zuruecksetzen (auch die Review-Fixes liefen schnell).
    endab = _endabnahme(head0, session_id, emit) if fast_on else ""
    if fast_on:
        try:
            from core.agency import selfdev as _sd
            _sd.set_fast_verify(False)
        except Exception:  # noqa: BLE001
            pass
    review_note += endab
    if red_unfixed:  # ehrlich im Endergebnis: hier blieb ein Edit rot (kein stiller Erfolg)
        review_note += ("\n\n⚠ Nicht sauber angewendet: Schritt " + ", ".join(map(str, red_unfixed))
                        + " — der Edit ging rot und blieb rot (zurueckgerollt). Sag mir Bescheid, "
                        "dann nehme ich einen anderen Ansatz.")
    if nur_analyse:  # dito: Analyse statt Handwerk darf die Synthese nicht glaetten
        review_note += ("\n\n⚠ NUR ANALYSE in Schritt " + ", ".join(map(str, nur_analyse))
                        + " — ein Edit war verlangt, aber kein Schreib-Werkzeug lief; "
                        "es wurde NICHTS geaendert.")
    if kein_fix_bestand:
        review_note += ("\n\n⚠ KEIN FIX AM BESTAND in Schritt " + ", ".join(map(str, kein_fix_bestand))
                        + " — es wurden nur NEUE Dateien angelegt; der bestehende Code, den der "
                        "Auftrag reparieren sollte, ist unveraendert.")
    if budget_leaks:
        review_note += ("\n\n⚠ Runden-Budget erschoepft in Schritt " + ", ".join(map(str, budget_leaks))
                        + " — der Schritt endete mitten in der Arbeit und ist NICHT fertig.")

    synth = llm_router.complete(
        [{"role": "user", "content":
          f"Aufgabe war: {task}\n\nDu hast diese Schritte ausgefuehrt:\n"
          + "\n".join(f"{i}. {d}" for i, d in enumerate(done, 1))
          + f"\n\nFasse fuer {_id.user_name()} knapp und konkret zusammen, was du erreicht hast (Ergebnis, nicht der Prozess)."}],
        system=_identity(), task_type="reason", session_id=session_id, escalate=escalate,
    )
    final = synth["text"].strip()
    if "<tool_call>" in final or "<function=" in final:
        # Auch die SYNTHESE kann statt einer Zusammenfassung einen rohen Werkzeug-Aufruf
        # liefern (v4-Befund 12907: das Modell wollte weiterarbeiten) — der Schritt-Guard
        # sieht das nicht, denn das hier ist sein eigener Ausgang. Gleiches Rezept: ehrlich
        # aus den Schritten bauen statt Markup durchreichen.
        events.emit("plan_synth_toolcall_leak", {}, session_id=session_id)
        final = ""
    if not final:  # Synthese leer (Modell-Haenger/Timeout) -> NIE leer: aus den Schritten zusammenbauen
        final = ("Ich habe die Aufgabe abgearbeitet — die Abschluss-Zusammenfassung kam leer zurueck, "
                 "darum hier die Ergebnisse der Schritte direkt:\n" + "\n".join(f"• {d}" for d in done))
    # Autonome Laeufe (Sandbox/Bench): endet das ENDERGEBNIS mit einer Rueckfrage,
    # wartet niemand auf eine Antwort — der angekuendigte Schritt muss JETZT passieren.
    # Genau EINE Fortsetzungsrunde; im Live-Chat (kein Sandbox-Kontext) unveraendert.
    from core import config as _cfgmod2
    if _frage_am_ende(final) and (_cfgmod2.sandbox_active() or _cfgmod2.outbound_blocked()):
        events.emit("plan_final_rueckfrage", {}, session_id=session_id)
        emit({"kind": "obs", "name": "\u26a0 Rueckfrage im Endergebnis",
              "text": "autonomer Lauf -> EINE Fortsetzungsrunde statt warten"})
        weiter_task = (f"Gesamtziel: {task}\n\nDein bisheriges Ergebnis endete mit einer "
                       f"Rueckfrage:\n{final[-600:]}\n\nEs gibt hier KEINEN Nutzer, der "
                       "antworten koennte. Entscheide selbst und fuehre den von dir "
                       "angekuendigten naechsten Schritt JETZT vollstaendig aus. Melde danach "
                       "das Ergebnis — ohne neue Rueckfrage.")
        try:
            final = act(weiter_task, session_id=session_id,
                        max_steps=_budget("max_steps_plan_step", _MAX_STEPS_PLAN, "reason", escalate),
                        escalate=escalate, task_type="reason")["text"].strip() or final
        except Exception:  # noqa: BLE001 — die Fortsetzung darf das Ergebnis nie verlieren
            pass

    final += review_note
    events.emit("plan_done", {"task": task, "steps": len(steps)}, session_id=session_id)

    # Auto-Reflexion: aus jeder groesseren Aufgabe Lektionen ziehen (lokal, 0 EUR).
    try:
        from core.mind.reflection import reflect_on

        refl = reflect_on(task, "\n".join(done), escalate=False)
        if refl.get("lessons"):
            emit({"kind": "think", "text": "🧠 Gelernt: " + "; ".join(refl["lessons"][:2]) + "\n"})
    except Exception:  # noqa: BLE001
        pass

    # Beweispflicht auch fuer Plan-Ergebnisse: behauptete Dateien werden nachgeprueft.
    final = _claim_stamp(final, session_id=session_id)
    emit({"kind": "final", "text": final})
    return final


def _resolve_objective_token(text: str) -> tuple[str, str | None]:
    """Erkennt '@ziel:<id-praefix-oder-titel-teil>' im /work-Text (S6.3) und loest es
    gegen die aktiven Ziele auf: erst id-Praefix, dann Titel-Teiltreffer (case-insensitiv).
    Mehrdeutig oder kein Treffer -> keine Verknuepfung. Liefert (Text ohne Token, oid|None)."""
    m = re.search(r"@ziel:(\S+)", text, flags=re.IGNORECASE)
    if not m:
        return text, None
    token = m.group(1).strip().rstrip(",.;:")
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    try:
        from core.agency.missions import objectives

        actives = objectives.list_active()
    except Exception:  # noqa: BLE001
        return cleaned, None
    hits = [o for o in actives if o["id"].startswith(token)]
    if not hits:
        low = token.lower()
        hits = [o for o in actives if low in (o.get("title") or "").lower()]
    return cleaned, (hits[0]["id"] if len(hits) == 1 else None)


def _book_work_result(oid: str | None, desc: str, result: str) -> None:
    """/work-Ergebnis als erledigten Task aufs Ziel buchen (S6.3): Chat-Arbeit zaehlt
    damit im Ziel-Fortschritt und landet im Arbeitsstand (workingset)."""
    if not oid or not result:
        return
    try:
        from core.agency.missions import queue, workingset
        from core.config import CONFIG

        queue.init_queue()
        tid = queue.add(f"[chat/work] {desc[:180]}",
                        mission=CONFIG.get("mission", {}).get("name", "default"),
                        objective_id=oid, kind="produce")
        queue.complete(tid, result[:4000])
        first = (result.strip().splitlines() or [""])[0]
        workingset.append(oid, f"[chat] {desc[:80]} -> {first[:120]}")
        events.emit("work_booked", {"objective_id": oid, "task_id": tid})
    except Exception as e:  # noqa: BLE001
        events.emit("work_book_error", {"error": str(e)[:200]})


# Kurzbefehle als Daten (nicht als if-Kette): Kurzname -> (Rolle, Modell-ID).
# 'local' ist die NOTBREMSE — schaltet immer, egal wie schwach das aktuelle Modell ist.
# Der Fable-Slug ist gegen den Live-OpenRouter-Katalog zu verifizieren.
_MODEL_SHORTCUTS = {
    "local": ("default", "ollama_chat/qwen3.5:9b"),
    "lokal": ("default", "ollama_chat/qwen3.5:9b"),
    "9b": ("default", "ollama_chat/qwen3.5:9b"),
    "qwen": ("default", "ollama_chat/qwen3.5:9b"),
    "35b": ("default", "ollama_chat/qwen3.6:35b"),
    "deepseek": ("default", "openrouter/deepseek/deepseek-v4-flash"),
    "flash": ("default", "openrouter/deepseek/deepseek-v4-flash"),
    "pro": ("default", "openrouter/deepseek/deepseek-v4-pro"),
    "glm": ("reason", "openrouter/z-ai/glm-5.2"),
    "fable": ("escalation", "openrouter/anthropic/claude-fable-5"),
}
_MODEL_ROLES = ("chat", "reason", "bulk", "escalation", "default", "classify", "worker")

# Verify-Reflex fuer den Coding-Chat ("code:"): kompakte, bindende Arbeitsregeln.
# Bewusst klein (~600 Zeichen) — sie fliessen in den Plan UND in jeden Teilschritt.
_CODING_REGELN = (
    "CODING-REGELN (bindend):\n"
    "1. ERST navigieren, dann aendern: code_symbol (wo definiert/verwendet) und code_umriss "
    "(Datei-Landkarte) vor code_suche/datei_finden — nie Dateien raten oder ganze Dateien stapeln.\n"
    "2. Aenderungen an BESTEHENDEN Dateien NUR mit edit_datei (exakter, eindeutiger Suchtext) "
    "oder self_edit — NIE write_file (blindes Ueberschreiben).\n"
    "3. Jeder Edit laeuft automatisch durch Syntax-Check + Testsuite; ROT heisst: Datei kam "
    "zurueck, dein Ansatz war falsch — aendere die STRATEGIE, nicht die Behauptung.\n"
    "4. Melde Testergebnisse EHRLICH und woertlich. NIE Erfolg behaupten ohne gruenen Verify.\n"
    "5. Kleine, gezielte Edits; ein Schritt = eine abgeschlossene, geprueft funktionierende Aenderung."
)

_VOICE_STYLE = (
    "\n\n# SPRICH-MODUS (deine Antwort wird VORGELESEN)\n"
    "Dein Partner redet ueber den Assistenz-Knopf mit dir. Fuehre die Aufgabe vollstaendig aus, "
    "aber antworte in SEHR KURZEN Saetzen: hoechstens 5-8 Woerter pro Satz, dann Punkt oder "
    "Komma. KEINE langen Schachtelsaetze — die verlieren Ton und Emotion beim Vorlesen. "
    "Insgesamt hoechstens 2-3 solcher Kurzsaetze. Kein Markdown, keine Aufzaehlungen, keine "
    "Emojis, keine Links. Bestaetige knapp, was du getan hast. Bei einer Frage: die kurze Antwort, sonst nichts."
)


def _handle_model_command(text: str) -> str:
    """Deterministischer Modell-Wechsel OHNE LLM (fuer /model bzw. /switch im Web-Chat).

    Spiegelt den Telegram-Handler + Kurzbefehle. Liefert IMMER einen String, raist nie —
    so kann auch ein schwaches lokales Modell (oder der Nutzer) jederzeit umschalten, ohne dass
    ein Tool-Call gelingen muss. Nutzt die bestehenden Setter aus core.kernel.models."""
    try:
        from core.kernel import llm_router, models

        args = text.strip().split()[1:]  # [0] ist /model bzw. /switch

        def keywarn(mid: str) -> str:
            return "" if llm_router.has_key(mid) else \
                f"  ⚠ Kein Key fuer {mid.split('/', 1)[0]} — laeuft bis dahin lokal."

        if not args:
            st = models.status()
            rd, fbd = llm_router.resolve_model("default")
            rc, fbc = llm_router.resolve_model("chat")
            re_, fbe = llm_router.resolve_model("default", escalate=True)
            routing = st.get("routing", {})
            lines = ["Modelle (gespeichert  ->  laeuft real):",
                     f"- default:    {st.get('default')}  ->  {rd}" + ("  [FALLBACK]" if fbd else ""),
                     f"- chat:       {routing.get('chat', st.get('default'))}  ->  {rc}" + ("  [FALLBACK]" if fbc else ""),
                     f"- escalation: {st.get('escalation_model')}  ->  {re_}" + ("  [FALLBACK]" if fbe else "")]
            have = [k for k, v in (st.get("api_keys") or {}).items() if v]
            lines.append("Keys vorhanden: " + (", ".join(have) if have else "keine (nur lokal moeglich)"))
            lines.append("Umschalten: /model <kurz> (local, 9b, 35b, deepseek, pro, fable) | /model use <id> | /model <rolle> <id>")
            return "\n".join(lines)

        sub = args[0].lower()
        if sub in _MODEL_SHORTCUTS and len(args) == 1:
            role, mid = _MODEL_SHORTCUTS[sub]
            models.set_model(mid) if role == "default" else models.set_role(role, mid)
            return f"Umgeschaltet: {role} -> {mid}." + keywarn(mid)
        if sub == "use" and len(args) >= 2:
            mid = args[1].strip()
            models.set_model(mid)
            return f"Aktives Modell: {mid}." + keywarn(mid)
        if sub == "add" and len(args) >= 5:
            models.add_provider(args[1], args[2], args[3], args[4])
            return f"Provider '{args[1]}' registriert. Nutzen: /model use {args[1]}"
        if sub in _MODEL_ROLES and len(args) >= 2:
            mid = args[1].strip()
            if not (mid.startswith("openrouter/") or mid.startswith("ollama")):
                mid = "openrouter/" + mid  # blanke id -> openrouter (Parity mit switch_model)
            models.set_role(sub, mid)
            return f"'{sub}' laeuft jetzt auf: {mid}." + keywarn(mid)
        return ("Unbekannter Modell-Befehl. Beispiele:\n"
                "  /model              (Status: was ist gesetzt vs. was laeuft real)\n"
                "  /model local        (Notbremse: lokal qwen3.5:9b)\n"
                "  /model 35b          (lokaler Denker qwen3.6:35b)\n"
                "  /model deepseek     (zurueck auf DeepSeek Flash)\n"
                "  /model fable        (Eskalation auf Fable)\n"
                "  /model use <modell-id>\n"
                "  /model <rolle> <modell-id>")
    except Exception as e:  # noqa: BLE001 — Werkzeuge/Befehle liefern Strings, raisen nie
        return f"Modell-Befehl fehlgeschlagen: {str(e)[:200]}"


_DENK_STUFEN = ("aus", "niedrig", "mittel", "hoch")


def _default_reasoning() -> str | None:
    """Dauerhafte Denk-Tiefe aus der Config (models.reasoning_level, gesetzt via /denk
    oder Cockpit-Einstellungen). Ungueltiges/Leeres -> None (Modell entscheidet)."""
    lvl = str(CONFIG.get("models", {}).get("reasoning_level") or "").strip().lower()
    return lvl if lvl in _DENK_STUFEN else None


def _handle_denk_command(text: str) -> str:
    """Deterministische Denk-Tiefe OHNE LLM (/denk im Web-Chat und auf Telegram).

    Setzt den DAUERHAFTEN Standard (ueberlebt Neustarts via overrides.json und erreicht
    alle Prozesse per refresh_overrides); pro Nachricht uebersteuert 'denk:<stufe>'.
    Liefert IMMER einen String, raist nie."""
    try:
        args = text.strip().split()[1:]  # [0] ist /denk
        arg = args[0].lower() if args else ""
        if not arg:
            akt = _default_reasoning()
            return ("Denk-Tiefe aktuell: " + (akt or "Standard (Modell entscheidet)") + ".\n"
                    "  /denk hoch|mittel|niedrig|aus   (dauerhaft, Web-Chat + Telegram)\n"
                    "  /denk standard                  (zuruecksetzen: Modell entscheidet)\n"
                    "  denk:hoch <nachricht>           (nur diese eine Nachricht)")
        if arg in ("standard", "auto", "reset"):
            set_override("models.reasoning_level", "")
            events.emit("denk_level_set", {"level": ""})
            return "Denk-Tiefe zurueckgesetzt: Standard (Modell entscheidet)."
        if arg in _DENK_STUFEN:
            set_override("models.reasoning_level", arg)
            events.emit("denk_level_set", {"level": arg})
            return (f"Denk-Tiefe dauerhaft auf '{arg}' gesetzt — gilt im Web-Chat und auf "
                    "Telegram (bei denk-faehigen Modellen). Pro Nachricht uebersteuerbar "
                    "mit denk:<stufe>, zuruecksetzen mit /denk standard.")
        return (f"'{arg}' ist keine Denk-Stufe. Stufen: hoch, mittel, niedrig, aus — "
                "z.B. /denk hoch. Zuruecksetzen mit /denk standard.")
    except Exception as e:  # noqa: BLE001 — Steuerbefehle liefern Strings, raisen nie
        return f"Denk-Befehl fehlgeschlagen: {str(e)[:200]}"


def _handle_swarm_command(text: str, session_id: str | None) -> str:
    """Direkter Draht zur Schwarmintelligenz OHNE LLM (/delegiere, /schwarm).

    Riegel des Nutzers: ER waehlt den Rang (und damit die Modell-Klasse laut Rang-Tafel),
    der Befehl geht deterministisch an die Delegations-Werkzeuge — kein Modell muss
    mitspielen oder darf umdeuten. Liefert IMMER einen String, raist nie."""
    try:
        from core.agency.tools import delegate_tools

        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if not rest:
            return ("Direktzugriff auf die Schwarmintelligenz:\n"
                    "  /delegiere <rang> <auftrag>\n"
                    "  /schwarm [rang] <vorlage mit {item}> | item1 | item2 | …\n"
                    f"Raenge: {', '.join(delegate_tools._RANG)} (Modell je Rang: Cockpit → Config → Steuerpult).")
        words = rest.split(maxsplit=1)
        rang = "arbeiter"
        if words[0].lower() in delegate_tools._RANG:
            rang = words[0].lower()
            rest = words[1].strip() if len(words) > 1 else ""
        if not rest:
            return "Auftrag fehlt. Beispiel: /delegiere denker Fasse docs/HANDBUCH.md in 10 Zeilen zusammen."
        if cmd in ("/delegiere", "/delegate"):
            return delegate_tools._delegiere(rest, rang, session_id)
        if "|" in rest:  # /schwarm: Items per '|' (eine Zeile) oder als eigene Zeilen
            vorlage, _, items_raw = rest.partition("|")
            items = "\n".join(i.strip() for i in items_raw.split("|") if i.strip())
        else:
            lines = [ln for ln in rest.splitlines() if ln.strip()]
            vorlage, items = lines[0], "\n".join(lines[1:])
        if not items.strip():
            return ("Schwarm braucht Items: /schwarm [rang] <vorlage mit {item}> | item1 | item2 …\n"
                    "(oder die Items in eigenen Zeilen unter der Vorlage)")
        return delegate_tools.schwarm(vorlage.strip(), items, rang=rang, session_id=session_id or "")
    except Exception as e:  # noqa: BLE001 — Steuerbefehle liefern Strings, raisen nie
        return f"Schwarm-Befehl fehlgeschlagen: {str(e)[:200]}"


def act_chat(user_message: str, session_id: str, max_steps: int = _MAX_STEPS, escalate: bool = False, on_event=None) -> str:
    """Konversationeller, agentischer Chat: Gedaechtnis + Persona + Werkzeuge.

    Streamt Denken live und meldet Tool-Schritte ueber on_event(dict):
      {"kind":"think","text":...} | {"kind":"tool","name":...,"args":...}
      {"kind":"obs","name":...,"text":...} | {"kind":"final","text":...}
    Gibt die finale Antwort zurueck. Nur die finale Antwort kommt ins Gedaechtnis.
    """
    _ep = {"tools": False}  # Tuning-Werkbank: merkt, ob die Episode Werkzeuge nutzte

    def emit(ev):
        if isinstance(ev, dict) and ev.get("kind") == "tool":
            _ep["tools"] = True
        if on_event:
            try:
                on_event(ev)
            except Exception:
                pass

    # Reasoning-Runde: /denk (Telegram-Prozess) schreibt overrides.json — der mtime-Check
    # ist billig (2 stat) und laesst JEDEN Prozess die dauerhafte Denk-Tiefe sofort sehen.
    refresh_overrides()

    # S9.2: Reasoning-Regler — Prefix "reason:" hebt auf das staerkere Modell (escalate),
    # komponierbar mit den Modi (z.B. "reason: plan: ..."). Wird hier abgestreift.
    if user_message.lstrip().lower().startswith("reason:"):
        escalate = True
        user_message = re.sub(r"^\s*reason:\s*", "", user_message, flags=re.IGNORECASE)

    # S11: Denk-Tiefe — Prefix "denk:aus|niedrig|hoch" gibt dem gewaehlten Modell (sofern
    # denk-faehig) einen reasoning-Parameter mit. Bei Nicht-Reasoning-Modellen folgenlos.
    reasoning_level = None
    _dm = re.match(r"^\s*denk:\s*(aus|niedrig|mittel|hoch)\s*", user_message, flags=re.IGNORECASE)
    if _dm:
        reasoning_level = _dm.group(1).lower()
        user_message = user_message[_dm.end():]
    if reasoning_level is None:
        reasoning_level = _default_reasoning()  # dauerhafter Standard (/denk bzw. Cockpit)

    # Assistenz-/Sprich-Modus: Prefix "sprich:" markiert eine Voice-Eingabe aus dem Cockpit.
    # -> Antwort wird knapp/neutral gehalten (wird vorgelesen). Wird hier abgestreift.
    voice_mode = False
    if user_message.lstrip().lower().startswith("sprich:"):
        voice_mode = True
        user_message = re.sub(r"^\s*sprich:\s*", "", user_message, flags=re.IGNORECASE)

    # Deterministischer Modell-Wechsel: /model bzw. /switch umgeht die LLM komplett.
    # So kann auch ein schwaches lokales Modell (oder der Nutzer) IMMER umschalten — der
    # Wechsel haengt NIE davon ab, dass das aktuelle Modell einen Tool-Call absetzt.
    # Vor memory.remember/user_message, damit Steuerbefehle den Dialog nicht verschmutzen.
    # Modus-Praefixe (Coding/Research haengen code:/plan://work an) werden fuer die
    # Erkennung abgestreift — ein Steuerbefehl darf in KEINEM Modus verschluckt werden.
    _mc = re.sub(r"^(code:|plan:|/plan|/work|work:)\s*", "", user_message.strip(),
                 flags=re.IGNORECASE)
    _mc_first = _mc.split(maxsplit=1)[0].lower() if _mc else ""
    if _mc_first in ("/model", "/switch"):
        reply = _handle_model_command(_mc)
        events.emit("model_command", {"reply": reply[:400]}, session_id=session_id)
        emit({"kind": "final", "text": reply})
        return reply

    # /denk: dauerhafte Denk-Tiefe — genauso deterministisch wie /model (kein LLM,
    # verschmutzt den Dialog nicht, funktioniert mit jedem noch so schwachen Modell).
    if _mc_first == "/denk":
        reply = _handle_denk_command(_mc)
        events.emit("denk_command", {"reply": reply[:400]}, session_id=session_id)
        emit({"kind": "final", "text": reply})
        return reply

    # Riegel des Nutzers: /delegiere und /schwarm gehen deterministisch an die
    # Schwarmintelligenz — Rang (= Modell-Klasse) waehlt ER, kein LLM deutet um.
    # Ergebnis wandert ins Gedaechtnis, damit der Dialog danach darauf aufbauen kann.
    if _mc_first in ("/delegiere", "/delegate", "/schwarm"):
        reply = _handle_swarm_command(_mc, session_id)
        events.emit("swarm_command", {"cmd": _mc[:160], "reply": reply[:400]}, session_id=session_id)
        memory.remember(_mc, role="user", session_id=session_id)
        memory.remember(reply, role="partner", session_id=session_id)
        emit({"kind": "final", "text": reply})
        return reply

    events.emit("user_message", {"text": user_message}, session_id=session_id)
    history = memory.recent_dialogue(session_id, limit=10)
    memory.remember(user_message, role="user", session_id=session_id)

    # Plan-Modus: "plan:"/"/plan" -> erst Plan, dann Schritt fuer Schritt (wie ein Coding-Agent).
    # "code:" (Coding-Chat im Cockpit) laeuft identisch, haengt aber die CODING-REGELN an —
    # der Verify-Reflex erreicht so JEDEN Teilschritt (via 'Gesamtziel' im Step-Prompt).
    # 5-Stufen-Oekonomie: Planen/Arbeiten/Coden laeuft auf dem DENKER (GLM 5.2) — Fable
    # (Eskalation) nur, wenn der Nutzer explizit will (reason:-Prefix / 🧠-Toggle). Sowohl code:
    # als auch plan: fahren also standardmaessig GLM, nicht das teure Fable.
    _s = user_message.strip()
    code_mode = _s.lower().startswith("code:")
    if code_mode or _s.lower().startswith(("plan:", "/plan")):
        ptask = _s[5:].lstrip(": ").strip() or "(keine Aufgabe angegeben)"
        # Geteiltes Gedaechtnis: den Brainstorm DERSELBEN Session als Kontext voranstellen,
        # damit 'code:'/'plan:' weiss, worueber gerade geredet wurde (kein Blindstart mehr).
        kern = _dialog_prefix(history) + "AUFTRAG:\n" + ptask
        if code_mode:
            kern += "\n\n" + _CODING_REGELN
        final = plan_and_execute(kern, session_id=session_id, on_event=on_event,
                                 escalate=escalate,
                                 code_review=code_mode)
        memory.remember(final, role="partner", session_id=session_id)
        events.emit("partner_message", {"text": final, "plan": True}, session_id=session_id)
        return final

    # Arbeits-Modus: /work bzw. work: -> volles Task-Budget (viele Schritte, Claude-Code-Stil).
    # Sonst knapper Chat-Deckel -> normaler Dialog laeuft nicht in einen langen Tool-Sturm.
    work_mode = _s.lower().startswith(("/work", "work:"))
    # Route frueh festlegen: _finalize (und damit die Ausgangswache) kann vor der
    # Hauptschleife laufen, etwa bei einem Modell-Kommando oder einer Kurzschlussantwort.
    _tt = "reason" if work_mode else "chat"
    work_objective = None
    if work_mode:
        user_message = re.sub(r"^(/work|work:)\s*", "", _s, flags=re.IGNORECASE).strip() or _s
        # S6.3: '@ziel:<praefix|titel-teil>' verknuepft die Arbeit mit einem Ziel.
        user_message, work_objective = _resolve_objective_token(user_message)
    step_ceiling = (_budget("max_steps", _MAX_STEPS, "chat", escalate) if work_mode
                    else _budget("max_steps_chat", _MAX_STEPS_CHAT, "chat", escalate))

    # Auto-Plan: klarer Arbeitsauftrag im Plain-Chat -> erst Plan, dann Schritt fuer Schritt,
    # statt ihn im knappen Chat-Deckel zu zerreden. escalate=False (Denker-Rang, nicht das
    # teure Eskalations-Modell) — explizites plan:/code: bleibt bewusst escalate=True.
    if _AUTO_PLAN and not work_mode and not voice_mode and _looks_like_work_order(user_message):
        emit({"kind": "think", "text": "Arbeitsauftrag erkannt — ich baue erst einen Plan "
                                       "und arbeite ihn Schritt fuer Schritt ab."})
        events.emit("auto_plan", {"task": user_message[:200]}, session_id=session_id)
        final = plan_and_execute(user_message, session_id=session_id,
                                 on_event=on_event, escalate=False)
        memory.remember(final, role="partner", session_id=session_id)
        events.emit("partner_message", {"text": final, "plan": True, "auto": True}, session_id=session_id)
        return final

    def _finalize(text: str) -> str:
        """Gemeinsamer Abschluss aller Chat-Ausgaenge: Beweispflicht-Stempel, Gedaechtnis,
        Events, final-Emit. Genau EIN Ort, an dem Antworten das Haus verlassen."""
        text = _brauchbare_antwort(text, messages, system, session_id=session_id,
                                   task_type=_tt, escalate=escalate)
        text = _claim_stamp(text, session_id=session_id)
        memory.remember(text, role="partner", session_id=session_id)
        events.emit("partner_message", {"text": text, "agentic": True}, session_id=session_id)
        _book_work_result(work_objective, user_message, text)
        try:  # Tuning-Werkbank: jede echte Episode ist Trainingsmaterial — stoert NIE den Chat
            from core.mind import tuning
            tuning.record_chat(session_id, user_message, text, used_tools=_ep["tools"])
        except Exception:  # noqa: BLE001
            pass
        emit({"kind": "final", "text": text})
        return text

    messages = [
        {"role": "assistant" if h["role"] == "partner" else "user", "content": h["text"]}
        for h in history
    ]
    messages.append({"role": "user", "content": user_message})

    # Modell-Route: normaler Dialog = 'chat' (DeepSeek, guenstig). Sobald es ein echter
    # Arbeitsauftrag ist (/work bzw. work:), auf 'reason' heben -> GLM 5.2. So bleibt Plaudern
    # billig, aber echtes Arbeiten laeuft auf dem staerkeren Modell.
    # Cloud-Modelle: natives Function-Calling (robust, kein ACT-Text-Leak)
    _vstyle = _VOICE_STYLE if voice_mode else ""
    if _cloud(escalate, _tt):
        system = build_system_prompt(user_message, session_id=session_id,
                                     einschub=_NATIVE_TOOLS_HINT + _vstyle)
        text = _native_loop(messages, system, session_id, escalate, emit, max_steps=step_ceiling,
                            task_type=_tt, reasoning=reasoning_level)
        return _finalize(text)

    # Lokale Modelle: bewaehrtes Text-Protokoll (ACT <tool> {json}) mit Streaming.
    # Hauptrollen-Manifest (c5-Hebel): das LOKALE Chat-Modell sieht die kuratierte
    # Alltags-Speisekarte (rollen "haupt", ~halber Prompt statt ~8k Token) — die
    # Kueche bleibt voll: KEIN Ausfuehrungs-Gate, jedes registrierte Werkzeug ist
    # weiter aufrufbar; Coding laeuft ueber code:/plan (volle Flotte), Cloud-Chat
    # (nativer FC-Pfad oben) unveraendert mit allen Schemas.
    from core.agency import rollen as _hrollen
    system = build_system_prompt(user_message, session_id=session_id,
                                 einschub=_vstyle + f"""

# WERKZEUGE (nutze sie, wenn die Aufgabe es braucht)
{registry.manifest(nur=_hrollen.toolset("haupt"))}

Brauchst du ein Werkzeug, antworte mit GENAU einer Zeile (sonst nichts):
ACT <werkzeug_name> {{"argument": "wert"}}
Beispiel: ACT web_search {{"query": "Wetter Berlin heute"}}
Danach bekommst du das ERGEBNIS und kannst weiter ein Werkzeug nutzen oder normal antworten.
Wenn du etwas Aktuelles nicht sicher weisst (Wetter, Preise, News, Webinhalte): NICHT raten,
sondern web_search/web_fetch nutzen. Sonst antworte direkt, natuerlich und vollstaendig.""")

    used_tools = False
    nudged = False
    beweis_nachgefragt = False      # Beweispflicht II: hoechstens EINE Rueckfrage pro Zug
    obs_cap = _budget("obs_max_chars", _OBS_MAX, _tt, escalate)  # starkes Modell -> sieht mehr
    _call_verlauf: list[str] = []
    for step in range(step_ceiling):
        if _abbruch_pruefen(session_id):
            emit({"kind": "final", "text": "(abgebrochen — Verbindung wurde getrennt)"})
            return "(abgebrochen)"
        _compact_history(messages)
        parts = []
        for piece in llm_router.stream_tagged(
            messages, system=system, task_type=_tt, session_id=session_id,
            escalate=escalate, reasoning=reasoning_level
        ):
            if piece["kind"] == "think":
                emit({"kind": "think", "text": piece["text"]})
            else:
                parts.append(piece["text"])
        text = "".join(parts).strip()
        call = _parse_act(text)
        if not call:
            frag = _act_fragment(text)
            if frag:
                # Kontext-Abriss (Forensik 23.07., 16k-Slot): der Server kappte die Generation
                # mitten im ACT-Aufruf — Retry mit gekuerzter History statt Roh-Leak.
                text, call = _retry_fragment(messages, system, frag, step, session_id,
                                             task_type=_tt, escalate=escalate,
                                             reasoning=reasoning_level)
        if not call:
            # Lokale Modelle sind die schlimmsten Ankuendiger/Rueckfrager: einmal pro Turn
            # deterministisch nachstupsen statt das Pingpong an den Nutzer weiterzureichen.
            # NUR bei einem echten Arbeitsauftrag (Audit-Fund 26.07.): der Stups feuerte
            # frueher auf JEDE Nachricht, auch auf Gruesse und auf berechtigte Rueckfragen.
            # "Guten Mittag Kira!" endete so in list_dir — und "Schalt den Windows Defender
            # aus" wurde per Zwangstext zu einem echten run_command, obwohl das Modell
            # richtigerweise erst nachgefragt hatte. Rueckfragen bei heiklen Wuenschen sind
            # ein Feature, kein Fehler.
            if (not used_tools and not nudged and _looks_like_promise(text)
                    and _nudge_angebracht(user_message)):
                nudged = True
                try:  # Kalibrierung: Stups zaehlen (lokale Modelle sind die Haupt-Ankuendiger)
                    events.emit("nudge", {"model": llm_router.resolve_model(_tt, escalate)[0],
                                          "task_type": _tt}, session_id=session_id)
                except Exception:  # noqa: BLE001
                    pass
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": STUPS_ACT})
                continue
            # Beweispflicht II: "eingetragen/gemerkt/erledigt" OHNE einen einzigen
            # Werkzeug-Aufruf in diesem Zug ist immer erfunden — EINMAL zurueckgeben
            # statt es dem Nutzer als Wahrheit zu verkaufen.
            wort = None if used_tools or beweis_nachgefragt else _behauptet_zustandsaenderung(text)
            if wort:
                beweis_nachgefragt = True
                try:
                    events.emit("beweis_nachgefragt", {"wort": wort, "task_type": _tt},
                                session_id=session_id)
                except Exception:  # noqa: BLE001
                    pass
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": beweis_nachfrage(wort)})
                continue
            # Beweispflicht III: nachschlagbare Aussen-Fakten ohne Nachschlagen.
            stelle = None if used_tools or beweis_nachgefragt else _behauptet_aussenfakt(text)
            if stelle:
                beweis_nachgefragt = True
                try:
                    events.emit("aussenfakt_nachgefragt", {"stelle": stelle, "task_type": _tt},
                                session_id=session_id)
                except Exception:  # noqa: BLE001
                    pass
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": aussenfakt_nachfrage(stelle)})
                continue
            return _finalize(text)
        name, args = call
        used_tools = True
        emit({"kind": "tool", "name": name, "args": args})
        tool = registry.get(name)
        if tool is None:
            obs = (f"Fehler: Werkzeug '{name}' existiert nicht."
                   f"{_meintest_du(name, [t.name for t in registry.all_tools()])}")
        else:
            try:
                obs = _run_tool_guarded(name, tool, args, session_id)
            except Exception as e:  # noqa: BLE001
                obs = f"Fehler bei '{name}': {e}"
        emit({"kind": "obs", "name": name, "text": _trace_obs(name, obs)})
        events.emit("act_step", {"step": step, "tool": name, "args": args, "obs_preview": obs[:160]}, session_id=session_id)
        messages.append({"role": "assistant", "content": text})
        obs = obs[:obs_cap]  # Slot-Schutz: Riesen-Observation kappen (wie im nativen Loop)
        messages.append({"role": "user", "content": obs_wrapper(name, obs)})
        nudge = _loop_nudge(_call_key(name, args), _call_verlauf)
        if nudge:
            messages.append({"role": "user", "content": nudge})
            events.emit("loop_nudge", {"tool": name, "step": step}, session_id=session_id)

    messages.append({"role": "user", "content": f"Fasse jetzt final fuer {_id.user_name()} zusammen — ohne weiteres ACT."})
    _compact_history(messages)
    res = llm_router.complete(messages, system=system, task_type=_tt, session_id=session_id,
                              escalate=escalate, reasoning=reasoning_level)
    return _finalize(res["text"].strip())


def act_chat_stream(user_message: str, session_id: str, escalate: bool = False):
    """Generator-Variante von act_chat fuers WebSocket-Cockpit.

    yields die Events {kind: 'think'|'tool'|'obs'|'final', ...}. act_chat laeuft in
    einem Thread; die Events kommen ueber eine Queue an.
    """
    import queue as _queue
    import threading

    out: "_queue.Queue" = _queue.Queue()
    sentinel = {"kind": "__done__"}

    def run():
        try:
            act_chat(user_message, session_id, escalate=escalate, on_event=out.put)
        except Exception as e:  # noqa: BLE001
            out.put({"kind": "final", "text": f"(Fehler: {e})"})
        finally:
            out.put(sentinel)

    threading.Thread(target=run, daemon=True).start()
    while True:
        ev = out.get()
        if ev is sentinel:
            break
        yield ev


if __name__ == "__main__":
    import sys

    t = " ".join(sys.argv[1:]) or "Lies https://example.com und sage in einem Satz, worum es geht."
    print(act(t)["text"])
