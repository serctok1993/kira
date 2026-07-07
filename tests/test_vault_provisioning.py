"""Auto-Provisionierung: ein neues Business bekommt automatisch seinen Stammbaum-Ast
aus _VORLAGE.md — die Grundlage dafuer, dass Kira ihre eigene Ordnung selbst weiterbaut.
"""
from __future__ import annotations


def _tmp(monkeypatch, tmp_path):
    from core.kernel import events
    from core.agency import ventures
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(ventures, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    # Vault-Wurzel auf tmp umbiegen (echte _VORLAGE als Basis kopieren)
    import core.config as cfg
    from pathlib import Path
    real_vorlage = Path(cfg.ROOT) / "gedaechtnis" / "stammbaum" / "business" / "_VORLAGE.md"
    base = tmp_path / "gedaechtnis" / "stammbaum" / "business"
    base.mkdir(parents=True)
    (base / "_VORLAGE.md").write_text(real_vorlage.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    return ventures, tmp_path


def test_ensure_vault_leaf_legt_ast_an(monkeypatch, tmp_path):
    ventures, root = _tmp(monkeypatch, tmp_path)
    res = ventures.ensure_vault_leaf("Neue Bäckerei", vid="abc123")
    assert res["created"] is True
    leaf = root / "gedaechtnis" / "stammbaum" / "business" / "neue-baeckerei.md"
    assert leaf.exists()
    txt = leaf.read_text(encoding="utf-8")
    assert txt.startswith("# Neue Bäckerei")       # Name eingesetzt
    assert "venture-id (falls angelegt): abc123" in txt  # vid eingetragen
    assert "kurzbeschreibung: ???" in txt           # ???-Felder bleiben zum Fuellen


def test_ensure_vault_leaf_idempotent(monkeypatch, tmp_path):
    ventures, root = _tmp(monkeypatch, tmp_path)
    ventures.ensure_vault_leaf("QS Transporte", vid="v1")
    again = ventures.ensure_vault_leaf("QS Transporte", vid="v2")
    assert again["created"] is False and again.get("reason") == "exists"
    # bestehendes Blatt wird NICHT ueberschrieben (v1 bleibt)
    leaf = root / "gedaechtnis" / "stammbaum" / "business" / "qs-transporte.md"
    assert "v1" in leaf.read_text(encoding="utf-8")


def test_venture_add_provisioniert_automatisch(monkeypatch, tmp_path):
    ventures, root = _tmp(monkeypatch, tmp_path)
    ventures.init_ventures()
    vid = ventures.add("Solaranlagen Koblenz")
    leaf = root / "gedaechtnis" / "stammbaum" / "business" / "solaranlagen-koblenz.md"
    assert leaf.exists()
    from core.kernel import events
    assert "stammbaum_leaf_created" in [e["type"] for e in events.recent(20)]
    assert vid  # Venture-Anlage liefert weiterhin die id


def test_user_md_traegt_selbststaendigkeit():
    from core.config import ROOT
    user = (ROOT / "core" / "mind" / "USER.md").read_text(encoding="utf-8")
    assert "Wissenslücke = Struktur" in user
    assert "venture_add" in user and "neuer Ast" in user
