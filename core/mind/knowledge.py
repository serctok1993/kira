"""Wissens-Archiv: Sergens 'fertiger Schreibtisch' (S5).

Dokumente/Notizen werden hier abgelegt (Original in data/knowledge/) und in
Chunks mit lokalen Embeddings + Volltext-Index durchsuchbar gemacht — damit
JEDE kuenftige KI in diesem Harness sofort auf Sergens Wissen zugreifen kann.

Bewusst getrennt vom Gedaechtnis (memory = Erlebtes/Fakten, klein) und von den
Secrets (write-only Credentials): das Archiv ist INHALT, beliebig gross,
werkzeug-basiert abgerufen (knowledge_search) statt in jeden Prompt injiziert
(Kontext-Diaet). PDF via pypdf (optional — fehlt es, gibt es einen klaren
Hinweis statt eines Fehlers).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid

from core.config import DATA_DIR, DB_PATH

_VAULT = DATA_DIR / "knowledge"
_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 150


def embed(text: str):  # modul-global -> in Tests patchbar (wie memory)
    try:
        from core.mind.memory.embed import embed as _e

        return _e(text)
    except Exception:  # noqa: BLE001
        return None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_knowledge() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_docs (
                id     TEXT PRIMARY KEY,
                ts     REAL NOT NULL,
                title  TEXT NOT NULL,
                source TEXT,               -- paste | upload | telegram | note
                tags   TEXT,
                hash   TEXT,               -- sha256 -> Dedupe
                bytes  INTEGER,
                path   TEXT,               -- Original im Vault (oder NULL bei Notizen)
                chunks INTEGER
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id        TEXT PRIMARY KEY,
                doc_id    TEXT NOT NULL,
                chunk_no  INTEGER,
                text      TEXT NOT NULL,
                embedding TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_kchunks_doc ON knowledge_chunks(doc_id)")
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(chunk_id UNINDEXED, text)")
        except sqlite3.OperationalError:
            pass


def _chunk(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Absatzbewusstes Chunking: an Leerzeilen sammeln, harte Grenzen nur im Notfall."""
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    paras = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    cur = ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        while len(p) > size:  # Monster-Absatz hart teilen
            head, p = p[:size], p[max(0, size - overlap):]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if len(cur) + len(p) + 2 <= size:
            cur = (cur + "\n\n" + p).strip()
        else:
            chunks.append(cur)
            cur = (cur[-overlap:] + "\n\n" + p).strip() if overlap else p
    if cur:
        chunks.append(cur)
    return chunks


def ingest_text(title: str, text: str, source: str = "paste", tags: str = "",
                original: bytes | None = None, ext: str = "") -> dict:
    """Text ins Archiv: Dedupe -> Vault -> Chunks -> Embeddings/FTS."""
    init_knowledge()
    norm = " ".join((text or "").split())
    if len(norm) < 20:
        return {"ok": False, "error": "zu wenig Text (min. 20 Zeichen)"}
    h = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    with _conn() as c:
        row = c.execute("SELECT id, title FROM knowledge_docs WHERE hash=?", (h,)).fetchone()
    if row:
        return {"ok": True, "duplicate": True, "doc_id": row[0], "title": row[1]}

    did = uuid.uuid4().hex
    path = None
    try:
        _VAULT.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", (title or "doc"))[:60]
        p = _VAULT / f"{did[:8]}-{safe}{ext or '.txt'}"
        p.write_bytes(original if original is not None else text.encode("utf-8"))
        path = str(p)
    except Exception:  # noqa: BLE001 — Vault ist Komfort, Index ist Pflicht
        pass

    chunks = _chunk(text)
    with _conn() as c:
        for i, ch in enumerate(chunks):
            cid = uuid.uuid4().hex
            v = embed(ch)
            c.execute("INSERT INTO knowledge_chunks (id, doc_id, chunk_no, text, embedding) VALUES (?,?,?,?,?)",
                      (cid, did, i, ch, json.dumps(v) if v else None))
            try:
                c.execute("INSERT INTO knowledge_fts (chunk_id, text) VALUES (?,?)", (cid, ch))
            except sqlite3.OperationalError:
                pass
        c.execute("INSERT INTO knowledge_docs (id, ts, title, source, tags, hash, bytes, path, chunks) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (did, time.time(), (title or "Ohne Titel")[:200], source, tags, h,
                   len(text.encode('utf-8')), path, len(chunks)))
    try:
        from core.kernel import events

        events.emit("knowledge_ingested", {"doc_id": did, "title": title[:120],
                                           "source": source, "chunks": len(chunks)})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "doc_id": did, "chunks": len(chunks)}


