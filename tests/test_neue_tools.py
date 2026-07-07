"""Neue Komfort-Werkzeuge aus dem Audit: cron_remove (Crons wieder loeschen) und
objective_list (Ziele auflisten). Backend existierte laengst — jetzt als Tool erreichbar.
"""
from __future__ import annotations


def _tmp(monkeypatch, tmp_path):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()


def test_cron_remove_loescht_job(monkeypatch, tmp_path):
    from core.agency.missions import cron
    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    from core.agency.tools import builtin
    j = cron.add_job("Testlauf", "mach was", "taeglich 09:00")
    assert any(x["id"] == j["id"] for x in cron.list_jobs())
    # Kurzform-id (8 Zeichen) muss reichen
    out = builtin.cron_remove(j["id"][:8])
    assert "geloescht" in out.lower()
    assert not any(x["id"] == j["id"] for x in cron.list_jobs())


def test_cron_remove_unbekannt(monkeypatch, tmp_path):
    from core.agency.missions import cron
    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    from core.agency.tools import builtin
    out = builtin.cron_remove("gibtsnicht")
    assert "Keine" in out or "gefunden" in out


def test_cron_kaputte_datei_wird_gemeldet(monkeypatch, tmp_path):
    """Ein beschaedigtes cron.json darf NIE still alle Crons verschlucken: Event + Notify +
    .broken-Kopie, gedrosselt (kein Spam pro Loop-Tick)."""
    _tmp(monkeypatch, tmp_path)
    from core.kernel import events
    from core.agency.missions import cron
    monkeypatch.setattr(cron, "JOBS", tmp_path / "cron.json")
    monkeypatch.setattr(cron, "_LOAD_ERR_TS", 0.0)
    pings: list = []
    monkeypatch.setattr(cron, "_notify", lambda t: pings.append(t))
    (tmp_path / "cron.json").write_text("{kaputt", encoding="utf-8")

    assert cron._load() == []                                   # faellt sicher auf leer
    assert (tmp_path / "cron.json.broken").exists()             # Diagnose-Kopie liegt da
    assert "cron_load_error" in [e["type"] for e in events.recent(10)]
    assert pings and "beschaedigt" in pings[0]                  # Sergen wird benachrichtigt
    n = len(events.recent(50))
    cron._load()                                                # sofort nochmal -> gedrosselt
    assert len(events.recent(50)) == n and len(pings) == 1


def test_objective_list(monkeypatch, tmp_path):
    _tmp(monkeypatch, tmp_path)
    from core.agency.missions import objectives
    monkeypatch.setattr(objectives, "DB_PATH", str(tmp_path / "state.db"))
    from core.agency.tools import life_tools
    assert "keine ziele" in life_tools.objective_list().lower()
    objectives.init_objectives()
    objectives.add("Erste 10 Kunden", kind="monthly", domain="business")
    objectives.add("Mehr Schlaf", kind="weekly", domain="leben")
    alle = life_tools.objective_list()
    assert "Erste 10 Kunden" in alle and "Mehr Schlaf" in alle
    # Domain-Filter
    nur_biz = life_tools.objective_list(domain="business")
    assert "Erste 10 Kunden" in nur_biz and "Mehr Schlaf" not in nur_biz
