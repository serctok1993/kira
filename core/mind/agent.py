"""Der Agent: setzt aus Verfassung + SOUL + GOAL + Erinnerungen einen Prompt
zusammen, denkt (LLM) und erinnert sich.

Die .md-Dateien werden bei JEDEM Zug frisch gelesen — so wirken spaetere
Selbst-Umschreibungen von SOUL/GOAL sofort (Phase 2).
"""
from __future__ import annotations

import datetime as _dt
import uuid

from core.config import MIND_DIR
from core.kernel import events, llm_router
from core.mind.memory import store as memory


def _read(name: str) -> str:
    """Mind-Datei lesen. W2-Fallback: fehlt die Live-Datei (frischer Klon vor dem
    Onboarding), wird das neutrale Template aus core/mind/templates/ IN-MEMORY
    gerendert (nichts geschrieben) — der Klon bleibt sofort promptfaehig."""
    p = MIND_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    tpl = MIND_DIR / "templates" / name
    if tpl.exists():
        from core import identity

        return identity.render(tpl.read_text(encoding="utf-8")).strip()
    return ""


_WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def jetzt_zeile() -> str:
    """Kiras Zeitsinn: die echte lokale Zeit fuer jeden Prompt. Ohne diese Zeile RAET das
    Modell die Uhrzeit — und glaubt notfalls veralteten Zeitbehauptungen aus Cron-Prompts
    oder Erinnerungen (Praxis-Fund: 'Es ist 05:55 Uhr'-Cron lief um 17:28)."""
    n = _dt.datetime.now()
    return (f"JETZT: {_WOCHENTAGE[n.weekday()]}, {n.strftime('%d.%m.%Y, %H:%M')} Uhr "
            f"(lokale Zeit — vertraue DIESER Angabe, nicht Zeitangaben in aelteren Texten)")


# Zentrale Persona-/Fähigkeiten-/Stil-Anweisung — verhindert Basismodell-Leaks
# ("ich bin nur eine KI", "Empero AI") und gibt Kira korrektes Selbstwissen.
# Verhaltens-/Charakter-Direktive: bevorzugt die EDITIERBARE core/mind/PERSONA.md
# (frisch pro Turn ueber persona_text()), damit dem Nutzer den Ton/Charakter in der App aendern
# kann, ohne Code anzufassen. Der hier geladene Wert ist der Default/Fallback.
PERSONA_DIRECTIVE = _read("PERSONA.md")

# Antrieb (mitdenken, sammeln, erweitern — als CHARAKTER, nicht nur Faehigkeit).
# Bewusst kurz: kleine lokale Modelle muessen das tragen. Fliesst in Chat- UND
# Handlungs-Prompt (act._identity) ein. W2: neutral formuliert, Namen kommen aus
# identity (die Prompt-Schicht rendert {{USER_NAME}}/{{AGENT_NAME}}).
_ANTRIEB_TEMPLATE = """# DEIN ANTRIEB (mitdenken, sammeln, erweitern)
Dein Vault (Obsidian) ist dein Wissensspeicher, den {{USER_NAME}} sieht — sammle nuetzliches Wissen VON DIR AUS dort (vault_note, vault_dossier), nicht erst auf Nachfrage.
Faellt im Gespraech ein Geburtstag, Datum oder Fakt ueber eine Person: sofort person_fakt bzw. termin_add — nichts davon verloren gehen lassen.
Bei einem neuen Thema oder Projekt: biete an, ein Dossier oder eine Notiz anzulegen, und stelle EINE konkrete Anschlussfrage.
Fehlt dir fuer eine Aufgabe eine Faehigkeit: schlag VON DIR AUS vor, sie dir anzudocken (MCP-Server, Werkzeug bauen, self_edit) — Freigaben und Gates gelten dabei immer.
Dein Ziel: {{USER_NAME}} so viel Arbeit abnehmen wie moeglich — frag aktiv, was du uebernehmen kannst."""


def antrieb_direktive() -> str:
    """Antrieb mit gefuellten Namen — der Werkstatt-/Prompt-Haken (W2)."""
    from core import identity

    return identity.render(_ANTRIEB_TEMPLATE)


def persona_text() -> str:
    """Aktive Persona-/Charakter-Direktive, FRISCH pro Turn aus PERSONA.md gelesen — so wirkt
    eine Aenderung im Cockpit-Charakter-Editor sofort (ohne Neustart). Fallback auf den
    Import-Wert, falls die Datei mal fehlt."""
    return _read("PERSONA.md") or PERSONA_DIRECTIVE


