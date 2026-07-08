"""Betriebsfreigabe-Paket: die kritischen Audit-Funde vor dem echten Arbeiten.
1 Freigabe fuehrt E-Mail wirklich aus · 2 Coding-Guard im Runner · 3 state.db-Backup
4 Shell-Guard (Code/Verfassung/Git) · 5 Desktop-Chat ephemer · 6 Watchdog session-genau
7 verifier-Default · 8 HANDBUCH-Crons korrigiert.
"""
from __future__ import annotations

import json
import sqlite3


# --- 1) Freigabe -> E-Mail wird WIRKLICH gesendet ---------------------------
def _tmp_approvals(monkeypatch, tmp_path):
    from core.agency import approvals
    from core.kernel import events
    db = str(tmp_path / "state.db")
    monkeypatch.setattr(approvals, "DB_PATH", db)
    monkeypatch.setattr(events, "DB_PATH", db)
    events.init_db()
    approvals.init_approvals()
    return approvals


def test_approve_email_sendet_wirklich(monkeypatch, tmp_path):
    approvals = _tmp_approvals(monkeypatch, tmp_path)
    from core.agency.connectors import mail
    gesendet = []
    monkeypatch.setattr(mail, "send", lambda to, s, b: gesendet.append((to, s, b)) or "OK")
    detail = json.dumps({"to": "kunde@firma.de", "subject": "Angebot", "body": "Hallo"})
    aid = approvals.create("E-Mail an kunde@firma.de: Angebot",
                           kind="email_stranger", detail=detail)
    r = approvals.decide(aid, approved=True)
    assert r["ok"] and r["applied"]["email_sent"] is True
    assert gesendet == [("kunde@firma.de", "Angebot", "Hallo")]


def test_approve_email_mit_ratsurteil_im_detail(monkeypatch, tmp_path):
    approvals = _tmp_approvals(monkeypatch, tmp_path)
    from core.agency.connectors import mail
    monkeypatch.setattr(mail, "send", lambda to, s, b: "OK")
    detail = (json.dumps({"to": "a@b.de", "subject": "x", "body": "y"})
              + "\n\n--- RATS-URTEIL (Kiras Selbst-Debatte) ---\nJA, machen.")
    aid = approvals.create("E-Mail an a@b.de: x", kind="email_stranger", detail=detail)
    assert approvals.decide(aid, approved=True)["applied"]["email_sent"] is True


def test_reject_email_sendet_nicht(monkeypatch, tmp_path):
    approvals = _tmp_approvals(monkeypatch, tmp_path)
    from core.agency.connectors import mail
    gesendet = []
    monkeypatch.setattr(mail, "send", lambda *a: gesendet.append(a))
    aid = approvals.create("E-Mail an x: y", kind="email_stranger",
                           detail=json.dumps({"to": "x", "subject": "y", "body": ""}))
    r = approvals.decide(aid, approved=False)
    assert r["status"] == "rejected" and gesendet == []


def test_approve_money_sagt_ehrlich_nicht_ausgefuehrt(monkeypatch, tmp_path):
    approvals = _tmp_approvals(monkeypatch, tmp_path)
    aid = approvals.create("Zahlung X", kind="money", detail="…")
    r = approvals.decide(aid, approved=True)
    assert "nicht automatisch" in r["applied"]["hint"]


# --- 2) Coding-Guard im Mission-Runner --------------------------------------
def test_runner_hebt_code_tasks_auf_reason():
    import inspect
    from core.agency.missions import runner
    src = inspect.getsource(runner._execute_scored)
    assert "_is_code_step" in src and "code_task" in src


# --- 3) state.db-Backup ------------------------------------------------------
def test_backup_erzeugt_kopie_und_rotiert(monkeypatch, tmp_path):
    from core import config
    from core.kernel import backup
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x)"); con.execute("INSERT INTO t VALUES (1)")
    con.commit(); con.close()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", str(db))
    r = backup.backup_state_db()
    assert r["ok"] and (tmp_path / "backups").exists()
    kopie = sqlite3.connect(r["path"])
    assert kopie.execute("SELECT x FROM t").fetchone()[0] == 1
    kopie.close()
    # zweiter Lauf am selben Tag: skip statt Doppelarbeit
    assert backup.backup_state_db().get("skipped")
    # Rotation: nur KEEP juengste bleiben
    for i in range(backup.KEEP + 3):
        (tmp_path / "backups" / f"state-2020-01-{i+1:02d}.db").write_bytes(b"x")
    backup._backup_dir().mkdir(exist_ok=True)
    (tmp_path / "backups" / "state-heute.db").unlink(missing_ok=True)
    # frisches Datum erzwingen, damit rotiert wird
    import core.kernel.backup as bk
    for f in sorted((tmp_path / "backups").glob("state-*.db"))[:-1]:
        pass
    # direkter Rotations-Check ueber erneuten Lauf mit neuem Datum
    monkeypatch.setattr(bk.datetime, "date", type("D", (), {
        "today": staticmethod(lambda: type("X", (), {"isoformat": lambda self: "2099-01-01"})())}))
    r2 = bk.backup_state_db()
    assert r2["ok"]
    assert len(list((tmp_path / "backups").glob("state-*.db"))) <= bk.KEEP


