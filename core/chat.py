"""Testchat im Terminal — reden + Phase-2-Faehigkeiten.

Slash-Befehle machen Reflexion, Council und Selbst-Evolution direkt erlebbar.
"""
from __future__ import annotations

from core.config import CONFIG
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
  exit                         beenden
Beispiele:  /council! Welche Nische zuerst?   (einmalig Cloud)
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

    else:
        print("Unbekannter Befehl. /help fuer Hilfe.")


def main() -> None:
    print(f"Prometheus — Testchat mit {PARTNER}.  (/help fuer Befehle, 'exit' zum Beenden)\n")
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
        result = agent.respond(user)
        tag = "  (lokal, 0 EUR)" if result["fell_back"] else f"  ({result['model']})"
        print(f"\n{PARTNER}{tag}:\n{result['text']}")


if __name__ == "__main__":
    main()
