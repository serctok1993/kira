"""Ein Zustellweg fuer alle Prozesse ausserhalb des Bots (Cron, Runner, Wartung).

Vorher hatte jeder Melder seine eigene Kopie desselben blinden httpx.post:
Rueckgabewert verworfen, kein Stueckeln, kein Retry, und ein fehlender Token brach
still ab. Telegram antwortet aber mit HTTP 200 und {"ok": false}, wenn der Bot
blockiert wurde, die chat_id nicht stimmt oder das Limit greift — all das galt als
erfolgreiche Zustellung (Fund 27.07.). Wer danach seinen Puffer leerte oder einen
Tag als erledigt stempelte, verlor die Nachricht endgueltig.

Der Bot selbst hat seinen eigenen Sender (telegram_bot._send) mit HTML-Formatierung
und wiederverwendetem Client; dieses Modul ist fuer alle anderen.
"""
from __future__ import annotations

import time

from core.kernel import events

_API = "https://api.telegram.org/bot{token}/sendMessage"
_STUECK = 3800   # Telegram-Limit ~4096; Reserve fuer Mehrbyte-Zeichen
TIMEOUT_S = 15


def _ziel() -> tuple[str | None, object | None]:
    from core import config as _cfg
    from core.config import CONFIG

    try:
        return (_cfg.telegram_token(),
                CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id"))
    except Exception:  # noqa: BLE001
        return (None, None)


def an_nutzer(text: str, quelle: str = "") -> bool:
    """Text per Telegram zustellen. True = alle Stuecke sind angekommen.

    Raist nie. Jeder Fehlschlag wird als Event 'telegram_send_failed' aktenkundig,
    damit eine verschwundene Meldung im Cockpit auffindbar ist."""
    from core import config as _cfg

    if _cfg.outbound_blocked():   # Firewall (Benchmark/Sandbox): kein Telegram
        return False
    text = (text or "").strip()
    if not text:
        return False
    token, chat = _ziel()
    if not (token and chat):
        # Frueher ein stilles return — der haeufigste Grund fuer "meine Meldung kam nie".
        events.emit("telegram_send_failed",
                    {"grund": "kein Token oder keine chat_id konfiguriert",
                     "quelle": quelle, "anfang": text[:120]})
        return False

    import httpx

    url = _API.format(token=token)
    alles_raus = True
    for i in range(0, len(text), _STUECK):
        stueck = text[i : i + _STUECK]
        try:
            j = httpx.post(url, json={"chat_id": chat, "text": stueck},
                           timeout=TIMEOUT_S).json()
            if not j.get("ok") and j.get("error_code") == 429:   # Limit: kurz warten, 1x erneut
                time.sleep(min(6, ((j.get("parameters") or {}).get("retry_after") or 2)))
                j = httpx.post(url, json={"chat_id": chat, "text": stueck},
                               timeout=TIMEOUT_S).json()
            if not j.get("ok"):
                alles_raus = False
                events.emit("telegram_send_failed",
                            {"grund": str(j.get("description") or j.get("error_code") or "?")[:200],
                             "quelle": quelle, "anfang": stueck[:120]})
        except Exception as e:  # noqa: BLE001 — Zustellung darf den Aufrufer nie umbringen
            alles_raus = False
            events.emit("telegram_send_failed",
                        {"grund": f"{type(e).__name__}: {str(e)[:120]}",
                         "quelle": quelle, "anfang": stueck[:120]})
    return alles_raus
