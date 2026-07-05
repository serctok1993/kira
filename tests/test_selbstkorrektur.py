"""Selbstkorrektur-Reflex im Code-Modus: ein ROTER Edit loest EINEN gezielten Retry aus.

Ein schwaches Modell (GLM/DeepSeek) gibt gern beim ersten Fehlschlag auf. Geht ein Edit ROT
(Syntax/Test/nicht eindeutig -> zurueckgerollt) und wird im Schritt nicht mehr gruen, zwingt
der Lauf EINEN Retry mit Strategiewechsel; bleibt es rot, steht das EHRLICH im Ergebnis.
"""
from __future__ import annotations


def _db(monkeypatch, tmp_path):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()


# ---- Tracker ---------------------------------------------------------------------------

def test_edit_fail_tracker():
    from core.agency import act
    act._edit_fail_clear("t")
    act._edit_fail_record("t", "edit_datei", "Fehlgeschlagen: SEARCH nicht eindeutig")
    assert "nicht eindeutig" in act._edit_fail_get("t")
    act._edit_fail_record("t", "edit_datei", "OK — x.py geaendert (+1 −0).")
    assert act._edit_fail_get("t") == ""            # gruener Edit loescht den Marker
    act._edit_fail_record("t", "edit_datei", "Fehlgeschlagen: Syntaxfehler -> zurueckgerollt")
    assert act._edit_fail_get("t") != ""
    act._edit_fail_record("t", "read_file", "Fehlgeschlagen: egal")  # kein Edit-Werkzeug
    assert act._edit_fail_get("t") != ""            # unveraendert (nicht von read_file beeinflusst)
    act._edit_fail_clear("t")


def test_guard_registriert_roten_edit(monkeypatch, tmp_path):
    from core.agency import act
    from core.agency.tools import registry
    _db(monkeypatch, tmp_path)
    act._edit_fail_clear("g1")

    class T:
        func = staticmethod(lambda **kw: "Fehlgeschlagen: nicht eindeutig")
    monkeypatch.setattr(registry, "get", lambda n: T())
    act._run_tool_guarded("edit_datei", T(), {"pfad": "x.py", "suche": "a", "ersetze": "b"}, "g1")
    assert "nicht eindeutig" in act._edit_fail_get("g1")
    act._edit_fail_clear("g1")


# ---- Verdrahtung im Plan-Lauf ----------------------------------------------------------

def _wire(monkeypatch):
    from core.agency import act
    from core.kernel import llm_router
    from core.mind import reflection
    monkeypatch.setattr(act, "_scout", lambda *a, **k: "")
    monkeypatch.setattr(act, "_make_plan",
                        lambda t, sid, esc=True: [{"schritt": "editiere x.py", "rang": "arbeiter"}])
    monkeypatch.setattr(act, "_code_review_run", lambda *a, **k: "")
    monkeypatch.setattr(act, "_endabnahme", lambda *a, **k: "")
    monkeypatch.setattr(llm_router, "complete", lambda *a, **k: {"text": "fertig"})
    monkeypatch.setattr(reflection, "reflect_on", lambda *a, **k: {"lessons": []})


def test_roter_edit_loest_genau_einen_retry(monkeypatch, tmp_path):
    from core.agency import act
    _db(monkeypatch, tmp_path)
    _wire(monkeypatch)
    calls = {"n": 0, "tasks": []}

    def fake_act(task, session_id=None, **k):
        calls["n"] += 1
        calls["tasks"].append(task)
        if calls["n"] == 1:
            act._EDIT_FAIL[session_id or "_"] = "Fehlgeschlagen: nicht eindeutig"  # roter Edit
            return {"text": "hab es versucht"}
        act._EDIT_FAIL.pop(session_id or "_", None)                                 # Retry -> gruen
        return {"text": "jetzt sauber angewendet"}

    monkeypatch.setattr(act, "act", fake_act)
    out = act.plan_and_execute("mach x dunkel", session_id="sk1", code_review=True)
    assert calls["n"] == 2                                   # genau EIN Korrektur-Retry
    assert "STRATEGIE" in calls["tasks"][1]                  # Retry traegt den Strategie-Hinweis
    assert "weiterhin rot" not in out                        # nach dem Fix kein Alarm


def test_bleibt_rot_wird_ehrlich_gemeldet(monkeypatch, tmp_path):
    from core.agency import act
    _db(monkeypatch, tmp_path)
    _wire(monkeypatch)
    calls = {"n": 0}

    def fake_act(task, session_id=None, **k):
        calls["n"] += 1
        act._EDIT_FAIL[session_id or "_"] = "Fehlgeschlagen: Syntaxfehler -> zurueckgerollt"  # bleibt rot
        return {"text": "versucht"}

    monkeypatch.setattr(act, "act", fake_act)
    out = act.plan_and_execute("mach x", session_id="sk2", code_review=True)
    assert calls["n"] == 2                                   # nur EIN Retry, dann Schluss
    assert "Nicht sauber angewendet" in out                 # ehrlich im Endergebnis statt falscher Erfolg
    act._edit_fail_clear("sk2")


def test_gruener_edit_kein_retry(monkeypatch, tmp_path):
    from core.agency import act
    _db(monkeypatch, tmp_path)
    _wire(monkeypatch)
    calls = {"n": 0}

    def fake_act(task, session_id=None, **k):
        calls["n"] += 1
        act._EDIT_FAIL.pop(session_id or "_", None)          # alles gruen
        return {"text": "erledigt"}

    monkeypatch.setattr(act, "act", fake_act)
    act.plan_and_execute("mach x", session_id="sk3", code_review=True)
    assert calls["n"] == 1                                   # kein Retry ohne roten Edit
