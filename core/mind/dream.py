"""dream (P7, grok-Muster): naechtliche Verdichtung episodisch -> dauerhaft.

Abgeschlossene, alte Chat-Sessions werden zu hoechstens 3 KERN-Erinnerungen
(kind='dream') verdichtet; der Rohverlauf faellt danach — mit zeilenweisem
Backup (data/backups/), nichts ist unwiederbringlich weg. Das loest das
Episodic-Aergernis: Muell ("asdf", Tipp-Tests) verwaessert nicht mehr jeden
Recall, Wichtiges ueberlebt als praegnanter Satz.

"Cheapest gate first" (alle Gates VOR dem ersten LLM-Call, billigste zuerst):
  1. enabled        — config dream.enabled (ein Blick in die Config)
  2. reife Sessions — genug alte, abgeschlossene Sessions (eine SQL-Abfrage)
  3. Lock           — data/dream.lock; NUR Zeitstempel-Staleness, KEIN
                      os.kill(pid, 0) (toetet auf Windows — Lehre aus #169)
Das Zeit-Gate (hoechstens 1x pro min_hours) haelt der Runner via
maintenance.maybe_run — derselbe Mechanismus wie bei allen Pflege-Jobs.

Konservativ wie der Curator: geloescht wird NUR, wenn das Modell sauber
antwortet (KERN-Zeilen oder exakt NICHTS). Unparsebares laesst die Session
unangetastet und beendet den Lauf.
"""
from __future__ import annotations

import json
import time
import uuid

from core.config import CONFIG, DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write

_LOCK = DATA_DIR / "dream.lock"
_LOCK_STALE_S = 2 * 3600

_SYSTEM = (
    "Du bist der Gedaechtnis-Verdichter eines Partner-Agenten. Du entscheidest "
    "nuechtern, was aus einem alten Gespraech DAUERHAFT wert ist, erinnert zu "
    "werden — und wirfst den Rest weg. Du erfindest nichts dazu."
)


def _cfg() -> dict:
    d = CONFIG.get("dream")
    return d if isinstance(d, dict) else {}


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def intervall_s() -> int:
    try:
        return int(float(_cfg().get("min_hours", 24)) * 3600)
    except Exception:  # noqa: BLE001
        return 24 * 3600


def _int(key: str, default: int) -> int:
    try:
        return int(_cfg().get(key, default))
    except Exception:  # noqa: BLE001
        return default


def _lock_setzen() -> bool:
    """True = Lock gehoert jetzt uns. Frischer Fremd-Lock -> False."""
    try:
        if _LOCK.exists():
            alter = time.time() - float(json.loads(_LOCK.read_text(encoding="utf-8")).get("ts", 0))
            if alter < _LOCK_STALE_S:
                return False
        atomic_write(_LOCK, json.dumps({"ts": time.time()}))
        return True
    except Exception:  # noqa: BLE001
        return False


def _lock_loesen() -> None:
    try:
        _LOCK.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _reife_sessions(min_alter_s: int, limit: int) -> list[str]:
    """Sessions, deren LETZTER episodischer Eintrag aelter als min_alter_s ist —
    abgeschlossene Gespraeche, keine laufenden. Ephemere nie (test-/bench-/desktop-)."""
    from core.mind.memory import store

    grenze = time.time() - min_alter_s
    with store._conn() as c:
        rows = c.execute(
            "SELECT session_id, MAX(ts) AS last FROM memory "
            "WHERE kind='episodic' AND session_id IS NOT NULL "
            "GROUP BY session_id HAVING last < ? ORDER BY last ASC LIMIT ?",
            (grenze, limit),
        ).fetchall()
    return [sid for sid, _ in rows if not store._is_ephemeral(sid)]


