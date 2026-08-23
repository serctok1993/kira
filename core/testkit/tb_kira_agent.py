"""Terminal-Bench-2.0-Adapter (Harbor): Kiras ECHTER Harness-Loop faehrt den Benchmark.

Kein Nachbau: run() ruft act._native_loop — denselben Code mit denselben Waechtern
(Promise-Stups, Beweispflicht II/III, Leak-Recovery, Degradation), der auch Chat und
Missionen traegt. Einziges Werkzeug ist 'terminal' (exec im Task-Container); das misst
exakt den Harness-Anteil, den das Leaderboard vergleichen will.

Aufruf (eigene Umgebung, Python >= 3.13 — siehe scripts/tb-setup.sh):
  .tb-venv/bin/harbor run --dataset <terminal-bench-2.0-registry-name> \
      --agent core.testkit.tb_kira_agent:KiraAgent \
      --model openrouter/nvidia/nemotron-3-ultra-550b-a55b:free

Der Adapter setzt seine Sandbox-Env (KIRA_DATA_DIR/TEST_MODE/ALLOW_LLM) VOR den
Kira-Imports — core.config friert Pfade beim Import ein. Kiras Loop ist synchron,
Harbor async: der Loop laeuft im Executor-Thread, das terminal-Werkzeug reicht jeden
Befehl per run_coroutine_threadsafe an environment.exec() zurueck.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

_KIRA_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("KIRA_DATA_DIR", tempfile.mkdtemp(prefix="kira-tb-data-"))
os.environ.setdefault("KIRA_TEST_MODE", "1")
os.environ.setdefault("KIRA_ALLOW_LLM", "1")
# Gratis-Reasoning-Modelle denken teils >300s/Zug (wf2-Befund 23.08.)
os.environ.setdefault("KIRA_HARD_CALL_TIMEOUT", "600")
if str(_KIRA_ROOT) not in sys.path:
    sys.path.insert(0, str(_KIRA_ROOT))

from harbor.agents.base import BaseAgent  # noqa: E402
from harbor.environments.base import BaseEnvironment  # noqa: E402
from harbor.models.agent.context import AgentContext  # noqa: E402

from core.agency.tools.registry import tool  # noqa: E402

# Aktuelle (Event-Loop, Environment) je Task — thread-lokal, weil Harbor Tasks
# parallel fahren kann (--n-concurrent) und Kiras Loop je Task in einem eigenen
# Executor-Thread laeuft.
_TL = threading.local()


@tool("terminal",
      "Fuehrt einen Shell-Befehl im Task-Container aus (bash, root) und liefert "
      "stdout/stderr/Exit-Code. WICHTIG: Jeder Aufruf ist eine FRISCHE Shell — "
      "Arbeitsverzeichnis und Variablen persistieren NICHT; nutze absolute Pfade "
      "oder 'cd /pfad && befehl'. Langlaeufer via 'nohup ... > log 2>&1 &' starten "
      "und das Log pruefen. Interaktive Programme meiden (printf/cat/sed statt "
      "Editor); notfalls tmux im Container nutzen.",
      {"befehl": "der Shell-Befehl (bash -c)",
       "timeout_sek": "max. Laufzeit in Sekunden (Default 60, Max 600)"})
def terminal(befehl: str = "", timeout_sek: float = 60.0) -> str:
    loop = getattr(_TL, "loop", None)
    env = getattr(_TL, "env", None)
    if loop is None or env is None:
        return "Fehler: keine aktive Container-Umgebung (Adapter-Zustand)."
    try:
        timeout = max(1, min(int(float(timeout_sek)), 600))
    except (TypeError, ValueError):
        timeout = 60
    try:
        fut = asyncio.run_coroutine_threadsafe(
            env.exec(command=befehl, timeout_sec=timeout), loop)
        r = fut.result(timeout=timeout + 30)
    except Exception as e:  # noqa: BLE001 — Timeout/Exec-Fehler lehrend zurueckgeben
        return f"Fehler bei der Ausfuehrung (evtl. Timeout {timeout}s): {e}"
    teile = [f"EXIT-CODE: {r.return_code}"]
    if r.stdout:
        teile.append("STDOUT:\n" + r.stdout)
    if r.stderr:
        teile.append("STDERR:\n" + r.stderr)
    if not r.stdout and not r.stderr:
        teile.append("(keine Ausgabe)")
    return "\n".join(teile)


_SYSTEM = """Du bist ein autonomer Terminal-Agent und loest die gestellte Aufgabe \
vollstaendig und selbststaendig in einem Linux-Container (root).

# ARBEITSWEISE (direkt statt zoegernd)
- Einziges Werkzeug: 'terminal'. Jeder Aufruf ist eine frische Shell — absolute Pfade
  oder 'cd /pfad && befehl'; Umgebungsvariablen pro Aufruf setzen.
- Handle sofort; es gibt KEINEN Nutzer fuer Rueckfragen. Erst pruefen, dann melden.
- Lange Ausgaben in Dateien umleiten und gezielt mit head/tail/grep lesen.
- Langlaeufer (Server, Builds) mit 'nohup ... > /tmp/log 2>&1 &' starten, dann das
  Log pruefen — nie blind warten.
