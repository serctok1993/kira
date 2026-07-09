"""Werkbank PR 6: Zentrale-Erst-Blick — News-Laufband unterm HUD, 'Kira heute'-Panel,
Schnellzugriff raus."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s


def test_zentrale_erstblick():
    html = TestClient(s.app).get("/").text
    home = html.split('id="v-home"', 1)[1].split('id="v-chat"', 1)[0]
    # Laufband direkt unterm HUD (Reihenfolge: hud-strip VOR ticker VOR direktive)
    assert home.index('id="hud-strip"') < home.index('id="news-ticker"') < home.index("direktive")
    # grosses Intel-Panel + Schnellzugriff + home-side sind raus
    assert 'id="news-list"' not in html
    assert '"Schnellzugriff"' not in html        # Karte weg (nur noch Kommentar-Erwaehnung)
    assert 'class="home-side"' not in html
    # EIN Erst-Blick-Panel 'Kira heute' mit Tagewerk + Digest + Lektionen-Slot
    assert "Kira heute" in home
    for el in ('id="tagewerk"', 'id="digest"', 'id="z-lektionen"'):
        assert el in home, f"fehlt im Kira-heute-Panel: {el}"
    # Lektionen-Renderer + entschlackter News-Loader vorhanden
    assert "ZULETZT GELERNT" in html and "z-lektionen" in html
    assert 'const tk=$("#news-ticker");if(!tk)return;' in html