def _dialog_text(session_id: str, cap: int = 6000) -> str:
    from core.mind.memory import store

    with store._conn() as c:
        rows = c.execute(
            "SELECT role, text FROM memory WHERE session_id=? AND kind='episodic' ORDER BY ts ASC",
            (session_id,),
        ).fetchall()
    zeilen = [f"{r or '?'}: {(t or '').strip()[:400]}" for r, t in rows]
    text = "\n".join(zeilen)
    if len(text) > cap:  # Anfang + Ende behalten — dort stehen Anliegen und Ausgang
        text = text[: cap // 2] + "\n[…]\n" + text[-cap // 2:]
    return text


def _kerne_erfragen(dialog: str) -> list[str] | None:
    """Hoechstens 3 'KERN:'-Zeilen, [] bei explizitem NICHTS, None bei Unparsebarem."""
    from core.kernel import llm_router

    prompt = (
        "Hier ist ein abgeschlossenes, altes Gespraech (chronologisch):\n\n"
        f"{dialog}\n\n"
        "Extrahiere daraus hoechstens 3 KERN-Erinnerungen, die DAUERHAFT nuetzlich "
        "sind: Fakten ueber den Nutzer, getroffene Entscheidungen, Vorlieben, offene "
        "Zusagen. Je Zeile genau: KERN: <ein vollstaendiger, ohne Kontext verstaendlicher Satz>\n"
        "Ist nichts davon dauerhaft wichtig (Smalltalk, Tests, Tippfehler, reine "
        "Werkzeug-Protokolle), antworte mit exakt einem Wort: NICHTS"
    )
    res = llm_router.complete([{"role": "user", "content": prompt}],
                              system=_SYSTEM, task_type="bulk")
    text = (res.get("text") or "").strip()
    if not text:
        return None
    kerne = [ln.split(":", 1)[1].strip() for ln in text.splitlines()
             if ln.strip().upper().startswith("KERN") and ":" in ln]
    kerne = [k for k in kerne if k][:3]
    if kerne:
        return kerne
    if "NICHTS" in text.upper()[:200]:
        return []
    return None


def _session_wegsichern(session_id: str, backup_pfad) -> int:
    """Episodik EINER Session zeilenweise ins Lauf-Backup haengen, dann loeschen."""
    from core.mind.memory import store

    with store._conn() as c:
        rows = c.execute(
            "SELECT id, ts, session_id, role, kind, text FROM memory "
            "WHERE session_id=? AND kind='episodic'", (session_id,),
        ).fetchall()
        cols = ["id", "ts", "session_id", "role", "kind", "text"]
        with open(backup_pfad, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(dict(zip(cols, r)), ensure_ascii=False) + "\n")
        c.execute("DELETE FROM memory WHERE session_id=? AND kind='episodic'", (session_id,))
        for r in rows:
            try:
                c.execute("DELETE FROM memory_fts WHERE mem_id=?", (r[0],))
            except Exception:  # noqa: BLE001
                pass
    return len(rows)


def dream(force: bool = False) -> dict:
    """Ein Verdichtungs-Lauf. force=True (Cockpit) ueberspringt enabled/Reife-Minimum,
    nie den Lock. Rueckgabe: {gelaufen, grund?, sessions, kerne, geloescht, backup}."""
    from core.mind.memory import store

    if not force and not enabled():
        return {"gelaufen": False, "grund": "dream.enabled ist aus"}
    store.init_memory()

    reif = _reife_sessions(_int("min_alter_stunden", 48) * 3600, _int("max_sessions", 4))
    if not force and len(reif) < _int("min_sessions", 3):
        return {"gelaufen": False,
                "grund": f"erst {len(reif)} reife Sessions (min_sessions={_int('min_sessions', 3)})"}
    if not reif:
        return {"gelaufen": False, "grund": "keine reifen Sessions"}
    if not _lock_setzen():
        return {"gelaufen": False, "grund": "ein anderer dream-Lauf haelt den Lock"}

    bdir = DATA_DIR / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    backup = bdir / f"dream-{int(time.time())}-{uuid.uuid4().hex[:4]}.jsonl"
    sessions = kerne_gesamt = geloescht = 0
    try:
        for sid in reif:
            dialog = _dialog_text(sid)
            if not dialog.strip():
                continue
            kerne = _kerne_erfragen(dialog)
            if kerne is None:  # unparsebar/LLM weg -> nichts anfassen, Lauf beenden
                events.emit("dream_abbruch", {"session": sid, "grund": "keine saubere Antwort"})
                break
            for k in kerne:
                store.remember(k, role="self", kind="dream")
            geloescht += _session_wegsichern(sid, backup)
            sessions += 1
            kerne_gesamt += len(kerne)
    finally:
        _lock_loesen()

    res = {"gelaufen": True, "sessions": sessions, "kerne": kerne_gesamt,
           "geloescht": geloescht, "backup": str(backup) if geloescht else ""}
    events.emit("dream_done", res)
    return res
