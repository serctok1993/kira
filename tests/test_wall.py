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
    # PHRASES wurden injiziert (Platzhalter ist ersetzt)
    assert "/*__PHRASES__*/" not in body
