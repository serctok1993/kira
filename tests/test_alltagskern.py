"""Phase 2 "Alltags-Kern": Termine, Vault-Schreibpfad, person_fakt, Reports — offline, 0 LLM."""
from __future__ import annotations

import datetime
import json

import core.agency.tools.builtin  # noqa: F401  -> registriert die Tools

from core.agency import termine, vault_notes
from core.agency.tools import registry


# ---------- Termine (data/kalender.json) ----------------------------------------------

def _kalender(monkeypatch, tmp_path):
    # termine.add/remove emittieren Events -> eigene tmp-DB, sonst haengen die Tests
    # an der Reihenfolge (ein FRUEHERER Test muesste die events-Tabelle anlegen).
    from core.kernel import events

    monkeypatch.setattr(termine, "_PATH", tmp_path / "kalender.json")
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()


def test_termin_add_list_remove(monkeypatch, tmp_path):
    _kalender(monkeypatch, tmp_path)
    res = termine.add("15.08.2026", "Zahnarzt", zeit="14:30")
    assert res["ok"] and res["id"]
    heute = datetime.date(2026, 8, 10)
    up = termine.list_upcoming(14, heute=heute)
    assert len(up) == 1 and up[0]["tage_bis"] == 5 and up[0]["titel"] == "Zahnarzt"
    assert termine.remove(res["id"]) is True
    assert termine.list_upcoming(14, heute=heute) == []
    assert termine.remove("gibtsnicht") is False


def test_termin_unfug_datum_lehrt(monkeypatch, tmp_path):
    _kalender(monkeypatch, tmp_path)
    res = termine.add("31.02.2026", "Quatsch")
    assert res["ok"] is False and "31.02.2026" in res["error"]
    # Tool-Schicht gibt eine lehrende Fehlermeldung mit Beispiel-ACT-Zeile
    from core.agency.tools.termin_tools import termin_add
    out = termin_add(datum="31.02.2026", titel="Quatsch")
    assert "ACT termin_add" in out


def test_termin_jaehrlich_ueber_jahreswechsel(monkeypatch, tmp_path):
    _kalender(monkeypatch, tmp_path)
    termine.add("02.01.1950", "Omas Geburtstag", jaehrlich=True)
    funde = termine.naechste(vorlauf_tage=8, heute=datetime.date(2026, 12, 28))
    assert len(funde) == 1
    tage, zeile = funde[0]
    assert tage == 5 and "02.01." in zeile and "Omas Geburtstag" in zeile
    # nicht-jaehrlicher Eintrag in der Vergangenheit taucht nie wieder auf
    termine.add("01.01.2020", "alt")
    assert len(termine.naechste(vorlauf_tage=8, heute=datetime.date(2026, 12, 28))) == 1


def test_termin_block_mergt_stammbaum_und_kalender(monkeypatch, tmp_path):
    from core.agency.missions import standup

    _kalender(monkeypatch, tmp_path)
    base = tmp_path / "gedaechtnis" / "stammbaum" / "leben"
    base.mkdir(parents=True)
    (base / "sandra.md").write_text("- geburtstag: 12.07.1995\n", encoding="utf-8")
    monkeypatch.setattr(standup, "ROOT", tmp_path)
    termine.add("10.07.2026", "Zahnarzt", zeit="09:00")

    out = standup._termin_block(heute=datetime.date(2026, 7, 8))
    assert out.count("TERMIN-RADAR") == 1                      # EIN Block, zwei Quellen
    assert "Zahnarzt" in out and "Sandra" in out
    assert out.index("Zahnarzt") < out.index("Sandra")         # nach Naehe sortiert (2 < 4 Tage)


def test_termine_api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import core.api.server as s

    _kalender(monkeypatch, tmp_path)
    r = termine.add("15.08.2099", "API-Test")
    c = TestClient(s.app)
    d = c.get("/api/termine?tage=99999").json()
    assert any(t["id"] == r["id"] for t in d["termine"])
    ok = c.post("/api/termine/delete", json={"id": r["id"]}).json()
    assert ok["ok"] is True
    assert c.post("/api/termine/delete", json={"id": "nix"}).json()["ok"] is False


# ---------- Vault-Schreibpfad ----------------------------------------------------------

