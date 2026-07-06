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


# ---- Trace-Upgrade (Hermes-Stil): aufklappbares Denken, Neon-Status, HTML-sicher ----

def test_render_trace_hermes_html():
    from core.agency.connectors import telegram_bot as tb
    out = tb._render_trace(None, "ich pruefe zuerst die Quelle", ["📖 lese: /pfad"], "Denkt", "⠹", True)
    assert "<blockquote expandable>" in out and "ich pruefe zuerst die Quelle" in out  # aufklappbares Denken
    assert "<b>Denkt</b>" in out and "⠹" in out                                        # Phase (fett) + Spinner
    assert "🧠" not in out and "💜" not in out and "💗" not in out                      # weder Gehirn noch Herz


def test_render_trace_escapes_html():
    # Denk-/Pfad-Text mit < & > darf die HTML-Nachricht nicht sprengen (sonst editiert Telegram nicht)
    from core.agency.connectors import telegram_bot as tb
    out = tb._render_trace(None, "wenn a<b & c>d dann <script>", [], "p", "·", True)
    assert "<script>" not in out and "&lt;script&gt;" in out and "&amp;" in out


def test_denken_toggle(tmp_path, monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    monkeypatch.setattr(tb, "_DENKEN_FILE", tmp_path / "denken.json")
    assert tb._denken_on(42) is False
    tb._denken_set(42, True)
    assert tb._denken_on(42) is True and tb._denken_on(43) is False   # nur diese Session
    tb._denken_set(42, False)
    assert tb._denken_on(42) is False


# ---- Premium-Extras: Effekt-Toggle (Default an) + Custom-Emoji-Glow ----

def test_effekt_toggle_default_an(tmp_path, monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    monkeypatch.setattr(tb, "_EFFEKT_FILE", tmp_path / "eff.json")
    assert tb._effekt_on(7) is True          # Default: an (Premium-Flair)
    tb._effekt_set(7, False)
    assert tb._effekt_on(7) is False
    tb._effekt_set(7, True)
    assert tb._effekt_on(7) is True
    assert "feuer" in tb._EFFECTS and tb._EFFECTS["feuer"].isdigit()   # echte message_effect_id


def test_custom_emoji_learn_und_glow(tmp_path, monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    monkeypatch.setattr(tb, "_EMOJI_FILE", tmp_path / "em.json")
    assert tb._lead_emoji(0) == ""                       # ohne gelernte Emoji: sauber, kein Glow
    assert tb._emoji_learn(["111", "222"]) == 2 and tb._emoji_ids() == ["111", "222"]
    lead = tb._lead_emoji(1)                             # rotiert je Takt -> ids[1]
    assert '<tg-emoji emoji-id="222">' in lead and "</tg-emoji>" in lead
    out = tb._render_trace(None, "", [], "Denkt", "⠹", True, lead)
    assert "<tg-emoji" in out and "<b>Denkt</b>" in out   # Glow im Status
