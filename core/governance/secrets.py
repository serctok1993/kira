"""Zugaenge / Secrets: API-Keys, Passwoerter, Tokens.

Speicher: data/secrets.json (gitignored). Beim Start werden die Werte in die
Umgebung (os.environ) geladen — so sieht der LLM-Router/Connector sie als Env-Var.
NIE im Chat eingeben (landet sonst im Gedaechtnis/Log) — Eingabe ist write-only
ueber das Dashboard. Der Agent kann fehlende Zugaenge ANFORDERN; der Nutzer fuellt sie aus.
"""
from __future__ import annotations

import json
import os
import time

from core.config import DATA_DIR
from core.kernel import events
from core.kernel.fs import atomic_write

SECRETS_FILE = DATA_DIR / "secrets.json"


def _load() -> dict:
    if SECRETS_FILE.exists():
        try:
            return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"secrets": {}, "requests": []}


def _save(d: dict) -> None:
    atomic_write(SECRETS_FILE, json.dumps(d, indent=2, ensure_ascii=False))


def load_into_env() -> None:
    for k, v in _load().get("secrets", {}).items():
        if v:
            os.environ[k] = str(v)


def set_secret(name: str, value: str) -> bool:
    d = _load()
    d.setdefault("secrets", {})[name] = value
    d["requests"] = [r for r in d.get("requests", []) if r.get("name") != name]  # Anfrage erfuellt
    _save(d)
    if value:
        os.environ[name] = str(value)
    events.emit("secret_set", {"name": name})  # nur der Name, NIE der Wert
    return True


def names_status() -> dict:
    """Vorhandene Zugaenge -> nur Name + ob gesetzt (Werte werden nie ausgegeben)."""
    return {k: bool(v) for k, v in _load().get("secrets", {}).items()}


def request(name: str, reason: str = "") -> bool:
    d = _load()
    reqs = d.setdefault("requests", [])
    if not any(r.get("name") == name for r in reqs):
        reqs.append({"name": name, "reason": reason, "ts": time.time()})
        _save(d)
        events.emit("secret_requested", {"name": name, "reason": reason})
    return True


def pending() -> list[dict]:
    return _load().get("requests", [])


# Secret-Maskierung (13.08.2026, Vorfall: GitHub-PAT im Telegram-Chat landete im
# Klartext in events+memory). Zentrale Wache fuer ALLE Speicherpfade: bekannte
# Token-Formate werden VOR der Persistierung unkenntlich gemacht. Der laufende
# Zug sieht das Original (damit secret_speichern den Wert in den Tresor legen
# kann) — nur die AUFBEWAHRUNG wird maskiert.
import re as _re

_SECRET_MUSTER = _re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{15,}"
    r"|eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})")


def maskiere(text: str) -> str:
    """Ersetzt erkennbare Secrets durch einen Platzhalter (fuer Logs/Memory/Events)."""
    if not text or not isinstance(text, str):
        return text
    return _SECRET_MUSTER.sub("<SECRET-MASKIERT>", text)
