"""Klassen-Wache: was das Manifest verspricht, muss die Funktion auch annehmen.

Audit-Fund 26.07.: @tool("schwarm") dekorierte den Helfer _items_aus(liste), weil der
beim Nacht-Fix ZWISCHEN Dekorator und Zielfunktion gerutscht war. Das Manifest
versprach vier Argumente, die registrierte Funktion nahm eines — JEDER Schwarm-Aufruf
endete in TypeError, obwohl das Modell alles richtig machte. Solche Fehler sind aus
Modellsicht unlernbar (die Beschreibung sagt ja etwas anderes), deshalb faengt die
Suite sie ab: fuer JEDES Werkzeug muessen die Manifest-Parameter in der Signatur
vorkommen — oder die Funktion muss **kwargs annehmen.
"""
from __future__ import annotations

import inspect

from core.agency.tools import builtin  # noqa: F401  (Import registriert die Werkzeuge)
from core.agency import act  # noqa: F401  (registriert todo_tools + delegate_tools)
from core.agency.tools import registry


def _nimmt_kwargs(sig: inspect.Signature) -> bool:
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


def test_manifest_parameter_passen_zur_signatur():
    fehler: list[str] = []
    for t in registry.all_tools(include_disabled=True):
        if t.name.startswith("mcp_"):      # Bruecken-Tools kommen zur Laufzeit dazu
            continue
        try:
            sig = inspect.signature(t.func)
        except (TypeError, ValueError):    # eingebaute/gewrappte Funktionen
            continue
        if _nimmt_kwargs(sig):
            continue
        unbekannt = [p for p in (t.params or {}) if p not in sig.parameters]
        if unbekannt:
            fehler.append(f"{t.name}: Manifest nennt {unbekannt}, "
                          f"Funktion {t.func.__name__}{sig} kennt sie nicht")
    assert not fehler, "Manifest und Funktion driften auseinander:\n" + "\n".join(fehler)


def test_werkzeugname_passt_zur_funktion():
    """Zweite Haelfte derselben Falle: der Dekorator sass auf einem Helfer, dessen Name
    mit dem Werkzeug nichts zu tun hatte. Ein privater Helfer (_name) ist immer ein
    Warnsignal — ein Werkzeug registriert nie eine Funktion mit fuehrendem Unterstrich."""
    verdaechtig = [f"{t.name} -> {t.func.__name__}"
                   for t in registry.all_tools(include_disabled=True)
                   if not t.name.startswith("mcp_") and t.func.__name__.startswith("_")]
    assert not verdaechtig, ("Werkzeuge zeigen auf private Helfer (Dekorator verrutscht?):\n"
                             + "\n".join(verdaechtig))


def test_schwarm_nimmt_seine_manifest_argumente():
    """Der konkrete Live-Fall, damit er nie zurueckkommt."""
    t = registry.get("schwarm")
    assert t is not None and t.func.__name__ == "schwarm"
    sig = inspect.signature(t.func)
    for p in ("auftrag_vorlage", "liste", "rang", "session_id"):
        assert p in sig.parameters, f"schwarm kennt {p} nicht"


# --- Auftrags-Verfall (Audit-Fund 26.07.) ------------------------------------------
# Ein Plan vom 21.07. mit 10 offenen Schritten stand am 27.07. immer noch als LETZTER
# Satz in jedem Chat-Prompt. Ein Plan, den tagelang niemand anfasst, darf die aktuelle
# Nachricht nicht mehr verdraengen — abrufbar bleibt er ueber todo_stand.

def test_frischer_auftrag_steht_im_prompt(tmp_path, monkeypatch):
    from core.agency import auftrag

    monkeypatch.setattr(auftrag, "_PATH", tmp_path / "auftrag.json")
    monkeypatch.setattr(auftrag, "_melden", lambda *a, **k: None)
    auftrag.set_plan("Testziel", ["Schritt eins", "Schritt zwei"])
    block = auftrag.prompt_block()
    assert "DEIN AKTIVER AUFTRAG" in block and "Schritt eins" in block
    assert not auftrag.ist_abgestanden()


def test_abgestandener_auftrag_faellt_aus_dem_prompt(tmp_path, monkeypatch):
    import json
    import time

    from core.agency import auftrag

    pfad = tmp_path / "auftrag.json"
    monkeypatch.setattr(auftrag, "_PATH", pfad)
    monkeypatch.setattr(auftrag, "_melden", lambda *a, **k: None)
    auftrag.set_plan("Altes Ziel", ["Nie angefasst"])
    d = json.loads(pfad.read_text(encoding="utf-8"))
    d["ts"] = time.time() - (auftrag.STALE_TAGE + 1) * 86400      # kuenstlich altern
    pfad.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    assert auftrag.ist_abgestanden()
    assert auftrag.prompt_block() == ""                            # draengt nicht mehr
    stand = auftrag.klartext()                                     # bleibt aber abrufbar
    assert "Altes Ziel" in stand and "unberuehrt" in stand


def test_leeres_board_bleibt_byte_identisch(tmp_path, monkeypatch):
    from core.agency import auftrag

    monkeypatch.setattr(auftrag, "_PATH", tmp_path / "leer.json")
    monkeypatch.setattr(auftrag, "_melden", lambda *a, **k: None)
    assert auftrag.prompt_block() == ""
    assert auftrag.klartext() == "(kein aktiver Auftrag)"
