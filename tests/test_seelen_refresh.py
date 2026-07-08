"""Seelen-Refresh (08.07.): Dateien auf Effizienz + VON-SERGEN-Platz; Termin-Radar
wendet Stammbaum-Daten automatisch an (Geburtstage/Termine ins Briefing)."""
from __future__ import annotations

import datetime

from core.agency.missions import standup
from core.config import MIND_DIR


# ---------- Seelen-Dateien: dicht, mit klarem Platz fuer Sergen ----------

def test_seelen_dateien_dicht_und_mit_sergen_platz():
    grenzen = {"SOUL.md": 2300, "GOAL.md": 2300, "USER.md": 2900}
    for name, cap in grenzen.items():
        text = (MIND_DIR / name).read_text(encoding="utf-8")
        assert len(text) < cap, f"{name} zu lang ({len(text)} >= {cap})"
        assert "VON SERGEN" in text, f"{name}: Sergen-Block fehlt"
        assert text.count("???") >= 4, f"{name}: zu wenig Ausfuell-Zeilen fuer Sergen"


def test_soul_hat_arbeitsfreiheit_und_partnerschaft():
    text = (MIND_DIR / "SOUL.md").read_text(encoding="utf-8")
    assert "Arbeitsfreiheit" in text and "Partnerin" in text
    assert "transparent melden" in text          # Freiheit UND Rechenschaft


def test_persona_hat_neue_regeln_und_haelt_budget():
    text = (MIND_DIR / "PERSONA.md").read_text(encoding="utf-8")
    assert "Zwischenstand" in text               # Update-Pflicht bei laengerer Arbeit
    assert "Termin-Radar" in text                # Fakten sichern -> Radar wendet an
    assert len(text) < 4200                      # Kontext-Diaet haelt


# ---------- Termin-Radar: Erinnerungen ANWENDEN ----------

def _stammbaum(monkeypatch, tmp_path, dateien: dict):
    base = tmp_path / "gedaechtnis" / "stammbaum" / "leben"
    base.mkdir(parents=True)
    for name, inhalt in dateien.items():
        (base / name).write_text(inhalt, encoding="utf-8")
    monkeypatch.setattr(standup, "ROOT", tmp_path)


def test_radar_findet_geburtstag_im_vorlauf(monkeypatch, tmp_path):
    heute = datetime.date(2026, 7, 8)
    _stammbaum(monkeypatch, tmp_path, {
        "sandra.md": "# Sandra\n- geburtstag: 12.07.1995\n- mag: Katzen",
        "sergen.md": "# Sergen\n- geburtstag: 01.07.1993",          # schon vorbei -> naechstes Jahr
    })
    out = standup._termin_radar(heute=heute)
    assert "TERMIN-RADAR" in out and "VON DIR AUS" in out
    assert "Sandra" in out and "12.07." in out and "in 4 Tagen" in out
    assert "(wird 31)" in out                                       # Alter aus Jahrgang
    assert "- Sergen" not in out                                    # 358 Tage hin -> kein Fund


def test_radar_heute_und_jahreswechsel(monkeypatch, tmp_path):
    _stammbaum(monkeypatch, tmp_path, {
        "sandra.md": "- geburtstag: 08.07.\n",                      # ohne Jahr, HEUTE
        "oma.md": "- geburtstag: 02.01.1950\n",
    })
    out = standup._termin_radar(heute=datetime.date(2026, 7, 8))
    assert "HEUTE" in out and "Sandra" in out
    out2 = standup._termin_radar(heute=datetime.date(2026, 12, 28))  # Jahreswechsel
    assert "Oma" in out2 and "02.01." in out2


def test_radar_einmaliger_termin_mit_jahr(monkeypatch, tmp_path):
    _stammbaum(monkeypatch, tmp_path, {
        "vertraege.md": "- kfz-versicherung kuendbar bis: 15.07.2026\n- alt: 01.01.2020\n",
    })
    out = standup._termin_radar(heute=datetime.date(2026, 7, 8))
    assert "kfz-versicherung" in out and "in 7 Tagen" in out
    assert "01.01." not in out                                      # Vergangenes bleibt still


def test_radar_leer_und_robust(monkeypatch, tmp_path):
    monkeypatch.setattr(standup, "ROOT", tmp_path)                  # kein Stammbaum-Ordner
    assert standup._termin_radar() == ""
    _stammbaum(monkeypatch, tmp_path, {"kaputt.md": "- geburtstag: 99.99.9999\n- x: kein datum"})
    assert standup._termin_radar(heute=datetime.date(2026, 7, 8)) == ""


def test_radar_haengt_im_briefing(monkeypatch, tmp_path):
    _stammbaum(monkeypatch, tmp_path, {"sandra.md": "- geburtstag: 10.07.\n"})
    monkeypatch.setattr(standup, "_news_block", lambda max_items=8: "")
    monkeypatch.setattr(standup, "_stammbaum_question", lambda heute="": "")
    monkeypatch.setattr(standup, "_termin_radar",
                        lambda heute=None, vorlauf_tage=8: "TERMIN-RADAR (Stub):\n- Sandra")
    text = standup.build_context()
    assert "TERMIN-RADAR" in text and "Sandra" in text
