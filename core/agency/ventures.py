"""Ventures: Kiras Unternehmungen als First-Class-Objekte (persistent in state.db).

Ein Venture ist ein Einkommens-Projekt mit eigener Akte: Hypothese, Status,
Meilenstein (EUR) — und einem eigenen Konto-Buch (venture_ledger) mit Einnahmen/
Ausgaben. So denkt Kira in ROI statt in Aktivitaet: Was bringt dieses Standbein
ein, was kostet es, wie weit ist der Meilenstein?

Geld-Wahrheit (kein Doppelzaehlen): Das Treasury (Budget-Autoritaet) summiert NUR
llm_call- und spend-Events. book() emittiert lediglich ein venture_book-Event
(informativ). Echte AUSGABEN laufen ueber treasury.record_spend(venture_id=...),
das zusaetzlich hier ins Ledger bucht — ein Schreibpfad, zwei Sichten.
EUR/USD werden wie im Treasury vereinfachend gleichgesetzt.
"""
from __future__ import annotations

import sqlite3
import time
import uuid

from core.config import DB_PATH
from core.kernel import events

STATUSES = ("idea", "building", "live", "scaling", "paused", "dead")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_ventures() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ventures (
                id            TEXT PRIMARY KEY,
                ts            REAL NOT NULL,
                name          TEXT NOT NULL,
                status        TEXT DEFAULT 'idea',   -- idea|building|live|scaling|paused|dead
                hypothesis    TEXT,
                milestone_eur REAL,
                notes         TEXT,
                updated_ts    REAL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS venture_ledger (
                id         TEXT PRIMARY KEY,
                ts         REAL NOT NULL,
                venture_id TEXT NOT NULL,
                direction  TEXT NOT NULL,             -- in | out
                amount_eur REAL NOT NULL,
                category   TEXT DEFAULT 'misc',
                note       TEXT,
                ref        TEXT                       -- z.B. Stripe-ID -> Sync-Dedupe
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_vledger_venture ON venture_ledger(venture_id, ts)")
        # UNIQUE nur fuer gesetzte refs: erlaubt beliebig viele manuelle Buchungen (ref NULL),
        # verhindert aber doppelte Sync-Buchungen derselben externen Zahlung.
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vledger_ref ON venture_ledger(ref) WHERE ref IS NOT NULL")


def add(name: str, hypothesis: str = "", milestone_eur: float | None = None,
        status: str = "idea", notes: str | None = None) -> str:
    init_ventures()
    vid = uuid.uuid4().hex
    status = status if status in STATUSES else "idea"
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO ventures (id, ts, name, status, hypothesis, milestone_eur, notes, updated_ts) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (vid, now, name.strip(), status, hypothesis, milestone_eur, notes, now),
        )
    events.emit("venture_created", {"id": vid, "name": name.strip(), "status": status})
    return vid


def update(vid: str, **fields) -> bool:
    allowed = {"name", "status", "hypothesis", "milestone_eur", "notes"}
    if "status" in fields and fields["status"] not in STATUSES:
        fields.pop("status")
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return False
    sets.append("updated_ts=?")
    params.append(time.time())
    params.append(vid)
    with _conn() as c:
        cur = c.execute(f"UPDATE ventures SET {', '.join(sets)} WHERE id=?", params)
    return cur.rowcount > 0


_V_COLS = ["id", "ts", "name", "status", "hypothesis", "milestone_eur", "notes", "updated_ts"]


def get(vid: str) -> dict | None:
    init_ventures()
    with _conn() as c:
        row = c.execute(f"SELECT {', '.join(_V_COLS)} FROM ventures WHERE id=?", (vid,)).fetchone()
    return dict(zip(_V_COLS, row)) if row else None


def list_all(include_dead: bool = False) -> list[dict]:
    init_ventures()
    with _conn() as c:
        rows = c.execute(
            f"SELECT {', '.join(_V_COLS)} FROM ventures ORDER BY ts ASC"
        ).fetchall()
    out = [dict(zip(_V_COLS, r)) for r in rows]
    return out if include_dead else [v for v in out if v["status"] != "dead"]


def book(venture_id: str, direction: str, amount_eur: float, category: str = "misc",
         note: str = "", ref: str | None = None) -> str:
    """Eine Buchung ins Venture-Konto-Buch. direction 'in' (Einnahme) | 'out' (Ausgabe).

    Duplikat-Schutz: gleicher ref (z.B. Stripe-ID) wird still verworfen (Sync-Idempotenz).
    Emittiert nur venture_book (Treasury zaehlt das NICHT — kein Doppelzaehlen)."""
    init_ventures()
    if direction not in ("in", "out"):
        raise ValueError(f"direction muss 'in' oder 'out' sein, nicht {direction!r}")
    lid = uuid.uuid4().hex
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO venture_ledger (id, ts, venture_id, direction, amount_eur, category, note, ref) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (lid, time.time(), venture_id, direction, float(amount_eur), category, note[:500], ref),
            )
    except sqlite3.IntegrityError:
        return ""  # ref schon gebucht -> Dedupe, keine zweite Zeile
    events.emit("venture_book", {"venture_id": venture_id, "direction": direction,
                                 "amount_eur": float(amount_eur), "category": category,
                                 "note": note[:200], "ref": ref})
    return lid


