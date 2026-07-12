"""Gedaechtnis-Browser (B-024): ganzer Vault im Cockpit — mit Traversal-Guard."""
from __future__ import annotations

from fastapi.testclient import TestClient

import core.api.server as s
import core.config as _c
from core.kernel import events


def _roots(monkeypatch, tmp_path):
    """Vault-Wurzeln auf tmp umbiegen, damit Tests nie echte Dateien anfassen."""
    g = tmp_path / "gedaechtnis"
    (g / "stammbaum").mkdir(parents=True)
    (g / "LIES-MICH.md").write_text("# Regeln", encoding="utf-8")
    (g / "stammbaum" / "MIA.md").write_text("# Wurzel\n- geburtstag: ???", encoding="utf-8")
    p = tmp_path / "playbooks"
    p.mkdir()
    (p / "akquise-email.md").write_text("---\nname: x\n---\nBody", encoding="utf-8")
    (p / "notiz.txt").write_text("kein markdown", encoding="utf-8")
    monkeypatch.setattr(s, "_VAULT_ROOTS", {"gedaechtnis": g, "playbooks": p})
    monkeypatch.setattr(_c, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()


def test_resolve_guard(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    ok = s._vault_resolve("gedaechtnis/stammbaum/MIA.md")
    assert ok and ok.name == "MIA.md"
    assert s._vault_resolve("gedaechtnis\\LIES-MICH.md")  # Windows-Slashes normalisiert
    assert s._vault_resolve("gedaechtnis/../core/mind/SOUL.md") is None   # Traversal
    assert s._vault_resolve("playbooks/notiz.txt") is None                # nur .md
    assert s._vault_resolve("core/mind/SOUL.md") is None                  # fremde Wurzel
    assert s._vault_resolve("gedaechtnis") is None                        # Wurzel selbst
    assert s._vault_resolve("") is None


def test_vault_listing(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    d = TestClient(s.app).get("/api/vault").json()
    paths = [f["path"] for f in d["files"]]
    assert "gedaechtnis/LIES-MICH.md" in paths
    assert "gedaechtnis/stammbaum/MIA.md" in paths
    assert "playbooks/akquise-email.md" in paths
    assert all(p.endswith(".md") for p in paths)          # .txt bleibt draussen
    assert all("name" in f for f in d["files"])


def test_vault_read_and_save(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    cl = TestClient(s.app)
    f = cl.get("/api/vault/file", params={"path": "gedaechtnis/stammbaum/MIA.md"}).json()
    assert "geburtstag: ???" in f["content"] and f["editable"]

    r = cl.post("/api/vault/file", json={"path": "gedaechtnis/stammbaum/MIA.md",
                                         "content": "# Wurzel\n- geburtstag: 01.01.1993"}).json()
    assert r["ok"]
    p = tmp_path / "gedaechtnis" / "stammbaum" / "MIA.md"
    assert "01.01.1993" in p.read_text(encoding="utf-8")
    baks = list((tmp_path / "data" / "vault_history").glob("*.bak"))
    assert len(baks) == 1 and "???" in baks[0].read_text(encoding="utf-8")  # Undo-Spur
    assert any(e["type"] == "file_edited" for e in events.recent(5))


def test_vault_save_creates_new_leaf(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    r = TestClient(s.app).post("/api/vault/file", json={
        "path": "gedaechtnis/stammbaum/business/neu.md", "content": "# Neuer Ast"}).json()
    assert r["ok"]
    assert (tmp_path / "gedaechtnis" / "stammbaum" / "business" / "neu.md").exists()


def test_vault_save_rejects_escape(monkeypatch, tmp_path):
    _roots(monkeypatch, tmp_path)
    cl = TestClient(s.app)
    for bad in ("gedaechtnis/../../etc/passwd.md", "core/mind/SOUL.md", "playbooks/x.txt"):
        r = cl.post("/api/vault/file", json={"path": bad, "content": "boese"}).json()
        assert not r["ok"] and "nicht erlaubt" in r["error"]
    f = cl.get("/api/vault/file", params={"path": "gedaechtnis/../config.yaml.md"}).json()
    assert "error" in f


def test_cockpit_zeigt_vault_browser():
    html = TestClient(s.app).get("/").text
    assert "openVaultFile" in html and "/api/vault" in html
