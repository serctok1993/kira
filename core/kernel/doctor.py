"""Doctor: zeigt, welches Modell aktiv ist (Cloud vs. lokal) und testet einen Call.

Nach dem Eintragen eines API-Keys in .env hier pruefen, ob Cloud aktiv ist.
"""
from __future__ import annotations

import os

from core.config import CONFIG
from core.kernel import events, llm_router


def main() -> None:
    print("=== Kira Doctor ===")
    models = CONFIG["models"]
    print(f"Default-Modell : {models['default']}")
    print(f"Lokaler Fallback: {models['local_fallback']}")

    print("\nAPI-Keys:")
    for prov, env in [("anthropic", "ANTHROPIC_API_KEY"), ("deepseek", "DEEPSEEK_API_KEY")]:
        print(f"  {prov:10s}: {'GESETZT' if os.getenv(env) else 'fehlt -> lokal'}")

    print("\nRouting pro Task-Typ:")
    for tt in ["chat", "reason", "bulk", "classify"]:
        m, fb = llm_router.resolve_model(tt)
        print(f"  {tt:9s} -> {m}  {'(Fallback lokal)' if fb else '(CLOUD)'}")

    print("\nTest-Call (task=chat) ...")
    events.init_db()
    r = llm_router.complete(
        [{"role": "user", "content": "Sag in genau fuenf Woertern hallo."}], task_type="chat"
    )
    where = "LOKAL" if r["fell_back"] else "CLOUD"
    print(f"  -> {where} via {r['model']}")
    print(f"     Antwort: {r['text'].strip()[:120]}")
    print(f"     Latenz {r['latency_s']:.2f}s | Kosten ${r['cost_usd']:.6f}")
    print("\nFertig.")


if __name__ == "__main__":
    main()
