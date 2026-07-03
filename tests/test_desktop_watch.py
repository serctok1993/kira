"""S8.5: Desktop-Pflege — lokaler Scan, Sortier-VORSCHLAG (kein Move ohne Freigabe)."""
from __future__ import annotations

from core.agency import desktop_watch as dw


def _cfg(tmp_path, **over):
    d = {"enabled": True, "auto": False, "folders": [str(tmp_path)], "ignore": [".lnk", "Kira"]}
    d.update(over)
    return d


def test_scan_guesses_categories(tmp_path):
    (tmp_path / "Rechnung_Juli.pdf").write_text("x")
    (tmp_path / "urlaub.jpg").write_bytes(b"x")
    (tmp_path / "setup_app.exe").write_bytes(b"x")
    (tmp_path / "notiz.txt").write_text("x")
    (tmp_path / "Kira-link.lnk").write_text("x")  # ignoriert
    (tmp_path / "unterordner").mkdir()

    res = dw.scan(_cfg(tmp_path))
    files = {s["file"]: s["target"] for s in res["suggestions"]}
    assert files["Rechnung_Juli.pdf"] == "Dokumente/Rechnungen"
    assert files["urlaub.jpg"] == "Bilder"
    assert files["setup_app.exe"] == "Installer"
    assert "Kira-link.lnk" not in files  # ignore greift
    assert res["scanned"] == 4  # der .lnk zaehlt nicht, Unterordner auch nicht


def test_propose_creates_approval_but_moves_nothing(monkeypatch, tmp_path):
    from core.agency import approvals
    from core.kernel import events

    db = str(tmp_path / "state.db")
    for mod in (approvals, events):
        monkeypatch.setattr(mod, "DB_PATH", db)
    events.init_db()
    approvals.init_approvals()

    src = tmp_path / "desk"
    src.mkdir()
    (src / "Rechnung.pdf").write_text("wichtig")
    (src / "foto.png").write_bytes(b"x")

    res = dw.propose(_cfg(src))
    assert res["suggestions"] == 2 and "approval_id" in res
    # DER Kern: nichts wurde verschoben, die Dateien liegen unveraendert da
    assert (src / "Rechnung.pdf").read_text() == "wichtig"
    assert (src / "foto.png").exists()
    pend = approvals.pending()
    assert len(pend) == 1 and "Desktop aufraeumen" in pend[0]["title"]
    assert "nichts wurde verschoben" in pend[0]["detail"]


def test_propose_skips_when_disabled(tmp_path):
    (tmp_path / "Rechnung.pdf").write_text("x")
    assert dw.propose(_cfg(tmp_path, enabled=False)) == {"skipped": "disabled"}


def test_config_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(dw, "_CFG", tmp_path / "desktop_watch.json")
    cfg = dw.load_cfg()
    assert cfg["enabled"] is False and cfg["auto"] is False  # sicher aus per Default
    cfg["enabled"] = True
    cfg["folders"] = [str(tmp_path / "a")]
    dw.save_cfg(cfg)
    assert dw.load_cfg()["enabled"] is True


def test_desktop_endpoints_and_ui():
    from fastapi.testclient import TestClient

    import core.api.server as s

    client = TestClient(s.app)
    d = client.get("/api/desktop").json()
    assert "config" in d and "preview" in d
    html = client.get("/").text
    for marker in ('id="dw-enabled"', 'id="dw-scan"', "loadDesktop", "Desktop-Pflege",
                   "api/desktop/scan"):
        assert marker in html, f"Desktop-Marker fehlt: {marker}"
