"""P2 (Working-Pod): der aktive Auftrag live im Cockpit.

Zwei Andockstellen (Chat-Seitenspalte + Board rechts), nur sichtbar wenn ein
Auftrag laeuft. Der Harness fuehrt die Liste — die UI liest nur; ✕ ist die
Notbremse des Nutzers. Offline, eigener Store-Pfad (tmp), keine Live-Daten.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.agency import auftrag


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(auftrag, "_PATH", tmp_path / "auftrag.json")


def test_api_auftrag_liefert_store_und_klartext():
    import core.api.server as s

    c = TestClient(s.app)
    r = c.get("/api/auftrag").json()
    assert r["auftrag"] == {} and "kein aktiver Auftrag" in r["klartext"]
    auftrag.set_plan("Report fertig", ["Daten sammeln", "Entwurf"])
    auftrag.update(1, "laeuft", "Quelle X offen")
    r = c.get("/api/auftrag").json()
    assert r["auftrag"]["ziel"] == "Report fertig"
    assert [s2["status"] for s2 in r["auftrag"]["schritte"]] == ["laeuft", "offen"]
    assert r["auftrag"]["schritte"][0]["notiz"] == "Quelle X offen"   # Store-Beleg je Schritt
    assert "-> Naechster Schritt: Nr. 1" in r["klartext"]


def test_api_auftrag_clear_ist_die_notbremse():
    import core.api.server as s

    auftrag.set_plan("Ziel", ["a", "b"])
    assert TestClient(s.app).post("/api/auftrag/clear").json() == {"ok": True}
    assert auftrag.get() == {}


def test_pod_marker_in_beiden_andockstellen():
    from core.api.ui.css import HEAD_AND_CSS
    from core.api.ui.script import SCRIPT
    from core.api.ui.views import VIEWS

    # beide Panels existieren und starten unsichtbar (kein leerer Kasten ohne Auftrag)
    for m in ("ct-auftrag-panel", "bd-auftrag-panel", "ct-au-stand", "bd-au-stand"):
        assert m in VIEWS, f"Pod-Marker fehlt in den Views: {m}"
    assert VIEWS.count('class="au-stop"') == 2                        # Notbremse in beiden Koepfen
    # Loader + Renderer + alle vier Hooks (Chat-Oeffnen, Poll, Stream-Ende, Boot)
    for m in ("function renderAuftrag", "async function loadAuftrag",
              'fetch("/api/auftrag")', "/api/auftrag/clear"):
        assert m in SCRIPT, f"Pod-Logik fehlt im Script: {m}"
    assert 'cur==="chat")loadAuftrag()' in SCRIPT                     # Live-Haekchen im Poll
    assert SCRIPT.count("loadAuftrag()") >= 4
    # Stile inkl. Puls fuer den laufenden Schritt
    for m in (".au-row", ".au-mark.au-l", "@keyframes auPuls", ".au-huerde"):
        assert m in HEAD_AND_CSS, f"Pod-Stil fehlt im CSS: {m}"
