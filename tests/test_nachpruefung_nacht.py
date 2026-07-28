"""Was die gegnerische Pruefung der Nacht (28.07.2026) an eigenen Fehlern fand.

Fuenf Blickwinkel gingen ueber die Aenderungen dieser Nacht, jeder Befund musste eine
Widerlegung ueberstehen. Sieben blieben stehen — vier davon in Code, der wenige Stunden
vorher als Verbesserung eingecheckt worden war. Diese Datei haelt sie zu.

Die Lehre daraus steht in jedem Test einzeln; gemeinsam ist ihnen: eine Aenderung, die
"offensichtlich richtig" aussieht, ist erst richtig, wenn sie auf dem ECHTEN Pfad mit
den ECHTEN Daten geprueft wurde.
"""
from __future__ import annotations

import inspect
import json
import re

import pytest

import core.agency.tools.builtin  # noqa: F401 — Registrierung ausloesen
import core.agency.tools.life_tools  # noqa: F401
import core.agency.tools.termin_tools  # noqa: F401
from core.agency import act
from core.agency.tools import registry
from core.mind import tuning


class TestInnenlebenErkennen:
    """Befund: die Wache fing die Faelle nicht, die ihr Docstring als Anlass nannte.

    Beim Verschaerfen gegen Fehlalarme wurde der JSON-Rumpf als "Prosa" mitgezaehlt —
    ein gekappter Aufruf mit langem Rumpf rutschte damit durch. Alle Beispiele hier
    sind aus data/state.db abgeschrieben, nicht erfunden."""

    LEAKS = [
        pytest.param("ACT list_models", id="rein-argumentlos"),
        pytest.param("ACT health()", id="rein-mit-klammern"),
        pytest.param('ACT remember_fact {"fact": "etwas Privates"}', id="rein-mit-argument"),
        pytest.param(
            'ACT vault_note {"titel": "DDR4 64GB Preisstand", "text": "# DDR4 64GB\\n'
            '**Erstellt:** 23.07.2026\\n\\n## Aktuelle Preisspanne (DE',
            id="mitten-im-json-gekappt"),
        pytest.param(
            "Ich sehe die Trace-Logik — aber die Datei scheint am Ende abgeschnitten zu "
            'sein. Lass mich pruefen. ACT run_command {"command": "powershell -c "(Get-'
            'Content \'x.py\' | Measure-Object -Line).Lines"}',
            id="kaputtes-json-verschachtelte-anfuehrungszeichen"),
        pytest.param("<tool_call>{...}", id="xml-stil"),
        pytest.param('ACT web_search {"query": "x"}\n\nIch schaue mal nach.',
                     id="aufruf-plus-kurzer-nachsatz"),
    ]

    ANTWORTEN = [
        pytest.param("Es ist 14:30 Uhr.", id="kurze-antwort"),
        pytest.param("Der Begriff ACT steht bei mir fuer Werkzeugaufrufe.", id="prosa-ueber-act"),
        pytest.param(
            "In core liegen **8 Unterordner** plus vier Python-Dateien. Die groesste ist "
            "im Moment nicht messbar — ACT write_file hat ein Recherche-Dossier angelegt, "
            "falls du mehr Felder brauchst.", id="prosa-erwaehnt-werkzeug"),
        pytest.param("", id="leer-ist-nicht-roh"),
    ]

    @pytest.mark.parametrize("text", LEAKS)
    def test_innenleben_wird_erkannt(self, text):
        assert act._ist_roher_werkzeugaufruf(text) is True

    @pytest.mark.parametrize("text", ANTWORTEN)
    def test_echte_antworten_bleiben(self, text):
        assert act._ist_roher_werkzeugaufruf(text) is False

    def test_die_protokoll_erklaerung_behaelt_ihr_beispiel(self):
        """Fragt der Partner, WIE Kira Werkzeuge aufruft, gehoert das Beispiel in die
        Antwort — es darf weder verworfen noch herausgeschnitten werden."""
        erklaerung = ('So rufe ich ein Werkzeug auf: ACT web_fetch {"url": '
                      '"https://example.com"} — danach bekomme ich das Ergebnis zurueck '
                      "und arbeite damit weiter. Pro Zug geht genau ein Aufruf.")
        assert act._ist_roher_werkzeugaufruf(erklaerung) is False
        rest, n, angefangen = act._werkzeugreste(erklaerung)
        assert n == 1 and not angefangen
        assert act._BEGINNT_MIT_AUFRUF.match(erklaerung) is None, "beginnt mit Prosa"


