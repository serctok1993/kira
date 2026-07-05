"""Erkundungsphase im Code-Modus: aus lockeren Worten die betroffenen Dateien finden.

Vor der Planung sucht Kira (code:-Laeufe) die wahrscheinlich betroffenen Projektdateien und
gibt sie dem Planer mit — so haengt der Plan an echten Dateien statt geraten. Raist nie.
"""
from __future__ import annotations


def _db(monkeypatch, tmp_path):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "s.db"))
    events.init_db()


# ---- Suchbegriffe -----------------------------------------------------------------------

def test_scout_terms_llm_plus_aufgabe(monkeypatch):
    from core.agency import act
    monkeypatch.setattr(act, "_complete_resilient",
                        lambda *a, **k: {"text": "loadHud\nhud-assist\n- setBg"})
    terms = act._scout_terms("aendere die Hintergrundfarbe im loadHud", "s1")
    assert "loadHud" in terms and "hud-assist" in terms   # aus dem Modell
    assert "Hintergrundfarbe" in terms                    # distinktives Wort aus der Aufgabe
    assert "die" not in [t.lower() for t in terms]        # Stoppwort raus
    assert len(terms) <= 6                                # gedeckelt


def test_scout_terms_ohne_llm(monkeypatch):
    from core.agency import act
    monkeypatch.setattr(act, "_complete_resilient",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kein Modell")))
    terms = act._scout_terms("repariere die Voice Ausgabe im telegram_bot", "s1")
    assert "telegram_bot" in terms and "Voice" in terms   # Fallback: Aufgaben-Woerter


# ---- Erkundung --------------------------------------------------------------------------

def test_scout_findet_dateien(monkeypatch, tmp_path):
    from core.agency import act
    from core.agency.tools import code_tools
    _db(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_scout_terms", lambda task, sid: ["bg"])
    monkeypatch.setattr(code_tools, "code_suche",
                        lambda m, *a, **k: "core/api/ui/css.py:12: background:#000\ncore/x.py:3: bg=1")
    monkeypatch.setattr(code_tools, "datei_finden", lambda m: "")
    evs = []
    block = act._scout("mach es dunkel", "s1", False, lambda e: evs.append(e))
    assert "ERKUNDUNG" in block and "core/api/ui/css.py" in block
    assert any(e.get("name") == "Erkundung" for e in evs)


def test_scout_leer_ohne_treffer(monkeypatch, tmp_path):
    from core.agency import act
    from core.agency.tools import code_tools
    _db(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_scout_terms", lambda task, sid: ["zzz"])
    monkeypatch.setattr(code_tools, "code_suche", lambda m, *a, **k: "Keine Treffer.")
    monkeypatch.setattr(code_tools, "datei_finden", lambda m: "")
    assert act._scout("x", "s1", False, lambda e: None) == ""


def test_scout_raist_nie(monkeypatch, tmp_path):
    from core.agency import act
    from core.agency.tools import code_tools
    _db(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_scout_terms", lambda task, sid: ["a"])
    monkeypatch.setattr(code_tools, "code_suche",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert act._scout("x", "s1", False, lambda e: None) == ""


# ---- Verdrahtung: nur code:-Laeufe, Ergebnis geht in die Planung -------------------------

def test_scout_nur_bei_code_review_und_fuettert_plan(monkeypatch, tmp_path):
    from core.agency import act
    from core.kernel import llm_router
    from core.mind import reflection
    _db(monkeypatch, tmp_path)
    seen: dict = {}
    monkeypatch.setattr(act, "_scout", lambda task, sid, esc, emit: "SCOUTBLOCK\n\n")
    monkeypatch.setattr(act, "_make_plan", lambda t, sid, esc=True: (seen.update(plan_in=t), [])[1])
    monkeypatch.setattr(act, "_code_review_run", lambda *a, **k: "")
    monkeypatch.setattr(act, "_endabnahme", lambda *a, **k: "")
    monkeypatch.setattr(llm_router, "complete", lambda *a, **k: {"text": "fertig"})
    monkeypatch.setattr(reflection, "reflect_on", lambda *a, **k: {"lessons": []})

    act.plan_and_execute("mach das dunkel", session_id="s1", code_review=True)
    assert "SCOUTBLOCK" in seen["plan_in"]        # Erkundung fliesst in den Plan

    # ohne code_review (plain plan:) KEINE Erkundung
    seen.clear()
    monkeypatch.setattr(act, "_scout",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Scout ohne code:")))
    act.plan_and_execute("normaler plan", session_id="s2", code_review=False)
    assert "SCOUTBLOCK" not in seen.get("plan_in", "")
