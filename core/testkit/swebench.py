"""SWE-bench-Lite-Adapter: der internationale HARNESS-Benchmark (Princeton; 300 echte
GitHub-Issues aus 12 Python-Repos). Anders als HumanEval (misst nur das Modell) misst
das hier Agent+Modell ZUSAMMEN: Repo am base_commit auschecken, Kira das Issue mit ihrem
kompletten Coding-Kreis loesen lassen, Patch einsammeln.

Bewusst OHNE Docker (Windows-first, Flexibilitaet):
- Der Lauf erzeugt eine OFFIZIELLE predictions.jsonl (instance_id / model_name_or_path /
  model_patch) — damit laesst sich der amtliche Score jederzeit extern rechnen
  (sb-cli bzw. swebench.com, dort laeuft die Docker-Auswertung in der Cloud).
- Sofort gibt es eine ehrliche PROGNOSE je Aufgabe: Patch erzeugt? und beruehrt er
  dieselben Dateien wie der Gold-Patch? Die Prognose ist KEIN offizieller Score —
  sie zeigt nur, ob der Harness ueberhaupt am richtigen Ort operiert hat.

Repos werden als Bare-Spiegel in data/bench/repos/ gecacht (ein Fetch je base_commit,
GitHub erlaubt Commit-Fetch per SHA) — der zweite Lauf laedt fast nichts mehr.
"""
from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

# HuggingFace datasets-server: 300 Zeilen in 3 Seiten (kein Extra-Paket noetig)
_ROWS_URL = ("https://datasets-server.huggingface.co/rows?dataset=SWE-bench%2FSWE-bench_Lite"
             "&config=default&split=test&offset={offset}&length=100")
_FIELDS = ("instance_id", "repo", "base_commit", "problem_statement", "patch")


def _bench_dir() -> Path:
    from core import config

    return Path(config.DATA_DIR) / "bench"


def _kira_repo() -> Path:
    return Path(__file__).resolve().parents[2]


def load_tasks(limit: int | None = None) -> list[dict]:
    """Laedt die 300 Lite-Aufgaben (Download beim ersten Mal, danach Cache)."""
    cache = _bench_dir() / "swebench_lite.jsonl"
    if not cache.exists():
        import httpx

        cache.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict] = []
        for off in (0, 100, 200):
            r = httpx.get(_ROWS_URL.format(offset=off), timeout=120, follow_redirects=True)
            r.raise_for_status()
            for row in r.json().get("rows", []):
                d = row.get("row") or {}
                rows.append({k: d.get(k) for k in _FIELDS})
        if not rows:
            raise RuntimeError("SWE-bench-Lite-Download lieferte 0 Zeilen")
        cache.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in rows),
                         encoding="utf-8")
    tasks = [json.loads(line) for line in
             cache.read_text(encoding="utf-8").splitlines() if line.strip()]
    return tasks[: int(limit)] if limit else tasks


def _repo_url(repo: str) -> str:
    return f"https://github.com/{repo}"


def _git(*args: str, cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, check=True, timeout=600)


def checkout(repo: str, commit: str, dest: Path) -> None:
    """Repo am base_commit nach dest auschecken — ueber einen gecachten Bare-Spiegel.
    GitHub erlaubt Fetch per Commit-SHA; der Spiegel macht Folge-Laeufe fast kostenlos."""
    mirror = _bench_dir() / "repos" / (repo.replace("/", "__") + ".git")
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _git("init", "--bare", str(mirror))
        _git("remote", "add", "origin", _repo_url(repo), cwd=mirror)
    ref = f"refs/bench/{commit}"
    have = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref],
                          cwd=str(mirror), capture_output=True, text=True)
    if have.returncode != 0:
        _git("fetch", "--depth", "1", "origin", f"{commit}:{ref}", cwd=mirror)
    # clone uebertraegt refs/bench/* nicht und der Spiegel ist shallow -> direkter
    # depth-1-Fetch der Bench-Ref in einen frischen Baum + Checkout von FETCH_HEAD.
    dest.mkdir(parents=True, exist_ok=True)
    _git("init", "--quiet", str(dest))
    _git("fetch", "--quiet", "--depth", "1", str(mirror), ref, cwd=dest)
    _git("checkout", "--quiet", "FETCH_HEAD", cwd=dest)