class TestAufrufePlusEchteAntwort:
    """Der schlimmste Live-Fall: vier remember_fact-Aufrufe mit privaten Finanzzahlen
    als JSON, darunter eine 1994 Zeichen lange, voellig richtige Antwort. Sie wegzuwerfen
    und neu zu fragen waere Verschwendung — das Innenleben gehoert raus, die Antwort bleibt."""

    GEMISCHT = (
        'ACT remember_fact {"fact": "Kredit laeuft bis 2029, Rate 250 im Monat"}\n'
        'ACT remember_fact {"fact": "Arbeitet abends, mag knappe Antworten"}\n'
        "Das war nicht zu viel — das war genau das, was ich brauche. Lass mich das "
        "mal ordentlich spiegeln, weil da mehrere Dinge drin waren. Deine Freiheits"
        "definition ist erfrischend konkret, und das Etappenziel macht damit Sinn."
    )

    def test_die_aufrufe_verschwinden(self):
        rest, n, angefangen = act._werkzeugreste(self.GEMISCHT)
        assert n == 2 and not angefangen
        assert "remember_fact" not in rest
        assert "Kredit laeuft" not in rest, "die privaten Zahlen sind noch da"

    def test_die_antwort_bleibt_vollstaendig(self):
        rest, _, _ = act._werkzeugreste(self.GEMISCHT)
        assert "das war genau das, was ich brauche" in rest
        assert "Etappenziel" in rest

    def test_die_wache_stellt_die_bereinigte_antwort_zu(self, monkeypatch):
        from core.kernel import events
        events.init_db()
        gerufen: list[int] = []
        monkeypatch.setattr(act, "_complete_resilient",
                            lambda *a, **k: gerufen.append(1) or {"text": "sollte nicht noetig sein"})
        raus = act._brauchbare_antwort(self.GEMISCHT, [], "S", session_id=None)
        assert "remember_fact" not in raus
        assert "das war genau das, was ich brauche" in raus
        assert gerufen == [], "es wurde unnoetig ein Modell befragt"

    def test_reines_innenleben_kostet_dagegen_einen_nachfass_zug(self, monkeypatch):
        from core.kernel import events
        events.init_db()
        monkeypatch.setattr(act, "_complete_resilient", lambda *a, **k: {"text": "Hier ist die Antwort."})
        assert act._brauchbare_antwort("ACT list_models", [], "S", session_id=None) \
            == "Hier ist die Antwort."


class TestKapitulationIstKeinLehrbeispiel:
    """Befund: der Ersatzsatz der Wache ist 135 Zeichen lang und rutscht damit durch den
    15-Zeichen-Filter von record_chat — er landete als Antwort auf die ECHTE Frage im
    Trainingsprotokoll. Das Modell haette gelernt, bei schweren Fragen aufzugeben."""

    def test_es_gibt_genau_eine_quelle_fuer_den_satz(self):
        quelltext = inspect.getsource(act)
        assert quelltext.count("keine brauchbare Antwort zustande gebracht") == 1

    def test_der_satz_wird_nicht_mitgeschrieben(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "_DIR", tmp_path)
        monkeypatch.setattr(tuning, "_EPISODES", tmp_path / "episodes.jsonl")
        monkeypatch.setattr(tuning, "test_mode", lambda: False)
        monkeypatch.setattr(tuning, "_is_ephemeral", lambda s: False)
        assert tuning.record_chat("s1", "Wie hoch ist meine Steuerlast?",
                                  act.KAPITULATION) is False
        assert not (tmp_path / "episodes.jsonl").exists()

    def test_eine_echte_antwort_wird_weiterhin_mitgeschrieben(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "_DIR", tmp_path)
        monkeypatch.setattr(tuning, "_EPISODES", tmp_path / "episodes.jsonl")
        monkeypatch.setattr(tuning, "test_mode", lambda: False)
        monkeypatch.setattr(tuning, "_is_ephemeral", lambda s: False)
        assert tuning.record_chat("s1", "Wie hoch ist meine Steuerlast?",
                                  "Rund 24 % — hier ist die Rechnung dazu.") is True


