"""Verpasste Termine nachholen — Befund der Generalinventur (27.07.2026).

Kiras Cron-Modell setzte einen Rechner voraus, der durchlaeuft. Der des Nutzers tut das
nicht: von 13.008 Ereignissen der letzten 14 Tage lagen nur 13 % zwischen 6 und 10 Uhr —
genau dort, wo vier von sechs Jobs terminiert sind. Jeder verpasste Termin wurde ersatzlos
gestrichen, mit Erfolgsquoten von 4/19 (Sunrise) bis 10/20 (Abend-Briefing), fast
ausschliesslich mit dem Vermerk "PC aus?".

Aus Nutzersicht: "die Daily Crons funktionieren nicht."

Jetzt wird nachgeholt, was verspaetet noch etwas taugt — und nur das. Ein Briefing um 11
statt um 8 ist nuetzlich; das Weck-Licht um 11 ist es nicht.
"""
from __future__ import annotations

import datetime as dt
import time

import pytest

from core.agency.missions import cron


@pytest.fixture
def crons(tmp_path, monkeypatch):
    from core.kernel import events

    events.init_db()
    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    return cron


class TestNachholbar:
    @pytest.mark.parametrize("label,prompt,erwartet", [
        ("Morgen-Briefing", "Erstelle ein Briefing mit den News des Tages.", True),
        ("Tägliche Notiz", "Lege eine Tagesnotiz im Vault an.", True),
        ("Wochen-Review", "Schreibe den Wochen-Review nach Vorlage.", True),
        ("Sunrise Schlafzimmer", "python core/tools/sunrise_hue.py 06:00", False),
        ("Licht an", "Schalte die Lampe im Wohnzimmer an.", False),
        ("Wecker", "Wecke mich mit dem Hue-Licht.", False),
        ("Backup", "Sichere die Datenbank per run_command.", False),
    ])
    def test_heuristik_trifft_die_echten_faelle(self, label, prompt, erwartet):
        assert cron.nachholbar({"label": label, "prompt": prompt}) is erwartet

    def test_explizites_feld_schlaegt_die_heuristik(self):
        j = {"label": "Sunrise", "prompt": "python sunrise.py", "nachholen": True}
        assert cron.nachholbar(j) is True
        j2 = {"label": "Briefing", "prompt": "News lesen", "nachholen": False}
        assert cron.nachholbar(j2) is False


# Bezugszeit fuer alle Lauf-Tests: MITTAGS. Sonst haengt das Ergebnis an der echten
# Uhrzeit — "vor 4 Stunden" faellt nachts um 01:00 auf den Vortag, und dann ist der
# Termin zu Recht nicht mehr nachholbar. Der Test war damit zwischen 0 und 4 Uhr rot.
def _mittags(tage_zurueck: float = 0) -> float:
    heute = dt.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    return (heute - dt.timedelta(days=tage_zurueck)).timestamp()


