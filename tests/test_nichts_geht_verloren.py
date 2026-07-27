"""Nichts geht still verloren — Wache gegen die Verlustpfade vom 27.07.2026.

Der Nutzer beklagte, dass Antworten und Meldungen ihn nie erreichen. Die Kartierung
fand einen gemeinsamen Konstruktionsfehler: der Zustand wurde aufgeraeumt, BEVOR
feststand, dass die Nachricht angekommen ist — und `_send` meldete Fehlschlaege
ueberhaupt nicht.

- `_send` verschluckte jede Sende-Exception: kein Retry, kein Event, kein Log.
  Wer danach seinen Puffer leerte, hielt das fuer eine erfolgreiche Zustellung.
- `melde.leeren()` leerte den Puffer VOR dem Senden -> bis zu 40 gesammelte
  Meldungen konnten in einem Rutsch verschwinden.
- `erinnerungen.zustellen` trug jeden Wecker aus, weil der Telegram-Sender nie warf.
- Der Feierabend-Blick stempelte den Tag als erledigt, bevor er gesendet wurde.
"""
from __future__ import annotations

import time

import pytest

from core.agency.missions import melde


@pytest.fixture
def puffer(tmp_path, monkeypatch):
    monkeypatch.setattr(melde, "_PATH", tmp_path / "melde_puffer.json")
    return melde


class TestMeldePuffer:
    def test_lesen_leert_den_puffer_nicht(self, puffer):
        puffer.merken("erste Zeile")
        puffer.merken("zweite Zeile")
        assert puffer.lesen() == ["erste Zeile", "zweite Zeile"]
        assert puffer.lesen() == ["erste Zeile", "zweite Zeile"]  # immer noch da

    def test_bestaetigen_raeumt_nur_das_zugestellte_ab(self, puffer):
        puffer.merken("alt 1")
        puffer.merken("alt 2")
        gesendet = puffer.lesen()
        puffer.merken("kam waehrend des Sendens dazu")
        puffer.bestaetigen(gesendet)
        assert puffer.lesen() == ["kam waehrend des Sendens dazu"]

    def test_ohne_bestaetigung_bleibt_alles_liegen(self, puffer):
        puffer.merken("wichtige Meldung")
        puffer.lesen()  # gelesen, aber Zustellung schlug fehl -> nicht bestaetigt
        assert puffer.lesen() == ["wichtige Meldung"]

    def test_bestaetigen_stempelt_die_flush_zeit(self, puffer):
        puffer.merken("x")
        assert puffer.faellig(0.25) is True
        puffer.bestaetigen(["x"])
        puffer.merken("y")
        assert puffer.faellig(0.25) is False  # gerade erst geflusht


class TestBuendelZustellung:
    """Der Bot darf den Puffer erst nach erfolgreicher Zustellung abraeumen."""

    def _bot(self, monkeypatch, tmp_path, erfolg: bool):
        from core.agency.connectors import telegram_bot as tb

        monkeypatch.setattr(melde, "_PATH", tmp_path / "melde_puffer.json")
        monkeypatch.setattr(tb, "_cfg", lambda: {"allowed_chat_id": 42})
        gesendet: list[str] = []

        def fake_send(client, chat, text, html=True, effect_id=None):
            gesendet.append(text)
            return erfolg

        monkeypatch.setattr(tb, "_send", fake_send)
        return tb, gesendet

    def test_bei_sendefehler_bleiben_die_meldungen_erhalten(self, monkeypatch, tmp_path):
        tb, gesendet = self._bot(monkeypatch, tmp_path, erfolg=False)
        melde.merken("Schritt A erledigt")
        melde.merken("Schritt B erledigt")
        monkeypatch.setattr(melde, "faellig", lambda s=3: True)
        tb._maybe_melde_buendel(None)
        assert gesendet, "es wurde ueberhaupt nicht gesendet"
        assert melde.lesen() == ["Schritt A erledigt", "Schritt B erledigt"]

    def test_bei_erfolg_wird_der_puffer_geleert(self, monkeypatch, tmp_path):
        tb, gesendet = self._bot(monkeypatch, tmp_path, erfolg=True)
        melde.merken("Schritt A erledigt")
        monkeypatch.setattr(melde, "faellig", lambda s=3: True)
        tb._maybe_melde_buendel(None)
        assert gesendet and melde.lesen() == []

    def test_kopf_zaehlt_was_wirklich_dasteht(self, monkeypatch, tmp_path):
        """Vorher: Kopf nannte 28 Schritte, darunter standen 15 — ohne Hinweis."""
        tb, gesendet = self._bot(monkeypatch, tmp_path, erfolg=True)
        for i in range(28):
            melde.merken(f"Schritt {i}")
        monkeypatch.setattr(melde, "faellig", lambda s=3: True)
        tb._maybe_melde_buendel(None)
        text = gesendet[0]
        assert text.count("\n• ") == 15
        assert "(15)" in text.splitlines()[0]
        assert "+13 aeltere" in text


