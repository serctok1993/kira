"""Playbooks: strukturierte Prozeduren im Vault (playbooks/*.md) — S11.

Sergens Idee: der Harness soll nicht jedes Mal nachdenken muessen, weil alles
strukturell hinterlegt ist ("Gesetzestext"). Jedes Playbook ist eine Markdown-
Datei mit Frontmatter (wann/reifegrad/zaehler) und nummerierten Schritten.
Drei Schichten:

  1. Router: router_block() haengt eine KOMPAKTE Liste (nur Kopfzeilen) an den
     System-Prompt — das Modell liest erst bei Treffer das ganze Playbook
     (playbook_read). Progressive Disclosure statt Alles-im-Prompt.
  2. Reifegrade: entwurf -> begleitet -> autonom. Rueckstufung bei Fehlschlag
     SOFORT (eine Stufe runter); Befoerderung NUR ueber die Freigabe-Inbox
     (PROMOTE_AFTER Erfolge in Serie -> Vorschlag an Sergen). Autonomie
     verdient man sich pro Prozedur, nicht global.
  3. Lernschleife: record_result()/add_lesson() schreiben Zaehler und Lektionen
     in die DATEI zurueck — das Playbook wird durch Benutzung besser. Lernen
     in Dateien statt in Gewichten; ueberlebt jeden Modellwechsel.

Obsidian zeigt denselben Ordner als Vault — das Dateisystem ist die
Schnittstelle, es gibt keinen zweiten Sync-Weg. Frontmatter wird bewusst
zeilenweise geparst (key: value), NICHT via yaml: robust gegen Doppelpunkte
in Werten und symmetrisch zum Schreiben.
"""
from __future__ import annotations

import time
from pathlib import Path

from core.config import ROOT
from core.kernel import events
from core.kernel.fs import atomic_write

PB_DIR = ROOT / "playbooks"
INDEX_PATH = ROOT / "INDEX.md"

GRADES = ("entwurf", "begleitet", "autonom")
PROMOTE_AFTER = 5          # Erfolge in Serie bis zum Befoerderungs-Vorschlag
MAX_LESSONS = 20           # aelteste Lektion faellt raus, wenn voll
_ROUTER_MAX = 20           # hoechstens so viele Playbooks im Prompt-Block

_AUTO_START = "<!-- AUTO:START -->"
_AUTO_END = "<!-- AUTO:END -->"

_META_KEYS = ("titel", "wann", "reifegrad", "erfolge", "fehlschlaege", "serie", "letzte")


def _emit(etype: str, payload: dict) -> None:
    """Telemetrie darf die Dateiarbeit nie blockieren (frische DB ohne events-Tabelle)."""
    try:
        events.init_db()
        events.emit(etype, payload)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- Parsen/Schreiben

def _parse_meta(text: str) -> tuple[dict, str]:
    """Frontmatter (--- ... ---) zeilenweise lesen -> (meta, body). Fail-soft."""
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].lstrip("\n")
            for line in parts[1].splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    for k in ("erfolge", "fehlschlaege", "serie"):
        try:
            meta[k] = int(meta.get(k) or 0)
        except Exception:  # noqa: BLE001
            meta[k] = 0
    grade = str(meta.get("reifegrad") or "entwurf").lower()
    meta["reifegrad"] = grade if grade in GRADES else "entwurf"
    meta.setdefault("titel", "")
    meta.setdefault("wann", "")
    meta.setdefault("letzte", "")
    return meta, body


