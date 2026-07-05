"""Paket B: Fast-Verify im Lauf — pro .py-Edit nur Syntax, volle Suite am Lauf-Ende,
bei Rot gesamter Lauf zurueckgerollt. Config-Schalter, echtes tmp-Git-Repo.
"""
from __future__ import annotations

import subprocess


def _git(repo, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    return (r.stdout or "").strip()


def _repo(monkeypatch, tmp_path):
    from core.agency import selfdev
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    monkeypatch.setattr(selfdev, "ROOT", tmp_path)
    monkeypatch.setattr(selfdev, "_request_restart", lambda which="all": None)
    selfdev.set_fast_verify(False)  # sauberer Start
    return tmp_path


# ---- selfdev: Fast-Verify committet ohne die Suite ------------------------------------

def test_fast_verify_committet_ohne_suite(monkeypatch, tmp_path):
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    called = {"verify": 0}
    monkeypatch.setattr(selfdev, "_verify", lambda: called.__setitem__("verify", called["verify"] + 1) or (True, "gruen"))

    selfdev.set_fast_verify(True)
    r = selfdev.apply_edit("mod.py", "def f():\n    return 2\n", reason="fast")
    selfdev.set_fast_verify(False)

    assert r["ok"] is True and r.get("verified") is False   # committet, aber Suite-Abnahme offen
    assert called["verify"] == 0                            # die Suite lief NICHT pro Edit
    assert "return 2" in (repo / "mod.py").read_text(encoding="utf-8")
    assert "selfdev: fast" in _git(repo, "log", "-1", "--format=%s")


def test_fast_verify_haelt_syntaxwache(monkeypatch, tmp_path):
    """Auch im Fast-Modus faengt py_compile kaputten Code (kein Commit)."""
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    selfdev.set_fast_verify(True)
    r = selfdev.apply_edit("mod.py", "def kaputt(:\n", reason="bad")
    selfdev.set_fast_verify(False)
    assert r["ok"] is False and "Syntaxfehler" in r["error"]
    assert _git(repo, "rev-parse", "HEAD") == head           # kein Commit
    assert "return 1" in (repo / "mod.py").read_text(encoding="utf-8")  # zurueckgerollt


def test_fast_verify_config_dateien_immer_voll(monkeypatch, tmp_path):
    """.yaml/.json behalten IMMER die volle Verify (Fast gilt nur fuer .py)."""
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)  # noqa: F841
    calls = {"n": 0}
    monkeypatch.setattr(selfdev, "_verify", lambda: calls.__setitem__("n", calls["n"] + 1) or (True, "gruen"))
    selfdev.set_fast_verify(True)
    selfdev.apply_edit("conf.yaml", "a: 1\n", reason="cfg")
    selfdev.set_fast_verify(False)
    assert calls["n"] == 1  # Config-Datei -> volle Verify trotz Fast-Modus


# ---- Endabnahme am Lauf-Ende -----------------------------------------------------------

def test_endabnahme_gruen(monkeypatch, tmp_path):
    from core.agency import act
    events = __import__("core.kernel.events", fromlist=["x"])
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()
    # HEAD hat sich bewegt (head0 != HEAD) -> Abnahme laeuft
    seq = iter(["HEAD_NEU"])  # rev-parse HEAD liefert etwas anderes als head0
    monkeypatch.setattr(act, "_git_out", lambda *a: next(seq) if a[:1] == ("rev-parse",) else "")
    from core.agency import selfdev
    monkeypatch.setattr(selfdev, "_verify", lambda: (True, "alles gruen"))
    note = act._endabnahme("HEAD_ALT", "e1", lambda ev: None)
    assert "gruen" in note
    assert "run_verify_pass" in [e["type"] for e in events.recent(10)]


def test_endabnahme_rot_rollt_zurueck(monkeypatch, tmp_path):
    from core.agency import act
    events = __import__("core.kernel.events", fromlist=["x"])
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()
    git_calls: list = []

    def fake_git(*a):
        git_calls.append(a)
        return "HEAD_NEU" if a[:1] == ("rev-parse",) else ""

    monkeypatch.setattr(act, "_git_out", fake_git)
    from core.agency import selfdev
    monkeypatch.setattr(selfdev, "_verify", lambda: (False, "3 failed"))
    note = act._endabnahme("HEAD_ALT", "e2", lambda ev: None)
    assert "ROT" in note and "zurueckgerollt" in note
    assert ("reset", "--hard", "HEAD_ALT") in git_calls       # gesamter Lauf zurueck
    assert "run_verify_rollback" in [e["type"] for e in events.recent(10)]


def test_endabnahme_ohne_edits_still(monkeypatch, tmp_path):
    from core.agency import act
    # HEAD == head0 -> keine Edits -> nichts abzunehmen
    monkeypatch.setattr(act, "_git_out", lambda *a: "SAME" if a[:1] == ("rev-parse",) else "")
    assert act._endabnahme("SAME", "e3", lambda ev: None) == ""


def test_config_hat_fast_verify_schalter():
    from core.config import CONFIG
    assert (CONFIG.get("selfdev", {}) or {}).get("fast_verify_in_run") is True
