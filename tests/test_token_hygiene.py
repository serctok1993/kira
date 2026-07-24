"""Token-Hygiene (Mehr-Agenten-Isolation): token_env-Aufloesung + getMe-Wache.

Hintergrund Sandy-Vorfall 23./24.07.2026: eine aus fremdem Kontext gestartete
Dev-Instanz ERBTE das TELEGRAM_BOT_TOKEN eines anderen Agenten und pollte mit
dessen Bot — der fremde Gateway wurde per Telegram-409 stillgelegt. Diese Tests
nageln die Gegenmassnahmen fest: konfigurierbarer Variablenname OHNE Fallback
und die Polling-Verweigerung bei fremder Bot-ID.
"""
import pytest

from core import config


def _telegram_cfg(monkeypatch, **werte):
    """channels.telegram in CONFIG kontrolliert setzen (monkeypatch raeumt auf)."""
    kanaele = dict(config.CONFIG.get("channels") or {})
    kanaele["telegram"] = {**(kanaele.get("telegram") or {}), **werte}
    monkeypatch.setitem(config.CONFIG, "channels", kanaele)


def test_token_env_werksdefault(monkeypatch):
    _telegram_cfg(monkeypatch)
    assert config.telegram_token_env() == "TELEGRAM_BOT_TOKEN"


def test_token_env_override_gilt(monkeypatch):
    _telegram_cfg(monkeypatch, token_env="KIRA_BOT_TOKEN")
    monkeypatch.setenv("KIRA_BOT_TOKEN", "111:eigen")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:fremd")
    assert config.telegram_token() == "111:eigen"


def test_kein_fallback_auf_werksnamen(monkeypatch):
    """Eigener Name konfiguriert, Variable aber leer -> Token ist LEER, auch wenn ein
    (potenziell geerbtes, fremdes) TELEGRAM_BOT_TOKEN in der Umgebung steht."""
    _telegram_cfg(monkeypatch, token_env="KIRA_BOT_TOKEN")
    monkeypatch.delenv("KIRA_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:fremd")
    assert config.telegram_token() == ""


class _GetMe:
    def __init__(self, bot_id, username):
        self._r = {"result": {"id": bot_id, "username": username}}

    def get(self, url):
        return self

    def json(self):
        return self._r


def test_getme_wache_laesst_eigenen_bot_durch(monkeypatch, capsys):
    from core.agency.connectors import telegram_bot as tb
    _telegram_cfg(monkeypatch, expected_bot_id=111)
    monkeypatch.setattr(tb, "_ctrl", lambda: _GetMe(111, "eigen_bot"))
    tb._getme_wache()  # kehrt zurueck, kein Schlaf
    assert "polle als @eigen_bot (id 111)" in capsys.readouterr().out


def test_getme_wache_verweigert_fremden_bot(monkeypatch, capsys):
    from core.agency.connectors import telegram_bot as tb
    _telegram_cfg(monkeypatch, expected_bot_id=111)
    monkeypatch.setattr(tb, "_ctrl", lambda: _GetMe(999, "fremd_bot"))
    ereignisse = []
    monkeypatch.setattr(tb.events, "emit", lambda typ, d: ereignisse.append((typ, d)))

    class _Stopp(Exception):
        pass

    def _kein_endlos_schlaf(_s):
        raise _Stopp

    monkeypatch.setattr(tb.time, "sleep", _kein_endlos_schlaf)
    with pytest.raises(_Stopp):
        tb._getme_wache()
    assert ("telegram_identity_mismatch",
            {"expected": 111, "actual": 999, "username": "fremd_bot"}) in ereignisse
    assert "POLLING VERWEIGERT" in capsys.readouterr().out


def test_getme_wache_ohne_erwartung_nur_logging(monkeypatch, capsys):
    """Werkszustand (expected_bot_id nicht gesetzt): Wache loggt die Identitaet, blockt nie."""
    from core.agency.connectors import telegram_bot as tb
    _telegram_cfg(monkeypatch)
    monkeypatch.setattr(tb, "_ctrl", lambda: _GetMe(424242, "werks_bot"))
    tb._getme_wache()
    assert "polle als @werks_bot (id 424242)" in capsys.readouterr().out
