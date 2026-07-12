"""S11: Datei-Anhang im Chat — /api/chat/attach extrahiert Text (PDF/txt/md/...),
damit Kira direkt darauf antworten oder eine Mail schreiben kann. Offline.
"""
from __future__ import annotations

from starlette.testclient import TestClient

from core.api import server


def _c():
    return TestClient(server.app)


def test_attach_txt():
    r = _c().post("/api/chat/attach",
                  files={"file": ("brief.txt", b"Sehr geehrte Damen und Herren, Angebot anbei.", "text/plain")})
    d = r.json()
    assert d["ok"] is True
    assert "Angebot" in d["text"]
    assert d["name"] == "brief.txt" and d["truncated"] is False


def test_attach_csv():
    r = _c().post("/api/chat/attach",
                  files={"file": ("daten.csv", b"name,umsatz\nAtlas,1000\nNord,2000", "text/csv")})
    assert r.json()["ok"] is True and "Atlas" in r.json()["text"]


def test_attach_unsupported():
    r = _c().post("/api/chat/attach",
                  files={"file": ("x.bin", b"\x00\x01\x02", "application/octet-stream")})
    d = r.json()
    assert d["ok"] is False and "nicht unterstuetzt" in d["error"]


def test_attach_truncates_large():
    big = ("A" * 20000).encode("utf-8")
    d = _c().post("/api/chat/attach", files={"file": ("gross.txt", big, "text/plain")}).json()
    assert d["ok"] is True and d["truncated"] is True
    assert len(d["text"]) == 12000 and d["chars"] == 20000


def test_bild_fliesst_in_den_chat():
    # #19: ein Bild wird nicht mehr nur einmal beschrieben, sondern die Vision-Beschreibung
    # fliesst in den laufenden Chat -> Kira kann darauf aufbauen (nachfragen, Mail schreiben).
    from core.api.ui.script import SCRIPT
    # Image-Zweig ruft /api/vision, speist die Beschreibung dann per ws.send in den Chat ein
    assert "Kiras Bildbeschreibung: " in SCRIPT       # Vision-Text wandert in die Chat-Nachricht
    assert 'startThinking();ws.send(full)' in SCRIPT   # -> agentischer Chat statt Einmal-Beschreibung
    # der Image-Zweig (vor attachFile) nutzt /api/vision
    assert SCRIPT.find("/api/vision") < SCRIPT.find("Kiras Bildbeschreibung")
