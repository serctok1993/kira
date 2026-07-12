"""Werkszustand / Blanko-Handover: den Agenten in einen sauberen Uebergabe-Zustand
bringen — der Dev-/Test-Wildwuchs raus, die echte Substanz (Verfassung, Persona,
USER.md, Zugaenge, Config) bleibt UNANGETASTET, ausser sie wird explizit gewaehlt.

Vorsatz: NICHTS still loeschen. preview() zeigt exakt, WAS und WIE VIEL fiele; reset()
sichert jede Kategorie vorher (Backups unter data/backups/) und raeumt nur die
ausgewaehlten. Fakten sind bewusst NICHT im Standard — echte Fakten ueber den Nutzer
sollen einen Neustart ueberleben, ausser er waehlt sie explizit.

W3-Scopes: 'identitaet' (Namen, Mind-.md, Stammbaum, Personalisierungs-Overrides,
onboarded.flag -> naechster Cockpit-Aufruf zeigt den /setup-Wizard) und
'persoenliche-daten' (Kalender, Fokus, Crons, Chat-Meta, Briefings, tuning/ & Co. —
MOVE ins Backup, kein Delete). 'alles' ist ein Meta-Scope in reset():
identitaet + alle Standard-Kategorien + persoenliche-daten.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from core.kernel import events

# Personalisierungs-Overrides (data/overrides.json), die zur IDENTITAET gehoeren —
# exakter Pfad oder Praefix (siehe config.remove_overrides).
_IDENT_OVERRIDES = ("identity", "channels.telegram.allowed_chat_id",
                    "desktop.vault_paths", "channels.email.own_addresses", "mission.goal")

# Persoenliche Daten-Artefakte unter data/ (MOVE ins Backup, kein Delete).
_PERSOENLICH_DATEIEN = ("kalender.json", "focus.json", "cron.json", "chat_meta.json",
                        "melde_puffer.json", "backlog.md", "avatar.jpg", "background.jpg")
_PERSOENLICH_ORDNER = ("tuning", "voice", "workspace", "widgets")


def _data_dir() -> Path:
    from core import config
    return Path(config.DATA_DIR)


def _stammbaum_dir() -> Path:
    from core import config
    return Path(config.ROOT) / "gedaechtnis" / "stammbaum"


def _backup_dir() -> Path:
    import datetime
    d = _data_dir() / "backups" / f"werkszustand-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stammbaum_persoenlich() -> list[Path]:
    """Persoenliche Stammbaum-Blaetter: alles ausser Vorlagen/Anleitungen."""
    wurzel = _stammbaum_dir()
    if not wurzel.exists():
        return []
    return [p for p in wurzel.rglob("*.md")
            if not p.name.startswith("_VORLAGE") and not p.name.startswith("LIES-MICH")]


def _ident_override_count() -> int:
    import json
    f = _data_dir() / "overrides.json"
    if not f.exists():
        return 0
    try:
        ov = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return 0
    return sum(1 for k in ov if any(k == p or k.startswith(p + ".") for p in _IDENT_OVERRIDES))


def _cnt_identitaet() -> int:
    from core.kernel import onboarding
    from core.mind import seed
    lebend = sum(1 for n in seed.TEMPLATES if (seed.MIND_DIR / n).exists())
    return (lebend + len(_stammbaum_persoenlich()) + _ident_override_count()
            + (1 if onboarding.is_onboarded() else 0))


def _clear_identitaet() -> int:
    """Identitaet auf Werkszustand: Backup -> Overrides raus -> Mind aus Templates ->
    Stammbaum-Blaetter ins Backup -> onboarded.flag weg (naechster Aufruf: Wizard)."""
    from core import config
    from core.kernel import onboarding
    from core.mind import seed

    n = 0
    bdir = _backup_dir()
    # 1) Sichern: Live-Mind + Overrides + persoenliche Stammbaum-Blaetter
    (bdir / "mind").mkdir(parents=True, exist_ok=True)
    for name in seed.TEMPLATES:
        p = seed.MIND_DIR / name
        if p.exists():
            shutil.copy2(p, bdir / "mind" / name)
    ov = _data_dir() / "overrides.json"
    if ov.exists():
        shutil.copy2(ov, bdir / "overrides.json")
    for blatt in _stammbaum_persoenlich():
        ziel = bdir / "stammbaum" / blatt.relative_to(_stammbaum_dir())
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(blatt), str(ziel))   # MOVE: das Blatt verschwindet aus dem Baum
        n += 1
    # 2) Personalisierung aus den Overrides entfernen (CONFIG wird in place neu aufgebaut)
    n += config.remove_overrides(_IDENT_OVERRIDES)
    # 3) Mind-.md aus den neutralen Templates force-rendern (jetzt mit Werks-Namen)
    n += sum(1 for s in seed.render_mind(force=True).values() if s == "geschrieben")
    # 4) Onboarding-Flag loeschen -> Erst-Einrichtung laeuft erneut
    if onboarding.is_onboarded():
        onboarding.flag_path().unlink(missing_ok=True)
        n += 1
    events.emit("werkszustand_identitaet", {"artefakte": n, "backup": bdir.name})
    return n


def _persoenlich_vorhanden() -> list[Path]:
    d = _data_dir()
    items = [d / name for name in _PERSOENLICH_DATEIEN if (d / name).exists()]
    items += [d / o for o in _PERSOENLICH_ORDNER if (d / o).exists()]
    items += sorted(d.glob("briefing_*.txt"))
    return items


def _clear_persoenlich() -> int:
    """Persoenliche Daten-Artefakte ins Backup VERSCHIEBEN (kein Delete) — vorher
    eine konsistente state.db-Kopie ziehen."""
    from core.kernel import backup

    backup.backup_state_db()
    bdir = _backup_dir() / "persoenlich"
    bdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in _persoenlich_vorhanden():
        shutil.move(str(p), str(bdir / p.name))
        n += 1
    events.emit("werkszustand_persoenlich", {"artefakte": n, "backup": bdir.parent.name})
    return n


def _cat_defs() -> list[dict]:
    """Kategorie-Register: key, label, Beschreibung, count(), clear()->Anzahl. Lazy-Importe,
    damit ein fehlendes Teilsystem den Rest nicht bricht."""
    from core.mind.memory import store as memory

    def _clear_kind(kinds):
        return lambda: memory.delete_by_kind(kinds, backup=True).get("deleted", 0)

    def _clear_chats():
        return memory.reset_episodic(backup=True).get("deleted", 0)

    def _clear_events():
        return events.clear_all()

    def _clear_wissen():
        from core.mind import knowledge
        return knowledge.clear_all()

    def _cnt_kind(kind):
        return lambda: memory.count_by_kind(kind)

    def _cnt_wissen():
        from core.mind import knowledge
        return knowledge.count_docs()

    return [
        {"key": "chats", "label": "Chat-Verlaeufe", "standard": True,
         "desc": "alle Gespraeche (episodisches Gedaechtnis)",
         "count": _cnt_kind("episodic"), "clear": _clear_chats},
        {"key": "skills", "label": "Skills", "standard": True,
         "desc": "waehrend der Bauphase gelernte Faehigkeiten",
         "count": _cnt_kind("skill"), "clear": _clear_kind(["skill"])},
        {"key": "lektionen", "label": "Lektionen", "standard": True,
         "desc": "gelernte Lektionen (Reflexion)",
         "count": _cnt_kind("lesson"), "clear": _clear_kind(["lesson"])},
        {"key": "events", "label": "Live-Ops-Protokoll", "standard": True,
         "desc": "Ereignis-/Aktionslog der Bauphase",
         "count": events.count_all, "clear": _clear_events},
        {"key": "wissen", "label": "Wissens-Archiv", "standard": False,
         "desc": "hochgeladene Dokumente (nur leeren, wenn Test-Dateien)",
         "count": _cnt_wissen, "clear": _clear_wissen},
        {"key": "fakten", "label": "Gemerkte Fakten", "standard": False,
         "desc": "Dauer-Fakten — VORSICHT: auch echte ueber den Nutzer!",
         "count": _cnt_kind("fact"), "clear": _clear_kind(["fact"])},
        {"key": "persoenliche-daten", "label": "Persoenliche Daten", "standard": False,
         "desc": "Kalender, Fokus, Crons, Chat-Meta, Briefings, tuning/, voice/, workspace/ — wandern ins Backup",
         "count": lambda: len(_persoenlich_vorhanden()), "clear": _clear_persoenlich},
        {"key": "identitaet", "label": "Identitaet", "standard": False,
         "desc": "Namen, Seelen-Dateien, Stammbaum, Personalisierung — danach laeuft die Erst-Einrichtung (/setup) erneut",
         "count": _cnt_identitaet, "clear": _clear_identitaet},
    ]


def preview() -> dict:
    """Was fiele einem Reset zum Opfer? {categories: [{key,label,desc,standard,count}], total}."""
    cats = []
    for c in _cat_defs():
        try:
            n = int(c["count"]())
        except Exception:  # noqa: BLE001
            n = 0
        cats.append({"key": c["key"], "label": c["label"], "desc": c["desc"],
                     "standard": c["standard"], "count": n})
    return {"categories": cats, "total": sum(c["count"] for c in cats)}


def reset(scope: list[str], confirm: str = "") -> dict:
    """Setzt die AUSGEWAEHLTEN Kategorien auf Werkszustand — jede vorher gesichert.

    Schutz: confirm muss exakt 'WERKSZUSTAND' sein (bewusste, nicht versehentliche Aktion).
    Gibt {ok, cleared:{key:anzahl}, error?} zurueck; eine kaputte Kategorie stoppt die
    anderen nicht."""
    if confirm != "WERKSZUSTAND":
        return {"ok": False, "error": "Bestaetigung fehlt (confirm='WERKSZUSTAND')."}
    wanted = set(scope or [])
    if not wanted:
        return {"ok": False, "error": "Keine Kategorie gewaehlt."}
    if "alles" in wanted:  # Meta-Scope (W3): kompletter Blanko-Handover
        wanted.discard("alles")
        wanted |= {"identitaet", "persoenliche-daten"}
        wanted |= {c["key"] for c in _cat_defs() if c["standard"]}
    cleared: dict[str, int] = {}
    for c in _cat_defs():
        if c["key"] not in wanted:
            continue
        try:
            cleared[c["key"]] = int(c["clear"]())
        except Exception as e:  # noqa: BLE001 — eine Kategorie darf den Rest nicht abreissen
            cleared[c["key"]] = -1
            events.emit("factory_reset_error", {"category": c["key"], "error": str(e)[:200]})
    events.emit("factory_reset", {"scope": sorted(wanted),
                                  "cleared": {k: v for k, v in cleared.items() if k != "events"}})
    return {"ok": True, "cleared": cleared}