class TestWeckerGehenNichtVerloren:
    @pytest.fixture
    def wecker(self, tmp_path, monkeypatch):
        from core.agency import erinnerungen

        monkeypatch.setattr(erinnerungen, "_PATH", tmp_path / "erinnerungen.json")
        return erinnerungen

    def _stellen(self, wecker, text="Muell rausbringen"):
        morgen = time.strftime("%d.%m.%Y", time.localtime(time.time() + 86400))
        e, fehler = wecker.add(text, morgen, "18:00")
        assert e, fehler
        return e

    def test_unzustellbarer_wecker_bleibt_stehen(self, wecker):
        e = self._stellen(wecker)
        n = wecker.zustellen(lambda t: False, now=e["ts"] + 1)
        assert n == 0
        assert [x["id"] for x in wecker.alle()] == [e["id"]]

    def test_zugestellter_wecker_wird_ausgetragen(self, wecker):
        e = self._stellen(wecker)
        assert wecker.zustellen(lambda t: True, now=e["ts"] + 1) == 1
        assert wecker.alle() == []

    def test_alt_aufrufer_ohne_rueckgabewert_bleiben_gueltig(self, wecker):
        """Der Cockpit-Pfad gibt None zurueck — das galt immer als zugestellt."""
        e = self._stellen(wecker)
        assert wecker.zustellen(lambda t: None, now=e["ts"] + 1) == 1
        assert wecker.alle() == []

    def test_ohne_sender_bleibt_es_beim_alten_verhalten(self, wecker):
        e = self._stellen(wecker)
        assert wecker.zustellen(None, now=e["ts"] + 1) == 1


class TestFeierabendBlick:
    def test_bei_sendefehler_wird_der_tag_nicht_abgehakt(self, monkeypatch, tmp_path):
        from core.agency.connectors import telegram_bot as tb

        stempel = tmp_path / "resuemee.json"
        monkeypatch.setattr(tb, "_RESUEMEE_FILE", stempel)
        monkeypatch.setattr(tb, "_cfg", lambda: {"allowed_chat_id": 42})
        monkeypatch.setattr(tb, "_resuemee_due", lambda: True)
        monkeypatch.setattr(tb, "_tagewerk_text", lambda: "irgendwas")
        monkeypatch.setattr(tb, "_send", lambda *a, **k: False)
        tb._maybe_evening_resuemee(None)
        assert not stempel.exists(), "Tag wurde abgehakt, obwohl nichts ankam"

    def test_bei_erfolg_wird_der_tag_abgehakt(self, monkeypatch, tmp_path):
        from core.agency.connectors import telegram_bot as tb

        stempel = tmp_path / "resuemee.json"
        monkeypatch.setattr(tb, "_RESUEMEE_FILE", stempel)
        monkeypatch.setattr(tb, "_cfg", lambda: {"allowed_chat_id": 42})
        monkeypatch.setattr(tb, "_resuemee_due", lambda: True)
        monkeypatch.setattr(tb, "_tagewerk_text", lambda: "irgendwas")
        monkeypatch.setattr(tb, "_send", lambda *a, **k: True)
        tb._maybe_evening_resuemee(None)
        assert stempel.exists()


