"""Der ACT-Parser verzeiht, was ein kleines Modell falsch macht — Befund 28.07.2026.

Der ACT-Textpfad ist per Konstruktion die Umgebung der LOKALEN Modelle: `_cloud()`
schickt GLM 5.2 und Kimi K3 in den nativen Function-Calling-Loop. Jede Haertung hier
ist für starke Modelle also ein No-Op — sie kommen hier nie vorbei.

Zwei Luecken, beide mit einem Wort zu schliessen:

1. ARGUMENTLOSE AUFRUFE fielen durch, weil der Parser eine '{' verlangte. Das Manifest
   preist aber zwoelf Werkzeuge ausdruecklich als "Argumente: keine" an (jetzt, health,
   cron_list, list_models, todo_list …) — ausgerechnet der einfachste Fall, und
   ausgerechnet die Werkzeuge, die ein kleines Modell im Alltag am haeufigsten braucht.

2. ECHTE ZEILENUMBRUECHE in JSON-Zeichenketten: kleine Modelle escapen sie fast nie
   korrekt. Betroffen sind die Werkzeuge, die ARBEIT erzeugen — write_file, vault_note,
   knowledge_note. Fiel der Aufruf durch, landete der halb geschriebene Text als
   "Antwort" beim Nutzer (13 solcher Faelle in der Live-DB).
"""
from __future__ import annotations

import pytest

from core.agency.act import _parse_act


class TestArgumentloseAufrufe:
    @pytest.mark.parametrize("text,werkzeug", [
        ("ACT jetzt", "jetzt"),
        ("ACT health()", "health"),
        ("ACT health(  )", "health"),
        ("Ich schaue nach.\nACT cron_list", "cron_list"),
        ("ACT list_models\n", "list_models"),
    ])
    def test_werden_erkannt(self, text, werkzeug):
        assert _parse_act(text) == (werkzeug, {})

    def test_das_manifest_verspricht_diese_faelle_wirklich(self):
        """Gegenprobe: es gibt Werkzeuge, die als 'Argumente: keine' beworben werden."""
        import core.agency.tools.builtin  # noqa: F401
        from core.agency.tools import registry

        ohne = [z for z in registry.manifest().splitlines() if "Argumente: keine" in z]
        assert len(ohne) >= 8, f"nur {len(ohne)} — Annahme des Fundes stimmt nicht mehr"
        # und jedes davon ist jetzt aufrufbar
        for zeile in ohne[:6]:
            name = zeile.split("(")[0].strip("- ").strip()
            assert _parse_act(f"ACT {name}") == (name, {}), name


class TestZeilenumbruecheInArgumenten:
    def test_write_file_mit_echtem_umbruch(self):
        r = _parse_act('ACT write_file {"path": "a.md", "content": "Zeile eins\nZeile zwei"}')
        assert r and r[0] == "write_file"
        assert r[1]["content"] == "Zeile eins\nZeile zwei"

    def test_notiz_mit_absatz(self):
        r = _parse_act('ACT vault_note {"titel": "T", "text": "Erster\n\nZweiter"}')
        assert r and r[1]["text"].count("\n") == 2

    def test_korrekt_escapte_umbrueche_unveraendert(self):
        r = _parse_act('ACT write_file {"path": "a.md", "content": "eins\nzwei"}')
        assert r[1]["content"] == "eins\nzwei"


class TestKeineFalschtreffer:
    @pytest.mark.parametrize("text", [
        "Der Begriff ACT steht bei mir fuer Werkzeugaufrufe.",
        "Ich koennte ACT jetzt benutzen, aber ich sage es dir direkt.",
        "Es ist 14:30 Uhr.",
        "",
        "ACT ist die Abkuerzung fuer Agent Command Text.",
    ])
    def test_prosa_ist_kein_aufruf(self, text):
        assert _parse_act(text) is None


class TestBestehendesVerhalten:
    @pytest.mark.parametrize("text,erwartet", [
        ('ACT web_search {"query": "Wetter"}', ("web_search", {"query": "Wetter"})),
        ('```\nACT read_file {"path": "x.py"}\n```', ("read_file", {"path": "x.py"})),
        ('Text davor. ACT list_dir {"path": "core"} und danach.',
         ("list_dir", {"path": "core"})),
        ('ACT **write_file** {"path": "a"}', ("write_file", {"path": "a"})),
    ])
    def test_unveraendert(self, text, erwartet):
        assert _parse_act(text) == erwartet

    def test_kaputtes_json_bleibt_ungeparst(self):
        """Ein abgerissener Aufruf ist KEIN Aufruf — dafuer gibt es die Fragment-Rettung."""
        assert _parse_act('ACT write_file {"path": "a.md", "content": "unvollstaen') is None