class TestNachholenImLauf:
    def _faellig_vor(self, crons, stunden: float, label="Morgen-Briefing",
                     prompt="Erstelle ein Briefing.", jetzt: float | None = None):
        crons.add_job(label, prompt, "08:00")
        jobs = crons._load()
        jobs[-1]["next_run"] = (jetzt or _mittags()) - stunden * 3600
        crons._save(jobs)
        return jobs[-1]

    def test_briefing_von_heute_frueh_wird_nachgeholt(self, crons, monkeypatch):
        gelaufen: list[str] = []
        monkeypatch.setattr(crons, "_notify", lambda t: gelaufen.append("MELDUNG") or True)
        monkeypatch.setattr(crons, "run_job",
                            lambda j, notify=True, verspaetet_min=0:
                            gelaufen.append(f"LAUF:{verspaetet_min}") or {"ok": True, "summary": ""})
        self._faellig_vor(crons, 4)     # heute frueh, 4 h her
        res = crons.run_due(now=_mittags())
        assert any(g.startswith("LAUF:") for g in gelaufen), "wurde nicht nachgeholt"
        assert res and res[0].get("nachgeholt") is True
        # der Lauf weiss, dass er verspaetet ist
        assert any(g.startswith("LAUF:2") for g in gelaufen)  # ~240 Minuten

    def test_zeitgebundener_job_wird_nicht_nachgeholt(self, crons, monkeypatch):
        gemeldet: list[str] = []
        monkeypatch.setattr(crons, "_notify", lambda t: gemeldet.append(t) or True)
        monkeypatch.setattr(crons, "run_job",
                            lambda j, notify=True, verspaetet_min=0: pytest.fail("darf nicht laufen"))
        self._faellig_vor(crons, 5, label="Sunrise Schlafzimmer",
                          prompt="python core/tools/sunrise_hue.py 06:00")
        crons.run_due(now=_mittags())
        assert gemeldet and "ausgefallen" in gemeldet[0]

    def test_termin_von_gestern_wird_nicht_nachgeholt(self, crons, monkeypatch):
        """Ein Morgen-Briefing von vorgestern ist Altpapier."""
        gemeldet: list[str] = []
        monkeypatch.setattr(crons, "_notify", lambda t: gemeldet.append(t) or True)
        monkeypatch.setattr(crons, "run_job",
                            lambda j, notify=True, verspaetet_min=0: pytest.fail("darf nicht laufen"))
        self._faellig_vor(crons, 30)    # gestern
        crons.run_due(now=_mittags())
        assert gemeldet and "ausgefallen" in gemeldet[0]

    def test_hoechstens_zwei_nachholungen_pro_durchlauf(self, crons, monkeypatch):
        laeufe: list[str] = []
        monkeypatch.setattr(crons, "_notify", lambda t: True)
        monkeypatch.setattr(crons, "run_job",
                            lambda j, notify=True, verspaetet_min=0:
                            laeufe.append(j["label"]) or {"ok": True, "summary": ""})
        for i in range(4):
            self._faellig_vor(crons, 3, label=f"Briefing {i}", prompt="News lesen.")
        crons.run_due(now=_mittags())
        assert len(laeufe) == crons.MAX_NACHHOLEN, laeufe

    def test_puenktlicher_job_laeuft_ohne_verspaetungs_hinweis(self, crons, monkeypatch):
        gesehen: list[int] = []
        monkeypatch.setattr(crons, "run_job",
                            lambda j, notify=True, verspaetet_min=0:
                            gesehen.append(verspaetet_min) or {"ok": True, "summary": ""})
        self._faellig_vor(crons, 0.2)   # 12 Minuten, innerhalb der Karenz
        crons.run_due(now=_mittags())
        assert gesehen == [0]

    def test_nachgeholter_lauf_bekommt_den_hinweis_in_den_prompt(self, crons, monkeypatch):
        erfasst = {}
        monkeypatch.setattr("core.agency.act.act",
                            lambda p, **k: erfasst.update(prompt=p) or {"text": "fertig, hier ist es"})
        monkeypatch.setattr(crons, "_notify", lambda t: True)
        job = crons.add_job("Morgen-Briefing", "Es ist 08:00 Uhr. Erstelle das Briefing.", "08:00")
        voll = next(j for j in crons._load() if j["id"] == job["id"])
        crons.run_job(voll, verspaetet_min=200)
        assert "NACHGEHOLT" in erfasst["prompt"]
        assert "3.3 Stunden" in erfasst["prompt"]
        assert "nicht nach einer Uhrzeit, die im Auftrag steht" in erfasst["prompt"]


class TestMeldungUnterscheidet:
    def test_meldung_verspricht_kein_generelles_liegenlassen_mehr(self, crons, monkeypatch):
        gemeldet: list[str] = []
        monkeypatch.setattr(crons, "_notify", lambda t: gemeldet.append(t) or True)
        crons._melde_verpasste([("Sunrise", time.time() + 3600)])
        assert "Was noch etwas taugt, reiche ich von selbst nach" in gemeldet[0]