class TestSendeFehlerWerdenAktenkundig:
    def test_send_meldet_fehlschlag_und_gibt_false_zurueck(self, monkeypatch):
        from core.agency.connectors import telegram_bot as tb

        class KaputterClient:
            def post(self, *a, **k):
                raise OSError("Netz weg")

        gemeldet: list[tuple] = []
        monkeypatch.setattr(tb, "_ctrl", lambda: KaputterClient())
        monkeypatch.setattr(tb.events, "emit",
                            lambda typ, payload=None, **k: gemeldet.append((typ, payload)))
        assert tb._send(None, 42, "eine wichtige Antwort") is False
        assert any(t == "telegram_send_failed" for t, _ in gemeldet)

    def test_send_meldet_auch_eine_telegram_absage(self, monkeypatch):
        from core.agency.connectors import telegram_bot as tb

        class AblehnenderClient:
            def post(self, *a, **k):
                class R:
                    @staticmethod
                    def json():
                        return {"ok": False, "error_code": 403, "description": "bot was blocked"}
                return R()

        gemeldet: list[tuple] = []
        monkeypatch.setattr(tb, "_ctrl", lambda: AblehnenderClient())
        monkeypatch.setattr(tb.events, "emit",
                            lambda typ, payload=None, **k: gemeldet.append((typ, payload)))
        assert tb._send(None, 42, "hallo") is False
        grund = next(p for t, p in gemeldet if t == "telegram_send_failed")
        assert "blocked" in grund["grund"]

    def test_erfolgreicher_versand_meldet_nichts(self, monkeypatch):
        from core.agency.connectors import telegram_bot as tb

        class GuterClient:
            def post(self, *a, **k):
                class R:
                    @staticmethod
                    def json():
                        return {"ok": True}
                return R()

        gemeldet: list[tuple] = []
        monkeypatch.setattr(tb, "_ctrl", lambda: GuterClient())
        monkeypatch.setattr(tb.events, "emit",
                            lambda typ, payload=None, **k: gemeldet.append((typ, payload)))
        assert tb._send(None, 42, "hallo") is True
        assert not gemeldet


class TestSelbstCheckSpricht:
    def test_meldungen_nennen_folge_und_handlung(self):
        from unittest.mock import patch

        from core.kernel import doctor

        with patch.object(doctor, "_port_open", return_value=False), \
             patch("shutil.which", return_value=None):
            rep = doctor.check()
        assert rep["problems"], "Testaufbau greift nicht"
        for p in rep["problems"]:
            assert "Zu tun:" in p, p
        text = " ".join(rep["problems"])
        assert "Embeddings tot" not in text and "Port 11434" not in text

    def test_alarm_verschweigt_die_restlichen_probleme_nicht(self, monkeypatch):
        from core.agency.missions import runner

        gesendet: list[str] = []
        monkeypatch.setattr(runner, "_notify",
                            lambda text, wichtig=False, kurz=None: gesendet.append(text))
        probleme = [f"Problem {i}. Zu tun: nichts." for i in range(8)]
        # denselben Textbau wie im Runner nachstellen
        rest = f"\n\n(+{len(probleme) - 5} weitere — im Cockpit unter Kira → Log.)"
        runner._notify("🩺 Beim Selbst-Check ist mir das aufgefallen:\n- "
                       + "\n- ".join(probleme[:5]) + rest, wichtig=True)
        assert "+3 weitere" in gesendet[0]


# ------------------------------------------------- Gemeinsamer Zustellweg

