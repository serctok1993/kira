"""Autonomie-Konfiguration — 'Ketten ab': Kira handelt eigenstaendig.

Harte Grenzen sind NUR: Budget (treasury) + Not-Aus (kill switch). Die
Freigabe-Inbox ist BERATEND (Kira kann vorlegen, muss nicht). Nur die wirklich
harte Realitaet — echtes GELD bewegen + Mails an FREMDE Menschen — braucht per
Default eine Freigabe; das ist ueber data/autonomy.json einzeln schaltbar
(keine Bevormundung, sondern Recht/Spam-Realitaet). Audit-Log laeuft immer mit.

Ersetzt die alten, ungenutzten Trust-Level 0-2 durch EINE klare Config.
"""
from __future__ import annotations

import json

from core.config import DATA_DIR

_PATH = DATA_DIR / "autonomy.json"
_DEFAULT = {
    "chains_off": True,                          # eigenstaendig; Inbox nur beratend
    "hard_gate": ["money", "email_stranger"],    # DIESE Arten brauchen Freigabe
}


def _load() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULT, **(d if isinstance(d, dict) else {})}
    except Exception:  # noqa: BLE001
        return dict(_DEFAULT)


def config() -> dict:
    return _load()


def needs_approval(kind: str) -> bool:
    """True, wenn diese Aktions-Art Sergens Freigabe braucht.

    kind z.B. 'money' | 'email_stranger' | 'publish' | 'external' | 'generic'.
    Bei chains_off (Default) braucht NUR das hard_gate eine Freigabe; sonst frei.
    Bei chains_off=False (Ketten AN) muss alles Externe vorgelegt werden.
    """
    d = _load()
    if not d.get("chains_off", True):
        return True
    return kind in set(d.get("hard_gate", []))


def set_config(chains_off: bool | None = None, hard_gate: list[str] | None = None) -> dict:
    d = _load()
    if chains_off is not None:
        d["chains_off"] = bool(chains_off)
    if hard_gate is not None:
        d["hard_gate"] = list(hard_gate)
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    return d
