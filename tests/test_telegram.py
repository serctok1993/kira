"""S5.2: Telegram-Härtung — Regressions-Pins gegen stille Aufräum-Fehler."""
from __future__ import annotations

import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent
        / "core" / "agency" / "connectors" / "telegram_bot.py").read_text(encoding="utf-8")


def test_no_backslash_in_api_urls():
    """Telegram-API-Methoden immer mit Slash — ein Backslash wuerde still 404 laufen."""
    assert not re.search(r"\{API\}\\", _SRC)
    assert "/deleteMessage" in _SRC and "/editMessageText" in _SRC


def test_cleanup_is_checked_with_fallback():
    """Das Loeschen der Transkript-Nachricht wird GEPRUEFT (kein stilles Scheitern mehr);
    bei Fehlschlag kollabiert sie zur Mini-Zeile + Diagnose-Event (Chat-Sprenger-Schutz)."""
    assert "telegram_cleanup_failed" in _SRC
    assert "🎙️ ✓" in _SRC


def test_clean_strips_markdown():
    from core.agency.connectors.telegram_bot import _clean

    assert _clean("**fett** und __unter__") == "fett und unter"
    assert _clean("kein markdown") == "kein markdown"


def test_render_trace_structure():
    """S5.6: der pure Trace-Renderer — Transkript-Kopf, Denk-Strom, Schritte, Puls."""
    from core.agency.connectors.telegram_bot import _render_trace

    live = _render_trace("mein memo", "ich denke nach", ["🔧 web_search"], "arbeite", "···", True)
    assert "🎙️" in live and "mein memo" in live
    assert "ich denke nach" in live and "web_search" in live
    assert "arbeite" in live and "···" in live  # Puls-Zeile nur waehrend running

    final = _render_trace(None, "fertig gedacht", [], "egal", "···", False)
    assert "arbeite" not in final and "···" not in final  # kein Puls mehr am Ende
    assert "fertig gedacht" in final


def test_render_trace_caps_length():
    from core.agency.connectors.telegram_bot import _render_trace

    out = _render_trace(None, "x" * 5000, [], "p", "·", True)
    assert len(out) <= 4000  # Telegram-Limit