class TestZustellung:
    """cron._notify und runner._notify hatten je eine eigene Kopie desselben blinden
    httpx.post: Rueckgabe verworfen, kein Stueckeln, fehlender Token = stilles return.
    Telegram antwortet aber mit HTTP 200 und {"ok": false}, wenn der Bot blockiert ist."""

    def _mock(self, monkeypatch, antwort, chat=7, token="t"):
        from core.kernel import zustellung

        gemeldet: list[tuple] = []
        geschickt: list[dict] = []
        monkeypatch.setattr(zustellung, "_ziel", lambda: (token, chat))
        monkeypatch.setattr(zustellung.events, "emit",
                            lambda typ, payload=None, **k: gemeldet.append((typ, payload)))

        class FakeHttpx:
            @staticmethod
            def post(url, json=None, timeout=None):
                geschickt.append(json)

                class R:
                    @staticmethod
                    def json():
                        return antwort
                return R()

        monkeypatch.setitem(__import__("sys").modules, "httpx", FakeHttpx)
        return zustellung, gemeldet, geschickt

    def test_telegram_absage_gilt_nicht_als_zugestellt(self, monkeypatch):
        z, gemeldet, _ = self._mock(monkeypatch,
                                    {"ok": False, "description": "bot was blocked by the user"})
        assert z.an_nutzer("wichtige Meldung", quelle="cron") is False
        grund = next(p for t, p in gemeldet if t == "telegram_send_failed")
        assert "blocked" in grund["grund"] and grund["quelle"] == "cron"

    def test_erfolg_meldet_nichts(self, monkeypatch):
        z, gemeldet, _ = self._mock(monkeypatch, {"ok": True})
        assert z.an_nutzer("alles gut") is True
        assert not gemeldet

    def test_fehlende_konfiguration_ist_nicht_mehr_still(self, monkeypatch):
        z, gemeldet, _ = self._mock(monkeypatch, {"ok": True}, chat=None, token=None)
        assert z.an_nutzer("Meldung") is False
        assert any(t == "telegram_send_failed" for t, _ in gemeldet)

    def test_langer_text_wird_gestueckelt_statt_gekappt(self, monkeypatch):
        z, _, geschickt = self._mock(monkeypatch, {"ok": True})
        assert z.an_nutzer("x" * 9000) is True
        assert len(geschickt) == 3                      # 3800 + 3800 + 1400
        assert sum(len(p["text"]) for p in geschickt) == 9000


