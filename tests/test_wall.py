"""Phase 1 — Desktop-Wallpaper-Seite /wall + Live-Obsidian-Vault-Graph.

Prueft den rein lesenden Graph-Bau (Notizen + [[Verlinkungen]]) und dass die Seite/Endpoint
sauber ausgeliefert werden.
"""
from __future__ import annotations

from starlette.testclient import TestClient

from core.api import vault_graph
from core.api.server import app


# ---- Vault-Graph aus echten Markdown-Dateien ----------------------------------------

def test_graph_liest_notizen_und_wikilinks(tmp_path):
    ged = tmp_path / "gedaechtnis" / "stammbaum"
    ged.mkdir(parents=True)
    (ged / "sergen.md").write_text("Wurzel. Siehe [[luvex]] und [[qs-transporte]].", encoding="utf-8")
    (ged / "luvex.md").write_text("Business. Gehoert zu [[sergen]].", encoding="utf-8")
    pb = tmp_path / "playbooks"
    pb.mkdir()
    (pb / "akquise.md").write_text("kein Link hier", encoding="utf-8")

    g = vault_graph.build_graph([tmp_path / "gedaechtnis", tmp_path / "playbooks"])
    ids = {n["id"].lower() for n in g["nodes"]}
    assert {"sergen", "luvex", "qs-transporte", "akquise"} <= ids   # Notizen + unaufgeloestes Ziel
    assert g["counts"]["notes"] == 3                                # 3 echte .md-Dateien
    # Kanten: sergen->luvex, sergen->qs-transporte, luvex->sergen
    edges = {(l["source"].lower(), l["target"].lower()) for l in g["links"]}
    assert ("sergen", "luvex") in edges and ("luvex", "sergen") in edges
    # Gruppe/Farbe je Bereich (stammbaum = Lila, playbooks = Gruen)
    grp = {n["id"].lower(): n["group"] for n in g["nodes"]}
    assert grp["sergen"] == "stammbaum" and grp["akquise"] == "playbooks"


def test_graph_leerer_ordner_raist_nicht(tmp_path):
    g = vault_graph.build_graph([tmp_path / "nix"])
    assert g == {"nodes": [], "links": [], "counts": {"notes": 0, "links": 0}}


# ---- Endpoint + Seite ---------------------------------------------------------------

def test_api_vault_graph_liefert_struktur():
    c = TestClient(app)
    r = c.get("/api/vault/graph")
    assert r.status_code == 200
    d = r.json()
    assert "nodes" in d and "links" in d and "counts" in d
    assert isinstance(d["nodes"], list) and isinstance(d["links"], list)


def test_wall_seite_wird_ausgeliefert():
    c = TestClient(app)
    r = c.get("/wall")
    assert r.status_code == 200
    body = r.text
    # Kern-Bausteine der rahmenlosen Seite
    for m in ('id="graph"', 'class="edge"', 'id="bar"', 'id="srow"', 'data-mode="chat"'):
        assert m in body, f"Baustein fehlt: {m}"
    # ephemerer Chat ueber den bestehenden WS (frische desktop-Session) + Cockpit-Farbanpassung uebernommen
    assert "/ws/chat?sid=" in body and '"desktop-"' in body
    assert "kira_custom" in body
    # Wall v2: wechselbares Hintergrundbild (/api/bg), Modellwechsel per Klick, echtes Reasoning
    assert 'id="bg" src="/api/bg"' in body
    assert 'id="mpop"' in body and "/api/model/role" in body and "/api/model/catalog" in body
    assert 'm.kind==="think"' in body and "reasonBuf" in body   # Reasoning wird angezeigt
    assert "/api/news" in body                                   # zusaetzliche Stat
    # PHRASES wurden injiziert (Platzhalter ist ersetzt)
    assert "/*__PHRASES__*/" not in body


def test_vault_graph_nimmt_config_obsidian_pfad(monkeypatch, tmp_path):
    # desktop.vault_paths in der Config -> der echte Obsidian-Vault fliesst in den Graph
    import core.config as cfg
    from core.api import vault_graph
    monkeypatch.setitem(cfg.CONFIG, "desktop", {"vault_paths": [str(tmp_path)]})
    roots = vault_graph._default_roots()
    assert tmp_path in roots
    assert (cfg.ROOT / "gedaechtnis") in roots   # Kiras Gedaechtnis bleibt immer dabei
