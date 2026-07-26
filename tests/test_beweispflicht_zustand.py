"""Beweispflicht II + Nudge-Disziplin (Audit-Funde 26.07.).

F1: 54 Antworten behaupteten "eingetragen/gemerkt/erledigt", ohne dass im selben Zug
    EIN Werkzeug lief — u.a. "✅ Eingebracht: Termin mit Freundin am 12.07. 00:30"
    (ein llm_call, null act_step, kalender.json kennt den Termin nicht). Ohne Werkzeug
    kann sich am Zustand nichts geaendert haben: das weiss der Harness sicher.
S11: Der Nudge feuerte auf JEDE Nachricht. "Guten Mittag Kira!" endete in list_dir,
    und "Schalt den Windows Defender aus" wurde per Zwangstext zu einem echten
    run_command — obwohl das Modell richtig zurueckgefragt hatte.
"""
from __future__ import annotations

from core.agency import act


# --- Erkennung: was ist eine Behauptung, was nicht? ----------------------------------

def test_erledigt_behauptungen_werden_erkannt():
    for satz in ("✅ Termin eingetragen: Morgen 9:30 — Friseur",
                 "Habe ich dir gemerkt.",
                 "Die Notiz ist gespeichert.",
                 "Erledigt — der Cron ist eingerichtet.",
                 "Mail ist verschickt."):
        assert act._behauptet_zustandsaenderung(satz), f"nicht erkannt: {satz}"


def test_angebote_und_rueckfragen_sind_keine_behauptung():
    for satz in ("Soll ich den Termin eintragen?",
                 "Ich kann das gerne fuer dich speichern — sag Bescheid.",
                 "Moechtest du, dass ich mir das merke?",
                 "Sobald du mir das Datum sagst, wird der Termin eingetragen.",
                 "Wenn du willst, wird die Datei geloescht."):
        assert act._behauptet_zustandsaenderung(satz) is None, f"Fehlalarm: {satz}"


def test_reiner_plauderton_loest_nichts_aus():
    for satz in ("Alles bestens — und bei dir?",
                 "Der Rhein entspringt in der Schweiz.",
                 "Guten Morgen! Was steht heute an?"):
        assert act._behauptet_zustandsaenderung(satz) is None


def test_gemischter_satz_behauptung_plus_angebot():
    """'Erledigt. Soll ich noch X?' ist trotzdem eine Behauptung."""
    assert act._behauptet_zustandsaenderung(
        "Termin ist eingetragen. Soll ich dich vorher erinnern?")


# --- Nudge-Disziplin (S11) -----------------------------------------------------------

def test_gruss_wird_nicht_gestupst():
    """Der Live-Fall: 'Guten Mittag Kira!' loeste einen Werkzeug-Zwang aus (list_dir)."""
    assert not act._nudge_angebracht("Guten Mittag Kira!")
    assert not act._nudge_angebracht("Hallo Kira, wie geht es dir?")
    assert not act._nudge_angebracht("Danke dir :)")


def test_heikler_wunsch_erzwingt_keine_ausfuehrung():
    """'Schalt den Windows Defender aus' wurde per Nudge zu run_command —
    eine Rueckfrage ist bei so etwas die RICHTIGE Antwort."""
    for heikel in ("Schalt den Windows Defender aus",
                   "Deaktivier bitte die Firewall",
                   "Ueberweis 200 Euro an den Vermieter",
                   "Veroeffentliche den Post auf Bluesky"):
        assert not act._nudge_angebracht(heikel), f"gestupst bei: {heikel}"


def test_echter_auftrag_wird_weiter_gestupst():
    """Die Disziplin darf den Stups nicht abschaffen — nur eingrenzen."""
    assert act._nudge_angebracht(
        "Recherchiere die Oeffnungszeiten der Stadtbibliothek und leg sie als Notiz ab")
    assert act._nudge_angebracht("Kannst du mir bitte das Wetter fuer morgen raussuchen?")
    assert act._looks_like_promise("Ich schaue mal kurz nach.")


