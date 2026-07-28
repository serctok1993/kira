"""Ein Mass fuer alle passt niemandem — Grenzen muessen dem Modell folgen.

Befund der Nacht (28.07.2026), gemessen an 14 Tagen Ereignis-DB. Von 103 Fehlern
sind 51 derselbe:

    "LLM-Call ueberschritt harte Wall-Clock-Grenze (150s)"

verteilt auf Verifier (23), Missionen (16), Wartung (4), Heartbeat (3), Chat (5).
Dazu 9x ContextWindowExceededError. Beide Fehlerklassen haben dieselbe Wurzel: EINE
global konfigurierte Zahl, kalibriert am schnellen Cloud-Call, angewandt auch auf ein
35B, das auf der heimischen GPU rechnet.

Die Latenzen der letzten Wochen zeigen, wie schief das sitzt:

    Modell        n     median   p90     p99     >150s
    glm-5.2    2625      6,5s   27,5s   88,3s    0,1 %
    deepseek   2208      6,9s   19,1s   59,6s    0,0 %
    kira-c6-9b  361     10,1s   55,3s  108,2s    0,3 %
    qwen35b      33     79,7s  268,1s  573,0s   27,3 %
    nacht35b     44     50,9s  112,2s  378,6s    6,8 %

Fuer die grossen lokalen Modelle lag die Grenze MITTEN im Normalbetrieb. Ein lokaler
Call kostet nichts ausser Zeit; ihn abzuschiessen wirft die ganze Runde weg. Cloud
bleibt eng — dort ist ein haengender Socket real (ein Call hing ~8 Minuten) und laeuft
aufs Geld.

Beim Kontext dasselbe Muster: das Zeichenbudget der ACT-History ist eine Zahl fuer
alle. Der lokale 35B-Endpunkt hat 8192 Token Kontext und bekam 16412 geschickt —
exakt das Doppelte. Statt eine Kontextgroesse je Modell zu pflegen, rechnet der
Harness sie aus dem Fehler aus und versucht es einmal gekuerzt erneut.
"""
from __future__ import annotations

import pytest

from core.kernel import llm_router as r


class TestWallClockFolgetDemModell:
    @pytest.mark.parametrize("kwargs", [
        {"model": "ollama_chat/kira-c6-9b"},
        {"model": "ollama/qwen3.5:9b"},
        {"model": "openai/nacht35b", "api_base": "http://127.0.0.1:8080/v1"},
        {"model": "openai/x", "api_base": "http://localhost:11434/v1"},
    ])
    def test_lokale_calls_werden_erkannt(self, kwargs):
        assert r._ist_lokaler_call(kwargs) is True

    @pytest.mark.parametrize("kwargs", [
        {"model": "openrouter/z-ai/glm-5.2"},
        {"model": "openrouter/deepseek/deepseek-v4-flash"},
        # aimlapi ist ein CLOUD-Anbieter, hat aber ebenfalls ein api_base — ein
        # api_base allein taugt deshalb nicht als Kennzeichen fuer "lokal".
        {"model": "openai/gpt-x", "api_base": "https://api.aimlapi.com/v1"},
    ])
    def test_cloud_calls_bleiben_cloud(self, kwargs):
        assert r._ist_lokaler_call(kwargs) is False

    def test_lokal_bekommt_mehr_luft_als_cloud(self):
        assert r._hard_cap_seconds(lokal=True) > r._hard_cap_seconds(lokal=False)

    def test_die_lokale_grenze_deckt_den_gemessenen_normalbetrieb(self):
        """qwen35b p99 = 573s — darunter darf die Grenze nicht liegen."""
        assert r._hard_cap_seconds(lokal=True) >= 573

    def test_cloud_bleibt_eng(self):
        """Ein haengender Cloud-Socket kostet Geld — da bleibt der Deckel scharf."""
        assert r._hard_cap_seconds(lokal=False) <= 300


