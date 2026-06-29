"""Gedaechtnis: episodisch / semantisch / prozedural in SQLite.

Recall laeuft ueber FTS5-Keyword-Suche (falls verfuegbar) + Recency-Fallback.
Vektor-Recall (sqlite-vec + Ollama-Embeddings) ist als Upgrade vorgesehen und
kann spaeter ohne Aenderung der Aufrufer ergaenzt werden.
"""
from __future__ import annotations

import re
import sqlite3
import time
import uuid

from core.config import DB_PATH

_HAS_FTS: bool | None = None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_memory() -> None:
    global _HAS_FTS
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id         TEXT PRIMARY KEY,
                ts         REAL NOT NULL,
                session_id TEXT,
                role       TEXT,   -- user | partner | system
                kind       TEXT,   -- episodic | semantic | procedural
                text       TEXT NOT NULL
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_memory_session ON memory(session_id, ts)")
        try:
            c.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(mem_id UNINDEXED, text)"
            )
            _HAS_FTS = True
        except sqlite3.OperationalError:
            _HAS_FTS = False


def remember(
    text: str,
    role: str = "user",
    kind: str = "episodic",
    session_id: str | None = None,
) -> str:
    mid = uuid.uuid4().hex
    with _conn() as c:
        c.execute(
            "INSERT INTO memory (id, ts, session_id, role, kind, text) VALUES (?,?,?,?,?,?)",
            (mid, time.time(), session_id, role, kind, text),
        )
        if _HAS_FTS:
            c.execute("INSERT INTO memory_fts (mem_id, text) VALUES (?,?)", (mid, text))
    return mid


def _fts_query(query: str) -> str:
    tokens = [t for t in re.findall(r"\w+", query.lower(), flags=re.UNICODE) if len(t) > 2]
    return " OR ".join(f'"{t}"' for t in tokens[:12])


def recall(query: str, limit: int = 6, exclude_session: str | None = None) -> list[dict]:
    """Holt relevante Erinnerungen: erst Keyword-Treffer, dann Recency-Fallback."""
    results: list[tuple] = []
    with _conn() as c:
        terms = _fts_query(query) if _HAS_FTS else ""
        if terms:
            sql = (
                "SELECT m.ts, m.role, m.text, m.session_id "
                "FROM memory_fts f JOIN memory m ON m.id = f.mem_id "
                "WHERE memory_fts MATCH ? "
            )
            params: list = [terms]
            if exclude_session:
                sql += "AND m.session_id IS NOT ? "
                params.append(exclude_session)
            sql += "ORDER BY rank LIMIT ?"
            params.append(limit)
            try:
                results = c.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                results = []
        if not results:
            sql = "SELECT ts, role, text, session_id FROM memory "
            params = []
            if exclude_session:
                sql += "WHERE session_id IS NOT ? "
                params.append(exclude_session)
            sql += "ORDER BY ts DESC LIMIT ?"
            params.append(limit)
            results = c.execute(sql, params).fetchall()
    return [{"ts": r[0], "role": r[1], "text": r[2], "session_id": r[3]} for r in results]


def recent_dialogue(session_id: str, limit: int = 10) -> list[dict]:
    """Letzte Gespraechszuege EINER Session, chronologisch (alt -> neu)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, text FROM memory "
            "WHERE session_id = ? AND kind = 'episodic' "
            "ORDER BY ts DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    rows.reverse()
    return [{"role": r[0], "text": r[1]} for r in rows]


def clear_session(session_id: str) -> int:
    """Loescht das episodische Gedaechtnis EINER Session (frischer Start im Chat).

    Identitaet (Verfassung/Seele/Ziel) bleibt unberuehrt; nur der Gespraechsverlauf
    dieser Session wird vergessen. Gibt die Anzahl geloeschter Eintraege zurueck.
    """
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM memory WHERE session_id=?", (session_id,)).fetchone()[0]
        c.execute("DELETE FROM memory WHERE session_id=?", (session_id,))
    return int(n)


def forget_matching(substrings: list[str], role: str | None = None) -> int:
    """Loescht Erinnerungen, deren Text einen der Teilstrings enthaelt (z.B. Fehlaussagen)."""
    deleted = 0
    with _conn() as c:
        rows = c.execute("SELECT id, text, role FROM memory").fetchall()
        for mid, text, r in rows:
            if role and r != role:
                continue
            if any(s.lower() in (text or "").lower() for s in substrings):
                c.execute("DELETE FROM memory WHERE id=?", (mid,))
                deleted += 1
    return deleted


def recall_lessons(limit: int = 5) -> list[str]:
    """Die juengsten gelernten Lektionen (aus der Reflexion)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT text FROM memory WHERE kind = 'lesson' ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r[0] for r in rows]
