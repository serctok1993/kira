"""Falsche Argumente lehren statt abstuerzen — Befund der Generalinventur (27.07.2026).

61 der 81 Werkzeuge nahmen kein `**falsche_args` entgegen. Ein falscher Argumentname
warf dort einen rohen TypeError, und der lief in die Executor-Mechanik hinein:

  * drei Versuche mit exponentiellem Backoff — rund 3 Sekunden für einen Fehler, der
    beim vierten Versuch genauso scheitert wie beim ersten,
  * danach zählte der Fehlschlag auf den Circuit-Breaker; nach dreimal war das Werkzeug
    60 Sekunden gesperrt — wegen eines Tippfehlers,
  * und das Modell bekam nie zu lesen, WELCHE Argumente richtig gewesen wären.

Zwei Enden werden geschlossen: eine Argument-Wache vor dem Aufruf (der TypeError
entsteht gar nicht erst) und ein Executor, der TypeError als deterministisch behandelt
statt ihn zu wiederholen.
"""
from __future__ import annotations

import inspect

import pytest

import core.agency.tools.builtin  # noqa: F401 — Registrierung ausloesen
import core.agency.tools.life_tools  # noqa: F401
import core.agency.tools.termin_tools  # noqa: F401
from core.agency import act
from core.agency.tools import registry


@pytest.fixture(autouse=True)
def _ereignis_tabelle():
    """Executor und Runner schreiben Ereignisse — ohne Tabelle wirft jeder Aufruf."""
    from core.kernel import events

    events.init_db()


def _tool(name: str):
    t = registry.get(name)
    assert t, f"{name} ist nicht registriert"
    return t


class TestArgumentWache:
    @pytest.mark.parametrize("name,args,muss_drin", [
        ("web_fetch", {"link": "https://example.com"}, ["url"]),
        ("todo_add", {"aufgabe": "Muell rausbringen"}, ["text"]),
        ("knowledge_note", {"name": "x", "inhalt": "y"}, ["title", "text"]),
    ])
    def test_unbekanntes_argument_wird_erklaert(self, name, args, muss_drin):
        fehler = act._falsche_argumente(name, _tool(name), args)
        assert fehler.startswith("Fehler:")
        for wort in muss_drin:
            assert wort in fehler, fehler
        assert f"ACT {name}" in fehler, "kein nachahmbares Beispiel"

    def test_fehlendes_pflichtargument_wird_benannt(self):
        fehler = act._falsche_argumente("objective_add", _tool("objective_add"), {})
        assert "braucht title" in fehler

    def test_gueltiger_aufruf_wird_durchgelassen(self):
        assert act._falsche_argumente("web_fetch", _tool("web_fetch"),
                                      {"url": "https://example.com"}) == ""

    def test_optionale_argumente_duerfen_fehlen(self):
        assert act._falsche_argumente("todo_add", _tool("todo_add"), {"text": "x"}) == ""

    def test_beispiel_zeigt_nur_pflichtargumente(self):
        """Ein Beispiel mit allen Optionalen lehrt das Modell, sie immer mitzuschicken."""
        fehler = act._falsche_argumente("todo_add", _tool("todo_add"), {"aufgabe": "x"})
        assert 'ACT todo_add {"text": "…"}' in fehler
        assert "prio" not in fehler.split("Beispiel:")[1]

    def test_werkzeuge_mit_eigener_lehre_werden_uebersprungen(self):
        """Die 20 Werkzeuge mit **falsche_args antworten spezifischer — nicht dazwischenfunken."""
        t = _tool("read_file")
        assert any(p.kind is p.VAR_KEYWORD for p in inspect.signature(t.func).parameters.values())
        assert act._falsche_argumente("read_file", t, {"pfad": "x.md"}) == ""

    def test_wache_verhindert_nie_einen_aufruf_wenn_sie_selbst_stolpert(self):
        class Kaputt:
            params: dict = {}

            @property
            def func(self):
                raise RuntimeError("kein Zugriff")

        assert act._falsche_argumente("irgendwas", Kaputt(), {"a": 1}) == ""