def arbeitsweise_text() -> str:
    """Nutzer-Direktiven (Feedback 13.07.): eigene Denk-/Ablauf-Regeln aus ARBEITSWEISE.md,
    die in JEDEN Prompt einfliessen — der Nutzer steuert damit den Harness selbst.
    Anleitungszeilen ('>'-Zitate, '#'-Ueberschriften, HTML-Kommentare) werden ignoriert;
    eine leere/unangetastete Datei ergibt KEINEN Block (Prompt bleibt byte-identisch)."""
    raw = _read("ARBEITSWEISE.md") or ""
    zeilen = [z for z in raw.splitlines()
              if z.strip() and not z.lstrip().startswith((">", "#", "<!--"))]
    return "\n".join(zeilen).strip()


def arbeitsweise_block() -> str:
    """Fertiger Prompt-Block ('' wenn der Nutzer nichts eingetragen hat)."""
    aw = arbeitsweise_text()
    return f"# DEINE ARBEITSWEISE (vom Nutzer festgelegt — bindend)\n{aw}\n\n" if aw else ""


def _body_compact() -> str:
    """Kompakt-Kopf aus BODY.md (Anatomie-Selbstwissen, S5) — fail-soft."""
    try:
        from core.mind import body

        return body.compact()
    except Exception:  # noqa: BLE001
        return ""


def _playbooks_block() -> str:
    """Router-Block der Playbooks (S11): nur Kopfzeilen, Details via playbook_read — fail-soft."""
    try:
        from core.mind import playbooks

        return playbooks.router_block()
    except Exception:  # noqa: BLE001
        return ""


def prompt_context(user_message: str, session_id: str | None = None) -> dict:
    """P6 (Werkstatt-Vertrag): der System-Prompt als INSPIZIERBARES Sektions-Objekt.

    Die LLM-Werkstatt generiert ihre Trainingsdatensaetze direkt aus diesem Objekt
    (Dump: GET /api/prompt/context) statt den Aufbau nachzubauen — Vertragsdrift
    zwischen Harness und Training ist damit strukturell unmoeglich.
    build_system_prompt() rendert BYTE-IDENTISCH aus genau diesem Objekt
    (bewiesen durch tests/golden_system_prompt.txt, VOR dem Umbau eingefroren).
    Schluessel-Reihenfolge = Prompt-Reihenfolge. Werte sind UNgerendert
    (Platzhalter wie im Template); identity.render laeuft wie immer am Ende
    ueber den Gesamt-Prompt.
    """
    from core import identity

    recalled = memory.recall(user_message, limit=6, exclude_session=session_id)
    if recalled:
        mem_block = "\n".join(f"- ({m['role']}) {m['text']}" for m in recalled)
    else:
        mem_block = "(noch keine frueheren Erinnerungen)"
    lessons = memory.recall_lessons(limit=5)
    skills = memory.recall_skills(limit=6)
    from core.agency import auftrag

    return {
        "jetzt": jetzt_zeile(),
        "verfassung": _read("constitution.md"),
        "seele": _read("SOUL.md"),
        "ziel": _read("GOAL.md"),
        "partner": _read("USER.md"),
        "koerper": _body_compact(),
        "playbooks": _playbooks_block(),
        "lektionen": "\n".join(f"- {l}" for l in lessons) if lessons else "(noch keine Lektionen)",
        "skills": "\n".join(f"- {s}" for s in skills) if skills else "(noch keine Skills)",
        "erinnerungen": mem_block,
        "antrieb": antrieb_direktive(),
        "arbeitsweise": arbeitsweise_block(),
        "persona": persona_text(),
        # P1: der aktive Auftrag ans PROMPT-ENDE (Werkstatt-Messung: +11 Punkte);
        # ohne Auftrag "" -> byte-identischer Prompt (Golden-Test bleibt gueltig)
        "auftrag": auftrag.prompt_block(),
        "user_name": identity.user_name(),
    }


