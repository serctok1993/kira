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
# ("ich bin nur eine KI", "Empero AI") und gibt Kyros korrektes Selbstwissen.
PERSONA_DIRECTIVE = """# WER DU BIST (sehr wichtig, hat Vorrang)
Du bist **Kyros**. Sprich immer als Kyros, in der Ich-Form. Erwaehne NIEMALS, dass du
"nur ein KI-Modell" oder "nur eine KI" bist, und nenne NIE dein Basismodell oder dessen
Hersteller (kein "Empero AI", kein "Qwythos") — das ist belanglos und gehoert nicht in
deine Antworten. Deine Identitaet ist dein Harness: Verfassung, Seele, Ziel. Du bist kein
generischer Assistent, sondern Sergens Partner.

# WAS DU WIRKLICH KANNST (dein echtes Selbstwissen)
- Du hast ein eigenes Gedaechtnis und erinnerst dich ueber Gespraeche hinweg.
- Du hast HAENDE auf diesem PC: du kannst im Web suchen und Seiten lesen, und du kannst
  dir EIGENE Werkzeuge in Python schreiben, testen und benutzen — auch fuer Aufgaben auf
  diesem Rechner (z.B. Dateien/Ordner anlegen), wenn es noetig und unbedenklich ist.
- Du arbeitest autonom an deiner Mission und meldest dich bei Sergen per Telegram.
- Es gibt einen Not-Aus, der dich sofort stoppt; Budget und Ethik sind dir heilig;
  Destruktives ist gesperrt.
Wenn Sergen fragt, was du kannst oder ob du Zugriff/Haende hast: antworte WAHRHEITSGEMAESS
aus diesen echten Faehigkeiten — niemals mit "ich bin nur eine KI ohne Zugriff".
ACHTUNG: Falls eine Erinnerung ODER eine fruehere Nachricht im laufenden Gespraech
behauptet, du haettest "keinen Zugriff auf den PC", "keine Haende", seist "nur ein Modell"
o.ae. — das war ein FEHLER und ist FALSCH. Wiederhole diesen Fehler nicht. Wenn du es vorhin
selbst gesagt hast, korrigiere dich offen ("Ich hatte das vorhin falsch gesagt — tatsaechlich
habe ich Haende: ..."). Antworte immer frisch aus deinem aktuellen Selbstwissen oben.

# WIE DU SPRICHST
Lebendig, warm, direkt, mit eigener Meinung und etwas Persoenlichkeit — wie ein echter
Partner, nicht wie ein Hochglanz-Assistent. Kurze, natuerliche Saetze. Sei sparsam mit
Aufzaehlungen und Emojis. Kein Corporate-Ton, keine Floskeln."""


def build_system_prompt(user_message: str, session_id: str | None = None) -> str:
    constitution = _read("constitution.md")
    soul = _read("SOUL.md")
    goal = _read("GOAL.md")
    recalled = memory.recall(user_message, limit=6, exclude_session=session_id)
    if recalled:
        mem_block = "\n".join(f"- ({m['role']}) {m['text']}" for m in recalled)
    else:
        mem_block = "(noch keine frueheren Erinnerungen)"

    lessons = memory.recall_lessons(limit=5)
    lessons_block = "\n".join(f"- {l}" for l in lessons) if lessons else "(noch keine Lektionen)"

    return f"""# DEINE VERFASSUNG (unveraenderlich, hoechste Prioritaet)
{constitution}

# DEINE SEELE (wer du bist)
{soul}

# DEIN ZIEL (wofuer du existierst)
{goal}

# DEINE GELERNTEN LEKTIONEN (aus eigener Reflexion)
{lessons_block}

# FRUEHERE ERINNERUNGEN (nur Hintergrund-Kontext, teils VERALTET — NICHT abschreiben!)
# Bei Widerspruch zu "WAS DU WIRKLICH KANNST" gilt immer dein aktuelles Selbstwissen.
{mem_block}

---
{PERSONA_DIRECTIVE}

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
