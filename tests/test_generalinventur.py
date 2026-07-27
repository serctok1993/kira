"""Befunde der Generalinventur (27.07.2026) — ein Agententeam quer durchs Repo.

Die schwersten Funde, jeder mit dem Beleg, der ihn nachgewiesen hat:

1. parse_schedule verstand "taeglich 08:00" nicht (nur englisch "daily 08:00") und
   verwandelte alles Unverstandene stillschweigend in einen Stundentakt. In der Live-DB
   stehen 15 cron_added-Ereignisse mit schedule "taeglich 09:00" — gewuenscht war EIN
   Briefing pro Tag, angelegt wurden 24. Wahrscheinlichster Einzeltreiber der Melde-Flut.
2. llm_router.stream() fragte in seiner ersten Zeile `model` ab, hatte den Parameter
   aber nicht in der Signatur -> UnboundLocalError bei JEDEM Aufruf.
3. Ein gelungener Cron-Lauf war verloren, wenn Telegram klemmte: im Cockpit ein Haken,
   beim Nutzer nichts.
4. Jede beliebige Webseite im Browser des Nutzers konnte dem Cockpit POST-Befehle
   schicken — auf dem Rechner, auf dem .env und secrets.json liegen.
5. run_now schrieb die ganze Job-Liste zurueck (derselbe Fehler, der am 26.07. in
   run_due behoben wurde) und loeschte damit parallele Aenderungen.
6. Wecker konnte man nur STELLEN — nicht sehen, nicht absagen. Und cron_update fehlte,
   obwohl cron.update_job existiert (und ein Fehlertext bereits darauf verwies).
"""
from __future__ import annotations

import pytest

from core.agency.missions import cron


class TestZeitplanVerstehen:
    @pytest.mark.parametrize("text,typ,zeit", [
        ("täglich 08:00", "daily", "08:00"),
        ("taeglich 09:00", "daily", "09:00"),      # 15x live so angelegt worden
        ("daily 08:00", "daily", "08:00"),
        ("08:00", "daily", "08:00"),
        ("08:00 uhr", "daily", "08:00"),
        ("um 08:00", "daily", "08:00"),
        ("jeden tag 08:00", "daily", "08:00"),
        ("jeden morgen 07:30", "daily", "07:30"),
        ("abends 20:00", "daily", "20:00"),
        ("9:05", "daily", "09:05"),
    ])
    def test_deutsche_tagesplaene(self, text, typ, zeit):
        s = cron.parse_schedule(text)
        assert s["type"] == typ and s["time"] == zeit, (text, s)

    @pytest.mark.parametrize("text,minuten", [
        ("30m", 30), ("2h", 120), ("90", 90),
        ("alle 30 minuten", 30), ("alle 2 stunden", 120),
        ("stündlich", 60), ("stuendlich", 60),
    ])
    def test_abstaende(self, text, minuten):
        s = cron.parse_schedule(text)
        assert s["type"] == "interval" and s["minutes"] == minuten, (text, s)

    def test_wochentage_bleiben_wie_sie_waren(self):
        assert cron.parse_schedule("werktags 08:00") == {
            "type": "weekly", "days": [0, 1, 2, 3, 4], "time": "08:00"}
        assert cron.parse_schedule("sonntags 20:00") == {
            "type": "weekly", "days": [6], "time": "20:00"}

    @pytest.mark.parametrize("text", ["aus", "irgendwann", "wenn ich zeit habe", "",
                                      "bei Sonnenaufgang", "manchmal"])
    def test_unverstandenes_wird_nicht_mehr_still_stuendlich(self, text):
        """DER Fund: der stumme 60-Minuten-Default hat Jobs angelegt, die niemand wollte."""
        assert cron.parse_schedule(text)["type"] == "unklar", text

    def test_cron_add_lehrt_statt_zu_raten(self, tmp_path, monkeypatch):
        from core.agency.tools import builtin
        from core.kernel import events

        events.init_db()
        monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
        antwort = builtin.cron_add("Briefing", "News lesen.", "wenn ich zeit habe")
        assert antwort.startswith("Fehler:")
        assert "verstehe ich nicht als Zeitplan" in antwort
        assert "werktags 08:00" in antwort      # nennt gueltige Formen
        assert cron.list_jobs() == [], "Job wurde trotzdem angelegt"


