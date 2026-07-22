"""Lehrfehler-Runde: zwei rohe TypeErrors aus den Nacht-Testbatterien (22.07.)
werden zu lehrenden Fehlern bzw. Durchreichen (#185-Muster).

Live-Fall 1 (c5b #12, events-belegt): cron_add ohne schedule ->
"Fehler bei 'cron_add': cron_add() missing 1 required positional argument: 'schedule'"
Live-Fall 2 (c5b #49): schwarm mit echtem JSON-Array ->
"Fehler bei 'schwarm': 'list' object has no attribute 'splitlines'"
"""
from __future__ import annotations

from core.agency.tools import delegate_tools
from core.agency.tools.builtin import cron_add


def test_cron_add_lehrt_statt_typeerror(monkeypatch):
    """DER Live-Fall: label+prompt ohne schedule -> Lehrfehler mit Beispiel-ACT."""
    aufrufe: list = []
    from core.agency.missions import cron
    monkeypatch.setattr(cron, "add_job", lambda *a, **k: aufrufe.append((a, k)) or
                        {"label": a[0], "schedule_text": a[2], "next_run": 1784700000})
    out = cron_add(label="Wetter-Fact", prompt="Erinnere an das Wetter.")
    assert "Fehler" in out and "schedule" in out and "ACT cron_add" in out
    assert aufrufe == []                                   # nichts halb angelegt
    assert "Fehler" in cron_add()                          # ganz leer -> lehrt
    kaputt = cron_add(label="x", prompt="y", schedule="08:00", zeitplan="08:00")
    assert "Fehler" in kaputt and aufrufe == []            # erfundenes Arg faengt


def test_cron_add_happy_path_unveraendert(monkeypatch):
    from core.agency.missions import cron
    monkeypatch.setattr(cron, "add_job", lambda label, prompt, schedule, scope="system":
                        {"label": label, "schedule_text": schedule, "next_run": 1784700000})
    out = cron_add(label="Wetter-Brief", prompt="Hol das Wetter.", schedule="07:30", scope="me")
    assert out.startswith("Geplant: Wetter-Brief")


def test_schwarm_nimmt_echte_listen():
    """DER Live-Fall: JSON-Array statt String — durchreichen, nicht crashen."""
    assert delegate_tools._items_aus(["a", " b ", ""]) == ["a", "b"]
    assert delegate_tools._items_aus(("x",)) == ["x"]
    assert delegate_tools._items_aus("eins\nzwei\n\n") == ["eins", "zwei"]
    assert delegate_tools._items_aus("") == []
    assert delegate_tools._items_aus(None) == []
    assert delegate_tools._items_aus([]) == []


def test_schwarm_leere_liste_lehrt():
    out = delegate_tools.schwarm("Vorlage {item}", [], session_id="")
    assert "Schwarm ohne Liste" in out
