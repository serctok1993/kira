"""Meldungen, die ein Mensch versteht — Wache gegen die Befunde vom 27.07.2026.

Der Nutzer legte drei Wochen Telegram-Verlauf vor und sagte: "Ich verstehe von all
dem nichts." Die Ursachen waren im Harness, nicht im Modell:

1. Das Missions-Buendel meldete die AUFGABENBESCHREIBUNG, hart bei 110 Zeichen
   mitten im Wort gekappt — nie das Ergebnis.
2. Leerer Modelltext ergab eine Meldung, die nur aus dem Praefix bestand.
3. Pruefer-Assertions gingen woertlich an den Nutzer.
4. Die "Erkenntnisse" bestanden aus Wortsalat ("zeichen, harte, checks").
5. Der Kalibrierungsbericht fuehrte mit Telemetrie; die Empfehlungen standen hinten
   und fielen der Kappung zum Opfer.
6. Das Planer-Prompt-Beispiel lautete "Micro-SaaS X" — das schwache Planer-Modell
   folgte dem Beispiel und plante wochenlang Marktforschung mit Lueckenfuellern.

Die Testdaten sind woertliche Live-Faelle aus dem Verlauf.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.agency import calibration, insights, verifier
from core.agency.missions import planner, runner


def _morgen() -> str:
    return time.strftime("%d.%m.%Y", time.localtime(time.time() + 86400))


@pytest.fixture
def wecker(tmp_path, monkeypatch):
    """Erinnerungs-Datei isoliert je Test."""
    from core.agency import erinnerungen

    monkeypatch.setattr(erinnerungen, "_PATH", tmp_path / "erinnerungen.json")
    return erinnerungen


@pytest.fixture
def crons(tmp_path, monkeypatch):
    """Cron-Datei isoliert je Test; add_job schreibt ein Event, also DB anlegen."""
    from core.agency.missions import cron
    from core.kernel import events

    events.init_db()
    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    return cron


# ---------------------------------------------------------------- Planer-Filter

class TestPlanerFilter:
    """Der Harness fuehrt das Modell — eine Bitte im Prompt bindet ein 4B nicht."""

    def test_platzhalter_aus_dem_live_verlauf_fliegen_raus(self):
        for echt in [
            "Recherchiere die monatlichen Kosten der drei direkten Wettbewerber von Produkt X",
            "Prüfe die letzten 3 offiziellen Update-Logs von [Tool C] und filtere konkret",
            "Suche und lies 3 offizielle Dokumente zur API von [Tool-Name]",
            "Recherchiere aktuelle Trends im Bereich Micro-Saas X fuer Q3 2024",
            "Recherchiere mindestens drei Anwendungsfaelle fuer Tool X",
        ]:
            assert planner.untauglich(echt) == "Platzhalter statt echtem Gegenstand", echt

    def test_englische_aufgaben_aus_dem_live_verlauf_fliegen_raus(self):
        for echt in [
            "Research customer discovery methods used by successful German Micro-SaaS startups",
            "Analyze MVP development processes in top German SaaS companies based on user feedback",
            "Find 3 case studies of failed German SaaS products due to inadequate customer validation",
        ]:
            assert planner.untauglich(echt) == "auf Englisch formuliert", echt

    def test_deutsches_finde_ist_kein_englisches_find(self):
        """Fehlalarm beim Test gegen die Live-Historie: 'find\\w*' verschluckte 'Finde ...'."""
        assert planner.untauglich("Finde eine Checkliste zur Validierung von Kurzerinnerungen") == ""
        assert planner.untauglich("Finde 3 echte Wettbewerber im Bereich KI") == ""

    def test_gute_alltagsaufgaben_kommen_durch(self):
        for gut in [
            "Pruefe die Termine der naechsten 7 Tage und nenne die, die Vorbereitung brauchen",
            "Lies die letzten 3 Tagesnotizen und sammle die offenen Punkte daraus",
            "Analysiere die Fehler-Logs der letzten 24 Stunden auf ein wiederkehrendes Muster",
            "Identifiziere fuenf Handwerksbetriebe am Ort mit veralteter Website",
            "Recherchiere die Preise von Ollama-tauglichen GPUs unter 500 Euro",
        ]:
            assert planner.untauglich(gut) == "", gut

    def test_generate_tasks_verwirft_untaugliche_und_meldet_das(self):
        antwort = {"text": "- Recherchiere die Kosten von Produkt X\n"
                           "- Pruefe die Termine der naechsten Woche\n"
                           "- Research German SaaS pricing models for the market\n"}
        with patch.object(planner.llm_router, "complete", return_value=antwort), \
             patch.object(planner.events, "emit") as emit:
            tasks = planner.generate_tasks("Ziel", "Kontext")
        assert tasks == ["Pruefe die Termine der naechsten Woche"]
        typen = [c.args[0] for c in emit.call_args_list]
        assert "plan_verworfen" in typen
        nutzlast = next(c.args[1] for c in emit.call_args_list if c.args[0] == "plan_verworfen")
        assert nutzlast["anzahl"] == 2

    def test_prompt_beispiel_nennt_kein_micro_saas_mehr(self):
        """Die Wurzel: das Beispiel im Prompt hatte das Ziel ueberstimmt."""
        erfasst = {}

        def fake(msgs, system=None, task_type=None, escalate=False):
            erfasst["user"] = msgs[0]["content"]
            return {"text": ""}

        with patch.object(planner.llm_router, "complete", side_effect=fake):
            planner.generate_tasks("Ziel", "Kontext")
        u = erfasst["user"].lower()
        assert "micro-saas x" not in u and "micro-saas" not in u
        assert "keine platzhalter" in u
        assert "deutsch" in u


# ------------------------------------------------------------ Buendel-Meldungen

class TestBuendelZeile:
    """Was der Nutzer alle 3 Stunden liest."""

    def test_kappen_schneidet_nie_mitten_im_wort(self):
        s = "Überprüfe die Fallstudien-Analyse-Prozedur darauf, ob sie eine konkrete Handlungsempfehlung liefert"
        for n in range(20, 100, 7):
            gekappt = runner._kappen(s, n)
            assert len(gekappt) <= n + 1  # +1 fuer das Auslassungszeichen
            rumpf = gekappt.rstrip("…")
            assert s.startswith(rumpf) and (len(rumpf) == len(s) or s[len(rumpf)] in " ,;:-–—")

    def test_der_live_fall_endet_nicht_mehr_auf_oder_nur_f(self):
        """Woertlich aus dem Verlauf: '... liefert oder nur F'."""
        alt = "Überprüfe die Fallstudien-Analyse-Prozedur darauf, ob sie eine konkrete Handlungsempfehlung liefert oder nur Floskeln"
        assert not runner._kappen(alt, 110).endswith("F…")

    def test_buendel_zeile_zeigt_das_ergebnis_nicht_das_vorhaben(self):
        zeile = runner._buendel_zeile(
            "Pruefe die Termine der naechsten 7 Tage und nenne die, die Vorbereitung brauchen",
            "Ich habe nachgesehen.\n\nZwei Termine brauchen Vorbereitung: Coaching am Mittwoch "
            "um 11:00 und der TÜV-Termin am Freitag.")
        assert "Zwei Termine brauchen Vorbereitung" in zeile
        assert zeile.startswith("✅")

    def test_buendel_zeile_bevorzugt_den_kurz_block(self):
        with patch.object(runner._id, "user_name", return_value="Partner"):
            zeile = runner._buendel_zeile(
                "Wochen-Review schreiben",
                "## Analyse\nviel Text ohne Belang der hier steht\n\n"
                "KURZ FUER PARTNER: Review liegt im Vault, 3 offene Punkte.")
        assert "Review liegt im Vault" in zeile
        assert "viel Text ohne Belang" not in zeile

    def test_leeres_ergebnis_wird_als_solches_gemeldet(self):
        """Vorher entstand '✅ (100) <Aufgabe>' — obwohl gar nichts geliefert wurde."""
        zeile = runner._buendel_zeile("Irgendeine Aufgabe", "   \n  \n ")
        assert zeile.startswith("⚠️")
        assert "ohne Ergebnis" in zeile

    def test_buendel_zeile_passt_in_den_melde_puffer(self):
        """melde.merken kappt bei 160 Zeichen — die Zeile darf davor fertig sein."""
        zeile = runner._buendel_zeile("A" * 300, "B" * 300)
        assert len(zeile) <= 160

    def test_keine_nackte_pruefernote_mehr(self):
        zeile = runner._buendel_zeile("Aufgabe", "Ergebnis mit ausreichend Substanz fuer den Kern.")
        assert "(100)" not in zeile and "Score" not in zeile


# ------------------------------------------------------------- Pruefer-Klartext

class TestPrueferKlartext:
    def test_der_live_fall_wird_ein_satz(self):
        roh = ("Harte Checks fehlgeschlagen: Ergebnis ist substanziell (>= 50 Zeichen) "
               "(0 Zeichen)")
        assert verifier.klartext(roh) == "Sie hat gar kein Ergebnis geliefert."

    def test_alle_harten_checks_haben_eine_uebersetzung(self):
        faelle = {
            "Harte Checks fehlgeschlagen: Kein Modell-Ausfall (Degrade-Abbruch) (Degrade-Marker gefunden)":
                "ausgefallen",
            "Harte Checks fehlgeschlagen: Artefakt out/x.md existiert und ist nicht leer (fehlt oder leer)":
                "nicht angelegt",
            "Harte Checks fehlgeschlagen: Python-Artefakt kompiliert (SyntaxError)":
                "laesst sich nicht ausfuehren",
            "Harte Checks fehlgeschlagen: Ergebnis nennt eine konkrete URL (keine URL im Ergebnis)":
                "Link",
        }
        for roh, erwartet in faelle.items():
            assert erwartet in verifier.klartext(roh), roh

    def test_mehrere_checks_werden_zu_mehreren_saetzen(self):
        roh = ("Harte Checks fehlgeschlagen: Ergebnis ist substanziell (>= 50 Zeichen) (0 Zeichen); "
               "Kein Modell-Ausfall (Degrade-Abbruch) (Degrade-Marker gefunden)")
        t = verifier.klartext(roh)
        assert "kein Ergebnis geliefert" in t and "ausgefallen" in t

    def test_judge_feedback_bleibt_unveraendert(self):
        """Freier Prueftext ist meist schon verstaendlich — nicht verschlimmbessern."""
        echt = "Liefere einen echten Produktnamen statt 'Produkt X', damit der Agent die Kriterien erfuellen kann."
        assert verifier.klartext(echt) == echt

    def test_leeres_feedback_sagt_das_ehrlich(self):
        assert "Kein Prueferbefund" in verifier.klartext("")


# ------------------------------------------------------------------ Erkenntnisse

class TestErkenntnisse:
    def test_kein_wortsalat_mehr(self):
        """Live-Ausgabe war: 'Wiederkehrende Pruefer-Kritik: zeichen, harte, checks'."""
        rows = [("retry", 10, 0.0,
                 "Harte Checks fehlgeschlagen: Ergebnis ist substanziell (>= 50 Zeichen) (0 Zeichen)",
                 "standard", "research", None)] * 4
        with patch.object(insights, "_rows", return_value=rows):
            themen = insights.feedback_themes()
        assert themen == ["gar kein Ergebnis geliefert (4x)"]
        for t in themen:
            assert "zeichen" not in t.lower() and "harte" not in t.lower()

    def test_ein_fehlschlag_zaehlt_nur_einmal(self):
        rows = [("retry", 10, 0.0,
                 "Harte Checks fehlgeschlagen: Ergebnis ist substanziell (0 Zeichen); "
                 "Artefakt fehlt; keine URL", "standard", "research", None)] * 3
        with patch.object(insights, "_rows", return_value=rows):
            themen = insights.feedback_themes()
        assert len(themen) == 1 and themen[0].endswith("(3x)")

    def test_bestandene_versuche_zaehlen_nicht(self):
        rows = [("pass", 90, 0.0, "Harte Checks fehlgeschlagen: substanziell", "standard", "research", None)] * 5
        with patch.object(insights, "_rows", return_value=rows):
            assert insights.feedback_themes() == []

    def test_einzelfaelle_werden_nicht_zum_muster_erklaert(self):
        rows = [("retry", 10, 0.0, "Harte Checks fehlgeschlagen: substanziell", "standard", "research", None)]
        with patch.object(insights, "_rows", return_value=rows):
            assert insights.feedback_themes() == []


# ------------------------------------------------------------ Kalibrierungs-Bericht

class TestKalibrierung:
    def _rep(self, mit_problem: bool) -> dict:
        return {
            "days": 7, "total_calls": 2165, "task_retries": 43, "tasks_failed": 6 if mit_problem else 0,
            "models": [{"model": "openrouter/z-ai/glm-5.2", "calls": 656, "nudges": 0,
                        "errors": 99 if mit_problem else 1, "nudge_rate": 0.0,
                        "error_rate": 0.31 if mit_problem else 0.0, "fallback_rate": 0.0,
                        "avg_latency_s": 16.5, "cost_usd": 10.28}],
            "strategies": {"standard": {"attempts": 80, "passed": 41, "pass_rate": 0.51}},
            "fallbacks": {},
        }

    def test_fazit_steht_vorne_und_ueberlebt_die_kappung(self):
        """Live-Fall: der Nutzer sah nur Telemetrie, abgeschnitten bei "Strategie 'esk"."""
        t = calibration.render(7, self._rep(mit_problem=True))
        kopf = t[:600]
        assert "Das solltest du wissen" in kopf
        assert "hohe Fehlerquote" in kopf
        assert kopf.index("Das solltest du wissen") < kopf.index("Die Zahlen dahinter")

    def test_erste_zeile_nennt_umfang_und_kosten(self):
        t = calibration.render(7, self._rep(mit_problem=False))
        erste = t.splitlines()[0]
        assert "2165" in erste and "10.28 USD" in erste

    def test_ohne_befund_sagt_er_dass_nichts_zu_tun_ist(self):
        t = calibration.render(7, self._rep(mit_problem=False))
        assert "Nichts Auffaelliges" in t
        assert "du musst hier nichts tun" in t

    def test_zahlen_bleiben_erhalten_nur_weiter_hinten(self):
        t = calibration.render(7, self._rep(mit_problem=True))
        assert "656 Anrufe" in t and "Strategie 'standard'" in t


# ------------------------------------------------------------- Doppelungs-Wache

class TestKeineDoppelten:
    """Live-Fund 27.07.: der Telegram-Spam war kein Zustell-Bug, sondern ein Anlege-Bug.

    "Muell rausbringen" fuer 18:00 wurde zweimal angelegt (22.07. 23:54 und 23.07. 00:21),
    und es entstanden fuenf Wetter-Jobs in 19 Stunden ("Wetter-Brief", "Wetter-Briefing",
    "Wetter-Fact", nochmal "Wetter-Brief", "Wetter"). Nichts prueft auf Doppelung."""

    def test_gleicher_wecker_wird_nicht_zweimal_gestellt(self, wecker):
        e, fehler = wecker.add("Muell rausbringen", _morgen(), "18:00")
        assert e and not fehler
        e2, fehler2 = wecker.add("Muell rausbringen", _morgen(), "18:00")
        assert e2 is None
        assert "gibt es schon" in fehler2 and "18:00" in fehler2

    def test_doppelungs_wache_ist_unempfindlich_fuer_schreibweise(self, wecker):
        wecker.add("Müll rausbringen!", _morgen(), "18:00")
        _, fehler = wecker.add("muell rausbringen", _morgen(), "18:00")
        assert "gibt es schon" in fehler

    def test_verschiedene_wecker_zur_gleichen_zeit_bleiben_erlaubt(self, wecker):
        assert wecker.add("Muell rausbringen", _morgen(), "18:00")[0]
        assert wecker.add("Katze fuettern", _morgen(), "18:00")[0]

    def test_zweiter_wetter_job_wird_erkannt(self, crons):
        crons.add_job("Wetter-Brief", "Hol das Wetter.", "08:00")
        for zwilling in ("Wetter-Briefing", "Wetter-Fact", "Wetter"):
            gefunden = crons.aehnlicher_job(zwilling, "08:00")
            assert gefunden and gefunden["label"] == "Wetter-Brief", zwilling

    def test_verschiedene_jobs_zur_gleichen_zeit_bleiben_erlaubt(self, crons):
        """Morgen-Briefing UND Backlog-Diagnose laufen beide um 08:00 — beide legitim."""
        crons.add_job("Morgen-Briefing", "Briefing.", "08:00")
        assert crons.aehnlicher_job("Backlog & Selbst-Diagnose", "08:00") is None

    def test_gleicher_stamm_zu_anderer_zeit_bleibt_erlaubt(self, crons):
        crons.add_job("Wetter-Brief", "Wetter.", "08:00")
        assert crons.aehnlicher_job("Wetter-Abendcheck", "20:00") is None

    def test_cron_add_lehrt_statt_zu_doppeln(self, crons):
        from core.agency.tools import builtin

        cron = crons
        assert "Geplant:" in builtin.cron_add("Wetter-Brief", "Hol das Wetter.", "08:00")
        antwort = builtin.cron_add("Wetter-Briefing", "Hol das Wetter nochmal.", "08:00")
        assert antwort.startswith("Fehler:")
        assert "Wetter-Brief" in antwort
        assert "cron_update" in antwort and "cron_remove" in antwort
        assert len(cron.list_jobs()) == 1


# ----------------------------------------------------- Beweispflicht: Fehlalarme

class TestBeweispflichtTrifftNurEchtes:
    """Live-Befund 27.07.: 12 von 12 Ausloesungen des Datei-Waechters waren Fehlalarme.

    Am 21.07. stempelte er einen reinen Struktur-VORSCHLAG als Luege ab — gezuendet vom
    Wort "fliegt" (enthaelt "liegt"), und sieben der acht angeprangerten Dateien gab es
    wirklich, sie lagen nur im Vault, den der Waechter nicht kannte."""

    @pytest.mark.parametrize("name,text", [
        ("wiki-platzhalter", "Die Struktur liegt so: `[[STAMM/...]]`, `[[ZIELE/...]]`"),
        ("modell-id", "Der Router hat `openrouter/glm/glm-5.2` und `z-ai/glm-5.2` hinterlegt."),
        ("code-beispiel", 'Ich habe `web_fetch("https://example.com"` geschrieben.'),
        ("fliegt-ist-nicht-liegt", "- `README.md` -> nur `START.md` (README fliegt raus)"),
        ("vergleichstabelle", "| Ideen | `Ideen-Sammlung.md` (root) | `Leben/Ideen.md` |"),
        ("ordner-baum", "├── STAMM/\n│   ├── `Leben/Ueber-mich.md`   (Herkunft)"),
        ("vorschlag", "Ich wuerde `Leben/Ideen.md` anlegen und alles dort ablegen."),
        ("konjunktiv", "Danach koennte `ZIELE/Nordstern.md` entstehen, dort liegen die Ziele."),
        ("angebot", "Der Plan steht. Soll ich `Leben/Ideen.md` anlegen?"),
    ])
    def test_kein_fehlalarm(self, name, text):
        from core.agency.act import _missing_claims

        assert _missing_claims(text) == [], name

    def test_echte_falschbehauptung_schlaegt_weiter_an(self):
        from core.agency.act import _missing_claims

        assert _missing_claims(
            "Fertig, die Liste habe ich unter `C:/Users/x/gibtesnicht_xyz.md` gespeichert."
        ) == ["C:/Users/x/gibtesnicht_xyz.md"]

    def test_mehrere_dateien_im_selben_satz(self):
        """Der Punkt in 'datei.md' darf den Satz nicht zerschneiden."""
        from core.agency.act import _missing_claims

        assert _missing_claims("Ich habe `a/gibtsnicht1.md` und `b/gibtsnicht2.md` angelegt.") == [
            "a/gibtsnicht1.md", "b/gibtsnicht2.md"]

    def test_stempel_spricht_den_nutzer_an_nicht_das_modell(self):
        from core.agency.act import _claim_stamp

        t = _claim_stamp("Fertig, gespeichert unter `zzz/gibtsnicht.md`.")
        assert "erledige es wirklich" not in t  # war eine Anweisung an Kira
        assert "nicht gedeckt" in t

    def test_satz_um_zerschneidet_dateinamen_nicht(self):
        from core.agency.act import _satz_um

        t = "Ich habe notiz.md geschrieben. Und dann Feierabend."
        pos = t.index("notiz.md")
        assert "geschrieben" in _satz_um(t, pos, pos + 8)


class TestPlanLaufBleibtSichtbar:
    """Live-Befund 27.07.: der Turn-Watchdog schoss am 21.07. einen laufenden Auftrag ab.

    plan_and_execute reichte die session_id nicht durch, also schrieb der ganze Plan-Lauf
    seine Events mit session_id NULL. Der Watchdog misst Fortschritt nur an der Session des
    Zugs (runstate.py:116) — er sah 504 s Stillstand, waehrend 170 Schritte liefen, und
    forderte einen Neustart an. Der Nutzer sah einen Spinner, der nie zur Antwort wurde."""

    def test_session_id_wird_durchgereicht(self, monkeypatch):
        from core.agency.tools import builtin
        from core.kernel import runstate

        gesehen = {}

        def fake_pe(task, escalate=True, session_id=None, **k):
            gesehen["session_id"] = session_id
            return "fertig"

        monkeypatch.setattr("core.agency.act.plan_and_execute", fake_pe)
        runstate.enter_turn("telegram-4711")
        try:
            builtin.plan_and_execute("Grosse Aufgabe")
        finally:
            runstate.exit_turn("telegram-4711")
        assert gesehen["session_id"] == "telegram-4711"

    def test_ohne_aktiven_zug_bleibt_es_bei_none(self, monkeypatch):
        from core.agency.tools import builtin

        gesehen = {}

        def fake_pe(task, escalate=True, session_id=None, **k):
            gesehen["session_id"] = session_id
            return "fertig"

        monkeypatch.setattr("core.agency.act.plan_and_execute", fake_pe)
        builtin.plan_and_execute("Aufgabe")
        assert gesehen["session_id"] is None


class TestKeinNachschubAnKarteileichen:
    """Die 9 Geister-Ziele (domain='business') waren Venture-Erbe. Der Nachschub-Kanal
    blieb offen: das Cockpit legte neue Ziele per Default in genau diese tote Domaene,
    und die Werkzeug-Beschreibung versprach dem Modell, der Heartbeat arbeite sie ab."""

    def test_objective_add_landet_im_board(self):
        from core.agency.missions import objectives
        from core.agency.tools import life_tools

        objectives.init_objectives()
        antwort = life_tools.objective_add("Ein Ziel", domain="business")
        assert "nicht von selbst abgearbeitet" in antwort
        neu = [o for o in objectives.list_all() if o["title"] == "Ein Ziel"]
        assert neu and neu[0]["domain"] == "leben"

    def test_manifest_verspricht_keine_automatik_mehr(self):
        """Die Beschreibung sagte "wird vom 24/7-Heartbeat bearbeitet" — seit W1 falsch.
        Kira las das, glaubte es und versprach es dem Nutzer weiter."""
        import core.agency.tools.life_tools  # noqa: F401 — Registrierung ausloesen
        from core.agency.tools import registry

        zeile = next(z for z in registry.manifest().splitlines() if "objective_add" in z)
        assert "Heartbeat" not in zeile
        assert "NICHT automatisch abgearbeitet" in zeile


def test_verify_cmd_faellt_im_worktree_auf_den_eigenen_interpreter(monkeypatch, tmp_path):
    """Worktree-Fall: .venv ist gitignored und existiert dort nicht — ein relativer
    Config-Pfad (.venv/bin/python) lief auf exit 127 und die Endabnahme rollte einen
    GRUENEN Fix zurueck. Das Kommando wird deterministisch neu gebaut (wie im
    Windows-Zweig); existiert .venv, bleibt die Config unangetastet."""
    import os
    import sys
    from core.agency import selfdev
    from core.config import CONFIG
    monkeypatch.setitem(CONFIG, "selfdev", {"verify_cmd": ".venv/bin/python -m pytest tests -q"})
    if os.name == "nt":  # der Zweig ist posix-only
        return
    monkeypatch.setattr(selfdev, "ROOT", tmp_path)          # Worktree ohne .venv
    assert sys.executable in selfdev._verify_cmd()
    (tmp_path / ".venv").mkdir()                            # .venv existiert -> Config gilt
    assert selfdev._verify_cmd() == ".venv/bin/python -m pytest tests -q"
