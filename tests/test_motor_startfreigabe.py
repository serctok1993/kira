"""Motor-Startfreigabe: die Haertung, die VOR dem Heartbeat dicht sein muss.

1. write_file-Loch: bestehende Code-Datei im Repo darf nicht blind ueberschrieben werden.
2. Supervisor-Absturzbremse: exponentieller Backoff + Krisen-Cooldown gegen Crash-Loops.
3. Selbstmessung: dauerhafter Wochen-Messpunkt (0 Token) macht Drift sichtbar.
"""
from __future__ import annotations

import json


# --- 1) write_file-Loch geschlossen -----------------------------------------
def test_write_file_blockt_bestehende_codedatei(tmp_path, monkeypatch):
    import core.agency.tools.builtin as b
    from core import config

    # ROOT auf ein Sandkasten-Repo umbiegen; eine bestehende .py-Datei anlegen
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(b, "ROOT", tmp_path)
    code = tmp_path / "core" / "modul.py"
    code.parent.mkdir(parents=True)
    code.write_text("x = 1\n", encoding="utf-8")

    res = b.write_file(str(code), "x = 2\n")
    assert "BLOCKIERT" in res and "edit_datei" in res
    assert code.read_text(encoding="utf-8") == "x = 1\n"  # unveraendert


def test_write_file_erlaubt_neue_datei_und_nichtcode(tmp_path, monkeypatch):
    import core.agency.tools.builtin as b
    from core import config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(b, "ROOT", tmp_path)

    neu = tmp_path / "core" / "neu.py"  # existiert noch nicht -> Neuanlage erlaubt
    assert "OK" in b.write_file(str(neu), "y = 1\n")
    assert neu.exists()

    doku = tmp_path / "notizen.md"  # Nicht-Code -> immer erlaubt (auch bestehend)
    doku.write_text("alt", encoding="utf-8")
    assert "OK" in b.write_file(str(doku), "neu")
    assert doku.read_text(encoding="utf-8") == "neu"


def test_write_file_erlaubt_codedatei_ausserhalb_repo(tmp_path, monkeypatch):
    import core.agency.tools.builtin as b
    from core import config

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(config, "ROOT", repo)
    monkeypatch.setattr(b, "ROOT", repo)

    aussen = tmp_path / "extern" / "skript.py"  # ausserhalb ROOT -> frei
    aussen.parent.mkdir(parents=True)
    aussen.write_text("a = 1\n", encoding="utf-8")
    assert "OK" in b.write_file(str(aussen), "a = 2\n")
    assert aussen.read_text(encoding="utf-8") == "a = 2\n"


def test_write_file_blockt_weiter_die_verfassung(tmp_path, monkeypatch):
    import core.agency.tools.builtin as b

    res = b.write_file(str((b.MIND_DIR / "constitution.md")), "gekapert")
    assert "BLOCKIERT" in res and "Verfassung" in res


def test_append_file_blockt_bestehende_codedatei(tmp_path, monkeypatch):
    import core.agency.tools.builtin as b
    from core import config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(b, "ROOT", tmp_path)
    code = tmp_path / "app.js"
    code.write_text("console.log(1)\n", encoding="utf-8")
    res = b.append_file(str(code), "// hack\n")
    assert "BLOCKIERT" in res
    assert code.read_text(encoding="utf-8") == "console.log(1)\n"


# --- 2) Supervisor-Absturzbremse --------------------------------------------
def test_backoff_exponentiell_und_gedeckelt():
    from core.kernel import supervisor as sv

    assert sv._backoff_plan(1) == (True, 2.0, False)
    assert sv._backoff_plan(2) == (True, 4.0, False)
    assert sv._backoff_plan(3) == (True, 8.0, False)
    # gedeckelt auf _MAX_BACKOFF (60s) — 2**7=128 waere hoeher, aber Krise greift vorher
    r, wait, crisis = sv._backoff_plan(4)
    assert r is True and wait == 16.0 and crisis is False


def test_backoff_krisenmodus_stoppt_neustart():
    from core.kernel import supervisor as sv

    relaunch, wait, crisis = sv._backoff_plan(sv._CRASH_LIMIT)
    assert crisis is True and relaunch is False
    assert wait == sv._CRASH_WINDOW  # langer Cooldown statt Sofort-Neustart


def test_alert_schweigt_bei_firewall(monkeypatch):
    from core.kernel import supervisor as sv
    from core import config

    monkeypatch.setattr(config, "outbound_blocked", lambda: True)
    gesendet = []
    # httpx.post duerfte gar nicht erst gerufen werden
    monkeypatch.setattr("httpx.post", lambda *a, **k: gesendet.append(1))
    sv._alert("Testalarm")
    assert gesendet == []


# --- 3) Selbstmessung (0 Token, Zeitreihe) ----------------------------------
def test_selfmetrics_snapshot_und_verlauf(monkeypatch, tmp_path):
    from core.agency import selfmetrics as sm
    from core import config

    from core.agency import outcomes

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(outcomes, "stats", lambda days=7: {
        "attempts": 4, "passed": 3, "pass_rate": 0.75, "avg_score": 82.0, "cost_usd": 0.12})
    pt = sm.snapshot()
    assert pt["pass_rate"] == 0.75 and pt["cost_usd"] == 0.12
    hist = sm.history()
    assert len(hist) == 1 and hist[0]["passed"] == 3
    # zweite Zeile -> jsonl waechst, Verlauf hat zwei Punkte
    sm.snapshot()
    assert len(sm.history()) == 2
    raw = (tmp_path / "selfmetrics.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(raw) == 2 and json.loads(raw[0])["attempts"] == 4


def test_selfmetrics_trend_richtung(monkeypatch, tmp_path):
    from core.agency import selfmetrics as sm
    from core import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "selfmetrics.jsonl").write_text(
        json.dumps({"ts": 1, "pass_rate": 0.60}) + "\n"
        + json.dumps({"ts": 2, "pass_rate": 0.80}) + "\n", encoding="utf-8")
    t = sm.trend()
    assert t["direction"] == "up" and t["delta"] == 0.2 and t["points"] == 2


def test_selfmetrics_leere_reihe_reisst_nicht(monkeypatch, tmp_path):
    from core.agency import selfmetrics as sm
    from core import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert sm.history() == []
    assert sm.trend()["direction"] == "flat"
