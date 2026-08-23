"""apply_edit gehaertet: atomar, Verify VOR Commit, dateiweiser Rollback (kein reset --hard).

Echtes tmp-Git-Repo (offline), _verify/_request_restart gefakt, Events auf tmp-DB.
"""
from __future__ import annotations

import subprocess


def _git(repo, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    return (r.stdout or "").strip()


def _repo(monkeypatch, tmp_path):
    """tmp-Git-Repo mit Seed-Commit; selfdev.ROOT + Events umgebogen, Restart neutral."""
    from core.agency import selfdev
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@test")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    monkeypatch.setattr(selfdev, "ROOT", tmp_path)
    monkeypatch.setattr(selfdev, "_request_restart", lambda which="all": None)
    # Diese Tests pruefen den VOLLPRUEFUNGS-Vertrag (Suite vor Commit, Rollback bei Rot).
    # Seit der Entfesselung 23.08. ist der schnelle Syntax-Check der Default (sonst kostete
    # jeder Einzel-Edit Minuten) — fuer den Vertrag hier schalten wir ihn ab.
    monkeypatch.setattr(selfdev, "fast_verify_active", lambda: False)
    return tmp_path


def test_roter_verify_stellt_nur_die_datei_zurueck(monkeypatch, tmp_path):
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    monkeypatch.setattr(selfdev, "_verify", lambda: (False, "[exit 1] 1 failed"))
    head_vorher = _git(repo, "rev-parse", "HEAD")
    # zweite, UNGESPEICHERTE Arbeit im Repo — die frueher git reset --hard vernichtet haette
    dirty = repo / "andere.py"
    dirty.write_text("wichtig = True\n", encoding="utf-8")

    r = selfdev.apply_edit("mod.py", "def f():\n    return 2\n", reason="test")

    assert r["ok"] is False and "Verifizierung" in r["error"]
    assert (repo / "mod.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"  # zurueck
    assert dirty.read_text(encoding="utf-8") == "wichtig = True\n"  # UNANGETASTET
    assert _git(repo, "rev-parse", "HEAD") == head_vorher  # kein Commit
    assert _git(repo, "diff", "--cached", "--name-only") == ""  # nichts gestaged


def test_gruener_verify_committet(monkeypatch, tmp_path):
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    monkeypatch.setattr(selfdev, "_verify", lambda: (True, "[exit 0] alles gruen"))
    head_vorher = _git(repo, "rev-parse", "HEAD")

    r = selfdev.apply_edit("mod.py", "def f():\n    return 2\n", reason="upgrade")

    assert r["ok"] is True and r.get("verified") is True
    assert _git(repo, "rev-parse", "HEAD") != head_vorher
    assert "selfdev: upgrade" in _git(repo, "log", "-1", "--format=%s")
    assert "return 2" in (repo / "mod.py").read_text(encoding="utf-8")


def test_syntaxfehler_rollt_ohne_git_zurueck(monkeypatch, tmp_path):
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    monkeypatch.setattr(selfdev, "_verify", lambda: (True, "[exit 0]"))
    head_vorher = _git(repo, "rev-parse", "HEAD")

    r = selfdev.apply_edit("mod.py", "def kaputt(:\n", reason="bad")

    assert r["ok"] is False and "Syntaxfehler" in r["error"]
    assert "return 1" in (repo / "mod.py").read_text(encoding="utf-8")
    assert _git(repo, "rev-parse", "HEAD") == head_vorher


def test_neue_datei_bei_rotem_verify_geloescht(monkeypatch, tmp_path):
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    monkeypatch.setattr(selfdev, "_verify", lambda: (False, "[exit 1] rot"))

    r = selfdev.apply_edit("neu.py", "x = 1\n", reason="neu")

    assert r["ok"] is False
    assert not (repo / "neu.py").exists()  # alte Version gab es nicht -> weg


def test_verify_cmd_plattformfest(monkeypatch, tmp_path):
    """Windows-verify_cmd wird auf posix deterministisch als Testsuite-Lauf neu gebaut."""
    import os
    from core.agency import selfdev
    from core.config import CONFIG
    monkeypatch.setitem(CONFIG, "selfdev", {"verify_cmd": r".venv\Scripts\python.exe -m pytest tests -q"})
    if os.name == "nt":
        assert selfdev._verify_cmd() == r".venv\Scripts\python.exe -m pytest tests -q"
    else:
        cmd = selfdev._verify_cmd()
        assert "-m pytest tests -q" in cmd
        assert "\\Scripts\\" not in cmd  # kein Windows-Pfad mehr
    # ohne verify_cmd: Import-Smoke mit existierendem Python
    monkeypatch.setitem(CONFIG, "selfdev", {})
    assert "import core.api.server" in selfdev._verify_cmd()


# --- Entfesselung 23.08.: Schnellpruefung ist Default -------------------------------
def test_schnellpruefung_ist_default_und_spart_die_suite(monkeypatch, tmp_path):
    """Inventur-Befund H7/H11: ausserhalb von code:-Laeufen lief nach JEDEM Einzel-Edit
    die komplette Testsuite (Minuten pro Edit). Jetzt reicht der Syntax-/Truncation-Check;
    die Suite laeuft am Lauf-Ende bzw. auf Wunsch."""
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    monkeypatch.setattr(selfdev, "fast_verify_active", lambda: True)  # der echte Default
    gelaufen = []
    monkeypatch.setattr(selfdev, "_verify", lambda: (gelaufen.append(1), (True, ""))[1])

    r = selfdev.apply_edit("mod.py", "def f():\n    return 2\n", reason="schnell")

    assert r["ok"] is True and r["verified"] is False
    assert not gelaufen, "die volle Suite darf pro Einzel-Edit NICHT laufen"
    assert (repo / "mod.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"
    assert _git(repo, "log", "-1", "--pretty=%s").startswith("selfdev:")   # trotzdem committet


def test_kaputte_syntax_wird_auch_schnell_abgelehnt(monkeypatch, tmp_path):
    """Die Schnellpruefung ist kein Blankoscheck: Syntaxfehler fliegen weiter raus."""
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    monkeypatch.setattr(selfdev, "fast_verify_active", lambda: True)

    r = selfdev.apply_edit("mod.py", "def f(:\n  kaputt\n", reason="kaputt")

    assert r["ok"] is False
    assert (repo / "mod.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"


def test_config_dateien_behalten_die_vollpruefung(monkeypatch, tmp_path):
    """YAML/JSON koennen die ganze Instanz lahmlegen (config-Import) — dort bleibt die
    volle Verify PFLICHT, auch im Schnell-Modus."""
    from core.agency import selfdev
    repo = _repo(monkeypatch, tmp_path)
    monkeypatch.setattr(selfdev, "fast_verify_active", lambda: True)
    gelaufen = []
    monkeypatch.setattr(selfdev, "_verify", lambda: (gelaufen.append(1), (True, ""))[1])

    r = selfdev.apply_edit("konf.yaml", "a: 1\n", reason="konfig")

    assert r["ok"] is True and gelaufen, "Config-Edit muss die Suite laufen lassen"
