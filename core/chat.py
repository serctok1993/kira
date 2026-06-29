"""Testchat im Terminal — reden + Phase-2-Faehigkeiten.

Slash-Befehle machen Reflexion, Council und Selbst-Evolution direkt erlebbar.
"""
from __future__ import annotations

from core.agency.act import act as run_act
from core.agency.tools import synthesize
from core.config import CONFIG
from core.kernel import models
from core.kernel.scheduler import kill_switch_path
from core.mind import council, evolution, reflection
from core.mind.agent import Agent, _read
from core.mind.memory import store as memory

PARTNER = CONFIG["identity"].get("partner_name") or "Partner"

HELP = """Befehle:  (ein '!' am Befehlsende eskaliert diese eine Aufgabe in die Cloud)
  /help                        diese Hilfe
  /reflect                     der Agent reflektiert sein juengstes Handeln (zieht Lektionen)
  /council <frage>             Beraterrat (3 Stimmen + Judge) entscheidet eine Frage
  /soul | /goal                aktuelles SOUL.md / GOAL.md anzeigen
  /lessons                     gelernte Lektionen anzeigen
  /evolve <soul|goal> [text]   Vorschlag zur Selbst-Ueberarbeitung erzeugen (+ Verfassungs-Check)
  /apply  <soul|goal> [grund]  letzten Vorschlag uebernehmen (Backup wird angelegt)
  /act <aufgabe>               Aufgabe mit Werkzeugen erledigen (Web etc.)
  /build <beschreibung>        Kira baut sich ein NEUES Werkzeug (testet + registriert)
  /model                       Modelle anzeigen (aktiv, lokal, eigene Provider)
  /model use <id>              aktives LLM wechseln (z.B. llama3.1:8b -> ollama_chat/...)
  /model add <alias> <litellm-modell> <api_base> <API_KEY_ENV>   eigenen API-Provider anlegen
  /stop | /go                  Not-Aus setzen / aufheben
  exit                         beenden
Beispiele:  /council! Welche Nische zuerst?   (einmalig Cloud)
            /act Lies https://example.com und fasse zusammen
"""

_DOC = {"soul": "SOUL.md", "goal": "GOAL.md"}


