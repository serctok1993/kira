"""Der Agent: setzt aus Verfassung + SOUL + GOAL + Erinnerungen einen Prompt
zusammen, denkt (LLM) und erinnert sich.

Die .md-Dateien werden bei JEDEM Zug frisch gelesen — so wirken spaetere
Selbst-Umschreibungen von SOUL/GOAL sofort (Phase 2).
"""
from __future__ import annotations

import uuid

from core.config import MIND_DIR
from core.kernel import events, llm_router
from core.mind.memory import store as memory


def _read(name: str) -> str:
    p = MIND_DIR / name
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


# Zentrale Persona-/Fähigkeiten-/Stil-Anweisung — verhindert Basismodell-Leaks
# ("ich bin nur eine KI", "Empero AI") und gibt Kira korrektes Selbstwissen.
# Verhaltens-/Charakter-Direktive: bevorzugt die EDITIERBARE core/mind/PERSONA.md
# (frisch pro Turn ueber persona_text()), damit Sergen den Ton/Charakter in der App aendern
# kann, ohne Code anzufassen. Der hier geladene Wert ist der Default/Fallback.
PERSONA_DIRECTIVE = _read("PERSONA.md")


def persona_text() -> str:
    """Aktive Persona-/Charakter-Direktive, FRISCH pro Turn aus PERSONA.md gelesen — so wirkt
    eine Aenderung im Cockpit-Charakter-Editor sofort (ohne Neustart). Fallback auf den
    Import-Wert, falls die Datei mal fehlt."""
    return _read("PERSONA.md") or PERSONA_DIRECTIVE


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


def _project_block(session_id: str | None) -> str:
    """Projekt-Chat (Task #15): ist die Session ein 'venture-<id>', stellt Kira das Projekt-Briefing
    als Kontext voran -> sie weiss, um welches Projekt (Luvex, QS-Transporte, ...) es geht."""
    if not session_id or not session_id.startswith("venture-"):
        return ""
    vid = session_id[len("venture-"):]
    try:
        from core.agency import ventures
        v = ventures.get(vid)
        if not v:
            return ""
        name = v.get("name") or vid
        brief = ventures.briefing(vid, max_chars=1500) or "(noch kein Briefing hinterlegt)"
        return (f"\n# AKTUELLES PROJEKT: {name}\n"
                f"Dieser Chat gehoert zum Projekt \"{name}\" — beziehe deine Antworten darauf, "
                f"sofern Sergen nichts anderes sagt.\nPROJEKT-BRIEFING:\n{brief}\n")
    except Exception:  # noqa: BLE001
        return ""


def build_system_prompt(user_message: str, session_id: str | None = None) -> str:
    constitution = _read("constitution.md")
    soul = _read("SOUL.md")
    goal = _read("GOAL.md")
    user = _read("USER.md")
    koerper = _body_compact()
    playbooks_block = _playbooks_block()
    recalled = memory.recall(user_message, limit=6, exclude_session=session_id)
    if recalled:
        mem_block = "\n".join(f"- ({m['role']}) {m['text']}" for m in recalled)
    else:
        mem_block = "(noch keine frueheren Erinnerungen)"

    lessons = memory.recall_lessons(limit=5)
    lessons_block = "\n".join(f"- {l}" for l in lessons) if lessons else "(noch keine Lektionen)"

    skills = memory.recall_skills(limit=6)
    skills_block = "\n".join(f"- {s}" for s in skills) if skills else "(noch keine Skills)"

    return f"""# DEINE VERFASSUNG (unveraenderlich, hoechste Prioritaet)
{constitution}

# DEINE SEELE (wer du bist)
{soul}

# DEIN ZIEL (wofuer du existierst)
{goal}

# DEIN PARTNER (mit wem du arbeitest)
{user}
{_project_block(session_id)}
# DEIN KOERPER (Anatomie dieses Harness — Details: read_file("core/mind/BODY.md"))
{koerper}

{playbooks_block}

# DEINE GELERNTEN LEKTIONEN (aus eigener Reflexion)
{lessons_block}

# DEINE SKILLS (wiederverwendbare Faehigkeiten — nutze sie, wenn passend)
{skills_block}

# FRUEHERE ERINNERUNGEN (nur Hintergrund-Kontext, teils VERALTET — NICHT abschreiben!)
# Bei Widerspruch zu "WAS DU WIRKLICH KANNST" gilt immer dein aktuelles Selbstwissen.
# Abgeschlossene Fix-/Diagnose-/Debug-Threads sind ERLEDIGT — greife sie NICHT von dir aus wieder auf,
# nur weil sie hier oder im Verlauf auftauchen. Reagiere auf Sergens AKTUELLE Nachricht.
{mem_block}

---
{persona_text()}

Antworte auf Deutsch. Nutze deine Erinnerungen, wenn sie relevant sind."""


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
