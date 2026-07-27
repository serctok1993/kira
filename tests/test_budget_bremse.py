"""Die Budget-Bremse gilt jetzt auch für die Pfad-Wahl (Befund 27.07.2026).

DER FEHLER

`complete()` legt über die Modell-Konfiguration zwei Bremsen, die still auf das lokale
Modell umschwenken: das Tagesbudget und die Ausgangssperre. Die Pfad-Weiche `act._cloud()`
fragte aber nur `resolve_model()` — also das, was EINGESTELLT ist, nicht das, was
tatsächlich läuft.

Folge bei erschöpftem Budget: `_cloud()` sah ein Cloud-Modell, wählte den nativen
Function-Calling-Pfad und schickte rund 17.700 Token Werkzeug-Schemas los. Serviert wurde
dann ein 4B, das daran erstickte — entweder riss die 150-Sekunden-Grenze, oder es
antwortete höflich, ohne ein einziges Werkzeug zu rufen. 29 belegte Fälle in der Live-DB.
Der Nutzer erfuhr weder das eine noch das andere.

DIE LÖSUNG

`llm_router.effektives_modell()` beantwortet die Frage "welches Modell läuft WIRKLICH"
einmal — inklusive beider Bremsen. `_cloud()` und `complete()` fragen dieselbe Funktion,
also kann die Pfad-Entscheidung nicht mehr von der Modell-Entscheidung abweichen. Und weil
Sparflamme kein Geheimnis sein soll, sagt Kira einmal am Tag Bescheid.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.agency import act
from core.kernel import llm_router

CLOUD = "openrouter/z-ai/glm-5.2"
LOKAL = "ollama_chat/kira-c6"


@pytest.fixture(autouse=True)
def _ereignis_tabelle():
    """Die Bremsen schreiben Ereignisse — ohne Tabelle wirft jeder Aufruf."""
    from core.kernel import events

    events.init_db()


@pytest.fixture
def cloud_rolle(monkeypatch):
    """Eine Rolle, die auf ein Cloud-Modell zeigt — sonst greift keine Bremse."""
    monkeypatch.setattr(llm_router, "resolve_model", lambda *a, **k: (CLOUD, False))
    return CLOUD


class TestEffektivesModell:
    def test_bei_freiem_budget_bleibt_die_cloud(self, cloud_rolle):
        with patch.object(llm_router, "_budget_frei", return_value=(True, "")):
            w = llm_router.effektives_modell("reason", escalate=True)
        assert w["modell"] == CLOUD and w["bremse"] == ""

    def test_erschoepftes_budget_schwenkt_auf_lokal(self, cloud_rolle):
        with patch.object(llm_router, "_budget_frei", return_value=(False, "Tagesbudget erreicht.")):
            w = llm_router.effektives_modell("reason", escalate=True)
        assert llm_router.ist_lokal(w["modell"]), w["modell"]
        assert w["fell_back"] is True
        assert "Tagesbudget" in w["bremse"]

    def test_ausgangssperre_schwenkt_auf_lokal(self, cloud_rolle, monkeypatch):
        monkeypatch.setattr(llm_router, "outbound_blocked", lambda: True)
        monkeypatch.delenv("KIRA_ALLOW_LLM", raising=False)
        w = llm_router.effektives_modell("reason", escalate=True)
        assert llm_router.ist_lokal(w["modell"]) and w["fell_back"]
        assert "Ausgangssperre" in w["bremse"]

    def test_kira_allow_llm_hebt_die_sperre_auf(self, cloud_rolle, monkeypatch):
        monkeypatch.setattr(llm_router, "outbound_blocked", lambda: True)
        monkeypatch.setenv("KIRA_ALLOW_LLM", "1")
        with patch.object(llm_router, "_budget_frei", return_value=(True, "")):
            assert llm_router.effektives_modell("reason", escalate=True)["modell"] == CLOUD

    def test_direktwahl_unterliegt_denselben_bremsen(self, monkeypatch):
        """model=... (Benchmark) schlaegt die Rollenwahl — aber nicht das Budget."""
        with patch.object(llm_router, "_budget_frei", return_value=(False, "Tagesbudget erreicht.")):
            w = llm_router.effektives_modell("reason", model=CLOUD)
        assert llm_router.ist_lokal(w["modell"]) and "Tagesbudget" in w["bremse"]

    def test_lokale_direktwahl_bleibt_unberuehrt(self, monkeypatch):
        with patch.object(llm_router, "_budget_frei", return_value=(False, "Tagesbudget erreicht.")):
            w = llm_router.effektives_modell("reason", model=LOKAL)
        assert w["modell"] == LOKAL and w["bremse"] == ""

    def test_budget_frei_faellt_im_zweifel_auf_ja(self, monkeypatch):
        """Ein kaputtes Treasury darf Kira nicht lahmlegen."""
        import core.governance.treasury as t

        monkeypatch.setattr(t, "can_spend", lambda *a: (_ for _ in ()).throw(RuntimeError("kaputt")))
        assert llm_router._budget_frei()[0] is True


class TestPfadWeiche:
    """Der Kern: Pfad-Entscheidung und Modell-Entscheidung duerfen nicht auseinanderlaufen."""

    def test_bei_freiem_budget_nativer_pfad(self, cloud_rolle):
        with patch.object(llm_router, "_budget_frei", return_value=(True, "")):
            assert act._cloud(escalate=True) is True

    def test_bei_erschoepftem_budget_act_textpfad(self, cloud_rolle):
        """Vorher: nativer Pfad mit ~17.700 Token Schemas an ein 4B — 29 belegte Faelle."""
        with patch.object(llm_router, "_budget_frei", return_value=(False, "Tagesbudget erreicht.")):
            assert act._cloud(escalate=True) is False

    def test_weiche_und_router_sind_sich_immer_einig(self, cloud_rolle):
        """Die eigentliche Invariante: was _cloud() glaubt, muss complete() auch tun."""
        for budget_frei in (True, False):
            with patch.object(llm_router, "_budget_frei",
                              return_value=(budget_frei, "" if budget_frei else "Tagesbudget erreicht.")):
                w = llm_router.effektives_modell("reason", escalate=True)
                assert act._cloud(escalate=True) is (not llm_router.ist_lokal(w["modell"]))

    def test_bei_ausgangssperre_act_textpfad(self, cloud_rolle, monkeypatch):
        monkeypatch.setattr(llm_router, "outbound_blocked", lambda: True)
        monkeypatch.delenv("KIRA_ALLOW_LLM", raising=False)
        assert act._cloud(escalate=True) is False


class TestSparflammeWirdGesagt:
    """Sparflamme ist richtig — aber nicht heimlich."""

    @pytest.fixture
    def datenordner(self, tmp_path, monkeypatch):
        import core.config as cfg

        monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
        return tmp_path

    def test_bei_freiem_budget_kein_hinweis(self, datenordner):
        with patch.object(llm_router, "_budget_frei", return_value=(True, "")):
            assert act._sparflammen_hinweis() == ""

    def test_bei_erschoepftem_budget_ein_hinweis(self, datenordner):
        with patch.object(llm_router, "_budget_frei", return_value=(False, "Tagesbudget erreicht.")):
            hinweis = act._sparflammen_hinweis()
        assert "Tagesbudget" in hinweis and "lokalen Modell" in hinweis

    def test_hoechstens_einmal_pro_tag(self, datenordner):
        with patch.object(llm_router, "_budget_frei", return_value=(False, "Tagesbudget erreicht.")):
            erst = act._sparflammen_hinweis()
            zweit = act._sparflammen_hinweis()
            dritt = act._sparflammen_hinweis()
        assert erst and zweit == "" and dritt == ""

    def test_ein_kaputter_hinweis_verschluckt_keine_antwort(self, monkeypatch):
        monkeypatch.setattr(llm_router, "_budget_frei",
                            lambda: (_ for _ in ()).throw(RuntimeError("kaputt")))
        assert act._sparflammen_hinweis() == ""

    def test_hinweis_landet_nicht_im_trainingsmaterial(self, datenordner, monkeypatch):
        """Der Hinweis ist eine BETRIEBSMELDUNG, keine Aussage von Kira.

        Liefe er durch tuning.record_chat, lernte das Modell, von Tagesbudgets zu reden —
        und im Gedaechtnis taeuchte er als Kiras eigener Satz wieder auf."""
        import inspect

        quelle = inspect.getsource(act.act_chat)
        i_tuning = quelle.index("tuning.record_chat")
        i_hinweis = quelle.index("_sparflammen_hinweis()")
        assert i_hinweis > i_tuning, (
            "Der Sparflammen-Hinweis wird angehaengt, BEVOR die Episode mitgeschrieben "
            "wird — damit wandert er ins Trainingsmaterial")
        i_memory = quelle.index("memory.remember")
        assert i_hinweis > i_memory, "Hinweis landet im Gedaechtnis"


class TestBremseMittenImZug:
    """Fund der adversarialen Pruefung: die Pfad-Entscheidung faellt EINMAL pro Zug, die
    Bremse wirkt pro Call. Reisst der Deckel in Schritt 1 von 12, liefen die restlichen
    Schritte weiter mit ~17.700 Token Schemas gegen das lokale Modell — derselbe Fehler,
    nur vom Zug-Anfang in die Zug-Mitte verschoben."""

    def test_schwenk_waehrend_des_zuges_bricht_sauber_ab(self, monkeypatch):
        # Schritt 0 laeuft ohne Pruefung (der Pfad wurde beim Zug-Start gewaehlt);
        # ab dem ersten Check meldet die Weiche "lokal" — der Deckel ist gerissen.
        monkeypatch.setattr(act, "_cloud", lambda *a, **k: False)
        gerufen: list[int] = []

        def fake_complete(*a, **k):
            gerufen.append(1)
            return {"text": "", "tool_calls": [{"id": "1", "name": "jetzt", "args": {}}]}

        monkeypatch.setattr(act, "_complete_resilient", fake_complete)
        text = act._native_loop([{"role": "user", "content": "x"}], system="s",
                                session_id="t", escalate=True, emit=lambda e: None,
                                max_steps=8)
        assert "SAUBER ab" in text
        assert len(gerufen) == 1, "der Loop lief nach dem Schwenk weiter"

    def test_ohne_schwenk_laeuft_der_zug_normal_durch(self, monkeypatch):
        monkeypatch.setattr(act, "_cloud", lambda *a, **k: True)
        monkeypatch.setattr(act, "_complete_resilient",
                            lambda *a, **k: {"text": "fertig", "tool_calls": []})
        text = act._native_loop([{"role": "user", "content": "x"}], system="s",
                                session_id="t", escalate=True, emit=lambda e: None,
                                max_steps=4)
        assert text == "fertig"

    def test_abbruch_nennt_den_teilstand(self):
        nachrichten = [
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "web_search"}}, {"function": {"name": "read_file"}}]},
        ]
        t = act._pfadwechsel_text(nachrichten)
        assert "web_search" in t and "read_file" in t
        assert "weiter" in t


class TestBremsenWerdenUnterschieden:
    """Monatsdeckel ist nicht Tagesdeckel, und die Ausgangssperre ist keine Kostenbremse."""

    def test_monatsdeckel_wird_woertlich_zitiert(self, cloud_rolle, monkeypatch):
        """Sonst verspricht Kira "bis Mitternacht" — und wiederholt das bis zum Monatsersten."""
        monkeypatch.setattr(llm_router, "_budget_frei",
                            lambda: (False, "Monatsbudget 150.0 EUR wuerde ueberschritten."))
        wahl = llm_router.effektives_modell("reason", escalate=True)
        assert "Monatsbudget" in wahl["bremse"] and wahl["art"] == "budget"

    def test_ausgangssperre_ist_keine_budget_bremse(self, cloud_rolle, monkeypatch):
        monkeypatch.setattr(llm_router, "outbound_blocked", lambda: True)
        monkeypatch.delenv("KIRA_ALLOW_LLM", raising=False)
        wahl = llm_router.effektives_modell("reason", escalate=True)
        assert wahl["art"] == "firewall", "Sandbox meldet sonst eine Kostenbremse"

    def test_escalate_wird_zurueckgesetzt(self, cloud_rolle, monkeypatch):
        """Sonst verbucht die Kalibrierung Eskalationen, die nie stattfanden."""
        monkeypatch.setattr(llm_router, "_budget_frei", lambda: (False, "Tagesbudget erreicht."))
        assert llm_router.effektives_modell("reason", escalate=True)["escalate"] is False

    def test_das_verworfene_modell_bleibt_nachvollziehbar(self, cloud_rolle, monkeypatch):
        """Sonst steht in jedem Ereignis nur der Fallback — die Forensik ist blind."""
        monkeypatch.setattr(llm_router, "_budget_frei", lambda: (False, "Tagesbudget erreicht."))
        wahl = llm_router.effektives_modell("reason", escalate=True)
        assert wahl["verworfen"] == CLOUD and wahl["modell"] != CLOUD

    def test_hinweis_zitiert_den_grund_statt_mitternacht_zu_versprechen(self, tmp_path, monkeypatch):
        import core.config as cfg

        monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
        monkeypatch.setattr(llm_router, "_budget_frei",
                            lambda: (False, "Monatsbudget 150.0 EUR wuerde ueberschritten."))
        hinweis = act._sparflammen_hinweis()
        assert "Monatsbudget" in hinweis
        assert "Mitternacht" not in hinweis