class TestKeineRegression:
    def test_intervall_jobs_bleiben_unberuehrt(self, crons, monkeypatch):
        """Intervall-Jobs kannten das Verfallsfenster noch nie — das bleibt so."""
        laeufe: list[str] = []
        monkeypatch.setattr(crons, "run_job",
                            lambda j, notify=True, verspaetet_min=0:
                            laeufe.append(f"{j['label']}:{verspaetet_min}") or {"ok": True, "summary": ""})
        crons.add_job("Puls", "Kurzer Check.", "30m")
        jobs = crons._load()
        jobs[-1]["next_run"] = _mittags() - 20 * 3600
        crons._save(jobs)
        crons.run_due(now=_mittags())
        assert laeufe == ["Puls:0"]

    def test_naechster_termin_wird_korrekt_weitergedreht(self, crons, monkeypatch):
        monkeypatch.setattr(crons, "_notify", lambda t: True)
        monkeypatch.setattr(crons, "run_job",
                            lambda j, notify=True, verspaetet_min=0: {"ok": True, "summary": ""})
        crons.add_job("Morgen-Briefing", "News.", "08:00")
        jobs = crons._load()
        jobs[-1]["next_run"] = _mittags() - 4 * 3600
        crons._save(jobs)
        crons.run_due(now=_mittags())
        neu = crons._load()[0]["next_run"]
        assert neu > time.time()
        assert dt.datetime.fromtimestamp(neu).strftime("%H:%M") == "08:00"


class TestEskalationBeiFehlschlag:
    """Befund 27.07.: die News-Briefings verlangen zehn Themenbereiche in einem Durchgang
    und liefen auf der billigsten Stufe (bulk = 4B). Ergebnis in der Live-Historie:
    "leere Antwort (Modell lieferte keinen Text)". Ein Termin fiel damit ersatzlos aus,
    obwohl ein staerkeres Modell verfuegbar gewesen waere."""

    def test_leerer_lauf_wird_einmal_hochgestuft(self, crons, monkeypatch):
        versuche: list[dict] = []

        def fake_act(prompt, **k):
            versuche.append({"escalate": k.get("escalate"), "task_type": k.get("task_type")})
            return {"text": "" if len(versuche) == 1 else "Hier ist dein Briefing, ausfuehrlich."}

        monkeypatch.setattr("core.agency.act.act", fake_act)
        monkeypatch.setattr(crons, "_notify", lambda t: True)
        job = crons.add_job("Morgen-Briefing", "News zu zehn Themen.", "08:00")
        voll = next(j for j in crons._load() if j["id"] == job["id"])
        res = crons.run_job(voll)
        assert res["ok"] is True, "Eskalation hat den Lauf nicht gerettet"
        assert len(versuche) == 2
        assert versuche[0]["escalate"] is False and versuche[0]["task_type"] == "bulk"
        assert versuche[1]["escalate"] is True and versuche[1]["task_type"] == "reason"

    def test_erfolgreicher_lauf_eskaliert_nicht(self, crons, monkeypatch):
        versuche: list[str] = []
        monkeypatch.setattr("core.agency.act.act",
                            lambda p, **k: versuche.append("x") or {"text": "Alles gut, hier das Ergebnis."})
        monkeypatch.setattr(crons, "_notify", lambda t: True)
        job = crons.add_job("Briefing", "News.", "08:00")
        voll = next(j for j in crons._load() if j["id"] == job["id"])
        crons.run_job(voll)
        assert len(versuche) == 1, "unnoetig eskaliert — das kostet Geld"

    def test_job_der_schon_eskaliert_versucht_es_nicht_doppelt(self, crons, monkeypatch):
        versuche: list[str] = []
        monkeypatch.setattr("core.agency.act.act",
                            lambda p, **k: versuche.append("x") or {"text": ""})
        monkeypatch.setattr(crons, "_notify", lambda t: True)
        crons.add_job("Teuer", "Aufwendig.", "08:00", escalate=True)
        voll = crons._load()[0]
        res = crons.run_job(voll)
        assert res["ok"] is False
        assert len(versuche) == 1

    def test_eskalation_wird_protokolliert(self, crons, monkeypatch):
        gemeldet: list[str] = []
        monkeypatch.setattr("core.agency.act.act", lambda p, **k: {"text": ""})
        monkeypatch.setattr(crons, "_notify", lambda t: True)
        monkeypatch.setattr(crons.events, "emit",
                            lambda typ, p=None, **k: gemeldet.append(typ))
        crons.add_job("Briefing", "News.", "08:00")
        crons.run_job(crons._load()[0])
        assert "cron_eskaliert" in gemeldet