def _agent_env(allow_llm: bool = True) -> dict:
    """Sandbox-Env fuer den Agenten-Subprozess. WICHTIG (0%-Bug, Lauf 1): KIRA_ROOT darf
    NICHT aufs Fremd-Repo zeigen — dort fehlen config.yaml und core/mind/, der Subprozess
    stirbt beim Import, bevor er anfaengt. Kira laeuft in IHREM Repo; das Fremd-Repo liegt
    als Unterordner in data/bench/work/ (Werkzeuge sind ROOT-gebunden -> erreichbar).
    Nur die DATEN sind umgelenkt (frische state.db), Firewall an, Modell erlaubt."""
    import os

    data = Path(tempfile.mkdtemp(prefix="kira-swb-data-"))
    env = {**os.environ,
           "KIRA_DATA_DIR": str(data),
           "KIRA_TEST_MODE": "1",
           "KIRA_NO_OUTBOUND": "1",
           # Rang-Boden: kein Schritt faellt auf reflex/lokal zurueck — im Fremd-Repo
           # (riesige Dateien) waere das Zeitlupe und verfaelscht den Harness-Messwert.
           "KIRA_RANK_FLOOR": "reason",
           "PYTHONPATH": str(_kira_repo())}
    env.pop("KIRA_ROOT", None)
    if allow_llm:
        env["KIRA_ALLOW_LLM"] = "1"
    return env


_PROMPT = ("SWE-BENCH-AUFGABE. Ein fremdes Python-Repository liegt in DIESEM Projekt "
           "unter dem relativen Pfad '{repo}'. Unten steht ein ECHTER GitHub-Issue dazu. "
           "Finde die Ursache im Quellcode und behebe sie mit einem moeglichst kleinen, "
           "gezielten Patch (edit_datei mit exaktem Suchtext).\n"
           "HARTE REGELN: Aendere AUSSCHLIESSLICH Dateien unter '{repo}/' — NIE Dateien "
           "ausserhalb (das eigene System ist tabu). Keine Tests, keine Doku anfassen, "
           "nichts loeschen, was du nicht verstehst.\n\nISSUE:\n{issue}")


def _run_agent(workdir: Path, task: dict, allow_llm: bool = True, timeout: int = 1800):
    """Kiras Coding-Kreis auf dem fremden Repo (Subprozess) — yieldet @EV-Ereignisse live."""
    env = _agent_env(allow_llm=allow_llm)
    try:
        rel = workdir.resolve().relative_to(_kira_repo()).as_posix()
    except ValueError:
        rel = str(workdir)
    payload = {"id": task.get("instance_id", "swb"),
               "prompt": _PROMPT.format(repo=rel,
                                        issue=(task.get("problem_statement") or "")[:6000]),
               # KEINE Kira-Endabnahme im Fremd-Repo: die waere dort immer rot und
               # wuerde den fertigen Patch zurueckrollen (0%-Bug). Das offizielle
               # SWE-bench-Eval IST die Abnahme.
               "code_review": False,
               "timeout": timeout}
    proc = subprocess.Popen([sys.executable, "-m", "core.testkit.attempt"],
                            cwd=str(_kira_repo()), env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    # Lebenszeichen + harter Timeout (Sergens 'haengt er oder denkt er?'-Problem):
    # ein Reader-Thread fuettert eine Queue; bleibt sie ~25s still, melden wir
    # 'arbeitet noch' statt Funkstille, und nach 'timeout' wird hart abgebrochen.
    import queue as _q
    import threading as _th

    lines: _q.Queue = _q.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout:
                lines.put(line.rstrip("\n"))
        finally:
            lines.put(None)

    _th.Thread(target=_reader, daemon=True).start()
    try:
        proc.stdin.write(json.dumps(payload))
        proc.stdin.close()
        start = time.time()
        while True:
            try:
                line = lines.get(timeout=25)
            except _q.Empty:
                laufzeit = int(time.time() - start)
                if laufzeit > timeout:
                    with contextlib.suppress(Exception):
                        proc.kill()
                    yield {"kind": "obs", "name": "⏱ Timeout",
                           "text": f"Aufgabe nach {laufzeit}s hart abgebrochen"}
                    break
                yield {"kind": "obs", "name": "⏳",
                       "text": f"arbeitet noch ({laufzeit}s) — Modell denkt/antwortet gerade"}
                continue
            if line is None:
                break
            if line.startswith("@EV "):
                with contextlib.suppress(Exception):
                    yield json.loads(line[4:])
    finally:
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)
        with contextlib.suppress(Exception):
            shutil.rmtree(env["KIRA_DATA_DIR"], ignore_errors=True)


