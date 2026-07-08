"""Werkbank PR 2b: Master-Detail im Projekte-Tab — Liste schmal links, Akte rechts."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s


def test_drill_ist_master_detail_grid():
    html = TestClient(s.app).get("/").text
    assert "#v-projekte.drill{display:grid;grid-template-columns:300px" in html
    assert "#v-projekte.drill #vent-detail{grid-column:2" in html
    # Alt-Verhalten bleibt: ohne Drill keine Akte, im Drill keine 3 Spalten
    assert "#v-projekte:not(.drill) #vent-detail{display:none!important}" in html
    assert "#v-projekte.drill .proj-cols{display:none}" in html
