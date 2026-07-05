"""Coding-Workspace: geteiltes Gedaechtnis (code:/plan: erbt den Brainstorm),
Diff-Review-Bezugspunkt (git diff head0), Telegram /code + /work.
"""
from __future__ import annotations


def _tmp_dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()
    return store


# ---- Geteiltes Gedaechtnis --------------------------------------------------------------

def test_dialog_prefix_formatiert_und_leer():
    from core.agency import act
    assert act._dialog_prefix([]) == ""
    assert act._dialog_prefix([{"role": "user", "text": "  "}]) == ""  # nur Leeres -> leer
    out = act._dialog_prefix([{"role": "user", "text": "Baue X"},
                              {"role": "partner", "text": "Verstanden"}])
    assert "GESPRAECH BISHER" in out
    assert "Sergen: Baue X" in out and "Kira: Verstanden" in out
    assert out.rstrip().endswith("---")


def test_dialog_prefix_gedeckelt():
    from core.agency import act
    lang = [{"role": "user", "text": "x" * 5000}]
    out = act._dialog_prefix(lang)
    assert "gekuerzt" in out and len(out) < 5000


def test_code_erbt_den_chat_verlauf(monkeypatch, tmp_path):
    """Der Kern-Bug: brainstorm im Chat -> code: kennt ihn jetzt."""
    store = _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    sid = "ws-1"
    store.remember("Das Dashboard liegt im Cockpit unter Config", role="user", session_id=sid)
    store.remember("Alles klar, verstanden", role="partner", session_id=sid)
    seen: dict = {}

    def fake_plan(task, session_id=None, on_event=None, escalate=True, code_review=False):
        seen["task"] = task
        return "fertig"

    monkeypatch.setattr(act, "plan_and_execute", fake_plan)
    act.act_chat("code: aendere den Knopf oben", session_id=sid)

    assert "GESPRAECH BISHER" in seen["task"]          # Verlauf ist drin
    assert "Dashboard liegt im Cockpit" in seen["task"]  # der konkrete Brainstorm
    assert "aendere den Knopf oben" in seen["task"]     # der Auftrag
    assert "CODING-REGELN" in seen["task"]              # code: haengt sie weiter an


def test_plan_ohne_verlauf_bleibt_schlank(monkeypatch, tmp_path):
    _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    seen: dict = {}
    monkeypatch.setattr(act, "plan_and_execute",
                        lambda task, **kw: seen.update(task=task) or "ok")
    act.act_chat("plan: neue Sache", session_id="ws-2")  # frische Session, kein Verlauf
    assert "GESPRAECH BISHER" not in seen["task"]        # nichts erfunden
    assert seen["task"].startswith("AUFTRAG:")
    assert "CODING-REGELN" not in seen["task"]           # plan: haengt sie NICHT an


# ---- Diff-Review-Bezugspunkt ------------------------------------------------------------

def test_review_nutzt_git_diff_head0(monkeypatch, tmp_path):
    _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    from core.kernel import llm_router
    calls: list = []

    def fake_git(*args):
        calls.append(args)
        return "diff --git a/x.py b/x.py\n+neu" if args[:1] == ("diff",) else "HEAD0SHA"

    monkeypatch.setattr(act, "_git_out", fake_git)
    monkeypatch.setattr(llm_router, "complete",
                        lambda *a, **k: {"text": "URTEIL: OK", "cost_usd": 0.0, "model": "f",
                                         "fell_back": False, "latency_s": 0.0,
                                         "escalated": False, "tool_calls": []})

    note = act._code_review_run("Auftrag", "HEAD0SHA", "rv-1", False, lambda ev_: None)

    # genau EIN, ehrlicher Bezugspunkt: 'git diff HEAD0SHA' (head0 -> Arbeitsbaum)
    assert ("diff", "HEAD0SHA") in calls
    assert not any(a == ("diff",) for a in calls)   # kein loser git-diff mehr (Alt-Reste-Leck)
    assert "bestanden" in note


# ---- Telegram /code + /work -------------------------------------------------------------

def test_telegram_code_und_work_routen(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    routed: list = []
    monkeypatch.setattr(tb, "_agentic_reply",
                        lambda client, chat_id, sid, text: routed.append((sid, text)))
    monkeypatch.setattr(tb, "_send", lambda *a, **k: None)

    tb._handle_command(None, 42, "/code fixe den Bug in act.py")
    tb._handle_command(None, 42, "/work recherchiere 20 Leads")

    assert routed[0] == ("telegram-42", "code: fixe den Bug in act.py")
    assert routed[1] == ("telegram-42", "/work recherchiere 20 Leads")


def test_telegram_code_ohne_text_zeigt_hilfe(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    msgs: list = []
    monkeypatch.setattr(tb, "_send", lambda client, chat_id, text, **k: msgs.append(text))
    monkeypatch.setattr(tb, "_agentic_reply", lambda *a, **k: (_ for _ in ()).throw(AssertionError("darf nicht routen")))
    tb._handle_command(None, 42, "/code")
    assert msgs and "Nutzung" in msgs[0]
