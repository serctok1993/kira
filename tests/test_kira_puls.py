"""Werkbank PR 4: Kira-Puls — erster Blick im Kira-Tab zeigt, was sie heute tut & lernt."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s


def _html() -> str:
    return TestClient(s.app).get("/").text


def test_puls_ist_start_subtab():
    html = _html()
    assert '<a data-s="puls" class="on">' in html          # erster Reiter, aktiv
    assert '<div class="subview on" id="v-puls">' in html  # Start-Subview
    assert '<div class="subview" id="v-files">' in html    # files nicht mehr Start
    assert 'kira:    {bar:"#kira-tabs", cur:"puls"' in html


def test_puls_loader_und_inhalte():
    html = _html()
    assert "async function loadPuls()" in html and "puls:()=>loadPuls()" in html
    for marker in ("HEUTE GETAN", "ZULETZT GELERNT", "/api/tagewerk", "/api/evolution",
                   "data-pdel", "Freigaben offen"):
        assert marker in html, f"fehlt: {marker}"


def test_puls_in_geist_gruppe():
    html = _html()
    assert '{key:"geist",   subs:["puls","files","mem","wissen"]}' in html
