"""Tool-Synthese: Kira schreibt, testet und registriert eigene Werkzeuge.

Ablauf:
1. LLM erzeugt EINE Python-Funktion (delimitiertes Format -> robust auch lokal).
2. Danger-Scan: klar destruktive Muster -> KEINE Auto-Registrierung (Verfassung).
3. Test in einem Subprozess mit Timeout (Isolation gegen Haenger).
4. Bei Erfolg: in den laufenden Prozess laden (registrieren) + in data/tools/ ablegen,
   damit das Werkzeug Neustarts ueberlebt (prozedurales Gedaechtnis).

Synthetisierte Werkzeuge liegen in data/tools/ (nicht im Git) und sind ab dann
fuer die Handlungs-Schleife (act) genauso verfuegbar wie eingebaute Werkzeuge.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys

from core.agency.tools import registry
from core.config import DATA_DIR, ROOT
from core.kernel import events
from core.kernel import llm_router
from core.kernel.scheduler import kill_switch_active
from core.mind.agent import _read

TOOLS_DIR = DATA_DIR / "tools"

# Klar destruktive/gefaehrliche Muster -> keine Auto-Registrierung (kein irreversibler Schaden).
_DANGER = [
    "rmtree", "os.remove", "os.unlink", "os.rmdir", ".unlink(", ".rmdir(",
    "os.system", "subprocess", "Popen", "shutil.move", "winreg", "ctypes",
    "eval(", "exec(", "__import__(",
]

_PROMPT = """Du brauchst ein neues Werkzeug: "{need}".

Schreibe es als GENAU EINE Python-Funktion. Antworte exakt in diesem Format:

NAME: <kurzer_name_in_snake_case>
DESC: <was das Werkzeug tut, ein Satz>
PARAMS: <arg1=Beschreibung; arg2=Beschreibung>   (oder: keine)
TEST: <JSON mit Testargumenten, z.B. {{"arg1": "wert"}}>   (oder: {{}})
CODE:
```python
def <name>(arg1, ...):
    # benoetigte Importe INNERHALB der Funktion
    ...
    return <ergebnis>
```

Regeln: genau eine Funktion; ihr Name = NAME; Importe nur innerhalb der Funktion;
gib immer einen sinnvollen Wert zurueck (kein print)."""


def _ask_llm(need: str, escalate: bool) -> dict:
    sysp = _read("constitution.md") + "\n\nDu konstruierst dir ein neues Werkzeug. Sei praezise und sicher."
    res = llm_router.complete(
        [{"role": "user", "content": _PROMPT.format(need=need)}],
        system=sysp,
        task_type="reason",
        escalate=escalate,
    )
    t = res["text"]
    m_name = re.search(r"NAME:\s*([A-Za-z_]\w*)", t)
    m_code = re.search(r"```(?:python)?\s*(.*?)```", t, re.DOTALL)
    if not (m_name and m_code):
        raise ValueError("Konnte die Werkzeug-Spezifikation nicht parsen. Modell-Ausgabe:\n" + t[:600])

    m_desc = re.search(r"DESC:\s*(.+)", t)
    m_params = re.search(r"PARAMS:\s*(.+)", t)
    m_test = re.search(r"TEST:\s*(\{.*?\})", t, re.DOTALL)

    params: dict[str, str] = {}
    if m_params and "keine" not in m_params.group(1).lower():
        for part in m_params.group(1).split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip()

    test: dict = {}
    if m_test:
        try:
            test = json.loads(m_test.group(1))
        except json.JSONDecodeError:
            test = {}

    return {
        "name": m_name.group(1),
        "desc": (m_desc.group(1).strip() if m_desc else need),
        "params": params,
        "code": m_code.group(1).strip(),
        "test": test,
    }


def _render(spec: dict) -> str:
    return (
        "# Auto-synthetisiert von Kira\n"
        "from core.agency.tools.registry import tool\n\n"
        f"@tool({spec['name']!r}, {spec['desc']!r}, {spec['params']!r})\n"
        f"{spec['code']}\n"
    )


def _load_tool_file(filepath) -> None:
    spec = importlib.util.spec_from_file_location(f"synth_{filepath.stem}", filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # der @tool-Dekorator registriert das Werkzeug


def load_synthesized() -> None:
    """Alle frueher gebauten Werkzeuge wieder registrieren (beim Start)."""
    if not TOOLS_DIR.exists():
        return
    for f in TOOLS_DIR.glob("*.py"):
        try:
            _load_tool_file(f)
        except Exception as e:  # noqa: BLE001
            events.emit("tool_load_error", {"file": f.name, "error": str(e)})


def _test_in_subprocess(name: str, filepath, test_args: dict) -> tuple[bool, str]:
    runner = (
        "import sys\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('synth_{name}', r'{filepath}')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "from core.agency.tools import registry\n"
        f"fn = registry.get('{name}').func\n"
        f"res = fn(**{test_args!r})\n"
        "print('SYNTH_OK', str(res)[:400])\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", runner],
            timeout=25,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout (>25s) — Werkzeug haengt."
    ok = proc.returncode == 0 and "SYNTH_OK" in proc.stdout
    return ok, (proc.stdout + proc.stderr).strip()[-800:]


def synthesize(need: str, escalate: bool = False) -> dict:
    if kill_switch_active():
        return {"ok": False, "reason": "Kill-Switch aktiv."}

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    spec = _ask_llm(need, escalate)
    name = spec["name"]
    file_content = _render(spec)

    hits = [d for d in _DANGER if d in spec["code"]]
    filepath = TOOLS_DIR / f"{name}.py"
    filepath.write_text(file_content, encoding="utf-8")
    events.emit("tool_synthesized", {"name": name, "need": need, "danger": hits})

    if hits:
        filepath.unlink(missing_ok=True)  # nicht aktiv ablegen
        return {"ok": False, "name": name, "needs_review": True,
                "reason": f"Sicherheits-Stop: potenziell gefaehrlich {hits}", "code": file_content}

    ok, out = _test_in_subprocess(name, filepath, spec.get("test") or {})
    if not ok:
        filepath.unlink(missing_ok=True)
        return {"ok": False, "name": name, "reason": "Test fehlgeschlagen", "test_output": out, "code": file_content}

    _load_tool_file(filepath)  # im laufenden Prozess registrieren
    events.emit("tool_registered", {"name": name})
    return {"ok": True, "name": name, "test_output": out, "code": file_content}


if __name__ == "__main__":
    need = " ".join(sys.argv[1:]) or "ein Werkzeug, das die Anzahl der Woerter in einem Text zaehlt"
    r = synthesize(need)
    print(json.dumps({k: v for k, v in r.items() if k != "code"}, ensure_ascii=False, indent=2))
    if r.get("code"):
        print("\n--- CODE ---\n" + r["code"])
