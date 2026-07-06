"""S12: Echtes Thinking sichtbar machen — auch fuer Cloud-Modelle (GLM & Co.).

Denk-Modelle liefern ihren Gedankenstrom entweder inline als <think>...</think> ODER
im dedizierten Feld reasoning_content. Beides faengt complete() jetzt ein und gibt es als
`reasoning` zurueck; _native_loop reicht es als think-Event durch -> Telegram (💭) UND
Cockpit zeigen das echte Denken statt eines leeren „nachdenken…"-Pulses. Offline.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.kernel import events, llm_router
from core.mind.memory import store as memory


def _use_tmp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "state.db")
    for mod in (memory, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    memory.init_memory()


# ---- _think_content: Inhalt der <think>-Bloecke (nicht nur strippen) -------------------

def test_think_content_extrahiert_inline():
    assert llm_router._think_content("<think>erst pruefen, dann handeln</think>Antwort") \
        == "erst pruefen, dann handeln"


def test_think_content_offenes_tag():
    # abgeschnittener Stream ohne schliessendes Tag -> Rest ab <think>
    assert llm_router._think_content("<think>ich ueberlege noch") == "ich ueberlege noch"


def test_think_content_leer_ohne_tag():
    assert llm_router._think_content("nur normale Antwort") == ""


# ---- complete() gibt reasoning zurueck — aus beiden Quellen ----------------------------

def _fake_resp(content: str, reasoning_content=None, reasoning=None):
    msg = SimpleNamespace(content=content, tool_calls=None)
    if reasoning_content is not None:
        msg.reasoning_content = reasoning_content
    if reasoning is not None:
        msg.reasoning = reasoning
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


def _patch_llm(monkeypatch, resp):
    monkeypatch.setattr(llm_router, "_completion", lambda **kw: resp)
    monkeypatch.setattr(llm_router.litellm, "completion_cost", lambda **kw: 0.001)
    # Cloud-Budget-Bremse ausser Kraft — wir testen nur die Reasoning-Erfassung.
    from core.governance import treasury
    monkeypatch.setattr(treasury, "can_spend", lambda *a, **k: (True, ""))


def test_complete_faengt_reasoning_content(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    _patch_llm(monkeypatch, _fake_resp("Die Hauptstadt ist Berlin.",
                                       reasoning_content="Frage nach Hauptstadt -> Deutschland -> Berlin."))
    res = llm_router.complete([{"role": "user", "content": "Hauptstadt?"}], task_type="reason")
    assert res["reasoning"] == "Frage nach Hauptstadt -> Deutschland -> Berlin."
    assert res["text"] == "Die Hauptstadt ist Berlin."          # sichtbare Antwort unberuehrt


def test_complete_faengt_inline_think(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    _patch_llm(monkeypatch, _fake_resp("<think>kurz nachgedacht</think>Fertig."))
    res = llm_router.complete([{"role": "user", "content": "x"}], task_type="reason")
    assert res["reasoning"] == "kurz nachgedacht"
    assert res["text"] == "Fertig."                              # <think> raus aus der Antwort


def test_complete_kein_reasoning_bleibt_none(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    _patch_llm(monkeypatch, _fake_resp("Nur eine schlichte Antwort."))
    res = llm_router.complete([{"role": "user", "content": "x"}], task_type="chat")
    assert res["reasoning"] is None                              # kein Denk-Feld -> kein Schein-Reasoning


# ---- _native_loop reicht reasoning als think-Event durch (Telegram + Cockpit) ---------

def test_native_loop_emittiert_think(monkeypatch, tmp_path):
    from core.agency import act
    _use_tmp_db(monkeypatch, tmp_path)

    # complete liefert Reasoning + KEINE tool_calls -> Loop endet sofort mit der Antwort.
    def fake_resilient(*a, **k):
        return {"text": "Antwort steht.", "tool_calls": [],
                "reasoning": "ich pruefe die Fakten und formuliere knapp"}
    monkeypatch.setattr(act, "_complete_resilient", fake_resilient)

    seen: list[dict] = []
    out = act._native_loop([{"role": "user", "content": "frag"}], "sys", "sess",
                           False, emit=seen.append, max_steps=3)
    assert out == "Antwort steht."
    thinks = [e for e in seen if e["kind"] == "think"]
    assert thinks and "pruefe die Fakten" in thinks[0]["text"]


def test_native_loop_dedupe_gleiches_reasoning(monkeypatch, tmp_path):
    from core.agency import act
    _use_tmp_db(monkeypatch, tmp_path)

    calls = {"n": 0}

    def fake_resilient(*a, **k):
        # erster Zug: ein Tool -> Schleife dreht; danach Final. Beide Male gleiches Reasoning.
        calls["n"] += 1
        if calls["n"] == 1:
            return {"text": "", "tool_calls": [{"id": "c1", "name": "noop", "args": {}}],
                    "reasoning": "identischer denk-strom"}
        return {"text": "fertig", "tool_calls": [], "reasoning": "identischer denk-strom"}

    monkeypatch.setattr(act, "_complete_resilient", fake_resilient)
    monkeypatch.setattr(act.registry, "get", lambda n: (lambda **kw: "ok"))
    monkeypatch.setattr(act, "_run_tool_guarded", lambda *a, **k: "ok")

    seen: list[dict] = []
    act._native_loop([{"role": "user", "content": "frag"}], "sys", "sess",
                     False, emit=seen.append, max_steps=3)
    thinks = [e for e in seen if e["kind"] == "think"]
    assert len(thinks) == 1                                       # gleiches Reasoning nur EINMAL


# ---- Telegram rendert den Denk-Strom (💭) ---------------------------------------------

def test_telegram_trace_zeigt_reasoning():
    from core.agency.connectors import telegram_bot
    txt = telegram_bot._render_trace(None, "ich waege die Optionen ab", [], "denkt", "·", True)
    assert "💭" in txt and "waege die Optionen" in txt