def ledger(venture_id: str, limit: int = 100) -> list[dict]:
    init_ventures()
    cols = ["id", "ts", "direction", "amount_eur", "category", "note", "ref"]
    with _conn() as c:
        rows = c.execute(
            f"SELECT {', '.join(cols)} FROM venture_ledger WHERE venture_id=? ORDER BY ts DESC LIMIT ?",
            (venture_id, limit),
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def balance(venture_id: str) -> float:
    """Kasse des Ventures: SUM(in) - SUM(out)."""
    init_ventures()
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(CASE direction WHEN 'in' THEN amount_eur ELSE -amount_eur END), 0) "
            "FROM venture_ledger WHERE venture_id=?",
            (venture_id,),
        ).fetchone()
    return round(float(row[0]), 2)


def summary() -> list[dict]:
    """Pro Venture: Einnahmen/Ausgaben/Kasse + Meilenstein-Fortschritt (fuers Cockpit/Standup)."""
    init_ventures()
    out = []
    with _conn() as c:
        for v in list_all(include_dead=True):
            row = c.execute(
                "SELECT COALESCE(SUM(CASE direction WHEN 'in' THEN amount_eur ELSE 0 END), 0), "
                "       COALESCE(SUM(CASE direction WHEN 'out' THEN amount_eur ELSE 0 END), 0) "
                "FROM venture_ledger WHERE venture_id=?",
                (v["id"],),
            ).fetchone()
            income, expenses = round(float(row[0]), 2), round(float(row[1]), 2)
            ms = v.get("milestone_eur")
            v2 = dict(v)
            v2.update({
                "income_eur": income,
                "expenses_eur": expenses,
                "balance_eur": round(income - expenses, 2),
                "milestone_progress": (min(100, round(100 * income / ms)) if ms else None),
            })
            out.append(v2)
    return out


# ---- Projekt-Gedaechtnis (S8.2): Briefing + Dateien + Kosten je Venture -----------

def _briefing_path(vid: str):
    """Pfad des Projekt-Briefings (Sergens Daueranweisungen) — Muster: workingset."""
    import re as _re
    from pathlib import Path as _Path

    from core.config import DATA_DIR
    safe = _re.sub(r"[^A-Za-z0-9_-]", "", str(vid))[:64] or "unbekannt"
    return _Path(DATA_DIR) / "workspace" / f"venture-{safe}-briefing.md"


def briefing(vid: str, max_chars: int = 1500) -> str:
    """Sergens Projekt-Anweisungen (bindend), fuer die Prompt-Injektion. '' wenn leer."""
    p = _briefing_path(vid)
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    nl = tail.find("\n")
    return tail[nl + 1:] if 0 <= nl < len(tail) - 1 else tail


def set_briefing(vid: str, text: str) -> None:
    from core.kernel.fs import atomic_write

    atomic_write(_briefing_path(vid), (text or "").strip() + "\n")
    events.emit("venture_briefing_set", {"venture_id": vid, "chars": len(text or "")})


def append_briefing(vid: str, note: str) -> None:
    """Eine Daueranweisung mit Datum anhaengen (project_note-Pfad)."""
    p = _briefing_path(vid)
    old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    stamp = time.strftime("%Y-%m-%d")
    from core.kernel.fs import atomic_write

    atomic_write(p, old + f"- [{stamp}] {note.strip()}\n")
    events.emit("venture_briefing_note", {"venture_id": vid, "note": note[:160]})


def files_dir(vid: str):
    """Ablage fuer Projekt-Dateien (Anhaenge, Bilder) — wird bei Bedarf angelegt."""
    import re as _re
    from pathlib import Path as _Path

    from core.config import DATA_DIR
    safe = _re.sub(r"[^A-Za-z0-9_-]", "", str(vid))[:64] or "unbekannt"
    d = _Path(DATA_DIR) / "workspace" / f"venture-{safe}-files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_files(vid: str) -> list[dict]:
    d = files_dir(vid)
    out = []
    for f in sorted(d.iterdir()):
        if f.is_file():
            out.append({"name": f.name, "bytes": f.stat().st_size, "path": str(f)})
    return out


def costs(vid: str) -> float:
    """LLM-Kosten des Projekts bislang (S8.2): Summe der Task-Versuche ueber die Kette
    outcomes.cost_usd -> tasks.objective_id -> objectives.venture_id. Kein ROI-Denken —
    nur 'was hat es gekostet'."""
    with _conn() as c:
        try:
            row = c.execute(
                "SELECT COALESCE(SUM(o.cost_usd), 0) FROM outcomes o "
                "JOIN tasks t ON t.id = o.task_id "
                "JOIN objectives ob ON ob.id = t.objective_id "
                "WHERE ob.venture_id = ?", (vid,),
            ).fetchone()
        except sqlite3.OperationalError:  # Tabellen fehlen noch (frische DB)
            return 0.0
    return round(float(row[0] or 0.0), 4)
