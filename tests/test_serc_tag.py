"""Werkbank PR 7: Serc "Tag" — Sergens Erst-Blick (heute faellig, heute erledigt,
Routinen des Tages, Freigaben-Zaehler) + Freigaben-Badge in der Sidebar."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.script import SCRIPT
from core.api.ui.views import VIEWS


def test_tag_subtab_markup():
    # "Tag" ist der ERSTE und default-aktive Serc-Subtab
    bar = VIEWS.split('id="me-tabs"', 1)[1].split("</div>", 1)[0]
    assert bar.index('data-s="tag"') < bar.index('data-s="todos"')
    assert '<a data-s="tag" class="on">' in bar
    # eigener Subview mit den vier Bausteinen
    tag = VIEWS.split('id="v-tag"', 1)[1].split('id="v-todos"', 1)[0]
    for el in ('id="tag-heute"', 'id="tag-done"', 'id="tag-routinen"',
               'id="tag-digest"', 'id="tag-frei"', 'id="tag-go-puls"'):
        assert el in tag, f"fehlt im Tag-Subview: {el}"
    # genau EIN default-aktiver Serc-Subview: v-tag hat das 'on', v-todos nicht mehr
    assert '<div class="subview on" id="v-tag">' in VIEWS
    assert '<div class="subview" id="v-todos">' in VIEWS


def test_tag_loader_registriert():
    # Registry: Tag ist Start-Subtab und hat einen Loader
    assert 'me:      {bar:"#me-tabs", cur:"tag"' in SCRIPT
    assert "tag:()=>loadTag()" in SCRIPT
    # Loader zieht NUR vorhandene Endpunkte (jede Zahl lebt an ihrem Ort)
    fn = SCRIPT.split("async function loadTag()", 1)[1].split("async function loadMeCrons", 1)[0]
    for api in ('"/api/life/board"', '"/api/digest"', '"/api/cron"'):
        assert api in fn, f"loadTag holt {api} nicht"
    assert "data-tgdone" in fn and '"/api/mission/task/update"' in fn  # Abhaken direkt im Tag
    assert 'subnav("me","freigaben")' in fn                            # Zaehler springt zur Inbox


def test_sidebar_freigaben_badge():
    assert 'id="side-frei" class="frei-badge"' in VIEWS
    assert ".frei-badge{" in CSS
    # Badge wird vom 5s-Statuspoll gefuettert (kein Extra-Polling)
    assert "s.freigaben_offen|0" in SCRIPT


def test_status_liefert_freigaben_zaehler():
    r = TestClient(s.app).get("/api/status").json()
    assert "freigaben_offen" in r and isinstance(r["freigaben_offen"], int)
