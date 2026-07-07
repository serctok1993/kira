"""Sandbox fuer Coding-Benchmarks: ein git-Worktree als isolierter Wegwerf-Arbeitsbaum.

Ein Benchmark-/Testlauf darf am ECHTEN Repo/Branch NICHTS aendern. make_worktree() legt einen
temporaeren Worktree auf einem Wegwerf-Branch an und liefert dazu die Sandbox-Env:
  KIRA_ROOT/KIRA_DATA_DIR  -> zeigen in den Worktree (state.db + Sidecars landen isoliert)
  KIRA_TEST_MODE + KIRA_NO_OUTBOUND -> Firewall an (kein Mail/Telegram/Cloud-Spend)
Git/Verify laufen darin voll REAL (sandbox_active() True -> suppress_repo_writes() False), aber
eingesperrt: der Live-Arbeitsbaum + die Live-state.db bleiben unberuehrt.

WICHTIG: dieses Modul importiert NUR stdlib (kein core.config). So kann ein Subprozess die Env
setzen, BEVOR core.config zum ersten Mal importiert wird — die Datenpfade werden beim Import
eingefroren, ein spaeteres Setzen wuerde nicht mehr greifen.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def sandbox_env(worktree: str | Path, allow_llm: bool = False) -> dict:
    """Env-Dict fuer einen Subprozess, der IN der Sandbox laeuft: Datenpfade zeigen in den
    Worktree, Outbound-Firewall an. Erbt die bestehende Umgebung (Keys etc.).

    allow_llm=True: erlaubt das ECHTE (konfigurierte) Modell — noetig, um Modelle real zu
    vergleichen (hy3 vs. GLM vs. lokal). Mail/Telegram bleiben trotzdem blockiert."""
    w = str(Path(worktree).resolve())
    env = {**os.environ,
           "KIRA_ROOT": w,
           "KIRA_DATA_DIR": str(Path(w) / "data"),
           "KIRA_TEST_MODE": "1",
           "KIRA_NO_OUTBOUND": "1"}
    if allow_llm:
        env["KIRA_ALLOW_LLM"] = "1"
    else:
        env.pop("KIRA_ALLOW_LLM", None)
    return env


@contextlib.contextmanager
def make_worktree(repo_root: str | Path | None = None, run_id: str | None = None,
                  allow_llm: bool = False):
    """Kontextmanager: legt einen git-Worktree auf Branch bench/<run_id> an und yieldet
    (worktree_pfad: Path, env: dict). Beim Verlassen wird Worktree + Branch restlos entfernt —
    auch bei einer Exception im Block. Der Live-Branch/Arbeitsbaum bleibt unangetastet."""
    root = Path(repo_root or _repo_root()).resolve()
    rid = run_id or uuid.uuid4().hex[:8]
    branch = f"bench/{rid}"
    base = Path(tempfile.mkdtemp(prefix=f"kira-bench-{rid}-"))
    wt = base / "wt"
    try:
        _git(root, "worktree", "add", "-b", branch, str(wt), "HEAD")
        (wt / "data").mkdir(parents=True, exist_ok=True)
        yield wt, sandbox_env(wt, allow_llm=allow_llm)
    finally:
        with contextlib.suppress(Exception):
            _git(root, "worktree", "remove", "--force", str(wt))
        with contextlib.suppress(Exception):
            _git(root, "branch", "-D", branch)
        with contextlib.suppress(Exception):
            shutil.rmtree(base, ignore_errors=True)