class TestEinWortlautFuerAlleTextpfade:
    """Befund: Stups und Beweispflicht wurden in den Missionspfad KOPIERT und liefen
    dabei auseinander ("Nicht ankuendigen." statt "Nicht ankuendigen, nicht
    zurueckfragen."; "in diesem Lauf" statt "in diesem Zug"). Die Werkstatt trainiert
    auf einen Wortlaut — sprach die Produktion drei, sah das Modell eine Aufforderung,
    die es nie geuebt hat. Jetzt kommen alle aus derselben Konstante."""

    def test_kein_pfad_baut_den_stups_selbst_zusammen(self):
        quelltext = inspect.getsource(act)
        assert quelltext.count("Der Auftrag liegt bereits vor") == 2, \
            "es gibt mehr Stups-Wortlaute als die zwei Konstanten"

    def test_kein_pfad_baut_die_beweisnachfrage_selbst_zusammen(self):
        quelltext = inspect.getsource(act)
        assert quelltext.count("lief KEIN Werkzeug") == 1, \
            "die Beweis-Nachfrage steht mehr als einmal im Quelltext"

    def test_chat_und_mission_sprechen_woertlich_gleich(self):
        """Beide fahren das ACT-Textprotokoll — da darf es keinen Unterschied geben."""
        assert "(ACT ...)" in act.STUPS_ACT
        assert "nicht zurueckfragen" in act.STUPS_ACT
        assert "in diesem Zug" in act.beweis_nachfrage("eingetragen")
        assert "ACT <werkzeug>" in act.beweis_nachfrage("eingetragen")

    def test_der_native_pfad_weicht_nur_dort_ab_wo_er_muss(self):
        """Cloud-Modelle rufen strukturiert auf — ein "(ACT ...)" waere dort falsch."""
        assert "ACT" not in act.STUPS_NATIV
        assert "nicht zurueckfragen" in act.STUPS_NATIV
        assert "ACT" not in act.beweis_nachfrage("eingetragen", nativ=True)

    def test_das_signalwort_steht_in_der_nachfrage(self):
        assert '"eingetragen"' in act.beweis_nachfrage("eingetragen")


