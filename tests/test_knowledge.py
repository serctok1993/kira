"""S5.4: Wissens-Archiv — Chunking, Dedupe, Suche, Upload. Offline, Temp-DB+Vault."""
from __future__ import annotations

import pytest

from core.kernel import events
from core.mind import knowledge


def _setup(monkeypatch, tmp_path, vectors=False):
    monkeypatch.setattr(knowledge, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(knowledge, "_VAULT", tmp_path / "vault")
    if vectors:
        # deterministischer Mini-Embedder: Vektor = Wort-Haeufigkeiten fester Begriffe
        def fake_embed(t):
            t = t.lower()
            return [float(t.count(w)) for w in ("hosting", "preis", "kira", "vertrag", "seo")]
        monkeypatch.setattr(knowledge, "embed", fake_embed)
    else:
        monkeypatch.setattr(knowledge, "embed", lambda t: None)  # reiner FTS-Pfad
    events.init_db()
    knowledge.init_knowledge()


# --- Chunker -------------------------------------------------------------------

def test_chunk_short_text_single():
    assert knowledge._chunk("kurzer Text") == ["kurzer Text"]


def test_chunk_respects_paragraphs_and_size():
    paras = [f"Absatz {i}: " + ("wort " * 120) for i in range(6)]
    chunks = knowledge._chunk("\n\n".join(paras), size=1200, overlap=150)
    assert len(chunks) >= 2
    assert all(len(c) <= 1200 + 200 for c in chunks)  # Groessen-Disziplin (+Overlap-Toleranz)


def test_chunk_monster_paragraph_hard_split():
    chunks = knowledge._chunk("x" * 5000, size=1200, overlap=100)
    assert len(chunks) >= 4 and all(len(c) <= 1200 for c in chunks)


# --- Ingest / Dedupe / Delete ----------------------------------------------------

def test_ingest_dedupe_and_vault(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    res = knowledge.ingest_text("Hosting-Recherche", "Hetzner kostet 5 Euro. " * 30, source="paste")
    assert res["ok"] and res["chunks"] >= 1
    docs = knowledge.list_docs()
    assert len(docs) == 1 and docs[0]["title"] == "Hosting-Recherche"
    assert (tmp_path / "vault").exists() and any((tmp_path / "vault").iterdir())

    dup = knowledge.ingest_text("Anderer Titel", "Hetzner kostet 5 Euro. " * 30)
    assert dup["ok"] and dup.get("duplicate")  # gleicher Inhalt -> kein zweites Dokument
    assert len(knowledge.list_docs()) == 1

    assert "zu wenig Text" in knowledge.ingest_text("x", "kurz")["error"]
    assert knowledge.delete(docs[0]["id"])
    assert knowledge.list_docs() == []
    assert not any((tmp_path / "vault").iterdir())  # Original mit entsorgt


def test_ingest_file_types(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    ok = knowledge.ingest_file(("Markdown Inhalt. " * 20).encode(), "notizen.md")
    assert ok["ok"]
    html = b"<html><style>x{}</style><body><h1>Titel</h1><p>" + b"Echter Inhalt. " * 20 + b"</p></body></html>"
    ok2 = knowledge.ingest_file(html, "seite.html")
    assert ok2["ok"]
    hits = knowledge.search("echter Inhalt")
    assert hits and hits[0]["title"] == "seite.html"
    assert "style" not in hits[0]["text"]  # Tags/Styles rausgestrippt

    bad = knowledge.ingest_file(b"\x00\x01", "bild.exe")
    assert not bad["ok"] and "nicht unterstuetzt" in bad["error"]
    zu_gross = knowledge.ingest_file(b"x" * (16 * 1024 * 1024), "big.txt")
    assert not zu_gross["ok"]


def test_pdf_without_pypdf_gives_hint(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    import builtins
    real_import = builtins.__import__

    def block_pypdf(name, *a, **k):
        if name == "pypdf":
            raise ImportError("nope")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", block_pypdf)
    res = knowledge.ingest_file(b"%PDF-1.4 fake", "doku.pdf")
    assert not res["ok"] and "pypdf" in res["error"]  # klarer Hinweis statt Crash


def test_pdf_roundtrip_if_available(monkeypatch, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    _setup(monkeypatch, tmp_path)
    import io
    from pypdf import PdfWriter

    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    res = knowledge.ingest_file(buf.getvalue(), "leer.pdf")
    assert not res["ok"]  # leere Seite -> "kein extrahierbarer Text"
    assert "extrahierbar" in res["error"]


# --- Suche -----------------------------------------------------------------------

def test_search_fts_fallback(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)  # embed -> None: reiner Volltext-Pfad
    knowledge.ingest_text("Vertrag Hosting", "Der Hosting-Vertrag laeuft bis 2027 und kostet 60 Euro. " * 10)
    knowledge.ingest_text("SEO-Notizen", "Kira plant die SEO-Struktur fuer QS-Transporte. " * 10)
    hits = knowledge.search("hosting vertrag")
    assert hits and hits[0]["title"] == "Vertrag Hosting"
    assert knowledge.search("") == []


def test_search_semantic_path(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, vectors=True)
    knowledge.ingest_text("Hosting", "hosting hosting preis " * 40)
    knowledge.ingest_text("SEO", "seo kira seo " * 40)
    hits = knowledge.search("hosting preis", k=1)
    assert hits and hits[0]["title"] == "Hosting" and hits[0]["score"] is not None


# --- Upload-Endpoint (beweist zugleich python-multipart) ---------------------------

def test_upload_endpoint_roundtrip(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import core.api.server as srv

    _setup(monkeypatch, tmp_path)
    c = TestClient(srv.app)
    r = c.post("/api/knowledge/upload",
               files={"file": ("mein-doc.txt", ("Wichtiger Inhalt. " * 20).encode(), "text/plain")})
    assert r.status_code == 200 and r.json()["ok"]
    docs = c.get("/api/knowledge").json()["docs"]
    assert any(d["title"] == "mein-doc.txt" for d in docs)
    hits = c.get("/api/knowledge/search?q=wichtiger inhalt").json()["hits"]
    assert hits
