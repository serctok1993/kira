"""Steuerpult: des Nutzers Riegel ueber die Schwarmintelligenz.

Deterministische Chat-Befehle /delegiere + /schwarm (kein LLM noetig),
/api/steuer (Rang-Tafel + Regler) und die Cockpit-Marker.
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


# ---- /delegiere + /schwarm: deterministisch, Rang waehlt WURZEL -----------------------

def test_swarm_command_hilfe_ohne_args():
    from core.agency import act
    out = act._handle_swarm_command("/delegiere", None)
    assert "/delegiere" in out and "/schwarm" in out and "reflex" in out


def test_delegiere_routet_rang_und_auftrag(monkeypatch):
    from core.agency import act
    from core.agency.tools import delegate_tools
    seen: dict = {}
    monkeypatch.setattr(delegate_tools, "_delegiere",
                        lambda auftrag, rang, sid, schritte="": seen.update(a=auftrag, r=rang) or "ok")
    act._handle_swarm_command("/delegiere denker Fasse das Handbuch zusammen", "s1")
    assert seen == {"a": "Fasse das Handbuch zusammen", "r": "denker"}
    act._handle_swarm_command("/delegiere Recherchiere Friseure Berlin", "s1")
    assert seen["r"] == "arbeiter"  # kein Rang angegeben -> Standard


def test_schwarm_pipe_syntax(monkeypatch):
    from core.agency import act
    from core.agency.tools import delegate_tools
    seen: dict = {}
    monkeypatch.setattr(delegate_tools, "schwarm",
                        lambda vorlage, liste, rang="arbeiter", session_id="":
                        seen.update(v=vorlage, l=liste, r=rang) or "ok")
    act._handle_swarm_command("/schwarm reflex Recherchiere kurz: {item} | Firma A | Firma B", "s2")
    assert seen["v"] == "Recherchiere kurz: {item}"
    assert seen["l"] == "Firma A\nFirma B"
    assert seen["r"] == "reflex"
    # ohne Items -> klare Anleitung statt Absturz
    out = act._handle_swarm_command("/schwarm nur eine Vorlage ohne Liste", "s2")
    assert "Items" in out


def test_swarm_command_raist_nie(monkeypatch):
    from core.agency import act
    from core.agency.tools import delegate_tools
    monkeypatch.setattr(delegate_tools, "_delegiere",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaputt")))
    out = act._handle_swarm_command("/delegiere denker x", "s3")
    assert "fehlgeschlagen" in out


def test_act_chat_faengt_delegiere_in_jedem_modus(monkeypatch, tmp_path):
    """Der Riegel darf von KEINEM Modus verschluckt werden (wie /model)."""
    events = _tmp_dbs(monkeypatch, tmp_path)
    from core.agency import act
    from core.agency.tools import delegate_tools
    monkeypatch.setattr(delegate_tools, "_delegiere", lambda a, r, s, schritte="": f"[{r}] erledigt")

    for praefix in ("", "code: ", "plan: ", "/work "):
        out = act.act_chat(praefix + "/delegiere reflex sag hallo", f"st-{praefix.strip(': /') or 'plain'}")
        assert "[reflex] erledigt" in out, f"verschluckt bei Praefix {praefix!r}"
    types = [e["type"] for e in events.recent(50)]
    assert "swarm_command" in types
    assert "user_message" not in types  # kein normaler Chat-Fluss


# ---- /api/steuer -----------------------------------------------------------------------

def test_api_steuer_shape(monkeypatch):
    from core.api import server
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda t="default", escalate=False: ("ollama_chat/qwen3.5:9b", False))
    r = server.api_steuer()
    raenge = {x["rang"]: x for x in r["raenge"]}
    assert set(raenge) == {"reflex", "arbeiter", "denker", "richter"}
    assert raenge["reflex"]["rolle"] == "classify"
    assert raenge["richter"]["rolle"] == "escalation"
    for x in r["raenge"]:
        assert x["real"] == "ollama_chat/qwen3.5:9b" and x["schritte"] >= 1
    assert r["schwarm_max"] >= 1 and r["max_kosten_eur"] > 0


def test_api_steuer_raist_nie(monkeypatch):
    from core.api import server
    from core.kernel import llm_router
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda t="default", escalate=False: (_ for _ in ()).throw(RuntimeError("weg")))
    r = server.api_steuer()  # faellt auf 'gesetzt' zurueck statt zu crashen
    assert len(r["raenge"]) == 4


def test_regler_whitelist_und_ui_marker():
    from core.api.server import _CONFIG_WHITELIST
    for p in ("agency.delegate.schritte.reflex", "agency.delegate.schritte.richter",
              "agency.delegate.schwarm_max", "agency.delegate.max_kosten_eur"):
        assert p in _CONFIG_WHITELIST
    from core.api.ui.script import SCRIPT
    from core.api.ui.views import VIEWS
    assert "loadSteuer" in SCRIPT and "st-cmd-go" in SCRIPT
    assert 'id="v-steuer"' in VIEWS and 'data-s="steuer"' in VIEWS
    assert "st-cmd-rang" in VIEWS and "st-regler-save" in VIEWS


def test_handbuch_dokumentiert_steuerpult():
    from core.config import ROOT
    hb = (ROOT / "docs" / "HANDBUCH.md").read_text(encoding="utf-8")
    assert "/delegiere" in hb and "/schwarm" in hb and "Steuerpult" in hb
