"""Onboarding (W3): Erst-Start-Erkennung + Werkszustand-Gate.

Ein frischer Klon kennt weder Agent- noch Nutzer-Name — das Cockpit leitet dann
auf den /setup-Wizard (Namen, optional Zugaenge). Der Abschluss schreibt
data/onboarded.flag; ab da ist das Gate ein No-Op.

LOCKOUT-SCHUTZ (Auto-Migration): Eine BESTANDS-Instanz — gelebte USER.md liegt
auf Platte UND ein Nutzer-Name ist gesetzt (config/overrides) — stempelt sich
beim ersten Boot nach dem Update still selbst als 'migrated'. Sie sieht den
Wizard NIE; ein Pull darf eine eingerichtete Instanz niemals aussperren.

Bewusst OHNE Cache (Muster identity/feature_on): factory.reset('identitaet')
loescht das Flag zur Laufzeit, und das Gate greift sofort wieder.
"""
from __future__ import annotations

import datetime
from pathlib import Path


def flag_path() -> Path:
    """Pfad des Flags — live aus config gelesen (Tests/Sandbox lenken DATA_DIR um)."""
    from core import config

    return Path(config.DATA_DIR) / "onboarded.flag"


def is_onboarded() -> bool:
    return flag_path().exists()


def complete(source: str = "wizard") -> None:
    """Onboarding abschliessen (wizard | migrated | test) — idempotent."""
    p = flag_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{source} {datetime.datetime.now().isoformat(timespec='seconds')}\n",
                 encoding="utf-8")


def auto_migrate() -> bool:
    """Bestands-Instanz erkennen und still stempeln (Lockout-Schutz). True = migriert."""
    if is_onboarded():
        return False
    from core.config import CONFIG, MIND_DIR

    ident = CONFIG.get("identity") or {}
    if (MIND_DIR / "USER.md").exists() and str(ident.get("user") or "").strip():
        complete("migrated")
        return True
    return False