class TestKontextZielAusrechnen:
    FEHLER = ("litellm.ContextWindowExceededError: request (16412 tokens) exceeds "
              "the available context size (8192 tokens), try increasing it")

    def _msgs(self, zeichen: int) -> list[dict]:
        return [{"role": "system", "content": "S" * (zeichen // 2)},
                {"role": "user", "content": "U" * (zeichen - zeichen // 2)}]

    def test_ziel_liegt_unter_dem_ist(self):
        msgs = self._msgs(60000)
        assert r._kontext_ziel(self.FEHLER, msgs, 2048) < 60000

    def test_ziel_beruecksichtigt_den_platz_fuer_die_antwort(self):
        """8192 verfuegbar, 2048 fuer die Antwort -> hoechstens 6144 Token Eingabe."""
        msgs = self._msgs(60000)
        pro_token = 60000 / 16412
        ziel = r._kontext_ziel(self.FEHLER, msgs, 2048)
        assert ziel <= (8192 - 2048) * pro_token

    def test_ohne_zahlen_im_fehlertext_wird_halbiert(self):
        msgs = self._msgs(60000)
        assert r._kontext_ziel("context length exceeded", msgs, 2048) == 30000

    def test_das_ziel_wird_nie_absurd_klein(self):
        assert r._kontext_ziel("context length exceeded", self._msgs(100), 2048) >= 2000


class TestAusgabeDeckelBeimZweitenAnlauf:
    """config.yaml erlaubt 8192 Ausgabe-Token — genau der GESAMTE Kontext des lokalen
    35B. Ohne Deckel faende der gekuerzte zweite Anlauf dieselbe Wand vor."""

    FEHLER = TestKontextZielAusrechnen.FEHLER

    def test_die_ausgabe_bekommt_hoechstens_den_halben_kontext(self):
        assert r._kontext_ausgabe_deckel(self.FEHLER, 8192) == 4096

    def test_ein_kleinerer_wunsch_bleibt_unangetastet(self):
        assert r._kontext_ausgabe_deckel(self.FEHLER, 1024) == 1024

    def test_ohne_zahlen_bleibt_der_wunsch_stehen(self):
        assert r._kontext_ausgabe_deckel("context too long", 8192) == 8192

    def test_eingabe_und_ausgabe_passen_zusammen_in_den_kontext(self):
        """Die eigentliche Probe: Rest-Eingabe + Ausgabe muessen unter 8192 bleiben."""
        msgs = [{"role": "system", "content": "S" * 30000},
                {"role": "user", "content": "U" * 30000}]
        deckel = r._kontext_ausgabe_deckel(self.FEHLER, 8192)
        ziel = r._kontext_ziel(self.FEHLER, msgs, deckel)
        kurz = r._auf_mass_kuerzen(msgs, ziel)
        pro_token = 60000 / 16412
        assert r._zeichen(kurz) / pro_token + deckel <= 8192


class TestAufMassKuerzen:
    def _lauf(self, n: int, laenge: int = 2000) -> list[dict]:
        msgs = [{"role": "system", "content": "SYSTEM " * 100}]
        for i in range(n):
            msgs.append({"role": "assistant", "content": f"Schritt {i} " * (laenge // 10)})
            msgs.append({"role": "user", "content": f"ERGEBNIS {i} " * (laenge // 10)})
        msgs.append({"role": "user", "content": "Worauf ich jetzt antworten soll."})
        return msgs

    def test_passt_schon_dann_bleibt_alles(self):
        msgs = [{"role": "system", "content": "kurz"}, {"role": "user", "content": "hallo"}]
        assert r._auf_mass_kuerzen(msgs, 10000) == msgs

    def test_kuerzt_unter_das_ziel(self):
        msgs = self._lauf(8)
        gekuerzt = r._auf_mass_kuerzen(msgs, 3000)
        assert r._zeichen(gekuerzt) <= 3000

    def test_die_letzte_nachricht_bleibt_ganz(self):
        """Darin steht, worauf das Modell gerade antworten soll."""
        msgs = self._lauf(8)
        gekuerzt = r._auf_mass_kuerzen(msgs, 3000)
        assert gekuerzt[-1]["content"] == "Worauf ich jetzt antworten soll."

    def test_das_original_wird_nicht_veraendert(self):
        msgs = self._lauf(8)
        vorher = r._zeichen(msgs)
        r._auf_mass_kuerzen(msgs, 3000)
        assert r._zeichen(msgs) == vorher

    def test_die_rolle_der_nachrichten_bleibt_gueltig(self):
        gekuerzt = r._auf_mass_kuerzen(self._lauf(8), 3000)
        assert all(m["role"] in ("system", "user", "assistant") for m in gekuerzt)
        assert gekuerzt[0]["role"] == "system"

    def test_der_verzicht_wird_sichtbar_gemacht(self):
        """Das Modell soll merken, dass etwas fehlt — nicht stillschweigend raten."""
        text = " ".join(str(m["content"]) for m in r._auf_mass_kuerzen(self._lauf(8), 3000))
        assert "gekuerzt" in text or "ausgelassen" in text

    def test_notnagel_stutzt_zuletzt_den_systemprompt(self):
        msgs = [{"role": "system", "content": "X" * 50000},
                {"role": "user", "content": "kurz"}]
        gekuerzt = r._auf_mass_kuerzen(msgs, 5000)
        assert r._zeichen(gekuerzt) <= 5000
        assert len(gekuerzt[0]["content"]) < 50000

    def test_eine_einzelne_nachricht_bleibt_unversehrt(self):
        msgs = [{"role": "user", "content": "X" * 9000}]
        assert r._auf_mass_kuerzen(msgs, 100) == msgs


class TestDieVerdrahtungInComplete:
    """Die Bausteine oben stimmen — hier geht es um den echten Weg durch complete()."""

    FEHLER = ("litellm.BadRequestError: ContextWindowExceededError: request "
              "(16412 tokens) exceeds the available context size (8192 tokens)")

    @pytest.fixture(autouse=True)
    def _ereignis_tabelle(self):
        from core.kernel import events
        events.init_db()

    def _antwort(self, text="Fertig."):
        class _M:
            def __init__(self): self.content = text; self.tool_calls = None
        class _C:
            def __init__(self): self.message = _M(); self.finish_reason = "stop"
        class _R:
            def __init__(self): self.choices = [_C()]; self.usage = None
        return _R()

    def test_zu_grosser_kontext_wird_gekuerzt_und_gelingt_beim_zweiten_mal(self, monkeypatch):
        aufrufe: list[int] = []

        def fake(**kw):
            aufrufe.append(r._zeichen(kw["messages"]))
            if len(aufrufe) == 1:
                raise r.litellm.ContextWindowExceededError(
                    message=self.FEHLER, model="nacht35b", llm_provider="openai")
            return self._antwort()

        monkeypatch.setattr(r, "_completion", fake)
        monkeypatch.setattr(r, "resolve_model", lambda *a, **k: ("nacht35b", False))
        lange = [{"role": "user", "content": "Wort " * 4000}]
        res = r.complete(lange, system="S" * 4000)

        assert res["text"] == "Fertig."
        assert len(aufrufe) == 2, "es gab keinen zweiten Anlauf"
        assert aufrufe[1] < aufrufe[0], "der zweite Anlauf war nicht kleiner"

    def test_der_gekuerzte_anlauf_wird_protokolliert(self, monkeypatch):
        gemeldet: list[tuple] = []
        zaehler: list[int] = []

        def fake(**kw):
            zaehler.append(1)
            if len(zaehler) == 1:
                raise r.litellm.ContextWindowExceededError(
                    message=self.FEHLER, model="nacht35b", llm_provider="openai")
            return self._antwort()

        monkeypatch.setattr(r, "_completion", fake)
        monkeypatch.setattr(r, "resolve_model", lambda *a, **k: ("nacht35b", False))
        monkeypatch.setattr(r.events, "emit",
                            lambda typ, p=None, **k: gemeldet.append((typ, p or {})))
        r.complete([{"role": "user", "content": "Wort " * 4000}], system="S" * 4000)

        retry = [p for typ, p in gemeldet if typ == "llm_call_retry"]
        assert retry, "kein llm_call_retry gemeldet"
        assert retry[0]["reason"] == "kontext"
        assert retry[0]["zeichen_nachher"] < retry[0]["zeichen_vorher"]

    def test_hilft_auch_das_kuerzen_nicht_wird_der_fehler_ehrlich_durchgereicht(self, monkeypatch):
        def immer_zu_gross(**kw):
            raise r.litellm.ContextWindowExceededError(
                message=self.FEHLER, model="nacht35b", llm_provider="openai")

        monkeypatch.setattr(r, "_completion", immer_zu_gross)
        monkeypatch.setattr(r, "resolve_model", lambda *a, **k: ("nacht35b", False))
        with pytest.raises(Exception):
            r.complete([{"role": "user", "content": "Wort " * 4000}], system="S")

    def test_ein_normaler_call_loest_keinen_zweiten_aus(self, monkeypatch):
        """Der Waechter darf im Regelfall nichts kosten."""
        zaehler: list[int] = []

        def fake(**kw):
            zaehler.append(1)
            return self._antwort()

        monkeypatch.setattr(r, "_completion", fake)
        monkeypatch.setattr(r, "resolve_model", lambda *a, **k: ("nacht35b", False))
        r.complete([{"role": "user", "content": "kurz"}], system="S")
        assert len(zaehler) == 1