class TestDerGeneratorLehrtNurGueltigeAufrufe:
    """Befund: 15 Beispiele im Datensatz-Generator brachten dem Modell Aufrufe bei, die
    der Harness seit der Argument-Wache deterministisch ablehnt — _tool_examples nahm
    nur das ERSTE Argument, und der Coding-Grundstock benutzte schlicht falsche Namen
    (query statt muster; path/suchen/ersetzen statt pfad/suche/ersetze).

    Dieselbe Fehlerklasse wie der 187-Faelle-Fund des vertrag_pruefer.py, nur in Kiras
    eigenem Generator. Dieser Test ist die stehende Wache dagegen."""

    _ACT = re.compile(r"ACT\s+([a-zA-Z_]\w*)\s*(\{.*)", re.DOTALL)

    def _beanstandung(self, zeile: str) -> str:
        m = self._ACT.match(zeile.strip())
        if not m:
            return ""
        name = m.group(1)
        try:
            args = json.loads(m.group(2))
        except json.JSONDecodeError:
            return f"{name}: JSON kaputt"
        tool = registry.get(name)
        if not tool:
            return f"{name}: Werkzeug existiert nicht"
        fehler = act._falsche_argumente(name, tool, args)
        return f"{name}: {fehler.split('Beispiel')[0].strip()}" if fehler else ""

    def test_jedes_werkzeug_beispiel_wuerde_wirklich_laufen(self):
        schlecht = [b for b in (self._beanstandung(x["assistant"])
                                for x in tuning._tool_examples()) if b]
        assert not schlecht, f"{len(schlecht)} Beispiele wuerden abgelehnt: {schlecht[:6]}"

    def test_der_coding_grundstock_benutzt_die_echten_argumentnamen(self):
        zeilen = [inhalt for episode in tuning._SEED_CODING for rolle, inhalt in episode
                  if rolle == "assistant" and inhalt.strip().startswith("ACT ")]
        assert zeilen, "der Grundstock enthaelt gar keine Aufrufe mehr"
        schlecht = [b for b in (self._beanstandung(z) for z in zeilen) if b]
        assert not schlecht, f"falsche Argumentnamen im Grundstock: {schlecht}"

    def test_werkzeuge_mit_mehreren_pflichtargumenten_bekommen_alle(self):
        """Der eigentliche Fehler: 'erstes Pflicht-Arg' statt 'alle Pflicht-Args'."""
        beispiele = {x["assistant"].split()[1]: x["assistant"] for x in tuning._tool_examples()}
        mail = beispiele.get("email_send", "")
        assert mail, "email_send fehlt im Generator"
        for pflicht in ("to", "subject", "body"):
            assert f'"{pflicht}"' in mail, f"{pflicht} fehlt in: {mail}"

    def test_argumentlose_werkzeuge_bleiben_argumentlos(self):
        beispiele = {x["assistant"].split()[1]: x["assistant"] for x in tuning._tool_examples()}
        assert beispiele.get("jetzt", "").strip() in ("ACT jetzt {}", "ACT jetzt")


class TestBeispielwerteSindPlausibel:
    """Zwei Nebenfunde derselben Pruefung, beide im Beispiel-Generator.

    Der Generator ignorierte die Beispiele, die in den Parameter-Beschreibungen schon
    DRINSTEHEN ("TT.MM.JJJJ, z.B. 15.08.2026") und setzte stattdessen "beispiel" ein —
    ein Modell lernte so, ein Datum als das Wort "beispiel" zu schicken. Und weil "text"
    als Teilstring in "Kontext" steckt, bekam der Zahlenparameter num_ctx einen ganzen
    Satz als Wert."""

    def _beispiele(self) -> dict:
        return {x["assistant"].split()[1]: x["assistant"] for x in tuning._tool_examples()}

    def test_die_beschreibung_liefert_ihr_eigenes_beispiel(self):
        b = self._beispiele()
        assert '"datum": "15.08.2026"' in b.get("termin_add", "")
        assert '"num_ctx": "16384"' in b.get("set_context", "")

    def test_ein_zahlenparameter_bekommt_keine_prosa(self):
        assert tuning._example_arg("Kontext-Token, z.B. 16384").isdigit()
        assert tuning._example_arg("der Zahlenwert").isdigit()
        assert tuning._example_arg("Anzahl Zeilen (Standard 80)").isdigit()

    def test_ein_textparameter_bekommt_weiterhin_text(self):
        wert = tuning._example_arg("der Text der Notiz")
        assert not wert.isdigit() and len(wert) > 10


class TestKeinEchterNameImDatensatz:
    """Die Identitaets-Variation des kommerziellen Datensatzes laeuft ueber
    system_stub(agent, user). Der Beispiel-Generator umging sie und schrieb den echten
    Nutzernamen direkt in 8 von 77 Beispiele — der waere so in jeden Export gewandert."""

    def test_kein_beispiel_traegt_den_live_namen(self):
        from core import identity

        name = identity.user_name().lower()
        treffer = [x["assistant"] for x in tuning._tool_examples()
                   if name and name in x["assistant"].lower()]
        assert not treffer, f"echter Name in {len(treffer)} Beispielen: {treffer[:3]}"

    def test_der_stub_bleibt_der_haken_fuer_die_variation(self):
        """Gegenprobe: ueber system_stub SOLL der Name variierbar sein."""
        assert "Nova" in tuning.system_stub("Nova", "Alex")
        assert "Alex" in tuning.system_stub("Nova", "Alex")