def _extract(data: bytes, filename: str) -> tuple[str | None, str]:
    """(text, fehler) aus Datei-Bytes — nach Endung."""
    name = filename.lower()
    if name.endswith((".txt", ".md", ".markdown", ".csv", ".log", ".json", ".yaml", ".yml")):
        return data.decode("utf-8", errors="replace"), ""
    if name.endswith((".html", ".htm")):
        raw = data.decode("utf-8", errors="replace")
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", raw).strip(), ""
    if name.endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader
        except ImportError:
            return None, "pypdf fehlt — Sergen: einmal 'uv add pypdf' (steht auf der Neustart-Checkliste)."
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
            if len(text.strip()) < 20:
                return None, "kein extrahierbarer Text (Scan-PDF ohne Textebene?)"
            return text, ""
        except Exception as e:  # noqa: BLE001
            return None, f"PDF unlesbar: {e}"
    return None, f"Dateityp nicht unterstuetzt: {filename} (txt/md/html/pdf gehen)"


def ingest_file(data: bytes, filename: str, source: str = "upload", tags: str = "") -> dict:
    if len(data) > 15 * 1024 * 1024:
        return {"ok": False, "error": "Datei zu gross (max 15 MB)"}
    text, err = _extract(data, filename)
    if text is None:
        return {"ok": False, "error": err}
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".txt"
    return ingest_text(filename, text, source=source, tags=tags, original=data, ext=ext)


def search(query: str, k: int = 5) -> list[dict]:
    """Top-k Chunks: semantisch (Cosine) wenn Embeddings da, sonst FTS-Stichwort."""
    init_knowledge()
    q = (query or "").strip()
    if not q:
        return []
    docs: dict[str, str] = {}
    with _conn() as c:
        for did, title in c.execute("SELECT id, title FROM knowledge_docs"):
            docs[did] = title

    qv = embed(q)
    if qv:
        try:
            from core.mind.memory.embed import cosine

            with _conn() as c:
                rows = c.execute("SELECT doc_id, chunk_no, text, embedding FROM knowledge_chunks "
                                 "WHERE embedding IS NOT NULL").fetchall()
            scored = []
            for did, no, text, emb in rows:
                try:
                    sc = cosine(qv, json.loads(emb))
                except Exception:  # noqa: BLE001
                    continue
                scored.append((sc, did, no, text))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = [x for x in scored if x[0] > 0.3][:k]
            if top:
                return [{"doc_id": d, "title": docs.get(d, "?"), "chunk_no": n,
                         "text": t, "score": round(s, 3)} for s, d, n, t in top]
        except Exception:  # noqa: BLE001
            pass

    # FTS-Fallback
    tokens = [t for t in re.findall(r"\w+", q.lower()) if len(t) > 2][:10]
    if not tokens:
        return []
    with _conn() as c:
        try:
            rows = c.execute(
                "SELECT f.chunk_id, f.text FROM knowledge_fts f WHERE knowledge_fts MATCH ? "
                "ORDER BY rank LIMIT ?",  # bm25: beste Uebereinstimmung zuerst (wie memory-FTS)
                (" OR ".join(f'"{t}"' for t in tokens), k),
            ).fetchall()
            out = []
            for cid, text in rows:
                d = c.execute("SELECT doc_id, chunk_no FROM knowledge_chunks WHERE id=?", (cid,)).fetchone()
                if d:
                    out.append({"doc_id": d[0], "title": docs.get(d[0], "?"),
                                "chunk_no": d[1], "text": text, "score": None})
            return out
        except sqlite3.OperationalError:
            return []


def list_docs(limit: int = 100) -> list[dict]:
    init_knowledge()
    cols = ["id", "ts", "title", "source", "tags", "bytes", "chunks", "path"]
    with _conn() as c:
        rows = c.execute(f"SELECT {', '.join(cols)} FROM knowledge_docs "
                         f"ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def delete(doc_id: str) -> bool:
    init_knowledge()
    with _conn() as c:
        row = c.execute("SELECT path FROM knowledge_docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return False
        ids = [r[0] for r in c.execute("SELECT id FROM knowledge_chunks WHERE doc_id=?", (doc_id,))]
        c.execute("DELETE FROM knowledge_chunks WHERE doc_id=?", (doc_id,))
        for cid in ids:
            try:
                c.execute("DELETE FROM knowledge_fts WHERE chunk_id=?", (cid,))
            except sqlite3.OperationalError:
                pass
        c.execute("DELETE FROM knowledge_docs WHERE id=?", (doc_id,))
    if row[0]:
        try:
            from pathlib import Path

            Path(row[0]).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    return True
