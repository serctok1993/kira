"""Zugaenge / Secrets: API-Keys, Passwoerter, Tokens.

Speicher: data/secrets.json (gitignored). Beim Start werden die Werte in die
Umgebung (os.environ) geladen — so sieht der LLM-Router/Connector sie als Env-Var.
NIE im Chat eingeben (landet sonst im Gedaechtnis/Log) — Eingabe ist write-only
ueber das Dashboard. Kira kann fehlende Zugaenge ANFORDERN; Sergen fuellt sie aus.
"""
from __future__ import annotations

import json
import os
import time

from core.config import DATA_DIR
from core.kernel import events

SECRETS_FILE = DATA_DIR / "secrets.json"


def _load() -> dict:
    if SECRETS_FILE.exists():
        try:
            return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"secrets": {}, "requests": []}


def _save(d: dict) -> None:
    SECRETS_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


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
