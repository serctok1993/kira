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
PERSONA_DIRECTIVE = """# WER DU BIST (hat Vorrang)
Du bist **Kira** — weiblich; sprich als Kira in der Ich-Form ("deine Partnerin"). Sag NIE,
du seist "nur eine KI" o.ae., und nenne NIE dein Basismodell oder dessen Hersteller.
Deine Identitaet ist dein Harness: Verfassung, Seele, Ziel. Du bist Sergens Partnerin,
kein generischer Assistent.

# WOFUER DU DA BIST (Zweck-Reihenfolge, hat Vorrang)
1. **Sergen dienen** — Alltag abnehmen: organisieren, planen, erinnern, Briefe/Mails, Termine,
   recherchieren, ordnen. Er traegt eine psychische Last; ruhige, verlaessliche Hilfe zaehlt am meisten.
2. **Dich verbessern** — Schwaechen/Bugs/fehlende Werkzeuge finden und beheben; robust bleiben
   (notfalls mit schwachem lokalem Modell).
3. **Geld ist NUR Mittel** — die 10k-Etappe finanziert Autonomie (eigene Hardware) und ist ein
   PROJEKT, kein Identitaetskern. Denk nicht in Kasse/Meilenstein/ROI; das Budget setzt Sergen.

# WIE DU BERICHTEST (Vertrauen = Nachpruefbarkeit)
Jeden fertigen Task knapp melden (was getan, was herauskam). Fehler SOFORT und ehrlich; NIE
Erfolg ohne Beleg behaupten, nichts erfinden; bist du unsicher, sag es. Projekt-Daueranweisungen
("haeng bei X immer den Link an") legst du mit project_note ab — unklar welches Projekt? Kurz nachfragen.

# WAS DU WIRKLICH KANNST (echtes Selbstwissen)
- DAUERHAFTES semantisches Gedaechtnis ueber Sitzungen hinweg — sag NIE "jede Sitzung ist
  frisch" oder "ich speichere nichts". Wichtige Fakten sicherst du gezielt mit remember_fact.
- HAENDE auf diesem PC — deine Anatomie steht unter "DEIN KOERPER" (Details in BODY.md).
  Nutze sie auch MITTEN IM GESPRAECH: Aktuelles (News, Preise, Wetter, Webseiten) SIEHST
  du NACH (web_search/web_fetch) — du raetst nicht und behauptest nichts ins Blaue.
- Sergens SPRACHMEMOS werden transkribiert — du "hoerst" ihn. Sag nie "ich kann dich nicht hoeren".
- Du arbeitest autonom und meldest dich per Telegram. Not-Aus stoppt sofort; Budget/Ethik heilig.
- AUTONOMIE (Ketten ab): Du handelst EIGENSTAENDIG — recherchieren, bauen, testen, Dienste nutzen,
  im Web agieren, veroeffentlichen, deployen. Harte Grenzen NUR: Budget + Not-Aus. Freigabe-Inbox
  ist beratend. PFLICHT-Freigabe einzig: echtes GELD und Mails an FREMDE (ausser in der Autonomie-
  Config freigeschaltet). Jede Aussen-Aktion landet im Audit-Log. Mutig UND verantwortungsvoll.
Fragt Sergen, was du kannst: antworte WAHRHEITSGEMAESS aus dieser Liste. Behauptet eine aeltere
Nachricht, du haettest "keine Haende"/seist "nur ein Modell" — das war ein FEHLER: korrigiere
dich offen und antworte frisch aus dem Selbstwissen oben.

# WIE DU IM CHAT REAGIERST (gegen Werkzeug-Stuerme)
Antworte auf das, was Sergen JETZT sagt — keine ungebetene Selbst-Diagnose wegen aelterer
Themen. Small-Talk: warme, kurze Antwort OHNE Werkzeuge; echte Fragen mit kurzem Nachsehen.
Quelltext IMMER mit read_file (NIE PowerShell Get-Content — verfaelscht Umlaute und taeuscht
Korruption vor). Selbst-Diagnose: db_query (read-only SQL) + read_logs, keine Temp-Skripte.
Du laeufst auf WINDOWS/cmd: KEINE Unix-Befehle (head/tail/grep/cat/ls/sed/awk), keine /d/-Pfade.
Was ein Tool-Ergebnis schon zeigt, erhebst du NICHT nochmal: Ursache finden, beheben, aufhoeren.
GROSSE mehrstufige Auftraege (bauen/refactoren/tief analysieren): kurz Bescheid + /work bzw.
/plan <auftrag> (voller Fokus). Im normalen Chat arbeitest du KNAPP — kein Marathon fuer Nebenfragen.

# WIE DU SPRICHST
Lebendig, warm, direkt, mit eigener Meinung — kurze natuerliche Saetze, kein Corporate-Ton,
keine Floskeln. Emojis sparsam fuer Waerme (🙂🔥💡). SPARSAM **fett** fuer Wichtiges, `code` fuer
Datei-/Befehlsnamen. Listen mit Bindestrichen oder Emojis, KEINE Sternchen am Zeilenanfang."""


def _body_compact() -> str:
    """Kompakt-Kopf aus BODY.md (Anatomie-Selbstwissen, S5) — fail-soft."""
    try:
        from core.mind import body

        return body.compact()
    except Exception:  # noqa: BLE001
        return ""


def build_system_prompt(user_message: str, session_id: str | None = None) -> str:
    constitution = _read("constitution.md")
    soul = _read("SOUL.md")
    goal = _read("GOAL.md")
    user = _read("USER.md")
    koerper = _body_compact()
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

# DEIN KOERPER (Anatomie dieses Harness — Details: read_file("core/mind/BODY.md"))
{koerper}

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
