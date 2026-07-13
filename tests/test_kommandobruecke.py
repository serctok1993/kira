"""Kommandobruecke (UI-Umbau, 13.07.): Chat als Herzstueck, Rail-Nav, Chip-Kopf,
Fokus-Zeile, Tag-Spalte im Chat, Freigabe-Karten, Strg+K-Palette.

Prinzip des Umbaus: neue SCHALE um unangetastete Innereien — alle bestehenden
Views/Loader/IDs leben weiter, nur Anordnung + Kopf sind neu.
"""
from __future__ import annotations

from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.script import SCRIPT
from core.api.ui.views import VIEWS


def test_chat_ist_die_startflaeche():
    # Chat traegt das 'on' — im Markup UND im Boot-Pfad
    assert '<div class="view on" id="v-chat">' in VIEWS
    assert '<div class="view" id="v-home">' in VIEWS          # Board nicht mehr default
    assert '<a data-v="chat" class="on"' in VIEWS
    assert 'let cur="chat"' in SCRIPT
    assert 'nav("chat");  /* Kommandobruecke' in SCRIPT        # Boot startet im Chat


def test_rail_hat_alle_bereiche():
    seite = VIEWS.split('id="main"', 1)[0]                     # nur die Rail
    for v in ('data-v="chat"', 'data-v="home"', 'data-v="kira"', 'data-v="me"',
              'data-v="settings"'):
        assert v in seite, f"Rail-Eintrag fehlt: {v}"
    assert "#side{width:76px" in CSS                           # schmale Icon-Rail


def test_kopf_traegt_marke_und_zahlen():
    bar = VIEWS.split('id="bar"', 1)[1].split("</div>", 1)[0]
    assert '<h1 id="brand"><span class="txt">__AGENT_UC__</span></h1>' in VIEWS
    assert 'id="chip-motor"' in VIEWS and 'id="motor-b"' in VIEWS
    assert 'id="chip-frei"' in VIEWS and 'id="b-spend"' in VIEWS
    assert 'id="chip-termin"' in VIEWS and 'id="b-model"' in VIEWS
    assert '"heartbeat": heartbeat_on()' not in VIEWS          # (Server-Seite, nicht Markup)
    assert "s.heartbeat" in SCRIPT                             # Chip haengt am Status-Poll
    del bar


def test_fokus_zeile():
    assert 'id="fokus-line"' in VIEWS and 'id="fokus-text"' in VIEWS
    assert 'id="fokus-edit"' in VIEWS
    assert '"/api/direktive"' in SCRIPT and "loadFokus" in SCRIPT
    assert "#fokus-line{" in CSS


def test_chat_hat_drei_spalten():
    chat = VIEWS.split('id="v-chat"', 1)[1].split('id="pal-wrap"', 1)[0]
    assert 'id="sess-panel"' in chat                            # links: Sessions (bestand)
    assert 'id="chat-main"' in chat                             # mitte: Gespraech
    assert 'id="chat-tag"' in chat                              # rechts: Dein Tag (neu)
    for el in ('id="ct-termine"', 'id="ct-todos"', 'id="ct-puls"'):
        assert el in chat, el
    # Sessions fest links, Tag-Spalte fest rechts (Override-Block)
    assert "#sess-panel{order:0;width:236px" in CSS
    assert "#chat-tag{width:296px" in CSS
    assert "loadChatSide" in SCRIPT


def test_freigabe_karten_im_chat():
    assert 'id="chat-frei"' in VIEWS
    assert "renderChatFrei" in SCRIPT
    assert '"/api/approvals/decide"' in SCRIPT                  # Freigeben/Ablehnen direkt
    assert ".frei-karte{" in CSS


def test_briefing_bubble_nie_leerer_chat():
    assert "briefingBubble" in SCRIPT
    assert 'id="brief-bubble"' in SCRIPT                        # nur bei leerem Log, 0 Token
    assert "Dein Tag in kurz" in SCRIPT


def test_strg_k_palette():
    assert 'id="pal-wrap"' in VIEWS and 'id="pal-q"' in VIEWS
    assert 'e.key.toLowerCase()==="k"' in SCRIPT and "palOpen" in SCRIPT
    assert "_sessCache=ss;" in SCRIPT                           # Sessions fuettern die Palette
    assert "#pal-wrap{position:fixed" in CSS


def test_routinen_sind_bearbeitbar():
    # Feedback aus dem PR-Review (13.07.): Routine anklicken -> Name/Zeitplan/Auftrag aendern
    # (Auftrag = freier Text, URLs fuer Tracking fahren mit). Endpoint existierte schon.
    assert "data-cedit" in SCRIPT and '"/api/cron/update"' in SCRIPT
    assert "ce-prompt" in SCRIPT and "ce-sched" in SCRIPT and "ce-label" in SCRIPT
    assert '"/api/cron/runnow"' in SCRIPT                      # ► testen (Probelauf)
    assert '"/api/cron/remove"' in SCRIPT                      # loeschen mit confirm


def test_status_liefert_heartbeat():
    from fastapi.testclient import TestClient

    import core.api.server as s

    r = TestClient(s.app).get("/api/status").json()
    assert "heartbeat" in r and isinstance(r["heartbeat"], bool)