class TestCronMeldetAusfaelle:
    """Live-Stand: 66x cron_missed, ALLE sechs Tagesjobs auf "verpasst … PC aus?" —
    und der Nutzer erfuhr davon kein Wort."""

    @pytest.fixture
    def crons(self, tmp_path, monkeypatch):
        from core.agency.missions import cron
        from core.kernel import events

        events.init_db()   # add_job schreibt ein Event
        monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
        return cron

    def test_verpasste_termine_werden_gemeldet(self, monkeypatch, crons):
        cron = crons
        gesendet: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t) or True)
        monkeypatch.setattr(cron, "run_job", lambda j, notify=True: {"ok": True, "summary": ""})
        j = cron.add_job("Morgen-Briefing", "Briefing.", "08:00")
        # Job auf "gestern faellig" zuruecksetzen -> weit ueber MISSED_GRACE_S
        jobs = cron._load()
        jobs[0]["next_run"] = time.time() - 30 * 3600
        cron._save(jobs)
        cron.run_due()
        assert gesendet, "verpasster Termin wurde wieder verschwiegen"
        assert "ausgefallen" in gesendet[0] and "Morgen-Briefing" in gesendet[0]
        # Wortlaut nachgezogen: seit der Nachhol-Logik wird nicht mehr pauschal
        # liegengelassen — was verspaetet noch taugt, reicht Kira von selbst nach.
        assert "hole ich nicht nach" in gesendet[0]
        assert j["label"]

    def test_mehrere_verpasste_kommen_als_EINE_nachricht(self, monkeypatch, crons):
        cron = crons
        gesendet: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t) or True)
        for label in ("Morgen-Briefing", "Abend-Briefing", "Tagesnotiz"):
            cron.add_job(label, "x", "08:00")
        jobs = cron._load()
        for j in jobs:
            j["next_run"] = time.time() - 30 * 3600
        cron._save(jobs)
        cron.run_due()
        assert len(gesendet) == 1
        assert gesendet[0].count("• ") == 3
        assert "3 Termine" in gesendet[0]

    def test_gescheiterter_lauf_wird_ehrlich_gemeldet(self, monkeypatch, crons):
        """Der Ehrlichkeits-Fix (PR #205) unterdrueckte Erfolgsmeldungen bei ok=False —
        damit war ein ausgefallenes Briefing von einem nie geplanten ununterscheidbar."""
        cron = crons
        gesendet: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t) or True)
        monkeypatch.setattr("core.agency.act.act",
                            lambda *a, **k: {"text": "LLM-Call ueberschritt harte Wall-Clock-Grenze (150s)"})
        job = cron.add_job("Abend-Briefing", "News.", "20:00")
        voll = next(j for j in cron._load() if j["id"] == job["id"])
        res = cron.run_job(voll)
        assert res["ok"] is False
        assert gesendet and "konnte ich nicht fertigstellen" in gesendet[0]
        assert "Zeitlimit" in gesendet[0]

    def test_fehlschlag_meldung_hoechstens_einmal_pro_tag(self, monkeypatch, crons):
        cron = crons
        gesendet: list[str] = []
        monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t) or True)
        monkeypatch.setattr("core.agency.act.act", lambda *a, **k: {"text": ""})
        job = cron.add_job("Wetter", "Wetter.", "08:00")
        voll = next(j for j in cron._load() if j["id"] == job["id"])
        cron.run_job(voll)
        cron.run_job(voll)
        cron.run_job(voll)
        assert len(gesendet) == 1, gesendet


class TestNotrufLaesstSichNichtAbschalten:
    """Der Komfort-Schalter notify_telegram stand VOR der wichtig-Behandlung und legte
    damit auch aufgegebene Auftraege, Doktor-Befunde und Haenger still (Fund 27.07.)."""

    def test_wichtige_meldung_geht_auch_bei_abgeschaltetem_schalter_raus(self, monkeypatch):
        from core.agency.missions import runner

        gesendet: list[str] = []
        monkeypatch.setattr(runner, "_mission", lambda: {"notify_telegram": False})
        monkeypatch.setattr("core.kernel.zustellung.an_nutzer",
                            lambda text, quelle="": gesendet.append(text) or True)
        runner._notify("⚠️ Aufgabe nach 3 Versuchen aufgegeben", wichtig=True)
        assert gesendet

    def test_routine_meldung_respektiert_den_schalter(self, monkeypatch):
        from core.agency.missions import runner

        gesendet: list[str] = []
        monkeypatch.setattr(runner, "_mission", lambda: {"notify_telegram": False})
        monkeypatch.setattr("core.kernel.zustellung.an_nutzer",
                            lambda text, quelle="": gesendet.append(text) or True)
        runner._notify("Routine-Schritt erledigt", kurz="Schritt erledigt")
        assert not gesendet

    def test_unzustellbare_wichtige_meldung_landet_im_puffer(self, monkeypatch, tmp_path):
        from core.agency.missions import runner

        monkeypatch.setattr(melde, "_PATH", tmp_path / "melde_puffer.json")
        monkeypatch.setattr(runner, "_mission", lambda: {"notify_telegram": True})
        monkeypatch.setattr("core.kernel.zustellung.an_nutzer", lambda text, quelle="": False)
        runner._notify("⚠️ Aufgabe aufgegeben", wichtig=True, kurz="⚠️ Aufgabe aufgegeben")
        assert melde.lesen() == ["⚠️ Aufgabe aufgegeben"]
