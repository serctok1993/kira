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
