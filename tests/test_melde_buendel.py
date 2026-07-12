"""Melde-Buendelung (Praxis-Fund 09.07.): 10 Missions-Meldungen in 3 Stunden sind
Flut — jetzt sammeln sich Einzeiler im Puffer und der Bot schickt alle N Stunden
EIN Buendel. Wichtiges (gescheitert, Stripe, Selbst-Check) geht weiter SOFORT raus."""
from __future__ import annotations

import json
import time

from core.agency.missions import melde, runner
from core.config import CONFIG


# ---------- melde-Modul (Puffer) ----------

def _puffer(monkeypatch, tmp_path):
    monkeypatch.setattr(melde, "_PATH", tmp_path / "melde_puffer.json")


def test_merken_normalisiert_und_kappt(monkeypatch, tmp_path):
    _puffer(monkeypatch, tmp_path)
    melde.merken("  ✅   Fallstudie \n GatherUp  " + "x" * 400)
    zeilen = melde.leeren()
    assert len(zeilen) == 1
    assert zeilen[0].startswith("✅ Fallstudie GatherUp")   # Whitespace normalisiert
    assert len(zeilen[0]) <= 160                            # Einzeiler-Kappe
    melde.merken("   ")                                     # leer = ignoriert
    assert melde.leeren() == []


def test_merken_ueberlauf_aeltestes_faellt_raus(monkeypatch, tmp_path):
    _puffer(monkeypatch, tmp_path)
    for i in range(melde.MAX_ZEILEN + 5):
        melde.merken(f"Schritt {i}")
    zeilen = melde.leeren()
    assert len(zeilen) == melde.MAX_ZEILEN
    assert zeilen[0] == "Schritt 5" and zeilen[-1] == f"Schritt {melde.MAX_ZEILEN + 4}"


def test_faellig_erst_nach_intervall(monkeypatch, tmp_path):
    _puffer(monkeypatch, tmp_path)
    assert melde.faellig(3) is False                        # leerer Puffer: nie faellig
    melde.merken("Schritt A")
    assert melde.faellig(3) is True                         # nie geflusht (last_flush 0)
    melde.leeren()                                          # stempelt last_flush=jetzt
    melde.merken("Schritt B")
    assert melde.faellig(3) is False                        # gerade erst geflusht
    d = json.loads(melde._PATH.read_text(encoding="utf-8"))
    d["last_flush"] = time.time() - 4 * 3600
    melde._PATH.write_text(json.dumps(d), encoding="utf-8")
    assert melde.faellig(3) is True                         # 4h her > 3h Intervall


def test_leeren_chronologisch_und_leert(monkeypatch, tmp_path):
    _puffer(monkeypatch, tmp_path)
    melde.merken("Erster")
    melde.merken("Zweiter")
    assert melde.leeren() == ["Erster", "Zweiter"]
    assert melde.leeren() == []


# ---------- runner._notify-Routing ----------

def _wire(monkeypatch, mode):
    """_notify verdrahten: Telegram 'an', Modus waehlbar, httpx + Puffer gecaptured."""
    import httpx
    posts, puffer = [], []
    monkeypatch.setattr(runner, "_mission",
                        lambda: {"notify_telegram": True, "notify_mode": mode})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setitem(CONFIG, "channels", {"telegram": {"allowed_chat_id": 5}})
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, timeout=None: posts.append(json["text"]))
    monkeypatch.setattr(melde, "merken", lambda z: puffer.append(z))
    return posts, puffer


def test_notify_gebuendelt_legt_kurzzeile_in_puffer(monkeypatch):
    posts, puffer = _wire(monkeypatch, "gebuendelt")
    runner._notify("Langer Bericht\nmit Details", kurz="✅ Fallstudie fertig")
    assert posts == []                                      # KEIN Einzelversand
    assert puffer == ["✅ Fallstudie fertig"]

    runner._notify("Nur Text ohne kurz\nZeile 2")           # Fallback: erste Zeile
    assert puffer[-1] == "Nur Text ohne kurz"


def test_notify_wichtig_geht_sofort_raus(monkeypatch):
    posts, puffer = _wire(monkeypatch, "gebuendelt")
    runner._notify("⚠️ Task endgueltig gescheitert", wichtig=True)
    assert posts == ["⚠️ Task endgueltig gescheitert"]      # Buendel-Modus egal
    assert puffer == []


def test_notify_modus_sofort_und_aus(monkeypatch):
    posts, puffer = _wire(monkeypatch, "sofort")
    runner._notify("Meldung X")
    assert posts == ["Meldung X"] and puffer == []          # Alt-Verhalten

    posts, puffer = _wire(monkeypatch, "aus")
    runner._notify("Meldung Y")
    assert posts == [] and puffer == []                     # still
    runner._notify("⚠️ Kritisch", wichtig=True)
    assert posts == ["⚠️ Kritisch"]                         # Wichtiges kommt IMMER


# ---------- Telegram-Bot: Buendel-Versand ----------

def test_maybe_melde_buendel_ein_sammelpost(monkeypatch, tmp_path):
    import core.agency.connectors.telegram_bot as tb
    _puffer(monkeypatch, tmp_path)
    melde.merken("✅ Fallstudie GatherUp")
    melde.merken("🔧 Selbst-Optimierung: Retry-Logik")
    sent = []
    monkeypatch.setattr(tb, "_cfg", lambda: {"allowed_chat_id": 7})
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append(txt))
    tb._maybe_melde_buendel(object())
    assert len(sent) == 1                                   # EIN Post, keine Flut
    assert "Missions-Bündel" in sent[0] and "(2 Schritte)" in sent[0]
    assert "• ✅ Fallstudie GatherUp" in sent[0]
    assert "• 🔧 Selbst-Optimierung: Retry-Logik" in sent[0]
    assert "/tagewerk" in sent[0]                           # Verweis auf Details

    tb._maybe_melde_buendel(object())                       # Puffer leer: still
    assert len(sent) == 1


def test_maybe_melde_buendel_wartet_aufs_intervall(monkeypatch, tmp_path):
    import core.agency.connectors.telegram_bot as tb
    _puffer(monkeypatch, tmp_path)
    melde.merken("Schritt A")
    d = json.loads(melde._PATH.read_text(encoding="utf-8"))
    d["last_flush"] = time.time() - 600                     # vor 10 min geflusht
    melde._PATH.write_text(json.dumps(d), encoding="utf-8")
    sent = []
    monkeypatch.setattr(tb, "_cfg", lambda: {"allowed_chat_id": 7})
    monkeypatch.setattr(tb, "_send", lambda c, ch, txt, *a, **k: sent.append(txt))
    tb._maybe_melde_buendel(object())
    assert sent == []                                       # 3h-Takt noch nicht um
    assert melde.leeren() == ["Schritt A"]                  # Puffer blieb unangetastet


def test_config_defaults():
    m = CONFIG.get("mission", {})
    assert str(m.get("notify_mode")) == "gebuendelt"
    assert float(m.get("buendel_stunden")) == 3
