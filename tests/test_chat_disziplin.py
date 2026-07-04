"""Arbeitsdisziplin im Chat: Auto-Plan, Rueckfrage-Killer, Beweispflicht-Stempel.

Sergens Live-Befund: grosser Auftrag im Plain-Chat -> Bestaetigungsschleife statt Plan,
und halluzinierte Ergebnisse ('10 E-Mails liegen auf dem Desktop') ohne Pruefung.
"""
from __future__ import annotations


def _tmp_dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()
    return events


# ---- Arbeitsauftrag-Heuristik ---------------------------------------------------------

def test_work_order_positive():
    from core.agency.act import _looks_like_work_order as w
    assert w("Erstelle mir aus den 400 Leads auf dem Desktop 10 E-Mails fuer die besten Kunden")
    assert w("Recherchiere die Konkurrenz und bau mir eine Uebersicht als Datei")
    assert w("Schreib mir einen Bericht ueber das Projekt Luvex mit den wichtigsten Punkten")
    assert w("Analysiere die Liste und erstelle daraus 5 Vorschlaege")


def test_work_order_negative():
    from core.agency.act import _looks_like_work_order as w
    assert not w("wie geht's dir heute?")
    assert not w("was haeltst du von der Idee?")
    assert not w("danke dir!")
    assert not w("Erstellst du eigentlich Backups?")  # Frage, kein Imperativ-Match
    assert not w("erzaehl mal")  # zu kurz, keine Substanz


# ---- Auto-Plan-Routing ----------------------------------------------------------------

def test_auto_plan_routet_auftrag(monkeypatch, tmp_path):
    from core.agency import act
    events = _tmp_dbs(monkeypatch, tmp_path)
    seen: dict = {}

    def fake_plan(task, session_id=None, on_event=None, escalate=True):
        seen["task"], seen["escalate"] = task, escalate
        return "plan fertig"

    monkeypatch.setattr(act, "plan_and_execute", fake_plan)
    monkeypatch.setattr(act, "_AUTO_PLAN", True)

    out = act.act_chat("Erstelle mir aus den Leads 10 E-Mails und leg sie als Dateien ab", "s1")
    assert out == "plan fertig"
    assert "10 E-Mails" in seen["task"]
    assert seen["escalate"] is False  # Denker-Rang, NICHT das teure Eskalations-Modell
    assert "auto_plan" in [e["type"] for e in events.recent(20)]


def test_auto_plan_laesst_smalltalk_und_plan_praefix(monkeypatch, tmp_path):
    from core.agency import act
    _tmp_dbs(monkeypatch, tmp_path)
    seen: dict = {}

    def fake_plan(task, session_id=None, on_event=None, escalate=True):
        seen["task"], seen["escalate"] = task, escalate
        return "ok"

    monkeypatch.setattr(act, "plan_and_execute", fake_plan)
    # explizites plan: bleibt escalate=True
    act.act_chat("plan: grosse Sache bauen", "s2")
    assert seen["escalate"] is True

    # Smalltalk erreicht plan_and_execute nicht (wuerde sonst fake_plan treffen);
    # er laeuft in den Chat-Pfad -> wir fangen ihn VOR dem LLM ab.
    seen.clear()
    monkeypatch.setattr(act, "_cloud", lambda e, t="chat": True)
    monkeypatch.setattr(act, "_native_loop",
                        lambda *a, **k: "hi!")
    out = act.act_chat("wie geht's dir?", "s3")
    assert out == "hi!"
    assert not seen  # kein Auto-Plan


def test_auto_plan_abschaltbar(monkeypatch, tmp_path):
    from core.agency import act
    _tmp_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_AUTO_PLAN", False)
    monkeypatch.setattr(act, "plan_and_execute",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("darf nicht")))
    monkeypatch.setattr(act, "_cloud", lambda e, t="chat": True)
    monkeypatch.setattr(act, "_native_loop", lambda *a, **k: "direkt")
    out = act.act_chat("Erstelle mir aus den Leads 10 E-Mails als Dateien", "s4")
    assert out == "direkt"


# ---- Rueckfrage-Killer ---------------------------------------------------------------

def test_promise_re_erkennt_rueckfragen():
    from core.agency.act import _looks_like_promise as p
    assert p("Soll ich das Projekt Luvex jetzt anlegen?")
    assert p("Moechtest du, dass ich die E-Mails schreibe?")
    assert p("Bestaetige kurz, dann lege ich los.")
    assert p("Darf ich die Dateien auf dem Desktop anlegen?")
    assert not p("Fertig: 10 Dateien liegen im Ordner, alle Tests gruen. Details unten." + " x" * 30)


# ---- Beweispflicht-Stempel ------------------------------------------------------------

def test_claim_stamp_fehlende_datei(monkeypatch, tmp_path):
    from core.agency import act
    events = _tmp_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_CLAIM_CHECK", True)

    text = "Erledigt! Ich habe 10 E-Mails erstellt und unter `~/Desktop/luvex/mail1.md` abgelegt."
    monkeypatch.setenv("HOME", str(tmp_path))  # leeres Zuhause -> Datei existiert nicht
    out = act._claim_stamp(text, session_id="s")
    assert "BEWEISPFLICHT" in out
    assert "claim_check_failed" in [e["type"] for e in events.recent(10)]


def test_claim_stamp_existierende_datei(monkeypatch, tmp_path):
    from core.agency import act
    _tmp_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_CLAIM_CHECK", True)
    f = tmp_path / "Desktop" / "luvex" / "mail1.md"
    f.parent.mkdir(parents=True)
    f.write_text("hallo", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    text = "Ich habe die Mail erstellt: `~/Desktop/luvex/mail1.md`"
    assert "BEWEISPFLICHT" not in act._claim_stamp(text, session_id="s")


def test_claim_stamp_nur_bei_erzeugungs_behauptung(monkeypatch, tmp_path):
    from core.agency import act
    monkeypatch.setattr(act, "_CLAIM_CHECK", True)
    # Pfad erwaehnt, aber nichts behauptet ("schau dir mal an") -> kein Check noetig...
    # Unser Gate ist das Verb: ohne erstellt/gespeichert/... wird gar nicht geprueft.
    text = "Du koenntest `~/Desktop/gibtsnicht/datei.md` als Vorlage nehmen."
    assert act._claim_stamp(text, session_id="s") == text
    # Werkzeugnamen in Backticks sind keine Pfade
    text2 = "Ich habe das mit `code_suche` erledigt und die Ergebnisse gespeichert."
    assert act._claim_stamp(text2, session_id="s") == text2


def test_claim_stamp_relative_pfade_gegen_root(monkeypatch, tmp_path):
    from core.agency import act
    _tmp_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_CLAIM_CHECK", True)
    # relative Behauptung, Datei existiert im ROOT -> kein Stempel (README.md existiert)
    text = "Ich habe die Notiz in `docs/KIRA-IST.md` gespeichert."
    assert "BEWEISPFLICHT" not in act._claim_stamp(text, session_id="s")