class TestZentralerRunner:
    def test_falscher_aufruf_erreicht_das_werkzeug_gar_nicht(self, monkeypatch):
        gerufen: list[str] = []
        t = _tool("web_fetch")
        monkeypatch.setattr("core.kernel.executor.run_tool",
                            lambda *a, **k: gerufen.append("x") or "sollte nicht laufen")
        obs = act._run_tool_guarded("web_fetch", t, {"link": "https://example.com"}, None)
        assert obs.startswith("Fehler:") and "url" in obs
        assert gerufen == [], "das Werkzeug wurde trotzdem aufgerufen"

    def test_gueltiger_aufruf_laeuft_normal_durch(self, monkeypatch):
        t = _tool("web_fetch")
        monkeypatch.setattr("core.kernel.executor.run_tool", lambda *a, **k: "Inhalt")
        assert act._run_tool_guarded("web_fetch", t, {"url": "https://example.com"}, None) == "Inhalt"

    def test_der_fehlgriff_wird_protokolliert(self, monkeypatch):
        gemeldet: list[str] = []
        monkeypatch.setattr(act.events, "emit",
                            lambda typ, p=None, **k: gemeldet.append(typ))
        act._run_tool_guarded("web_fetch", _tool("web_fetch"), {"link": "x"}, None)
        assert "tool_args_falsch" in gemeldet


class TestExecutorWiederholtNichtsDeterministisches:
    """Sicherheitsnetz: was die Wache durchlaesst, darf nicht dreimal versucht werden."""

    def test_typeerror_wird_sofort_durchgereicht(self, monkeypatch):
        from core.kernel import executor

        versuche: list[int] = []

        def kaputt(**kwargs):
            versuche.append(1)
            raise TypeError("unexpected keyword argument 'link'")

        monkeypatch.setattr(executor, "_failures", {})
        with pytest.raises(TypeError):
            executor.run_tool("probe", kaputt, link="x")
        assert len(versuche) == 1, f"{len(versuche)} Versuche — deterministischer Fehler"

    def test_typeerror_sperrt_das_werkzeug_nicht(self, monkeypatch):
        """Frueher: dreimal Tippfehler -> 60 Sekunden Circuit-Sperre."""
        from core.kernel import executor

        def kaputt(**kwargs):
            raise TypeError("falsches Argument")

        monkeypatch.setattr(executor, "_failures", {})
        for _ in range(4):
            with pytest.raises(TypeError):
                executor.run_tool("probe", kaputt, x=1)
        assert executor._failures.get("probe", 0) == 0, "Circuit-Zaehler lief mit"

    def test_echte_stoerungen_werden_weiter_wiederholt(self, monkeypatch):
        """Ein Netzfehler ist NICHT deterministisch — der Retry bleibt."""
        from core.kernel import executor

        versuche: list[int] = []

        def flackernd(**kwargs):
            versuche.append(1)
            if len(versuche) < 2:
                raise OSError("Netz weg")
            return "beim zweiten Mal geklappt"

        monkeypatch.setattr(executor, "_failures", {})
        monkeypatch.setattr("time.sleep", lambda s: None)
        assert executor.run_tool("probe", flackernd) == "beim zweiten Mal geklappt"
        assert len(versuche) == 2


class TestFlottenAbdeckung:
    def test_jedes_werkzeug_antwortet_lehrend_statt_abzustuerzen(self):
        """Der eigentliche Anspruch: KEIN Werkzeug wirft mehr bei einem Fantasie-Argument."""
        ungeschuetzt = []
        for t in registry.all_tools():
            if t.name.startswith("mcp_"):
                continue
            args = {"voellig_erfundenes_argument": "x"}
            hat_kwargs = any(p.kind is p.VAR_KEYWORD
                             for p in inspect.signature(t.func).parameters.values())
            if hat_kwargs:
                continue          # lehrt selbst — eigener Vertrag, eigene Tests
            if not act._falsche_argumente(t.name, t, args):
                ungeschuetzt.append(t.name)
        assert not ungeschuetzt, f"ohne Argument-Wache: {ungeschuetzt}"

    def test_die_flotte_ist_vollstaendig_abgedeckt(self):
        """Entweder eigenes **falsche_args oder die zentrale Wache — eines von beiden."""
        alle = [t for t in registry.all_tools() if not t.name.startswith("mcp_")]
        selbst = [t for t in alle
                  if any(p.kind is p.VAR_KEYWORD
                         for p in inspect.signature(t.func).parameters.values())]
        assert len(alle) - len(selbst) > 40, "Erwartungswert der Inventur verschoben?"
        assert len(selbst) >= 15, "die selbstlehrenden Werkzeuge sind verschwunden"