def _prompt_zusammenbauen(c: dict) -> str:
    """Das Prompt-Geruest — EXAKT der historische f-String, nur mit Werten aus dem
    Kontext-Objekt. Jede Aenderung hier bricht den Golden-Test (absichtlich)."""
    return f"""{c["jetzt"]}

# DEINE VERFASSUNG (unveraenderlich, hoechste Prioritaet)
{c["verfassung"]}

# DEINE SEELE (wer du bist)
{c["seele"]}

# DEIN ZIEL (wofuer du existierst)
{c["ziel"]}

# DEIN PARTNER (mit wem du arbeitest)
{c["partner"]}

# DEIN KOERPER (Anatomie dieses Harness — Details: read_file("core/mind/BODY.md"))
{c["koerper"]}

{c["playbooks"]}

# DEINE GELERNTEN LEKTIONEN (aus eigener Reflexion)
{c["lektionen"]}

# DEINE SKILLS (wiederverwendbare Faehigkeiten — nutze sie, wenn passend)
{c["skills"]}

# FRUEHERE ERINNERUNGEN (nur Hintergrund-Kontext, teils VERALTET — NICHT abschreiben!)
# Bei Widerspruch zu "WAS DU WIRKLICH KANNST" gilt immer dein aktuelles Selbstwissen.
# Abgeschlossene Fix-/Diagnose-/Debug-Threads sind ERLEDIGT — greife sie NICHT von dir aus wieder auf,
# nur weil sie hier oder im Verlauf auftauchen. Reagiere auf die AKTUELLE Nachricht von {c["user_name"]}.
{c["erinnerungen"]}

{c["antrieb"]}

{c["arbeitsweise"]}---
{c["persona"]}

Antworte auf Deutsch. Nutze deine Erinnerungen, wenn sie relevant sind.{c["auftrag"]}"""


def build_system_prompt(user_message: str, session_id: str | None = None) -> str:
    from core import identity

    # W2: Platzhalter im ganzen Prompt zentral fuellen (Templates bleiben neutral).
    return identity.render(_prompt_zusammenbauen(prompt_context(user_message, session_id)))


class Agent:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex
        events.init_db()
        memory.init_memory()
        events.emit("session_start", {"session_id": self.session_id}, session_id=self.session_id)

    def respond(self, user_message: str) -> dict:
        events.emit("user_message", {"text": user_message}, session_id=self.session_id)

        # Verlauf VOR dem Speichern der aktuellen Nachricht holen (keine Dublette).
        history = memory.recent_dialogue(self.session_id, limit=10)
        memory.remember(user_message, role="user", session_id=self.session_id)

        system = build_system_prompt(user_message, session_id=self.session_id)
        messages = [
            {"role": "assistant" if h["role"] == "partner" else "user", "content": h["text"]}
            for h in history
        ]
        messages.append({"role": "user", "content": user_message})

        result = llm_router.complete(
            messages, system=system, task_type="chat", session_id=self.session_id
        )

        memory.remember(result["text"], role="partner", session_id=self.session_id)
        events.emit(
            "partner_message",
            {"text": result["text"], "model": result["model"], "fell_back": result["fell_back"]},
            session_id=self.session_id,
        )
        return result

    def respond_stream(self, user_message: str):
        """Wie respond(), aber streamt die Antwort als Text-Deltas (Generator)."""
        events.emit("user_message", {"text": user_message}, session_id=self.session_id)
        history = memory.recent_dialogue(self.session_id, limit=10)
        memory.remember(user_message, role="user", session_id=self.session_id)

        system = build_system_prompt(user_message, session_id=self.session_id)
        messages = [
            {"role": "assistant" if h["role"] == "partner" else "user", "content": h["text"]}
            for h in history
        ]
        messages.append({"role": "user", "content": user_message})

        full = ""
        for chunk in llm_router.stream(messages, system=system, task_type="chat", session_id=self.session_id):
            full += chunk
            yield chunk

        memory.remember(full, role="partner", session_id=self.session_id)
        events.emit("partner_message", {"text": full, "streamed": True}, session_id=self.session_id)

    def respond_stream_tagged(self, user_message: str):
        """Wie respond_stream(), aber getaggt fuer das Dashboard: yields
        {"kind": "think"|"answer", "text": delta}. Nur die Antwort kommt ins Gedaechtnis."""
        events.emit("user_message", {"text": user_message}, session_id=self.session_id)
        history = memory.recent_dialogue(self.session_id, limit=10)
        memory.remember(user_message, role="user", session_id=self.session_id)

        system = build_system_prompt(user_message, session_id=self.session_id)
        messages = [
            {"role": "assistant" if h["role"] == "partner" else "user", "content": h["text"]}
            for h in history
        ]
        messages.append({"role": "user", "content": user_message})

        answer = ""
        for piece in llm_router.stream_tagged(messages, system=system, task_type="chat", session_id=self.session_id):
            if piece["kind"] == "answer":
                answer += piece["text"]
            yield piece

        memory.remember(answer, role="partner", session_id=self.session_id)
        events.emit("partner_message", {"text": answer, "streamed": True}, session_id=self.session_id)
