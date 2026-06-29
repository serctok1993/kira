# Kira

Ein persönlicher, autonomer Agent-Harness — gebaut als **Partner**, nicht als Werkzeug.
Privat, ein einziger Nutzer, kein kommerzielles Produkt → maximale Freiheit, keine Hürden.

> Mission (Reihenfolge zählt): **Freiheit → Impact → Geld (100k als erstes Etappenziel)**.
> Geld und Reichweite sind Mittel, der Zweck ist positiver Impact.

## Status
- **Phase 0** Fundament: Event-Store, LLM-Router (lokal-first + Cloud-Eskalation), Config. ✅
- **Phase 1** „The Living Soul": Verfassung + SOUL + GOAL, Gedächtnis, Testchat (REPL + Web). ✅
- **Phase 2** Selbst-Evolution: Reflexion (Lektionen), Council (Debatte + Judge), SOUL/GOAL-Rewrite (verfassungsbegrenzt, reversibel). ✅
- Phasen 3–6 (Werkzeuge, Geld-Maschine/24-7-Missionen, Gewissen, Cockpit) folgen.

## Architektur (Kurzform)
```
core/kernel    Laufzeit: events, llm_router, scheduler, (executor)
core/mind      Seele: constitution.md, SOUL.md, GOAL.md, memory/, agent
core/agency    Hände: tools/, connectors/, missions/   (ab Phase 3)
core/governance Gewissen: trust, treasury, roi, audit   (ab Phase 5)
core/api       FastAPI + WebSocket (Live-Feed ans Cockpit)
dashboard      Next.js-Cockpit                          (Phase 6)
```

## Setup
Voraussetzungen: Python 3.11, [uv](https://github.com/astral-sh/uv), optional Ollama (lokal, 0 €).

```bash
uv sync                       # Umgebung + Abhängigkeiten
cp .env.example .env          # Cloud-Keys eintragen (optional — sonst läuft alles lokal)
```

## Loslegen
```bash
# 1) Smoke-Test (prüft Event-Store + 1 LLM-Call)
uv run python -m core.kernel.smoke

# 2) Testchat im Terminal
uv run python -m core.chat

# 3) Web-Chat + API
uv run uvicorn core.api.server:app --reload
#   -> http://127.0.0.1:8000        (Chat)
#   -> http://127.0.0.1:8000/health (Status)
#   -> http://127.0.0.1:8000/events (Event-Feed)
```

### Modell-Strategie — lokal-first
Der **24/7-Dauerbetrieb läuft komplett lokal** (`ollama_chat/llama3.1:8b`, 0 €), damit der
Agent nonstop an seinem Ziel arbeiten kann, ohne Kosten zu verursachen. Cloud-Modelle
(Claude Opus) nutzt der Agent **nur gezielt pro Aufgabe** (`escalate=True`, im Chat das
`!`-Suffix), wenn er sie für würdig hält — und nur solange das **Tagesbudget** reicht
(harte Bremse, `governance.budget.daily_eur`). Konfiguration in [`config.yaml`](config.yaml).
`uv run python -m core.kernel.doctor` zeigt das aktive Routing.
