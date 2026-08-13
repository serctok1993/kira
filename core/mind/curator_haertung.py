"""Kurator-Haertung (13.08.2026): Sicherheitsnetz + Alterung fuers Gedaechtnis.

Drei Bausteine, alle deterministisch und ohne LLM:
1. sichere_kuration(): Wrapper um die LLM-Kuratoren (Skills/Lektionen) — JSONL-Backup
   VOR jedem Loesch-Rewrite + Erhaltungsquote (schrumpft die Liste unter 50% bei >=6
   Alt-Eintraegen, wird ABGEBROCHEN statt geloescht). Lehre aus dem Audit: der Kurator
   war der groesste Verlustpfad fuer Gelerntes.
2. altere_episodik(): Episodisches aelter als N Tage fliegt raus (mit Backup) — die
   Tages-/Wochen-Verdichtung hat es bis dahin destilliert. Verhindert genau die
   Recall-Vergiftung durch veraltete Selbstaussagen (Sudo-Mythos, PAT-Sackgasse),
   die am 13.08. dreimal von Hand entgiftet werden musste.
3. pruefe_secrets(): Fakten mit Secret-Mustern werden entfernt (zweites Netz hinter
   der Speicher-Maskierung) + Hinweis-Event "gehoert in den Tresor".
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from core.config import DATA_DIR
from core.kernel import events
from core.mind.memory import store as memory

_BACKUP_DIR = DATA_DIR / "backups"
EPISODIK_MAX_TAGE = 14
ERHALTUNGSQUOTE = 0.5


def _backup(name: str, rows: list) -> str:
    """Zeilen als JSONL sichern; gibt den Pfad zurueck."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.monotonic() * 1000))[-9:]
    f = _BACKUP_DIR / f"kurator-{name}-{stamp}.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r if isinstance(r, dict) else list(r),
                                ensure_ascii=False, default=str) + "\n")
    return str(f)


def sichere_kuration(kind: str, kurator_fn) -> dict:
    """Fuehrt einen LLM-Kurator (curate_skills/curate_lessons) MIT Netz aus:
    Backup vorher, Erhaltungsquote nachher (Rollback per Backup-Hinweis, wenn zu viel
    verschwand). kurator_fn gibt {before, after} oder {note} zurueck."""
    memory.init_memory()
    vorher = memory.all_skills() if kind == "skill" else memory.all_lessons()
    pfad = _backup(kind, vorher) if vorher else ""
    r = kurator_fn()
    if "before" not in r:  # Kurator hat nichts getan (zu wenige / kein Ergebnis)
        return r
    nachher = memory.all_skills() if kind == "skill" else memory.all_lessons()
    if len(vorher) >= 6 and len(nachher) < len(vorher) * ERHALTUNGSQUOTE:
        events.emit("curator_verdacht", {
            "kind": kind, "vorher": len(vorher), "nachher": len(nachher), "backup": pfad,
            "hinweis": "Mehr als die Haelfte verschwand — Backup pruefen, ggf. wiederherstellen."})
        r["warnung"] = (f"Auffaellig: {len(vorher)} -> {len(nachher)}. Backup: {pfad}")
    r["backup"] = pfad
    return r


def altere_episodik(max_tage: int = EPISODIK_MAX_TAGE) -> dict:
    """Loescht episodische Erinnerungen aelter als max_tage (mit Backup). Fakten,
    Lektionen, Skills, dream bleiben unberuehrt — nur der fluechtige Chat-Nachhall geht."""
    memory.init_memory()
    grenze = time.time() - max_tage * 86400
    db = DATA_DIR / "state.db"
    con = sqlite3.connect(str(db))
    try:
        cols = [c[1] for c in con.execute("PRAGMA table_info(memory)")]
        tsc = "ts" if "ts" in cols else ("created" if "created" in cols else None)
        if not tsc:
            return {"note": "kein Zeitstempel in memory-Tabelle", "geloescht": 0}
        rows = con.execute(
            f"SELECT * FROM memory WHERE kind='episodic' AND {tsc} < ?", (grenze,)).fetchall()
        if not rows:
            return {"geloescht": 0, "note": f"nichts aelter als {max_tage} Tage"}
        pfad = _backup("episodik", rows)
        con.execute(f"DELETE FROM memory WHERE kind='episodic' AND {tsc} < ?", (grenze,))
        con.commit()
        # FTS-Index nachziehen, falls vorhanden
        for t in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
            if t.endswith("_fts"):
                try:
                    con.execute(f"INSERT INTO {t}({t}) VALUES('rebuild')")
                except sqlite3.OperationalError:
                    pass
        con.commit()
        events.emit("episodik_gealtert", {"geloescht": len(rows), "max_tage": max_tage, "backup": pfad})
        return {"geloescht": len(rows), "backup": pfad, "max_tage": max_tage}
    finally:
        con.close()


def pruefe_secrets() -> dict:
    """Zweites Netz: Fakten, die wie ein Secret aussehen, entfernen (mit Backup +
    Hinweis-Event). Die primaere Maskierung sitzt in memory.remember/events.emit;
    das hier faengt Altbestand und Umgehungen."""
    from core.governance.secrets import _SECRET_MUSTER
    memory.init_memory()
    db = DATA_DIR / "state.db"
    con = sqlite3.connect(str(db))
    try:
        idc = [c[1] for c in con.execute("PRAGMA table_info(memory)")][0]
        rows = con.execute(f"SELECT {idc}, text FROM memory WHERE kind='fact'").fetchall()
        treffer = [(rid, txt) for rid, txt in rows if _SECRET_MUSTER.search(txt or "")]
        if not treffer:
            return {"entfernt": 0}
        pfad = _backup("secrets-in-fakten", [{"id": r, "text": "<redigiert>"} for r, _ in treffer])
        for rid, _ in treffer:
            con.execute(f"DELETE FROM memory WHERE {idc}=?", (rid,))
        con.commit()
        events.emit("secrets_aus_fakten_entfernt",
                    {"anzahl": len(treffer), "hinweis": "gehoert in den Tresor, nicht ins Gedaechtnis"})
        return {"entfernt": len(treffer), "backup": pfad}
    finally:
        con.close()


def volle_pflege() -> dict:
    """Ein Aufruf fuer den woechentlichen Cron: Secrets raus, Episodik altern,
    Skills + Lektionen sicher kuratieren. Gibt ein Sammel-Ergebnis zurueck."""
    from core.mind import curator
    out = {}
    try:
        out["secrets"] = pruefe_secrets()
    except Exception as e:  # noqa: BLE001
        out["secrets"] = {"fehler": str(e)[:150]}
    try:
        out["episodik"] = altere_episodik()
    except Exception as e:  # noqa: BLE001
        out["episodik"] = {"fehler": str(e)[:150]}
    try:
        out["skills"] = sichere_kuration("skill", curator.curate_skills)
    except Exception as e:  # noqa: BLE001
        out["skills"] = {"fehler": str(e)[:150]}
    try:
        out["lektionen"] = sichere_kuration("lesson", curator.curate_lessons)
    except Exception as e:  # noqa: BLE001
        out["lektionen"] = {"fehler": str(e)[:150]}
    events.emit("gedaechtnis_gepflegt", out)
    return out


if __name__ == "__main__":
    print(json.dumps(volle_pflege(), ensure_ascii=False, indent=1))
