"""Werkbank PR 3: Einstellungen als eigener Tab — Technik zieht aus dem Kira-Tab aus."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s


def _html() -> str:
    return TestClient(s.app).get("/").text


def test_settings_tab_existiert():
    html = _html()
    assert 'data-v="settings"' in html          # Sidebar-Eintrag
    assert 'id="v-settings"' in html and 'id="settings-tabs"' in html
    # eigene Registry mit den 6 Technik-Loadern
    assert 'settings:{bar:"#settings-tabs", cur:"models"' in html


def test_kira_tab_ohne_technik():
    html = _html()
    kira_tabs = html.split('id="kira-tabs"', 1)[1].split("</div>", 1)[0]
    for sub in ("models", "bench", "steuer", "keys", "cockpit", "wall"):
        assert f'data-s="{sub}"' not in kira_tabs, f"{sub} haengt noch im Kira-Tab"
    assert 'data-g="technik"' not in html       # Gruppe komplett weg
    assert '{key:"technik"' not in html


def test_alias_und_dom_move():
    html = _html()
    assert "_SETTINGS_SUBS" in html
    assert 'if(tab==="kira"&&_SETTINGS_SUBS.includes(s))' in html   # Alias-Map (Merge-Pflicht)
    assert "vs.appendChild(el)" in html                              # DOM-Move beim Boot
    assert 'nav("settings")' in html                                 # Gear-Shortcut umgeleitet


def test_settings_bar_hat_alle_sechs():
    html = _html()
    bar = html.split('id="settings-tabs"', 1)[1].split("</div>", 1)[0]
    for sub in ("models", "bench", "steuer", "keys", "cockpit", "wall"):
        assert f'data-s="{sub}"' in bar


def test_settings_bar_gegen_gedaechtnis_falle():
    """Praxis-Fund 09.07.: grosser Subview (Modelle/Benchmark) quetschte die
    Einstellungen-Leiste auf 2px — man kam nicht mehr aus dem Tab raus."""
    from core.api.ui.css import HEAD_AND_CSS as css
    # die Schutzregel enthaelt settings-tabs UND me-tabs
    rule = [z for z in css.splitlines() if "flex-shrink:0;align-self:flex-start" in z]
    assert rule and "#settings-tabs" in rule[0] and "#me-tabs" in rule[0]
    # grosse Subviews scrollen intern statt die Leiste zu verdraengen
    assert "#v-settings .subview.on{flex:1;min-height:0;overflow:auto" in css