def collect_patch(workdir: Path) -> str:
    """Unified-Diff aller Aenderungen (inkl. neuer Dateien) gegen den base_commit."""
    _git("add", "-A", cwd=workdir)
    p = _git("diff", "--cached", cwd=workdir)
    return p.stdout or ""


_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/", re.MULTILINE)


def patch_files(patch: str) -> set[str]:
    return set(_DIFF_FILE.findall(patch or ""))


def prognose(model_patch: str, gold_patch: str) -> tuple[bool, str]:
    """Ehrliche Sofort-Einschaetzung OHNE Docker: Patch da? richtige Datei(en) beruehrt?
    (Der amtliche Score kommt aus der offiziellen Auswertung der predictions.jsonl.)"""
    if not (model_patch or "").strip():
        return False, "kein Patch erzeugt"
    mine, gold = patch_files(model_patch), patch_files(gold_patch)
    hit = mine & gold
    if hit:
        return True, f"Patch beruehrt Gold-Datei(en): {', '.join(sorted(hit)[:3])}"
    return False, (f"Patch da ({len(mine)} Datei(en)), aber keine Gold-Datei getroffen "
                   f"(erwartet: {', '.join(sorted(gold)[:3])})")


def _predictions_path() -> Path:
    return _bench_dir() / "swebench-predictions.jsonl"


def _record_prediction(instance_id: str, model: str, patch: str) -> None:
    """Offizielles Format fuer die amtliche Auswertung (sb-cli / swebench.com)."""
    p = _predictions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"instance_id": instance_id,
                            "model_name_or_path": f"kira+{model}",
                            "model_patch": patch}, ensure_ascii=False) + "\n")


def stream_swebench(limit: int = 3, allow_llm: bool = True, agent_fn=None):
    """Generator fuer die Live-Ansicht im Cockpit — gleiche Ereignis-Formen wie
    bench.stream_suite/stream_humaneval. 'passed' = PROGNOSE (siehe oben), der
    Endstand traegt zusaetzlich den Pfad der predictions.jsonl."""
    agent_fn = agent_fn or _run_agent
    try:
        tasks = load_tasks(limit=max(1, min(int(limit or 3), 300)))
    except Exception as e:  # noqa: BLE001
        yield {"kind": "error", "text": f"SWE-bench-Datensatz nicht ladbar: {str(e)[:200]}"}
        return
    try:
        from core.kernel import llm_router

        model, _fb = llm_router.resolve_model("reason")
    except Exception:  # noqa: BLE001
        model = "?"
    yield {"kind": "suite_start", "total": len(tasks), "suite": "swebench",
           "role": "harness", "model": model}
    passed = 0
    for t in tasks:
        tid = str(t.get("instance_id") or "?")
        kopf = (t.get("problem_statement") or "").strip().splitlines()
        yield {"kind": "task_start", "id": tid,
               "prompt": (kopf[0] if kopf else tid)[:120]}
        # Arbeitsordner UNTER Kiras Datenbereich (gitignored) statt /tmp: die Werkzeuge
        # (edit_datei & Co.) sind ROOT-gebunden und kommen nur dorthin (0%-Bug, Lauf 1).
        base = _bench_dir() / "work" / f"{tid[:40]}-{uuid.uuid4().hex[:6]}"
        base.mkdir(parents=True, exist_ok=True)
        wd = base / "repo"
        try:
            t0 = time.time()
            checkout(str(t.get("repo")), str(t.get("base_commit")), wd)
            for ev in agent_fn(wd, t, allow_llm=allow_llm):
                yield {"kind": "act", "id": tid, "ev": ev}
            patch = collect_patch(wd)
            ok, info = prognose(patch, t.get("patch") or "")
            _record_prediction(tid, model, patch)
            info += f" · {int(time.time() - t0)}s"
        except Exception as e:  # noqa: BLE001
            ok, info = False, f"[Runner-Fehler] {str(e)[:200]}"
        finally:
            shutil.rmtree(base, ignore_errors=True)
        passed += 1 if ok else 0
        yield {"kind": "task_done", "id": tid, "passed": ok, "rc": 0 if ok else 1,
               "out": info[:300]}
    yield {"kind": "summary", "passed": passed, "total": len(tasks), "role": "harness",
           "model": model, "suite": "swebench",
           "pass_at_1": round(100 * passed / len(tasks), 1) if tasks else 0.0,
           "note": "PROGNOSE (Datei-Treffer) — amtlicher Score via predictions.jsonl",
           "predictions": str(_predictions_path())}