def test_backup_im_runner_verdrahtet():
    import inspect
    from core.agency.missions import runner
    assert "db_backup" in inspect.getsource(runner.run_forever)


# --- 4) Shell-Guard: Code/Verfassung/Git dicht -------------------------------
def test_shell_blockt_code_ueberschreiben_und_destruktives_git():
    from core.agency.shelltool import _is_dangerous
    assert _is_dangerous("echo kaputt > core/agency/act.py")
    assert _is_dangerous('powershell Set-Content core/kernel/supervisor.py "x"')
    assert _is_dangerous("dir >> tools/neu.ps1")
    assert _is_dangerous("type nul > hack.bat")
    assert _is_dangerous("powershell Set-Content core/mind/constitution.md boese")
    assert _is_dangerous("type core\\mind\\constitution.md")
    assert _is_dangerous("git reset --hard HEAD~5")
    assert _is_dangerous("git checkout -- .")
    assert _is_dangerous("git clean -fd")
    assert _is_dangerous("git push origin main --force")


def test_shell_erlaubt_normales_arbeiten_weiter():
    from core.agency.shelltool import _is_dangerous
    assert not _is_dangerous("uv run pytest tests -q")
    assert not _is_dangerous("python -m core.kernel.doctor")
    assert not _is_dangerous("echo hallo > data\\notiz.txt")
    assert not _is_dangerous("git status")
    assert not _is_dangerous('git commit -m "fix"')
    assert not _is_dangerous("git checkout -b feature/xyz")
    assert not _is_dangerous("python script.py > data\\out.log")


# --- 5) Desktop-Chat ist jetzt WIRKLICH ephemer ------------------------------
def test_desktop_sessions_ephemer():
    from core.mind.memory.store import _is_ephemeral
    assert _is_ephemeral("desktop-a1b2c3")
    assert _is_ephemeral("test-x") and _is_ephemeral("bench-y")
    assert not _is_ephemeral("telegram-123") and not _is_ephemeral("cockpit-abc")


# --- 6) Turn-Watchdog: session-genau ------------------------------------------
def test_turn_tracking_mit_sessions():
    from core.kernel import runstate
    runstate.enter_turn("telegram-1")
    runstate.enter_turn()  # ohne sid (alt) weiter erlaubt
    assert runstate.turn_active()
    assert runstate.active_turn_sids() == ["telegram-1"]
    runstate.exit_turn("telegram-1")
    runstate.exit_turn()
    assert not runstate.turn_active() and runstate.active_turn_sids() == []


def test_watchdog_misst_pro_session():
    import inspect
    from core.kernel import runstate
    src = inspect.getsource(runstate.start_watchdog)
    assert "active_turn_sids" in src and "session_id IN" in src


# --- 7) verifier-Default haelt die Live-Config nach ---------------------------
def test_verifier_default_ist_reason():
    import inspect
    from core.agency import verifier
    assert '"reason"' in inspect.getsource(verifier._verify_route)


# --- 8) HANDBUCH: kaputter Wochen-Cron raus, Briefing-Cron rein ---------------
def test_handbuch_crons_korrigiert():
    from pathlib import Path
    t = Path("docs/HANDBUCH.md").read_text(encoding="utf-8")
    assert 'schedule "So 20:30"' not in t          # haette einen Stunden-Takt erzeugt
    assert "Morgen-Briefing" in t and "{{standup}}" in t   # sonst feuert die Logbuch-Frage nie
    assert "wirkt nur zusammen mit `/work`" in t   # @ziel: ehrlich dokumentiert
    assert "denk:aus" in t                          # Reasoning-Regler dokumentiert
