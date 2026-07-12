"""Outbound-Firewall: mit KIRA_NO_OUTBOUND (Benchmark/Sandbox) reicht KEINE Aktion nach aussen —
keine Mail, kein Telegram, kein Cloud-LLM-Spend, keine gated Aussen-Aktion, keine bezahlten
Konnektoren. Standard AUS -> Live + normale Suite unveraendert.
"""
from __future__ import annotations

import httpx


def test_praedikat_outbound_blocked(monkeypatch):
    import core.config as cfg
    monkeypatch.delenv("KIRA_NO_OUTBOUND", raising=False)
    assert cfg.outbound_blocked() is False
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    assert cfg.outbound_blocked() is True


def test_mail_still(monkeypatch):
    from core.agency.connectors import mail
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    assert mail.enabled() is False


def test_gate_dry_run(monkeypatch, tmp_path):
    from core.kernel import events
    from core.governance import gate
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    ran: list = []
    out = gate.guarded("external", "Repo anlegen", "detail", execute=lambda: ran.append(1))
    assert "TESTMODUS" in out and ran == []  # protokolliert, aber NICHT ausgefuehrt


def test_telegram_notify_still(monkeypatch):
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    posted: list = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: posted.append(1))
    from core.agency.missions import runner, cron
    from core.agency.connectors import news_monitor
    runner._notify("x")
    cron._notify("x")
    news_monitor._notify("x")
    assert posted == []  # kein einziger Telegram-POST


def test_llm_kein_cloud_spend(monkeypatch):
    from core.kernel import llm_router
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    monkeypatch.delenv("KIRA_ALLOW_LLM", raising=False)
    # so tun, als waere ein Cloud-Modell geroutet
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda t="default", escalate=False: ("openrouter/z-ai/glm-5.2", False))
    seen: dict = {}

    def _stop(m):
        seen["model"] = m
        raise RuntimeError("stop-nach-Modellwahl")

    monkeypatch.setattr(llm_router, "_provider_config", _stop)
    try:
        llm_router.complete([{"role": "user", "content": "hi"}], task_type="reason")
    except Exception:
        pass
    assert seen["model"] == llm_router.CONFIG["models"]["local_fallback"]  # aufs lokale 0-EUR-Modell gezwungen


def test_llm_escape_mit_allow(monkeypatch):
    from core.kernel import llm_router
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    monkeypatch.setenv("KIRA_ALLOW_LLM", "1")  # bewusster Ausweg
    monkeypatch.setattr(llm_router, "resolve_model",
                        lambda t="default", escalate=False: ("openrouter/z-ai/glm-5.2", False))
    seen: dict = {}

    def _stop(m):
        seen["model"] = m
        raise RuntimeError("stop")

    monkeypatch.setattr(llm_router, "_provider_config", _stop)
    try:
        llm_router.complete([{"role": "user", "content": "hi"}], task_type="reason")
    except Exception:
        pass
    assert seen["model"] == "openrouter/z-ai/glm-5.2"  # mit KIRA_ALLOW_LLM bleibt Cloud


def test_bezahlte_konnektoren_still(monkeypatch):
    monkeypatch.setenv("KIRA_NO_OUTBOUND", "1")
    from core.agency.connectors import tts
    assert tts.enabled() is False
    from core.agency.mcp import registry_bridge
    registry_bridge.init_background()  # spawnt keinen npx-Prozess, wirft nicht


def test_firewall_aus_default(monkeypatch):
    """Ohne Flag ist die Firewall inert (Live + normale Suite unveraendert)."""
    import core.config as cfg
    monkeypatch.delenv("KIRA_NO_OUTBOUND", raising=False)
    assert cfg.outbound_blocked() is False
