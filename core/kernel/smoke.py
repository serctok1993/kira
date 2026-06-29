"""Smoke-Test: prueft Event-Store + einen LLM-Call (cloud-first, Fallback lokal)."""
from __future__ import annotations

from core.kernel import events, llm_router


def main() -> None:
    events.init_db()
    print("-> Event-Store init OK")

    eid = events.emit("smoke_test", {"hello": "prometheus"})
    print(f"-> Event geschrieben: {eid[:8]}")

    print("-> LLM-Call (cloud-first, Fallback lokal) ...")
    result = llm_router.complete(
        [{"role": "user", "content": "Antworte in genau einem kurzen Satz: Bist du bereit, Partner zu sein?"}],
        system="Du bist Prometheus, ein autonomer Partner-Agent.",
        task_type="chat",
    )
    where = "LOKAL (Ollama, 0 EUR)" if result["fell_back"] else f"CLOUD ({result['model']})"
    print(f"-> Antwort via {where}:")
    print(f"   {result['text'].strip()}")
    print(f"-> Latenz: {result['latency_s']:.2f}s | Kosten: ${result['cost_usd']:.6f}")
    print(f"-> Events nach Typ: {events.counts_by_type()}")
    print("\nOK — Smoke-Test bestanden. Prometheus atmet.")


if __name__ == "__main__":
    main()
