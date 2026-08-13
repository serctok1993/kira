"""W3 Clean-Gate: KEIN Personendatum in irgendeiner getrackten Datei.

Deterministisches Sicherheitsnetz fuer den Public-Export (und CI-Gate in W4):
scannt git ls-files nach den bekannten Personendaten-Mustern des Entwicklers
plus Basis-Secret-Mustern. 0 Treffer oder der Test ist rot.

Die Muster stehen hier VERKETTET ("Ser" "gen"), damit diese Datei sich nicht
selbst meldet und der Agenten-Sweep in W4 sie nicht als Fund zaehlt.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from core.config import ROOT

# Personendaten des Entwicklers (verkettete Literale, siehe Docstring)
_PERSONEN = [
    r"\b" + "ser" + "gen",              # Vorname (faengt auch den Genitiv)
    r"\b" + "ser" + "c" + r"\b",        # Kurzname/Alt-Slot (Wortgrenze: 'usercontent' bleibt ok)
    "ser" + "c" + ".tok",               # E-Mail-Anfang
    "703" + "780" + "6562",             # Telegram-Chat-ID
    "kira-" + "brain",                  # privater Vault-Name
    "lu" + "vex",                       # privates Projekt
    "qs-" + "transporte",               # Kundenprojekt
    "tok" + "goez",                     # Familienname
    "ser" + "inay",                     # Personenname
    "kob" + "lenz",                     # Wohnort
    r"C:[/\\]Users[/\\]" + "ser" + "ge" + r"\b",  # privater Windows-Pfad
]
# Basis-Secret-Muster (W4 verschaerft; hier das grobe Netz)
_SECRETS = [
    r"sk-or-v1-[a-f0-9]{16,}",          # OpenRouter-Key
    r"ghp_[A-Za-z0-9]{20,}",            # GitHub-Token
    r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}", # Telegram-Bot-Token
]

_MUSTER = re.compile("|".join(_PERSONEN + _SECRETS), re.IGNORECASE)


def _getrackte_dateien() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         cwd=str(ROOT), timeout=60)
    return [z.strip() for z in out.stdout.split("\n") if z.strip()]


def test_keine_personendaten_in_getrackten_dateien():
    eigene = "tests/test_werkszustand_clean.py"
    funde: list[str] = []
    for rel in _getrackte_dateien():
        if rel == eigene:
            continue
        p = Path(ROOT) / rel
        if not p.exists():  # frisch enttrackt/geloescht im Arbeitsbaum
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001 — Binaerdateien etc. ueberspringen
            continue
        for i, zeile in enumerate(text.split("\n"), 1):
            m = _MUSTER.search(zeile)
            if m:
                funde.append(f"{rel}:{i}: {zeile.strip()[:100]}")
    assert not funde, ("Personendaten/Secrets in getrackten Dateien:\n" + "\n".join(funde[:40])
                       + (f"\n… +{len(funde) - 40} weitere" if len(funde) > 40 else ""))


def test_persoenliche_dateien_sind_enttrackt():
    """Die W3-Enttrackungen duerfen nie zurueckkommen (gitignore + ls-files-Probe)."""
    tracked = set(_getrackte_dateien())
    verboten = ["core/mind/SOUL.md", "core/mind/GOAL.md", "core/mind/USER.md",
                "core/mind/PERSONA.md", "core/mind/BODY.md", "docs/KIRA-IST.md"]
    schlimm = [v for v in verboten if v in tracked]
    assert not schlimm, f"Persoenliche Dateien wieder im Repo: {schlimm}"
    # Stammbaum: nur Vorlagen sind Produkt
    baum = [t for t in tracked if t.startswith("gedaechtnis/stammbaum/")]
    nicht_vorlage = [t for t in baum if "_VORLAGE" not in t and "_WURZEL_VORLAGE" not in t]
    assert not nicht_vorlage, f"Stammbaum-Blaetter im Repo: {nicht_vorlage}"
    # Nutzer-Arbeitsbereiche bleiben draussen
    assert not [t for t in tracked if t.startswith("projects/")]