def _vault(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setitem(vault_notes.CONFIG, "desktop", {"vault_paths": [str(vault)]})
    return vault


def test_vault_note_schreibt_und_appendet(monkeypatch, tmp_path):
    vault = _vault(monkeypatch, tmp_path)
    r1 = vault_notes.write_note("Video Setup", "Kamera: A")
    f = vault / "notizen" / "video-setup.md"
    assert r1["ok"] and r1["created"] and f.exists()
    assert "# Video Setup" in f.read_text(encoding="utf-8")
    r2 = vault_notes.write_note("Video Setup", "Licht: B")
    assert r2["created"] is False
    text = f.read_text(encoding="utf-8")
    assert "Kamera: A" in text and "Licht: B" in text and "## Update" in text


def test_vault_dossier_und_fallback_root(monkeypatch, tmp_path):
    # kein gueltiger vault_paths-Eintrag -> Fallback ROOT/gedaechtnis
    monkeypatch.setitem(vault_notes.CONFIG, "desktop", {"vault_paths": ["Z:/gibts/nicht"]})
    monkeypatch.setattr(vault_notes, "ROOT", tmp_path)
    r = vault_notes.write_dossier("Social-Media-Hooks DACH", "- Hook X ([Q](https://x))")
    assert r["ok"]
    assert (tmp_path / "gedaechtnis" / "dossiers" / "social-media-hooks-dach.md").exists()


def test_vault_note_leer_lehrt():
    from core.agency.tools.vault_tools import vault_note

    assert "ACT vault_note" in vault_note(titel="", text="")


# ---------- person_fakt ----------------------------------------------------------------

def test_person_fakt_legt_blatt_an_und_ersetzt_luecke(monkeypatch, tmp_path):
    monkeypatch.setattr(vault_notes, "ROOT", tmp_path)
    menschen = tmp_path / "gedaechtnis" / "stammbaum" / "leben" / "menschen"
    menschen.mkdir(parents=True)
    (menschen / "_VORLAGE.md").write_text(
        "# VORNAME (Beziehung zum Nutzer)\n\n- beziehung: ???\n- geburtstag: ???\n\n"
        "## Notizen (mit Datum)\n\n-\n", encoding="utf-8")

    r = vault_notes.person_fakt_upsert("Ali Muster", "geburtstag", "03.08.1990")
    assert r["ok"] and r["created"]
    text = (menschen / "ali-muster.md").read_text(encoding="utf-8")
    assert text.startswith("# Ali Muster")                     # Vorlagen-Kopf ersetzt
    assert "- geburtstag: 03.08.1990" in text and "geburtstag: ???" not in text

    # Upsert ist idempotent: zweiter Aufruf ersetzt, dupliziert nicht
    vault_notes.person_fakt_upsert("Ali Muster", "geburtstag", "04.08.1990")
    text = (menschen / "ali-muster.md").read_text(encoding="utf-8")
    assert text.count("- geburtstag:") == 1 and "04.08.1990" in text


def test_person_fakt_neues_feld_vor_notizen(monkeypatch, tmp_path):
    monkeypatch.setattr(vault_notes, "ROOT", tmp_path)
    menschen = tmp_path / "gedaechtnis" / "stammbaum" / "leben" / "menschen"
    menschen.mkdir(parents=True)
    (menschen / "mama.md").write_text(
        "# Mama\n\n- geburtstag: 01.05.1965\n\n## Notizen (mit Datum)\n\n- x\n", encoding="utf-8")
    r = vault_notes.person_fakt_upsert("Mama", "wohnort", "Berlin")
    assert r["ok"] and not r["created"] and not r["ersetzt"]
    zeilen = (menschen / "mama.md").read_text(encoding="utf-8").splitlines()
    assert "- wohnort: Berlin" in zeilen
    assert zeilen.index("- wohnort: Berlin") < zeilen.index("## Notizen (mit Datum)")


def test_person_fakt_findet_blatt_in_unterordnern(monkeypatch, tmp_path):
    monkeypatch.setattr(vault_notes, "ROOT", tmp_path)
    base = tmp_path / "gedaechtnis" / "stammbaum"
    (base / "leben").mkdir(parents=True)
    (base / "MIA.md").write_text("# Mia\n- wohnort: ???\n", encoding="utf-8")
    r = vault_notes.person_fakt_upsert("Mia", "wohnort", "Berlin")
    assert r["ok"] and r["ersetzt"] and not r["created"]
    assert "- wohnort: Berlin" in (base / "MIA.md").read_text(encoding="utf-8")


def test_logbuch_frage_nennt_person_fakt(monkeypatch, tmp_path):
    from core.agency.missions import standup

    monkeypatch.setattr(standup, "ROOT", tmp_path)
    base = tmp_path / "gedaechtnis" / "stammbaum" / "leben"
    base.mkdir(parents=True)
    (base / "daten.md").write_text("- geburtsdatum: ???\n", encoding="utf-8")
    q = standup._stammbaum_question("2026-07-04")
    assert "person_fakt" in q and "edit_datei" not in q
    assert '"feld": "geburtsdatum"' in q and "daten.md" in q


# ---------- Reports ---------------------------------------------------------------------

def _reports_sandbox(monkeypatch, tmp_path):
    from core.agency.missions import maintenance, queue
    from core.kernel import events

    db = str(tmp_path / "state.db")
    monkeypatch.setattr(events, "DB_PATH", db)
    monkeypatch.setattr(queue, "DB_PATH", db)
    events.init_db()
    queue.init_queue()
    monkeypatch.setattr(maintenance, "_STATE_PATH", tmp_path / "maintenance.json")
    _kalender(monkeypatch, tmp_path)
    return _vault(monkeypatch, tmp_path)


def test_wochenreport_erzeugt_datei_mit_prioritaeten(monkeypatch, tmp_path):
    from core.agency import reports
    from core.agency.missions import queue
    from core.kernel import events

    vault = _reports_sandbox(monkeypatch, tmp_path)
    events.emit("mission_task_done", {"id": "x", "score": 80})
    queue.add("Steuern vorbereiten", mission="leben", priority=1)

    # "heute" = naechster Montag -> die Vorwoche (= Fenster mit dem Event von eben) ist dran
    heute = datetime.date.today()
    montag = heute + datetime.timedelta(days=(7 - heute.weekday()) % 7 or 7)
    r = reports.wochenreport(heute=montag)
    assert r and r["art"] == "Wochenreport"
    dateien = list((vault / "reports").glob("wochenreport-*.md"))
    assert len(dateien) == 1
    text = dateien[0].read_text(encoding="utf-8")
    assert "PRIORITAETEN" in text and "P1: Steuern vorbereiten" in text
    assert "1 erledigt" in text


def test_wochenreport_nur_montags_und_nur_einmal(monkeypatch, tmp_path):
    from core.agency import reports

    _reports_sandbox(monkeypatch, tmp_path)
    dienstag = datetime.date(2026, 7, 7)
    assert reports.wochenreport(heute=dienstag) is None            # nicht faellig
    montag = datetime.date(2026, 7, 6)
    assert reports.wochenreport(heute=montag) is not None          # faellig
    assert reports.wochenreport(heute=montag) is None              # Merker: nie doppelt


def test_monatsreport_verlinkt_wochen(monkeypatch, tmp_path):
    from core.agency import reports

    vault = _reports_sandbox(monkeypatch, tmp_path)
    reports.wochenreport(force=True)                               # eine Woche liegt schon da
    r = reports.monatsreport(heute=datetime.date(2026, 8, 1))
    assert r and r["art"] == "Monatsreport" and r["label"] == "2026-07"
    dateien = list((vault / "reports").glob("monatsreport-*.md"))
    assert len(dateien) == 1
    text = dateien[0].read_text(encoding="utf-8")
    assert "[[wochenreport-" in text and "PRIORITAETEN" in text
    assert reports.monatsreport(heute=datetime.date(2026, 8, 1)) is None  # Merker


def test_rollup_ist_failsoft(monkeypatch, tmp_path):
    from core.agency import reports

    _reports_sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(reports, "wochenreport", lambda **k: (_ for _ in ()).throw(RuntimeError("kaputt")))
    out = reports.rollup()                                         # crasht nicht
    assert isinstance(out, list)


# ---------- Manifest --------------------------------------------------------------------

def test_neue_tools_im_manifest():
    m = registry.manifest()
    for name in ("termin_add", "termin_list", "vault_note", "vault_dossier", "person_fakt"):
        assert f"- {name} (" in m, f"{name} fehlt im Manifest"
    schemas = [s for s in registry.tool_schemas() if not s["function"]["name"].startswith("mcp_")]
    assert len(schemas) <= 74  # 73 aktiv (P1 +3, P4 +2, erinnerung +1; Kollision aufgeloest), Luft fuer Synthese
    # Registry-Konvention: optionale Parameter tragen "optional"/"Standard" -> nicht required
    ta = next(s for s in schemas if s["function"]["name"] == "termin_add")
    assert set(ta["function"]["parameters"]["required"]) == {"datum", "titel"}
    pf = next(s for s in schemas if s["function"]["name"] == "person_fakt")
    assert set(pf["function"]["parameters"]["required"]) == {"name", "feld", "wert"}


def test_tool_namen_kollisionsfrei():
    # Wache gegen stille Namenskollisionen (aus PR #180 uebernommen): _REGISTRY ist ein
    # dict, die letzte @tool-Registrierung gewinnt — ein doppelter Name laesst ein
    # Werkzeug lautlos verschwinden (so geschehen bei todo_list: der P1-Plan verdeckte
    # das Lebens-Board, bis #179 die Plan-Ansicht in todo_stand umbenannte).
    import re
    from pathlib import Path

    tools_dir = Path(registry.__file__).parent
    namen: dict[str, list[str]] = {}
    for py in sorted(tools_dir.glob("*.py")):
        for m in re.finditer(r'@tool\(\s*"([^"]+)"', py.read_text(encoding="utf-8")):
            namen.setdefault(m.group(1), []).append(py.name)
    doppelt = {n: orte for n, orte in namen.items() if len(orte) > 1}
    assert not doppelt, f"Tool-Namen doppelt registriert: {doppelt}"
