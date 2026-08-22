"""Entfesselung II (22.08.): Zwei-Rollen-Betrieb — models.kopf/ausfuehrer kollabieren
die 5-Etagen-Kaskade. Kopf = Planung/Urteil (escalate, 'plan'), Ausfuehrer = Rest.
Ohne die Keys bleibt das historische Routing byte-gleich (Abwaertskompatibilitaet)."""
from __future__ import annotations

from core.kernel import llm_router


def _cfg(monkeypatch, models: dict):
    basis = {"local_fallback": "ollama_chat/lokal", "default": "alt/default",
             "routing": {"chat": "alt/chat", "reason": "alt/reason"},
             "escalation_model": "alt/eskalation", **models}
    monkeypatch.setattr(llm_router, "CONFIG", {"models": basis})
    monkeypatch.setattr(llm_router, "_has_key", lambda m: True)
    monkeypatch.delenv("KIRA_FORCE_MODEL", raising=False)


def test_zweirollen_kopf_fuer_plan_und_eskalation(monkeypatch):
    _cfg(monkeypatch, {"kopf": "stark/kopf", "ausfuehrer": "flink/hand"})
    assert llm_router.resolve_model("plan") == ("stark/kopf", False)
    assert llm_router.resolve_model("reason", escalate=True) == ("stark/kopf", False)
    for tt in ("chat", "reason", "classify", "worker", "bulk", "irgendwas"):
        assert llm_router.resolve_model(tt) == ("flink/hand", False), tt


def test_zweirollen_ein_modell_fuer_alles(monkeypatch):
    """Der Qwen-3.8-Zielbetrieb: EIN Modell traegt beide Rollen."""
    _cfg(monkeypatch, {"kopf": "ollama_chat/qwen3.8", "ausfuehrer": "ollama_chat/qwen3.8"})
    assert llm_router.resolve_model("chat") == ("ollama_chat/qwen3.8", False)
    assert llm_router.resolve_model("plan", escalate=True) == ("ollama_chat/qwen3.8", False)


def test_zweirollen_eine_rolle_reicht(monkeypatch):
    """Nur ausfuehrer gesetzt -> traegt auch die Kopf-Rolle (und umgekehrt)."""
    _cfg(monkeypatch, {"ausfuehrer": "flink/hand"})
    assert llm_router.resolve_model("plan", escalate=True) == ("flink/hand", False)
    _cfg(monkeypatch, {"kopf": "stark/kopf"})
    assert llm_router.resolve_model("chat") == ("stark/kopf", False)


def test_ohne_zweirollen_bleibt_das_alte_routing(monkeypatch):
    _cfg(monkeypatch, {})
    assert llm_router.resolve_model("chat") == ("alt/chat", False)
    assert llm_router.resolve_model("reason", escalate=True) == ("alt/eskalation", False)


def test_force_model_schlaegt_auch_die_zwei_rollen(monkeypatch):
    _cfg(monkeypatch, {"kopf": "stark/kopf", "ausfuehrer": "flink/hand"})
    monkeypatch.setenv("KIRA_FORCE_MODEL", "bench/modell")
    assert llm_router.resolve_model("plan", escalate=True) == ("bench/modell", False)


def test_identity_schlank_traegt_arbeitsbereichs_freiheit(monkeypatch):
    """Der Handlungs-Pfad nutzt im Schlank-Modus den Kompakt-Kern — ohne Kanon,
    ohne Zoeger-Ton, mit direkter Arbeitsweise."""
    from core.agency import act
    from core.mind import agent

    monkeypatch.setattr(agent, "_schlank_aktiv", lambda: True)
    p = act._identity()
    assert "ohne Rueckfrage-Reflex" in p and "Not-Aus" in p
    assert "# DEINE VERFASSUNG" not in p and "# DEINE SEELE" not in p
    monkeypatch.setattr(agent, "_schlank_aktiv", lambda: False)
    voll = act._identity()
    assert "# DEINE VERFASSUNG" in voll and len(p) < len(voll)
