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
from core.kernel import events

_HAS_FTS: bool | None = None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")  # Nebenlaeufigkeit: bis 5s warten statt sofort locken
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
            c.execute("ALTER TABLE memory ADD COLUMN embedding TEXT")  # fuer semantisches Erinnern
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
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
    emb = None
    try:
        import json

        from core.mind.memory.embed import embed

        v = embed(text)
        emb = json.dumps(v) if v else None
    except Exception:
        emb = None
    with _conn() as c:
        c.execute(
            "INSERT INTO memory (id, ts, session_id, role, kind, text, embedding) VALUES (?,?,?,?,?,?,?)",
            (mid, time.time(), session_id, role, kind, text, emb),
        )
        if _HAS_FTS:
            c.execute("INSERT INTO memory_fts (mem_id, text) VALUES (?,?)", (mid, text))
    try:  # Verlauf mitschreiben (fuer die Gedaechtnis-Historie im Cockpit)
        events.emit("memory_add", {"mem_id": mid, "role": role, "kind": kind,
                                   "text": (text or "")[:500]}, session_id=session_id)
    except Exception:  # noqa: BLE001
        pass
    return mid


def _fts_query(query: str) -> str:
    tokens = [t for t in re.findall(r"\w+", query.lower(), flags=re.UNICODE) if len(t) > 2]
    return " OR ".join(f'"{t}"' for t in tokens[:12])


def recall(query: str, limit: int = 6, exclude_session: str | None = None) -> list[dict]:
    """Holt relevante Erinnerungen.

    Zuerst SEMANTISCH (Embeddings/Cosine) — findet Relevantes auch ohne gleiche
    Woerter. Fallback: Stichwort (FTS) bzw. Recency, wenn keine Embeddings da sind.
    """
    try:
        import json

        from core.mind.memory.embed import cosine, embed

        qv = embed(query)
        if qv:
            with _conn() as c:
                rows = c.execute(
                    "SELECT ts, role, text, session_id, embedding, kind FROM memory WHERE embedding IS NOT NULL"
                ).fetchall()
            scored = []
            for ts, role, text, sid, emb, kind in rows:
                if exclude_session and sid == exclude_session:
                    continue
                try:
                    v = json.loads(emb)
                except Exception:
                    continue
                sc = cosine(qv, v)
                if kind in ("fact", "lesson"):
                    sc += 0.05  # Wichtiges bevorzugt erinnern
                scored.append((sc, ts, role, text, sid))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = [x for x in scored if x[0] > 0.35][:limit]
            if top:
                return [{"ts": t, "role": r, "text": tx, "session_id": s} for _, t, r, tx, s in top]
    except Exception:
        pass

    # --- Fallback: Stichwort (FTS) bzw. Recency ---
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

    S7c-Haertung: NUR kind='episodic' wird geloescht — semantisches Wissen
    (Fakten/Lektionen/Skills) ist damit technisch garantiert sicher, selbst wenn
    es je eine session_id truege. Gibt die Anzahl geloeschter Eintraege zurueck.
    """
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM memory WHERE session_id=? AND kind='episodic'",
                      (session_id,)).fetchone()[0]
        c.execute("DELETE FROM memory WHERE session_id=? AND kind='episodic'", (session_id,))
    return int(n)


def sessions(limit: int = 25) -> list[dict]:
    """Konversationen (Cockpit + Telegram) fuer die Chat-Session-Liste, neueste zuerst."""
    with _conn() as c:
        rows = c.execute(
            "SELECT session_id, MAX(ts) AS last, COUNT(*) AS n FROM memory "
            "WHERE kind='episodic' AND session_id IS NOT NULL AND role IN ('user','partner') "
            "GROUP BY session_id ORDER BY last DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for sid, last, n in rows:
            tr = c.execute(
                "SELECT text FROM memory WHERE session_id=? AND role='user' AND kind='episodic' "
                "ORDER BY ts ASC LIMIT 1",
                (sid,),
            ).fetchone()
            title = ((tr[0].strip() if tr and tr[0] else "") or "(neue Unterhaltung)")[:60]
            out.append({
                "session_id": sid,
                "last": last,
                "count": n,
                "title": title,
                "channel": "telegram" if str(sid).startswith("telegram-") else "cockpit",
            })
    return out


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


def recent(limit: int = 60) -> list[dict]:
    """Juengste Erinnerungen (fuer die Gedaechtnis-Verwaltung im Dashboard)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ts, session_id, role, kind, text FROM memory ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": r[0], "ts": r[1], "session_id": r[2], "role": r[3], "kind": r[4], "text": r[5]} for r in rows]


