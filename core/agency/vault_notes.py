"""Vault-Schreibpfad (Phase 2): Kira pflegt des Nutzers Obsidian AKTIV.

Ziel-Wurzel ist der erste existierende Eintrag aus desktop.vault_paths (des Nutzers
Obsidian-Vault, z.B. C:/Users/Name/Desktop/Mein-Vault) — Fallback: ROOT/gedaechtnis
(Kiras eigener Ast, den der /wall-Graph ebenfalls liest). Regeln:
- atomic_write, NIEMALS blind ueberschreiben: existiert die Datei, wird ein
  "## Update <Datum>"-Abschnitt angehaengt (append-only, nichts geht verloren).
- Abgrenzung: knowledge_note schreibt ins durchsuchbare ARCHIV (state.db) — hier
  entstehen ECHTE .md-Dateien, die der Nutzer in Obsidian sieht.
- person_fakt_upsert pflegt den Stammbaum (gedaechtnis/stammbaum/...) deterministisch:
  "- <feld>: <wert>"-Zeilen ersetzen (??? fuellen) oder ergaenzen — kleine Modelle
  treffen mit edit_datei kein Markdown zuverlaessig, ein Upsert ist idempotent.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from core.config import CONFIG, ROOT
from core.kernel import events
from core.kernel.fs import atomic_write

# Slug-Konvention wie im Stammbaum: umlaute -> ascii, rest -> '-'


def _slug(name: str) -> str:
    s = (name or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "notiz"


def vault_root() -> Path:
    """Erster existierender desktop.vault_paths-Eintrag, sonst ROOT/gedaechtnis."""
    try:
        for p in (CONFIG.get("desktop") or {}).get("vault_paths") or []:
            root = Path(str(p))
            if root.exists():
                return root
    except Exception:  # noqa: BLE001
        pass
    return ROOT / "gedaechtnis"


def write_note(titel: str, text: str, ordner: str = "notizen") -> dict:
    """Notiz als .md in den Vault schreiben; bestehende Datei bekommt einen Update-Abschnitt."""
    titel = (titel or "").strip()
    text = (text or "").strip()
    if not titel or not text:
        return {"ok": False, "error": "titel und text duerfen nicht leer sein"}
    # Ordner-Aufloesung 13.08.2026 (Analyse-Befund): Serges Vault hat Grossbuchstaben-
    # Ordner (GELERNT, IDEEN, Business...) — der Slug erzeugte auf Linux Duplikate
    # (gelernt/ neben GELERNT/). Erst case-insensitiv gegen EXISTIERENDE Ordner
    # aufloesen; nur wenn nichts passt, greift der Slug wie bisher.
    wunsch = (ordner or "notizen").strip().strip("/")
    ziel_ordner = _slug(wunsch)
    try:
        for d in vault_root().iterdir():
            if d.is_dir() and d.name.lower() == wunsch.lower():
                ziel_ordner = d.name
                break
    except OSError:
        pass
    f = vault_root() / ziel_ordner / f"{_slug(titel)}.md"
    datum = datetime.date.today().strftime("%d.%m.%Y")
    if f.exists():
        alt = f.read_text(encoding="utf-8")
        atomic_write(f, alt.rstrip() + f"\n\n## Update {datum}\n\n{text}\n")
        created = False
    else:
        atomic_write(f, f"# {titel}\n\n_angelegt von Kira am {datum}_\n\n{text}\n")
        created = True
    events.emit("vault_note_written",
                {"path": str(f), "created": created, "titel": titel[:80]})
    return {"ok": True, "path": str(f), "created": created}


def write_dossier(thema: str, text: str) -> dict:
    """Recherche-Dossier: dossiers/<slug>.md anlegen bzw. per Update-Abschnitt ergaenzen."""
    return write_note(thema, text, ordner="dossiers")


# ---------------------------------------------------------------------------
# Stammbaum-Pflege (person_fakt)
# ---------------------------------------------------------------------------

_MENSCHEN_DIR = ("stammbaum", "leben", "menschen")


def _stammbaum_base() -> Path:
    return ROOT / "gedaechtnis" / "stammbaum"


def _find_leaf(slug: str) -> Path | None:
    """Bestehendes Stammbaum-Blatt zum Slug — egal in welchem Unterordner
    (deckt auch die Wurzel-Datei und business-Blaetter ab, Gross-/Kleinschreibung egal)."""
    base = _stammbaum_base()
    if not base.exists():
        return None
    for p in sorted(base.rglob("*.md")):
        if "_VORLAGE" in p.name:
            continue
        if p.stem.lower() == slug:
            return p
    return None


def person_fakt_upsert(name: str, feld: str, wert: str) -> dict:
    """Deterministischer Upsert von '- <feld>: <wert>' in gedaechtnis/stammbaum/.

    Blatt fehlt -> aus leben/menschen/_VORLAGE.md anlegen (Fallback: Minimal-Blatt).
    Feld-Zeile existiert (auch mit ???) -> Wert ersetzen; sonst Zeile vor dem ersten
    '##'-Abschnitt ergaenzen. Idempotent."""
    name = (name or "").strip()
    feld = (feld or "").strip().lower()
    wert = (wert or "").strip()
    if not name or not feld or not wert:
        return {"ok": False, "error": "name, feld und wert duerfen nicht leer sein"}
    slug = _slug(name)
    leaf = _find_leaf(slug)
    created = False
    if leaf is None:
        base = _stammbaum_base()
        menschen = base / "leben" / "menschen"
        vorlage = menschen / "_VORLAGE.md"
        leaf = menschen / f"{slug}.md"
        if vorlage.exists():
            text = vorlage.read_text(encoding="utf-8")
            text = re.sub(r"^# .*$", f"# {name}", text, count=1, flags=re.M)
        else:
            text = f"# {name}\n\n- geburtstag: ???\n\n## Notizen (mit Datum)\n\n-\n"
        atomic_write(leaf, text)
        created = True

    zeilen = leaf.read_text(encoding="utf-8").splitlines()
    pat = re.compile(rf"^\s*-\s*{re.escape(feld)}\s*:", re.IGNORECASE)
    ersetzt = False
    for i, z in enumerate(zeilen):
        if pat.match(z):
            zeilen[i] = f"- {feld}: {wert}"
            ersetzt = True
            break
    if not ersetzt:
        # vor dem ersten '##'-Abschnitt einfuegen, sonst ans Ende
        pos = next((i for i, z in enumerate(zeilen) if z.startswith("##")), len(zeilen))
        while pos > 0 and not zeilen[pos - 1].strip():
            pos -= 1
        zeilen.insert(pos, f"- {feld}: {wert}")
    atomic_write(leaf, "\n".join(zeilen).rstrip() + "\n")
    events.emit("person_fakt",
                {"name": name[:60], "feld": feld[:40], "path": str(leaf), "created": created})
    return {"ok": True, "path": str(leaf), "created": created, "ersetzt": ersetzt}
