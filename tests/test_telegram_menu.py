"""Telegram-Befehlsmenue (setMyCommands) + /status.

Alle nuetzlichen Befehle tauchen im '/'-Menue auf — und jeder Menue-Eintrag hat auch wirklich
einen Handler (kein Klick ins Leere). /status zeigt Heartbeat/Budget/Modell auf einen Blick.
"""
from __future__ import annotations

import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent
        / "core" / "agency" / "connectors" / "telegram_bot.py").read_text(encoding="utf-8")


def test_register_commands_setzt_menue():
    from core.agency.connectors import telegram_bot as tb
    posts: list = []

    class C:
        def post(self, url, json=None, timeout=None):
            posts.append((url, json))

            class R:
                def json(self_):
                    return {"ok": True}
            return R()

    tb._register_commands(C())
    assert len(posts) == 1
    url, payload = posts[0]
    assert "setMyCommands" in url
    names = [c["command"] for c in payload["commands"]]
    assert {"status", "code", "plan", "work", "stop", "go", "model"} <= set(names)
    assert all(c["description"] for c in payload["commands"])   # jeder Eintrag hat einen Text


def test_register_commands_raist_nie():
    from core.agency.connectors import telegram_bot as tb

    class Boom:
        def post(self, *a, **k):
            raise RuntimeError("netz weg")
    tb._register_commands(Boom())   # darf nicht werfen (Bot-Start bleibt heil)


def test_menue_nur_echte_befehle():
    """Jeder Menue-Befehl hat einen Handler in _handle_command — sonst klickt der Nutzer ins Leere."""
    from core.agency.connectors import telegram_bot as tb
    handled = set(re.findall(r'cmd == "(\w+)"', _SRC)) | {"start", "help"}
    for grp in re.findall(r'cmd in \(([^)]*)\)', _SRC):   # auch 'cmd in ("a","b")'-Handler
        handled |= set(re.findall(r'"(\w+)"', grp))
    for c, _desc in tb._BOT_COMMANDS:
        assert c in handled, f"Menue-Befehl /{c} hat keinen Handler"


def test_run_registriert_menue():
    assert "_register_commands(_ctrl())" in _SRC   # beim Bot-Start einmal angemeldet


def test_status_befehl(monkeypatch):
    from core.agency.connectors import telegram_bot as tb
    sent: list = []
    monkeypatch.setattr(tb, "_send", lambda client, chat, txt, *a, **k: sent.append(txt))
    monkeypatch.setattr(tb, "kill_switch_active", lambda: False)
    tb._handle_command(object(), 7, "/status")
    assert sent and "Kira-Status" in sent[0]
    assert "Not-Aus" in sent[0]                     # immer vorhanden (best-effort-Block)