def handle_command(line: str) -> None:
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    escalate = cmd.endswith("!")
    cmd = cmd.rstrip("!")

    if cmd == "/help":
        print(HELP)

    elif cmd == "/reflect":
        print("...reflektiere..." + ("  [Cloud]" if escalate else ""))
        r = reflection.reflect(escalate=escalate)
        print("\n" + r["text"])
        if r["lessons"]:
            print("\nGespeicherte Lektionen:")
            for lesson in r["lessons"]:
                print("  -", lesson)

    elif cmd == "/council":
        if not rest:
            print("Nutzung: /council <frage>")
            return
        print("...der Rat tagt..." + ("  [Cloud]" if escalate else ""))
        r = council.deliberate(rest, escalate=escalate)
        for name, text in r["positions"]:
            print(f"\n[{name}]\n{text}")
        print(f"\n=== URTEIL ===\n{r['verdict']}")

    elif cmd in ("/soul", "/goal"):
        print(_read("SOUL.md" if cmd == "/soul" else "GOAL.md"))

    elif cmd == "/lessons":
        memory.init_memory()
        ls = memory.recall_lessons(20)
        print("\n".join(f"- {l}" for l in ls) if ls else "(noch keine Lektionen)")

    elif cmd == "/evolve":
        args = rest.split(maxsplit=1)
        doc = _DOC.get(args[0].lower()) if args else None
        if not doc:
            print("Nutzung: /evolve <soul|goal> [aenderungswunsch]")
            return
        instr = args[1] if len(args) > 1 else None
        print("...erzeuge Vorschlag + pruefe gegen Verfassung..." + ("  [Cloud]" if escalate else ""))
        p = evolution.propose_update(doc, instr, escalate=escalate)
        v = p["verdict"]
        print(f"\nVerfassungs-Check: {'OK (compliant)' if v['compliant'] else 'BEDENKEN -- manuell pruefen'}")
        print(f"  {v['reason']}")
        print(f"\n--- Vorschlag fuer {doc} (Auszug) ---\n{p['new'][:800]}")
        print(f"\nMit  /apply {args[0].lower()} <grund>  uebernehmen.")

    elif cmd == "/apply":
        args = rest.split(maxsplit=1)
        doc = _DOC.get(args[0].lower()) if args else None
        if not doc:
            print("Nutzung: /apply <soul|goal> <grund>")
            return
        reason = args[1] if len(args) > 1 else "(kein Grund)"
        res = evolution.apply_update(doc, reason)
        print(f"Uebernommen. Backup: {res['backup']}")

    elif cmd == "/act":
        if not rest:
            print("Nutzung: /act <aufgabe>")
            return
        print("...Kira arbeitet (Werkzeuge)..." + ("  [Cloud]" if escalate else ""))
        r = run_act(rest, escalate=escalate)
        print(f"\n{r['text']}\n[Schritte: {r['steps']}]")

    elif cmd == "/build":
        if not rest:
            print("Nutzung: /build <was das Werkzeug koennen soll>")
            return
        print("...Kira baut ein Werkzeug (generieren -> testen -> registrieren)..." + ("  [Cloud]" if escalate else ""))
        r = synthesize.synthesize(rest, escalate=escalate)
        if r["ok"]:
            print(f"✅ Werkzeug '{r['name']}' gebaut, getestet und registriert.")
            print(f"   Test: {r.get('test_output','')[:200]}")
        else:
            print(f"❌ Nicht registriert ({r.get('reason')}).")
            if r.get("test_output"):
                print(f"   {r['test_output'][:300]}")

    elif cmd == "/model":
        args = rest.split()
        if not args:
            s = models.status()
            print(f"Aktiv (default): {s['default']}")
            print(f"Routing: {s['routing']}")
            print(f"Eskalation (Cloud): {s['escalation_model']}")
            print(f"Eigene Provider: {s['providers'] or '(keine)'}")
            print(f"Lokal in Ollama: {s['ollama_local'] or '(keine)'}")
        elif args[0] == "use" and len(args) >= 2:
            print(f"Aktives Modell -> {models.set_model(args[1])}")
        elif args[0] == "openrouter" and len(args) >= 2:
            print(f"Aktiv ueber OpenRouter -> {models.add_openrouter(args[1])}  (OPENROUTER_API_KEY noetig)")
        elif args[0] == "add" and len(args) >= 5:
            models.add_provider(args[1], args[2], args[3], args[4])
            print(f"Provider '{args[1]}' angelegt. Nutzen mit: /model use {args[1]}")
        else:
            print("Nutzung: /model | /model use <id> | /model openrouter <modell> | /model add <alias> <modell> <api_base> <ENV>")

    elif cmd == "/stop":
        kill_switch_path().write_text("stop", encoding="utf-8")
        print("🛑 Not-Aus aktiv (data/STOP). Mit /go aufheben.")

    elif cmd == "/go":
        p = kill_switch_path()
        if p.exists():
            p.unlink()
        print("✅ Not-Aus aufgehoben.")

    else:
        print("Unbekannter Befehl. /help fuer Hilfe.")


def main() -> None:
    print(f"Kira — Testchat mit {PARTNER}.  (/help fuer Befehle, 'exit' zum Beenden)\n")
    agent = Agent()
    print(f"[Session {agent.session_id[:8]}]")
    while True:
        try:
            user = input("\nDu: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBis bald, Partner.")
            break
        if not user:
            continue
        if user.lower() in {"exit", "quit", ":q"}:
            print("Bis bald, Partner.")
            break
        if user.startswith("/"):
            try:
                handle_command(user)
            except Exception as e:
                print(f"Fehler: {e}")
            continue
        print(f"\n{PARTNER}: ", end="", flush=True)
        for chunk in agent.respond_stream(user):
            print(chunk, end="", flush=True)
        print()


if __name__ == "__main__":
    main()
