"""HumanEval-Adapter: der internationale Standard-Coding-Benchmark (OpenAI, 164 Aufgaben, MIT).

Misst das MODELL direkt (pass@1) — so sind die Zahlen mit den veroeffentlichten Scores
vergleichbar (Frontier ~90 %+, starke offene Modelle grob 70-90 %). Pro Aufgabe: das Modell
vervollstaendigt eine Python-Funktion, der mitgelieferte offizielle Test entscheidet
bestanden/nicht. Der generierte Code laeuft in einem Subprozess mit Timeout in einem
Temp-Verzeichnis — er beruehrt weder Repo noch state.db.

Datensatz wird beim ersten Lauf von GitHub geladen und in data/bench/ gecacht (~220 KB).
"""
from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

URLS = (  # mehrere Quellen: manche Proxies blocken den github.com-Redirect
    "https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz",
    "https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz",
)


def _cache_path() -> Path:
    from core import config

    return Path(config.DATA_DIR) / "bench" / "HumanEval.jsonl.gz"


def load_problems(limit: int | None = None) -> list[dict]:
    """Laedt die 164 Aufgaben (Download beim ersten Mal, danach Cache)."""
    p = _cache_path()
    if not p.exists():
        import httpx

        p.parent.mkdir(parents=True, exist_ok=True)
        fehler = None
        for url in URLS:
            try:
                r = httpx.get(url, follow_redirects=True, timeout=60)
                r.raise_for_status()
                p.write_bytes(r.content)
                break
            except Exception as e:  # noqa: BLE001 — naechste Quelle probieren
                fehler = e
        if not p.exists():
            raise RuntimeError(f"HumanEval-Download fehlgeschlagen: {fehler}")
    probs: list[dict] = []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                probs.append(json.loads(line))
    return probs[: int(limit)] if limit else probs


_FENCE = re.compile(r"```(?:python)?\s*\n?(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Holt den Code aus der Modell-Antwort: bevorzugt den ersten ```python-Block,
    sonst die rohe Antwort (manche Modelle antworten ohne Zaun)."""
    m = _FENCE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def build_program(problem: dict, generated: str) -> str:
    """Baut das lauffaehige Pruef-Programm: Loesung + offizieller Test + check()-Aufruf.

    Enthaelt die Antwort die komplette Funktion (def <entry_point>), gilt sie als
    Voll-Loesung; sonst wird sie als Fortsetzung an den Aufgaben-Prompt gehaengt."""
    code = extract_code(generated)
    if f"def {problem['entry_point']}" in code:
        prog = code
    else:
        prog = problem["prompt"] + code
    return prog + "\n\n" + problem["test"] + f"\n\ncheck({problem['entry_point']})\n"


def run_program(program: str, timeout: int = 15) -> bool:
    """Fuehrt das Pruef-Programm in einem Subprozess aus. returncode 0 = bestanden."""
    with tempfile.TemporaryDirectory(prefix="kira-humaneval-") as d:
        f = Path(d) / "prog.py"
        f.write_text(program, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, str(f)], cwd=d,
                               capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            return False


_PROMPT = ("Vervollstaendige die folgende Python-Funktion. Antworte NUR mit EINEM "
           "```python Codeblock, der die KOMPLETTE Funktion (inklusive Signatur und aller "
           "noetigen Imports) enthaelt. Keine Erklaerungen, keine Beispiele.\n\n")


def solve(problem: dict, role: str = "reason") -> tuple[bool, str]:
    """Eine Aufgabe: Modell fragen (Route = role) -> Programm bauen -> pruefen."""
    from core.kernel import llm_router

    try:
        r = llm_router.complete([{"role": "user", "content": _PROMPT + problem["prompt"]}],
                                task_type=role, session_id="bench-humaneval")
        gen = r.get("text") or ""
        model = r.get("model") or "?"
    except Exception as e:  # noqa: BLE001 — Modell-Fehler = nicht bestanden, Lauf geht weiter
        return False, f"LLM-Fehler: {str(e)[:120]}"
    try:
        return run_program(build_program(problem, gen)), model
    except Exception as e:  # noqa: BLE001
        return False, f"Programm-Fehler: {str(e)[:120]}"


def stream_humaneval(limit: int = 20, role: str = "reason"):
    """Generator fuer die Live-Ansicht im Cockpit — gleiche Ereignis-Formen wie
    bench.stream_suite (suite_start/task_start/task_done/summary)."""
    try:
        probs = load_problems(limit=limit)
    except Exception as e:  # noqa: BLE001
        yield {"kind": "error", "text": f"HumanEval-Datensatz nicht ladbar: {str(e)[:200]}"}
        return
    yield {"kind": "suite_start", "total": len(probs), "suite": "humaneval", "role": role}
    passed = 0
    for pr in probs:
        tid = pr.get("task_id", "?")
        kopf = (pr.get("prompt") or "").strip().splitlines()
        sig = next((z for z in kopf if z.strip().startswith("def ")), tid)
        yield {"kind": "task_start", "id": tid, "prompt": sig.strip()[:120]}
        ok, info = solve(pr, role=role)
        passed += 1 if ok else 0
        yield {"kind": "task_done", "id": tid, "passed": ok, "rc": 0 if ok else 1,
               "out": info[:200]}
    yield {"kind": "summary", "passed": passed, "total": len(probs),
           "pass_at_1": round(100 * passed / len(probs), 1) if probs else 0.0}
