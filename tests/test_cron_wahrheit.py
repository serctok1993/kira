"""Cron-Wahrheits-Runde (Audit 26.07.): Zusagen halten, ok bedeutet etwas, Volltext raus.

Drei belegte Live-Schaeden:
1. run_due lud die Job-Liste einmal und schrieb sie am Stapelende zurueck — ein
   waehrenddessen per cron_add angelegter Job war GARANTIERT weg, obwohl der Nutzer
   die Erfolgsmeldung bekam (11.07. + 21.07., beide "Metriken-Reminder" verschwunden).
2. ok=true hiess nur "act() hat nicht geworfen": 21 von 49 gruenen Laeufen waren
   Absagen, Leer-Antworten oder rohe ACT-Leaks — die Selbst-Diagnose las dieses Gruen.
3. Die 300-Zeichen-Kappung ging mit an Telegram: 38 Nachrichten endeten mitten im Wort.
"""
from __future__ import annotations

import json
import time

from core.agency.missions import cron
from core.kernel import events

events.init_db()  # Wegwerf-Datenwurzel der Suite: events-Tabelle auch im Solo-Lauf da


def _job(**kw) -> dict:
    basis = {"id": "test01", "label": "Testjob", "prompt": "tu was", "schedule": {"type": "daily", "time": "08:00"},
             "schedule_text": "08:00", "enabled": True, "escalate": False, "scope": "system",
             "last_run": 0, "next_run": 0, "runs": []}
    basis.update(kw)
    return basis


# --- 1) Zusagen halten ---------------------------------------------------------------

def test_cron_add_waehrend_eines_laufs_ueberlebt(tmp_path, monkeypatch):
    """Der Kernschaden: waehrend run_due laeuft, legt der Job selbst einen neuen an."""
    pfad = tmp_path / "cron.json"
    monkeypatch.setattr(cron, "JOBS", pfad)
    monkeypatch.setattr(cron, "_notify", lambda *a, **k: None)
    pfad.write_text(json.dumps([_job(next_run=time.time() - 10)]), encoding="utf-8")

    def act_der_einen_cron_anlegt(prompt, **kw):
        # genau das tat Kira live: mitten im Lauf einen weiteren Job planen
        roh = json.loads(pfad.read_text(encoding="utf-8"))
        roh.append(_job(id="neu99", label="Metriken-Reminder", next_run=time.time() + 9999))
        pfad.write_text(json.dumps(roh), encoding="utf-8")
        return {"text": "Erledigt — Reminder steht fuer morgen frueh."}

    monkeypatch.setattr("core.agency.act.act", act_der_einen_cron_anlegt)
    cron.run_due(now=time.time())

    ids = {j["id"] for j in json.loads(pfad.read_text(encoding="utf-8"))}
    assert "neu99" in ids, "waehrend des Laufs angelegter Cron wurde ueberschrieben"


def test_termin_wird_vor_dem_lauf_weitergedreht(tmp_path, monkeypatch):
    """Prozess-Crash mitten im act() darf keinen Doppel-Lauf erzeugen."""
    pfad = tmp_path / "cron.json"
    monkeypatch.setattr(cron, "JOBS", pfad)
    monkeypatch.setattr(cron, "_notify", lambda *a, **k: None)
    pfad.write_text(json.dumps([_job(next_run=time.time() - 10)]), encoding="utf-8")
    gesehen = {}

    def act_stirbt_gleich(prompt, **kw):
        gesehen["next_run"] = json.loads(pfad.read_text(encoding="utf-8"))[0]["next_run"]
        raise RuntimeError("Prozess weg")

    monkeypatch.setattr("core.agency.act.act", act_stirbt_gleich)
    cron.run_due(now=time.time())
    assert gesehen["next_run"] > time.time(), "next_run stand beim act() noch in der Vergangenheit"


# --- 2) ok bedeutet etwas ------------------------------------------------------------

def test_bewertung_erkennt_die_belegten_ausfaelle():
    assert cron._lauf_bewerten("")[0] is False
    assert cron._lauf_bewerten("   ")[0] is False
    assert cron._lauf_bewerten('ACT write_file {"path": "C:/x.md", "content": "…"}')[0] is False
    assert cron._lauf_bewerten("⚠️ Ich bin bei einem Modell-/Netzwerk-Schritt gescheitert")[0] is False
    assert cron._lauf_bewerten("LLM-Call ueberschritt harte Wall-Clock-Grenze (150s)")[0] is False


def test_bewertung_laesst_echte_ergebnisse_durch():
    ok, _ = cron._lauf_bewerten("Morgen-Briefing: 2 Termine, 3 offene Todos. Wetter 21 Grad.")
    assert ok
    # Ein Text, der das Wort ACT nur erwaehnt, ist kein Leak
    assert cron._lauf_bewerten("Die Abkuerzung ACT steht fuer Agent Command Text.")[0]


def test_leerer_lauf_wird_nicht_als_erfolg_gebucht(tmp_path, monkeypatch):
    pfad = tmp_path / "cron.json"
    monkeypatch.setattr(cron, "JOBS", pfad)
    gesendet = []
    monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t))
    pfad.write_text(json.dumps([_job(next_run=time.time() - 10)]), encoding="utf-8")
    monkeypatch.setattr("core.agency.act.act", lambda p, **k: {"text": "   "})

    res = cron.run_due(now=time.time())
    assert res and res[0]["ok"] is False
    assert not gesendet, "leerer Lauf wurde trotzdem zugestellt"
    gespeichert = json.loads(pfad.read_text(encoding="utf-8"))[0]["runs"][-1]
    assert gespeichert["ok"] is False and "leere" in gespeichert["summary"]


# --- 3) Volltext statt Wort-Abriss ---------------------------------------------------

def test_lange_meldung_geht_ungekappt_raus(tmp_path, monkeypatch):
    pfad = tmp_path / "cron.json"
    monkeypatch.setattr(cron, "JOBS", pfad)
    gesendet = []
    monkeypatch.setattr(cron, "_notify", lambda t: gesendet.append(t))
    pfad.write_text(json.dumps([_job(next_run=time.time() - 10)]), encoding="utf-8")
    lang = ("Briefing: " + "Punkt fuer Punkt sehr ausfuehrlich. " * 30).strip()  # > 300 Zeichen
    monkeypatch.setattr("core.agency.act.act", lambda p, **k: {"text": lang})

    cron.run_due(now=time.time())
    assert gesendet and lang in gesendet[0], "Telegram bekam die gekappte Fassung"
    kurz = json.loads(pfad.read_text(encoding="utf-8"))[0]["runs"][-1]["summary"]
    assert len(kurz) <= 300, "Dashboard-Zusammenfassung soll gekappt bleiben"


def test_zustellhinweis_steht_im_cron_prompt(tmp_path, monkeypatch):
    """Gegen die telegram_send-Phantomaufrufe: der Kanal ist Harness-Sache."""
    pfad = tmp_path / "cron.json"
    monkeypatch.setattr(cron, "JOBS", pfad)
    monkeypatch.setattr(cron, "_notify", lambda *a, **k: None)
    pfad.write_text(json.dumps([_job(next_run=time.time() - 10)]), encoding="utf-8")
    gesehen = {}

    def act_merkt_sich_prompt(prompt, **kw):
        gesehen["p"] = prompt
        return {"text": "fertig, hier das Ergebnis fuer heute frueh"}

    monkeypatch.setattr("core.agency.act.act", act_merkt_sich_prompt)
    cron.run_due(now=time.time())
    assert "automatisch" in gesehen["p"] and "KEIN Sende-Werkzeug" in gesehen["p"]
