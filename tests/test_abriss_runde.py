"""Kontext-Abriss-Runde: der 16k-Slot des lokalen Servers lief durch fette
Observations voll, der Server kappte die Generation MITTEN im ACT-Aufruf
(llama-Log: "n_tokens = 16383, truncated = 1") — das unparsebare Fragment ging
als 'finale Antwort' roh an den Nutzer, der Werkzeug-Schritt lief NIE
(Haerte-4-Forensik 23.07., events-belegt: nur 3 act_steps, keine Notiz im Vault).

Der Live-Leak steht unten WOERTLICH (191 Zeichen, aus der events-DB geborgen;
die \\n sind literale Backslash-Escapes, die das Modell in sein JSON schrieb).
"""
from __future__ import annotations

from core.agency import act
from core.agency.act import _act_fragment, _compact_history, _parse_act, _retry_fragment
from core.kernel import events

events.init_db()  # Wegwerf-Datenwurzel der Suite: events-Tabelle auch im Solo-Lauf da

# Woertlich aus der events-DB (partner_message der Haerte-4-Testfahrt, 191 Zeichen):
LEAK = ('ACT vault_note {"titel": "DDR4 64GB Preisstand & Kaufberatung (23.07.2026)", '
        '"text": "# DDR4 64GB (2x32GB) Preisstand & Kaufberatung\\n**Erstellt:** 23.07.2026'
        '\\n\\n## \U0001f4b0 Aktuelle Preisspanne (DE')

_WRAPPER_SCHLUSS = "\n\nMach weiter oder gib die finale Antwort."


def _antwort(text: str) -> dict:
    return {"text": text, "model": "test", "cost_usd": 0.0, "fell_back": False, "latency_s": 0.0}


def test_leak_woertlich_ist_fragment():
    assert len(LEAK) == 191                      # exakt der Stand, der beim Nutzer ankam
    assert _parse_act(LEAK) is None              # unparsebar -> der alte Loop gab es roh zurueck
    assert _act_fragment(LEAK) == "vault_note"   # jetzt: als Kontext-Abriss erkannt


def test_fragment_erkennung_bleibt_eng():
    # heiler Call ist KEIN Fragment (den fuehrt der Loop normal aus)
    assert _act_fragment('ACT health {}') is None
    assert _act_fragment('ACT vault_note {"titel": "x", "text": "y"}') is None
    # normale Antwort ohne ACT-Zeile ist KEIN Fragment
    assert _act_fragment("DDR4-64GB-Kits liegen aktuell bei 95-120 Euro.") is None
    assert _act_fragment("") is None
    # kaputtes, aber GESCHLOSSENES JSON ist kein Abriss (anderer Fehlerfall, unveraendert)
    assert _act_fragment("ACT vault_note {'titel': 'x'}") is None
    # Abriss mit Prosa davor wird trotzdem erkannt (wie bei _parse_act)
    assert _act_fragment('Ich lege das ab.\nACT vault_note {"titel": "DDR4') == "vault_note"


def test_retry_liefert_heilen_call(monkeypatch):
    """Anlauf 2 mit gekuerzter History bringt den Call heil -> Loop fuehrt ihn aus."""
    monkeypatch.setattr(act.llm_router, "complete",
                        lambda *a, **k: _antwort('ACT vault_note {"titel": "x", "text": "y"}'))
    messages = [{"role": "user", "content": "leg das Dossier ab"}]
    text, call = _retry_fragment(messages, "sys", "vault_note", 3,
                                 session_id=None, task_type="reason", escalate=False)
    assert call == ("vault_note", {"titel": "x", "text": "y"})


def test_retry_scheitert_ehrliche_meldung(monkeypatch):
    """Auch Anlauf 2 gekappt -> ehrliche Ansage statt Roh-Fragment beim Nutzer."""
    monkeypatch.setattr(act.llm_router, "complete", lambda *a, **k: _antwort(LEAK))
    text, call = _retry_fragment([{"role": "user", "content": "x"}], "sys", "vault_note", 3,
                                 session_id=None, task_type="reason", escalate=False)
    assert call is None
    assert "Kontext-Limit" in text and "vault_note" in text and "NICHT ausgefuehrt" in text
    assert "ACT " not in text                    # nie das rohe Fragment


def test_retry_llm_fehler_ehrliche_meldung(monkeypatch):
    """Der Retry-Call selbst wirft -> ebenfalls ehrliche Ansage, kein Crash."""
    def _boom(*a, **k):
        raise RuntimeError("Slot belegt")
    monkeypatch.setattr(act.llm_router, "complete", _boom)
    text, call = _retry_fragment([{"role": "user", "content": "x"}], "sys", "vault_note", 0,
                                 session_id=None, task_type="reason", escalate=False)
    assert call is None
    assert "Kontext-Limit" in text and "vault_note" in text


def test_act_loop_leakt_fragment_nicht(monkeypatch):
    """End-to-end durch den ACT-Loop: erst das gekappte Fragment, der Retry antwortet
    sauber — beim Nutzer kommt NIE das Roh-Fragment an."""
    antworten = iter([LEAK, "Das Dossier liegt im Brain-Ordner."])
    monkeypatch.setattr(act.llm_router, "complete", lambda *a, **k: _antwort(next(antworten)))
    monkeypatch.setattr(act, "_cloud", lambda *a, **k: False)
    out = act.act("leg das Dossier ab", max_steps=3)
    assert out["text"] == "Das Dossier liegt im Brain-Ordner."


def test_compact_history_kuerzt_alte_observations():
    fett = "ERGEBNIS von web_fetch:\n" + ("x" * 20000) + _WRAPPER_SCHLUSS
    frisch = "ERGEBNIS von web_search:\n" + ("y" * 20000) + _WRAPPER_SCHLUSS
    messages = [
        {"role": "user", "content": "Aufgabe"},
        {"role": "assistant", "content": 'ACT web_fetch {"url": "https://x"}'},
        {"role": "user", "content": fett},
        {"role": "assistant", "content": 'ACT web_search {"query": "x"}'},
        {"role": "user", "content": frisch},
    ]
    _compact_history(messages)
    assert messages[0]["content"] == "Aufgabe"           # Aufgabe bleibt voll
    assert messages[4]["content"] == frisch              # juengste Observation bleibt voll
    kurz = messages[2]["content"]
    assert len(kurz) < 1000                              # alte Observation -> Vorschau
    assert kurz.startswith("ERGEBNIS von web_fetch:")    # Wrapper-Kopf bleibt (Zuordnung)
    assert kurz.endswith("Mach weiter oder gib die finale Antwort.")  # Wrapper-Schluss bleibt


def test_compact_history_unter_budget_unangetastet():
    messages = [
        {"role": "user", "content": "Aufgabe"},
        {"role": "user", "content": "ERGEBNIS von health:\nok" + _WRAPPER_SCHLUSS},
    ]
    vorher = [dict(m) for m in messages]
    _compact_history(messages)
    assert messages == vorher