def delete(mem_id: str) -> bool:
    old = role = None
    with _conn() as c:
        row = c.execute("SELECT text, role FROM memory WHERE id=?", (mem_id,)).fetchone()
        if row:
            old, role = row[0], row[1]
        c.execute("DELETE FROM memory WHERE id=?", (mem_id,))
        try:
            c.execute("DELETE FROM memory_fts WHERE mem_id=?", (mem_id,))
        except sqlite3.OperationalError:
            pass
    try:
        events.emit("memory_delete", {"mem_id": mem_id, "role": role, "text": (old or "")[:500]})
    except Exception:  # noqa: BLE001
        pass
    return True


def update_text(mem_id: str, text: str) -> bool:
    """Text einer Erinnerung aendern (inkl. FTS-Index + Embedding neu berechnen)."""
    emb = None
    try:
        import json as _j

        from core.mind.memory.embed import embed

        v = embed(text)
        emb = _j.dumps(v) if v else None
    except Exception:
        emb = None
    old = role = None
    with _conn() as c:
        row = c.execute("SELECT text, role FROM memory WHERE id=?", (mem_id,)).fetchone()
        if row:
            old, role = row[0], row[1]
        c.execute("UPDATE memory SET text=?, embedding=? WHERE id=?", (text, emb, mem_id))
        if _HAS_FTS:
            try:
                c.execute("DELETE FROM memory_fts WHERE mem_id=?", (mem_id,))
                c.execute("INSERT INTO memory_fts (mem_id, text) VALUES (?,?)", (mem_id, text))
            except sqlite3.OperationalError:
                pass
    try:  # Verlauf: alt -> neu (vorher/nachher nachvollziehbar)
        events.emit("memory_update", {"mem_id": mem_id, "role": role,
                    "old": (old or "")[:500], "new": (text or "")[:500]})
    except Exception:  # noqa: BLE001
        pass
    return True


def recall_lessons(limit: int = 5) -> list[str]:
    """Die juengsten gelernten Lektionen (aus der Reflexion)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT text FROM memory WHERE kind = 'lesson' ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r[0] for r in rows]


def recall_skills(limit: int = 6) -> list[str]:
    """Gelernte, wiederverwendbare Faehigkeiten (kind='skill')."""
    with _conn() as c:
        rows = c.execute(
            "SELECT text FROM memory WHERE kind = 'skill' ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r[0] for r in rows]


def all_skills() -> list[dict]:
    """Alle Skills (id + text) — fuer den Curator."""
    with _conn() as c:
        rows = c.execute("SELECT id, text FROM memory WHERE kind = 'skill' ORDER BY ts DESC").fetchall()
    return [{"id": r[0], "text": r[1]} for r in rows]


def all_lessons() -> list[dict]:
    """Alle Lektionen (id + text) — fuer den Curator (S4: Lektionen wachsen sonst unbegrenzt)."""
    with _conn() as c:
        rows = c.execute("SELECT id, text FROM memory WHERE kind = 'lesson' ORDER BY ts DESC").fetchall()
    return [{"id": r[0], "text": r[1]} for r in rows]


def backfill_embeddings(limit: int = 5000) -> int:
    """Alt-Eintraege ohne Embedding nachvektorisieren (lokal, 0 EUR) -> Anzahl.

    Ohne Embedding faellt recall() fuer diese Eintraege auf Stichwort/Recency
    zurueck — der Backfill macht das Gedaechtnis vollstaendig semantisch."""
    import json

    try:
        from core.mind.memory.embed import embed
    except Exception:  # noqa: BLE001
        return 0
    with _conn() as c:
        rows = c.execute("SELECT id, text FROM memory WHERE embedding IS NULL LIMIT ?", (limit,)).fetchall()
    done = 0
    for mid, text in rows:
        try:
            v = embed(text)
        except Exception:  # noqa: BLE001
            break
        if not v:
            break  # Embedder gerade nicht verfuegbar -> naechster Wartungslauf
        with _conn() as c:
            c.execute("UPDATE memory SET embedding=? WHERE id=?", (json.dumps(v), mid))
        done += 1
    return done