def _render(meta: dict, body: str) -> str:
    lines = ["---"]
    for k in _META_KEYS:
        lines.append(f"{k}: {meta.get(k, '')}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def _path(name: str) -> Path:
    return PB_DIR / f"{name}.md"


def _load(name: str) -> tuple[dict, str] | None:
    p = _path(name)
    if not p.exists():
        return None
    try:
        meta, body = _parse_meta(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    meta["name"] = name
    return meta, body


def _save(name: str, meta: dict, body: str) -> None:
    m = {k: meta.get(k, "") for k in _META_KEYS}
    atomic_write(_path(name), _render(m, body))


# ---------------------------------------------------------------- Lesen

def list_playbooks() -> list[dict]:
    """Alle Playbooks (nur Metadaten), alphabetisch. Dateien mit '_' sind Vorlagen."""
    out: list[dict] = []
    if not PB_DIR.exists():
        return out
    for p in sorted(PB_DIR.glob("*.md")):
        if p.stem.startswith("_"):
            continue
        loaded = _load(p.stem)
        if loaded:
            meta, body = loaded
            meta["lektionen"] = sum(1 for l in body.splitlines() if l.startswith("- 20"))
            out.append(meta)
    return out


def resolve(name: str) -> str | None:
    """Namen aufloesen: exakt -> case-insensitiv -> eindeutiger Teiltreffer."""
    q = (name or "").strip().removesuffix(".md")
    if not q:
        return None
    # Immer gegen die echte Stem-Liste aufloesen (Windows-FS ist case-insensitiv —
    # _path(q).exists() waere ein Treffer, lieferte aber den nicht-kanonischen Namen).
    stems = [p.stem for p in PB_DIR.glob("*.md") if not p.stem.startswith("_")] if PB_DIR.exists() else []
    if q in stems:
        return q
    lower = [s for s in stems if s.lower() == q.lower()]
    if len(lower) == 1:
        return lower[0]
    part = [s for s in stems if q.lower() in s.lower()]
    return part[0] if len(part) == 1 else None


def read_full(name: str) -> str | None:
    """Volltext eines Playbooks (fuer playbook_read)."""
    real = resolve(name)
    if not real:
        return None
    try:
        return _path(real).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None


def router_block() -> str:
    """Kompakter Prompt-Block: nur Kopfzeilen + Spielregeln. '' wenn keine Playbooks."""
    pbs = list_playbooks()
    if not pbs:
        return ""
    lines = []
    for m in pbs[:_ROUTER_MAX]:
        wann = (m.get("wann") or m.get("titel") or "")[:90]
        lines.append(f"- {m['name']} [{m['reifegrad']}]: {wann}")
    return (
        "# DEINE PLAYBOOKS (feste Prozeduren — pruefe VOR jeder Aufgabe, ob eine passt)\n"
        + "\n".join(lines)
        + "\nPasst eines: playbook_read(name) und die Schritte GENAU befolgen. Nach Abschluss "
        "IMMER playbook_result(name, erfolg) melden — daraus lernt das Playbook.\n"
        "Reifegrade: [entwurf] = Ergebnis NUR als Vorschlag in die Freigabe-Inbox "
        "(request_approval), nichts Aussenwirksames direkt. [begleitet] = handeln erlaubt, "
        "knapp melden. [autonom] = handeln, nur Ergebnis melden. Harte Gates (Geld, Mails an "
        "Fremde) gelten IMMER zusaetzlich."
    )


# ---------------------------------------------------------------- Lernschleife

def record_result(name: str, erfolg: bool, notiz: str = "") -> dict:
    """Ergebnis verbuchen: Zaehler + Serie + Datum in die Datei zurueckschreiben.

    Fehlschlag -> sofort eine Stufe runter (Vertrauen ist schneller weg als da).
    PROMOTE_AFTER Erfolge in Serie -> Befoerderungs-VORSCHLAG in die Freigabe-Inbox
    (Serie wird dabei genullt, damit nicht jeder weitere Erfolg neu vorschlaegt)."""
    real = resolve(name)
    if not real:
        return {"ok": False, "error": f"Playbook '{name}' nicht gefunden"}
    loaded = _load(real)
    if not loaded:
        return {"ok": False, "error": f"Playbook '{real}' nicht lesbar"}
    meta, body = loaded
    grade = meta["reifegrad"]
    demoted = promoted_proposal = None

    if erfolg:
        meta["erfolge"] += 1
        meta["serie"] += 1
        if meta["serie"] >= PROMOTE_AFTER and grade != "autonom":
            naechster = GRADES[GRADES.index(grade) + 1]
            try:
                from core.agency import approvals

                promoted_proposal = approvals.create(
                    f"Playbook befoerdern: {real} ({grade} -> {naechster})",
                    kind="playbook", ref=real, source="kira",
                    detail=(f"{meta['serie']} Erfolge in Serie ({meta['erfolge']} gesamt, "
                            f"{meta['fehlschlaege']} Fehlschlaege).\n"
                            f"Freigabe stuft das Playbook auf '{naechster}' hoch — "
                            "Ablehnung laesst alles wie es ist."))
            except Exception as e:  # noqa: BLE001
                _emit("playbook_error", {"where": "promote_proposal", "error": str(e)[:200]})
            meta["serie"] = 0
    else:
        meta["fehlschlaege"] += 1
        meta["serie"] = 0
        if grade != "entwurf":
            meta["reifegrad"] = demoted = GRADES[GRADES.index(grade) - 1]

    meta["letzte"] = time.strftime("%Y-%m-%d %H:%M")
    _save(real, meta, body)
    if notiz.strip():
        add_lesson(real, notiz)
    _emit("playbook_result", {"name": real, "erfolg": bool(erfolg),
                              "reifegrad": meta["reifegrad"], "serie": meta["serie"],
                              "demoted": demoted, "proposal": promoted_proposal})
    return {"ok": True, "name": real, "reifegrad": meta["reifegrad"],
            "erfolge": meta["erfolge"], "fehlschlaege": meta["fehlschlaege"],
            "serie": meta["serie"], "demoted": demoted, "proposal": promoted_proposal}


def promote(name: str) -> dict:
    """Eine Stufe hoch — wird NUR von der Freigabe-Inbox (approve) gerufen."""
    real = resolve(name)
    loaded = _load(real) if real else None
    if not loaded:
        return {"ok": False, "error": f"Playbook '{name}' nicht gefunden"}
    meta, body = loaded
    if meta["reifegrad"] == "autonom":
        return {"ok": True, "name": real, "reifegrad": "autonom", "hinweis": "war schon autonom"}
    meta["reifegrad"] = GRADES[GRADES.index(meta["reifegrad"]) + 1]
    _save(real, meta, body)
    _emit("playbook_promoted", {"name": real, "reifegrad": meta["reifegrad"]})
    return {"ok": True, "name": real, "reifegrad": meta["reifegrad"]}


def add_lesson(name: str, text: str) -> dict:
    """Lektion ans Playbook anhaengen (Sektion '## Lektionen', aelteste faellt bei >MAX raus)."""
    real = resolve(name)
    loaded = _load(real) if real else None
    if not loaded:
        return {"ok": False, "error": f"Playbook '{name}' nicht gefunden"}
    text = " ".join((text or "").split())
    if not text:
        return {"ok": False, "error": "leere Lektion"}
    meta, body = loaded
    stamp = time.strftime("%Y-%m-%d")
    if "## Lektionen" not in body:
        body = body.rstrip() + "\n\n## Lektionen\n"
    body = body.rstrip() + f"\n- {stamp}: {text}\n"

    kopf, _, rest = body.partition("## Lektionen")
    zeilen = rest.splitlines()
    bullets = [i for i, l in enumerate(zeilen) if l.startswith("- ")]
    if len(bullets) > MAX_LESSONS:
        del zeilen[bullets[0]]
        body = kopf + "## Lektionen" + "\n".join(zeilen) + "\n"

    _save(real, meta, body)
    _emit("playbook_lesson", {"name": real, "text": text[:200]})
    return {"ok": True, "name": real}


# ---------------------------------------------------------------- Index (Vault-Einstieg)

_INDEX_DEFAULT = """# INDEX — Kiras Vault

> Einstiegspunkt fuer jedes Modell in diesem Harness und fuer Sergen in Obsidian.
> Lies von oben nach unten: erst Identitaet, dann Prozeduren, dann laufende Arbeit.

1. **Identitaet & Regeln** -> `core/mind/` (constitution, SOUL, GOAL, USER, BODY)
2. **Prozeduren** -> `playbooks/` (feste Ablaeufe mit Reifegrad — Tabelle unten)
3. **Laufende Arbeit** -> `data/workspace/` (Objectives + Venture-Briefings)
4. **Wissen & Referenz** -> `docs/` (KIRA-IST.md = Uebergabe-Dossier)

<!-- AUTO:START -->
<!-- AUTO:END -->
"""


def refresh_index() -> dict:
    """AUTO-Block in INDEX.md aus der Wirklichkeit rendern (taeglich via Wartung).

    Abgeschrieben statt erinnert — wie body.refresh(). Fehlt INDEX.md, wird sie
    mit dem Standard-Kopf angelegt."""
    try:
        text = INDEX_PATH.read_text(encoding="utf-8") if INDEX_PATH.exists() else _INDEX_DEFAULT
        if _AUTO_START not in text or _AUTO_END not in text:
            text = text.rstrip() + f"\n\n{_AUTO_START}\n{_AUTO_END}\n"
        pbs = list_playbooks()
        lines = [f"Stand: {time.strftime('%d.%m.%Y %H:%M')} (automatisch generiert — nicht von Hand editieren)",
                 "", f"## Playbooks ({len(pbs)})", ""]
        if pbs:
            lines.append("| Playbook | Reifegrad | Wann | Erfolge | Fehlschlaege | Lektionen | Letzte |")
            lines.append("|---|---|---|---|---|---|---|")
            for m in pbs:
                lines.append(f"| [[playbooks/{m['name']}\\|{m['name']}]] | {m['reifegrad']} "
                             f"| {(m.get('wann') or '')[:70]} | {m['erfolge']} | {m['fehlschlaege']} "
                             f"| {m.get('lektionen', 0)} | {m.get('letzte') or '—'} |")
        else:
            lines.append("(noch keine Playbooks — Vorlage: playbooks/_VORLAGE.md)")
        head, rest = text.split(_AUTO_START, 1)
        _, tail = rest.split(_AUTO_END, 1)
        atomic_write(INDEX_PATH, head + _AUTO_START + "\n" + "\n".join(lines) + "\n" + _AUTO_END + tail)
        return {"ok": True, "playbooks": len(pbs)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}