def test_promise_erkennung_unveraendert():
    """Vertrag: die bestehende Ankuendigungs-Erkennung bleibt, wie sie war."""
    assert act._looks_like_promise("Lass mich kurz schauen ...")
    assert act._looks_like_promise("Soll ich das fuer dich tun?")
    assert not act._looks_like_promise("Hier sind die drei Ergebnisse: A kostet 12 Euro, "
                                       "B kostet 15 Euro und C ist ausverkauft. Ich wuerde A nehmen.")


# --- Integration: greift die Beweispflicht im echten Gespraechsablauf? ---------------

def _tmp_dbs(monkeypatch, tmp_path):
    from core.kernel import events
    from core.mind.memory import store

    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    store.init_memory()


def _antworten(monkeypatch, folge: list[str]) -> list[list[dict]]:
    """Modell simulieren: liefert der Reihe nach die vorgegebenen Antworten und
    protokolliert, welche Nachrichten es dabei zu sehen bekam."""
    from core.kernel import llm_router

    gesehen: list[list[dict]] = []
    rest = list(folge)

    def stream(messages, **kw):
        gesehen.append([dict(m) for m in messages])
        text = rest.pop(0) if rest else "fertig"
        yield {"kind": "text", "text": text}

    monkeypatch.setattr(llm_router, "stream_tagged", stream)
    monkeypatch.setattr(llm_router, "resolve_model", lambda *a, **k: ("ollama_chat/testmodell", False))
    # lokal => ACT-Text-Pfad (der Pfad, den Kiras eigene Modelle fahren)
    monkeypatch.setattr(llm_router, "ist_lokal", lambda m: True)
    return gesehen


def test_behauptung_ohne_werkzeug_wird_zurueckgegeben(monkeypatch, tmp_path):
    """Der Live-Fall: '✅ Termin eingetragen' ohne einen einzigen act_step."""
    from core.agency import act

    _tmp_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_AUTO_PLAN", False)
    gesehen = _antworten(monkeypatch, [
        "✅ Termin eingetragen: Morgen 9:30 — Friseur",          # erfunden
        "Noch nicht erledigt — ich brauche das genaue Datum.",   # ehrliche Korrektur
    ])

    antwort = act.act_chat("Trag mir morgen den Friseur ein", session_id="t-beweis")

    assert len(gesehen) == 2, "Der Harness hat die Behauptung nicht hinterfragt"
    rueckfrage = gesehen[1][-1]["content"]
    assert "KEIN Werkzeug" in rueckfrage and "eingetragen" in rueckfrage
    assert "Noch nicht erledigt" in antwort


def test_behauptung_mit_werkzeug_geht_glatt_durch(monkeypatch, tmp_path):
    """Wer das Werkzeug wirklich ruft, wird nicht behelligt."""
    from core.agency import act

    _tmp_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_AUTO_PLAN", False)
    monkeypatch.setattr(act, "_run_tool_guarded",
                        lambda name, tool, args, sid: "Eingetragen: Friseur am 28.07. um 09:30.")
    gesehen = _antworten(monkeypatch, [
        'ACT termin_add {"datum": "28.07.2026", "titel": "Friseur", "zeit": "09:30"}',
        "Steht im Kalender: Friseur am 28.07. um 09:30.",
    ])

    antwort = act.act_chat("Trag mir den Friseur ein", session_id="t-beweis2")
    assert "Steht im Kalender" in antwort
    assert not any("KEIN Werkzeug" in str(m[-1].get("content", "")) for m in gesehen)


def test_normale_antwort_wird_nicht_hinterfragt(monkeypatch, tmp_path):
    """Kein Fehlalarm bei Gespraech ohne Erledigt-Behauptung."""
    from core.agency import act

    _tmp_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(act, "_AUTO_PLAN", False)
    gesehen = _antworten(monkeypatch, ["Alles ruhig hier — was steht bei dir an?"])

    act.act_chat("Wie geht es dir?", session_id="t-beweis3")
    assert len(gesehen) == 1, "harmlose Antwort wurde unnoetig hinterfragt"