- Die Aufgabe ist erst fertig, wenn du das geforderte Ergebnis VERIFIZIERT hast
  (Datei existiert, Test gruen, Dienst antwortet). Melde dann kurz das Ergebnis —
  ohne weitere Werkzeug-Aufrufe."""


class KiraAgent(BaseAgent):
    """Kira als Terminal-Bench-Agent — der Harness-Loop ist das Original."""

    @staticmethod
    def name() -> str:
        return "kira"

    def version(self) -> str | None:
        return "2026.08"

    async def setup(self, environment: BaseEnvironment) -> None:
        # Kira laeuft AUSSERHALB des Containers — nichts fuer den Agenten zu
        # installieren. Aber: Diese Sandbox re-terminiert ALLEN HTTPS-Verkehr
        # (Container transparent via Egress-Gateway-CA, nicht ueber die lokale
        # Agent-Proxy-CA!). Damit Laufzeit-Downloads im Task-Container
        # (pip/curl/git/apt) nicht an der Verifikation scheitern, wird das
        # komplette Host-CA-Bundle (Mozilla-Roots + Anthropic-Abfang-CAs) VOR dem
        # Agenten-Lauf installiert — reine Umgebungs-Akkommodation, die
        # Task-Definition bleibt unberuehrt. Einzelzert-Dateien in
        # /usr/local/share machen das Vertrauen fest gegen ein spaeteres
        # update-ca-certificates im Task (das ueberschreibt das Bundle sonst).
        # Ausserhalb dieser Sandbox (keine CA-Datei) ist das ein No-op.
        ca = Path("/root/.ccr/ca-bundle.crt")
        if not ca.exists():
            return
        try:
            await environment.exec(
                command="mkdir -p /etc/ssl/certs /usr/local/share/ca-certificates",
                timeout_sec=30)
            await environment.upload_file(ca, "/etc/ssl/certs/ca-certificates.crt")
            cmd = (
                "awk '/BEGIN CERTIFICATE/{c++; keep=1} "
                "keep{print > (\"/usr/local/share/ca-certificates/ccr-\" c \".crt\")} "
                "/END CERTIFICATE/{keep=0}' /etc/ssl/certs/ca-certificates.crt && "
                "{ command -v update-ca-certificates >/dev/null 2>&1 && "
                "update-ca-certificates >/dev/null 2>&1 || true; } && "
                "printf '[global]\\ncert = /etc/ssl/certs/ca-certificates.crt\\n' > /etc/pip.conf && "
                "printf 'SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt\\n"
                "REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt\\n"
                "NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt\\n' >> /etc/environment"
            )
            await environment.exec(command=cmd, timeout_sec=120)
        except Exception:  # noqa: BLE001 — Minimal-Container ohne awk/sh: Agent laeuft trotzdem
            pass

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        if self.model_name:
            os.environ["KIRA_FORCE_MODEL"] = self.model_name
        sid = "tb-" + uuid.uuid4().hex[:10]
        loop = asyncio.get_running_loop()

        def _kira_lauf() -> str:
            _TL.loop = loop
            _TL.env = environment
            try:
                from core.agency import act
                from core.kernel import events

                events.init_db()
                messages = [{"role": "user", "content": instruction}]
                # max_steps grosszuegig: die echte Grenze ist Harbors Task-Wall-Clock
                # (900-1800s); der Loop endet frueher, sobald die Aufgabe fertig ist.
                return act._native_loop(
                    messages, _SYSTEM, session_id=sid, escalate=True,
                    emit=lambda ev: None, max_steps=150, task_type="reason",
                    erlaubt=frozenset({"terminal"}), rolle="terminal-bench")
            finally:
                _TL.loop = None
                _TL.env = None

        final = await loop.run_in_executor(None, _kira_lauf)

        ein, aus, kosten = self._bilanz(sid)
        context.n_input_tokens = ein or None
        context.n_output_tokens = aus or None
        context.cost_usd = kosten or None
        context.metadata = {"kira_final": (final or "")[:1500], "session_id": sid}

        # Degradation (Provider-/Quota-Tod: _native_loop liefert einen Degrade-Bericht
        # statt zu werfen — richtig fuer Live, falsch fuer den Benchmark) als Exception
        # melden: nur so zaehlt Harbor den Trial als Fehler und `harbor jobs resume`
        # wiederholt ihn spaeter, statt eine 0 als "fertig" festzuschreiben.
        deg = self._degradiert(sid)
        if deg:
            raise RuntimeError(f"KiraDegraded: {deg}")

    @staticmethod
    def _degradiert(session_id: str) -> str | None:
        """Letzter act_degraded-Fehler dieses Tasks aus Kiras Event-Log, sonst None."""
        try:
            from core.kernel import events
            for e in events.recent(5000):
                if e.get("session_id") == session_id and e["type"] == "act_degraded":
                    return str((e["payload"] or {}).get("error") or "unbekannt")[:300]
            return None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _bilanz(session_id: str) -> tuple[int, int, float]:
        """Tokens/Kosten aus Kiras eigenem llm_call-Event-Log dieses Tasks."""
        try:
            from core.kernel import events
            ein = aus = 0
            kosten = 0.0
            for e in events.recent(5000):
                if e.get("session_id") == session_id and e["type"] == "llm_call":
                    t = (e["payload"] or {}).get("tokens") or {}
                    ein += int(t.get("prompt") or 0)
                    aus += int(t.get("completion") or 0)
                    kosten += float((e["payload"] or {}).get("cost_usd") or 0.0)
            return ein, aus, round(kosten, 6)
        except Exception:  # noqa: BLE001
            return 0, 0, 0.0