class TestStreamSignatur:
    def test_stream_kennt_model(self):
        """stream() fragte `model` ab, ohne es als Parameter zu haben — UnboundLocalError."""
        import inspect

        from core.kernel import llm_router

        for fn in (llm_router.stream, llm_router.stream_tagged):
            assert "model" in inspect.signature(fn).parameters, fn.__name__

    def test_beide_streamer_haben_dieselben_parameter(self):
        """Der Fehler entstand beim Angleichen — die Abweichung faellt jetzt auf."""
        import inspect

        from core.kernel import llm_router

        a = set(inspect.signature(llm_router.stream).parameters)
        b = set(inspect.signature(llm_router.stream_tagged).parameters)
        assert a == b, f"nur in stream: {a - b} / nur in stream_tagged: {b - a}"


class TestFremdseitenSchutz:
    """Der Fernzugriff-Schutz laesst Loopback frei — richtig fuer die Desktop-Huelle,
    aber damit stand das Cockpit auch jeder Seite offen, die im selben Browser lief."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        import core.api.server as s
        return TestClient(s.app)

    def test_post_von_fremder_seite_wird_abgewiesen(self, client):
        r = client.post("/api/focus", json={"focus": "x"},
                        headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403

    def test_post_mit_fremdem_origin_wird_abgewiesen(self, client):
        r = client.post("/api/focus", json={"focus": "x"},
                        headers={"origin": "https://boese.example"})
        assert r.status_code == 403

    def test_praefix_trick_faellt_nicht_durch(self, client):
        """'localhost.boese.example' faengt an wie localhost, ist aber fremd."""
        r = client.post("/api/focus", json={"focus": "x"},
                        headers={"origin": "http://localhost.boese.example"})
        assert r.status_code == 403

    def test_cockpit_darf_weiter_schreiben(self, client):
        r = client.post("/api/focus", json={"focus": "x"},
                        headers={"sec-fetch-site": "same-origin",
                                 "origin": "http://127.0.0.1:8000"})
        assert r.status_code != 403

    def test_native_aufrufer_ohne_header_bleiben_unberuehrt(self, client):
        """Desktop-Huelle, Skripte und curl senden keine Browser-Header."""
        assert client.post("/api/focus", json={"focus": "x"}).status_code != 403

    def test_lesen_bleibt_frei(self, client):
        assert client.get("/health", headers={"sec-fetch-site": "cross-site"}).status_code == 200


class TestNeueWerkzeuge:
    @pytest.fixture
    def crons(self, tmp_path, monkeypatch):
        from core.kernel import events

        events.init_db()
        monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
        return cron

    @pytest.fixture
    def wecker(self, tmp_path, monkeypatch):
        from core.agency import erinnerungen

        monkeypatch.setattr(erinnerungen, "_PATH", tmp_path / "erinnerungen.json")
        return erinnerungen

    def test_cron_update_aendert_und_behaelt_die_historie(self, crons):
        from core.agency.tools import builtin

        job = crons.add_job("Briefing", "News.", "08:00")
        jobs = crons._load()
        jobs[0]["runs"] = [{"ts": 1, "ok": True, "summary": "alter Lauf"}]
        crons._save(jobs)
        antwort = builtin.cron_update(job_id=job["id"], schedule="werktags 09:00")
        assert "Geaendert" in antwort and "werktags 09:00" in antwort
        neu = crons._load()[0]
        assert neu["schedule"]["type"] == "weekly"
        assert neu["runs"], "Historie wurde vernichtet"

    def test_cron_update_ohne_aenderung_lehrt(self, crons):
        from core.agency.tools import builtin

        job = crons.add_job("Briefing", "News.", "08:00")
        assert "nichts zu aendern" in builtin.cron_update(job_id=job["id"])

    def test_cron_update_lehnt_unklaren_zeitplan_ab(self, crons):
        from core.agency.tools import builtin

        job = crons.add_job("Briefing", "News.", "08:00")
        a = builtin.cron_update(job_id=job["id"], schedule="irgendwann")
        assert a.startswith("Fehler:") and "verstehe ich nicht" in a

    def test_der_duplikat_fehlertext_verweist_auf_ein_echtes_werkzeug(self):
        """Der Waechter aus der Duplikat-Runde nannte cron_update — das es nicht gab."""
        import core.agency.tools.builtin  # noqa: F401
        from core.agency.tools import registry

        assert "- cron_update (" in registry.manifest()

    def test_wecker_lassen_sich_auflisten_und_absagen(self, wecker):
        import time as _t

        from core.agency.tools import termin_tools

        morgen = _t.strftime("%d.%m.%Y", _t.localtime(_t.time() + 86400))
        e, fehler = wecker.add("Aufstehen", morgen, "09:00")
        assert e, fehler
        liste = termin_tools.erinnerung_list()
        assert "Aufstehen" in liste and e["id"] in liste
        assert "abgesagt" in termin_tools.erinnerung_remove(kennung=e["id"])
        assert wecker.alle() == []

    def test_wecker_absagen_geht_auch_ueber_den_text(self, wecker):
        import time as _t

        from core.agency.tools import termin_tools

        morgen = _t.strftime("%d.%m.%Y", _t.localtime(_t.time() + 86400))
        wecker.add("Muell rausbringen", morgen, "18:00")
        assert "abgesagt" in termin_tools.erinnerung_remove(kennung="muell rausbringen")
        assert wecker.alle() == []

    def test_erinnerung_remove_nimmt_id_als_alias(self, wecker):
        import time as _t

        from core.agency.tools import termin_tools

        morgen = _t.strftime("%d.%m.%Y", _t.localtime(_t.time() + 86400))
        e, _ = wecker.add("Anruf", morgen, "10:00")
        assert "abgesagt" in termin_tools.erinnerung_remove(id=e["id"])

    def test_unbekannter_wecker_wird_erklaert(self, wecker):
        from core.agency.tools import termin_tools

        a = termin_tools.erinnerung_remove(kennung="gibtsnicht")
        assert "erinnerung_list" in a

    def test_neue_werkzeuge_sind_im_chat_erreichbar(self):
        """31 Werkzeuge stehen in keiner Rolle und wurden nie aufgerufen — die neuen nicht."""
        import core.agency.tools.builtin  # noqa: F401
        import core.agency.tools.termin_tools  # noqa: F401
        from core.agency import rollen

        karte = rollen.manifest("haupt")
        for name in ("cron_update", "erinnerung_list", "erinnerung_remove"):
            assert f"- {name} (" in karte, f"{name} fehlt in der haupt-Karte"


class TestRunNow:
    def test_run_now_zerstoert_keine_parallelen_aenderungen(self, tmp_path, monkeypatch):
        """Derselbe Fehler, der am 26.07. in run_due behoben wurde, lebte hier weiter."""
        from core.kernel import events

        events.init_db()
        monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
        job = cron.add_job("Briefing", "News.", "08:00")

        def waehrenddessen(j, notify=True, verspaetet_min=0):
            cron.add_job("Waehrend des Laufs angelegt", "x", "10:00")
            return {"ok": True, "summary": ""}

        monkeypatch.setattr(cron, "run_job", waehrenddessen)
        cron.run_now(job["id"])
        labels = [j["label"] for j in cron.list_jobs()]
        assert "Waehrend des Laufs angelegt" in labels, labels
