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
from core.kernel.fs import atomic_write

_PATH = DATA_DIR / "autonomy.json"
_DEFAULT = {
    "chains_off": True,                          # eigenstaendig; Inbox nur beratend
    "hard_gate": ["money", "email_stranger", "publish"],    # DIESE Arten brauchen Freigabe
}


def _load() -> dict:
    """Gespeicherte Config ueber den Default legen — das hard_gate aber als VEREINIGUNG.

    Audit-Fund 27.07.: der Top-Level-Merge ersetzte die Liste komplett. data/autonomy.json
    stammt vom 02.07. und kennt nur ["money", "email_stranger"]; als spaeter "publish"
    zum Default kam, blieb es fuer diese Instanz WIRKUNGSLOS — needs_approval('publish')
    war False, waehrend das Post-Werkzeug dem Modell versprach, der Beitrag "wartet in
    der Freigabe-Inbox". Ein Gate, das lautlos verschwindet, ist schlimmer als keines.
    Neue Schutz-Arten greifen ab jetzt auch fuer bestehende Instanzen; bewusst abwaehlen
    laesst sie 'hard_gate_off'."""
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        d = {}
    merged = {**_DEFAULT, **d}
    gate = set(_DEFAULT["hard_gate"]) | set(d.get("hard_gate") or [])
    merged["hard_gate"] = sorted(gate - set(d.get("hard_gate_off") or []))
    return merged


def config() -> dict:
    return _load()


def needs_approval(kind: str) -> bool:
    """True, wenn diese Aktions-Art die Freigabe des Nutzers braucht.

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
        # Abwahl muss ausdruecklich sein (sonst kaeme sie beim naechsten Laden zurueck):
        # was der Nutzer streicht, landet in hard_gate_off.
        gewuenscht = set(hard_gate)
        d["hard_gate"] = sorted(gewuenscht)
        d["hard_gate_off"] = sorted(set(_DEFAULT["hard_gate"]) - gewuenscht)
    atomic_write(_PATH, json.dumps(d, indent=2, ensure_ascii=False))
    return d
