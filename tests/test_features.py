"""S12 Rezentrierung: Feature-Flags — Registry-Trim, Laufzeit-Toggle, Defaults.

Flag aus = Werkzeug fliegt aus manifest()/tool_schemas()/get()/all_tools(), Code und
Registrierung bleiben (all_tools(include_disabled=True) sieht alles). Toggle via
set_override wirkt sofort, ohne Neustart.
"""
import core.agency.tools.builtin  # noqa: F401  -> registriert die Tools

import core.config as config
from core.agency.tools import registry
from core.config import feature_on

BUSINESS = ("venture_add", "venture_list", "venture_update", "ledger_book", "project_note")
RADAR = ("radar_scan_now", "radar_fokus", "opportunity_list", "opportunity_decide", "opportunity_convert")
DESKTOP = ("bildschirm_foto", "maus_klick", "maus_bewegen", "tippen", "taste",
           "fenster_liste", "fenster_fokus")


def test_feature_defaults_alles_aus():
    f = config.CONFIG.get("features") or {}
    assert {"business", "radar", "desktop_low_level", "linkedin"} <= set(f)
    for name in ("business", "radar", "desktop_low_level", "linkedin"):
        assert feature_on(name) is False
    # fail-closed: unbekannte Namen (z.B. 'legacy') sind AUS, ohne Config-Eintrag
    assert feature_on("legacy") is False
    assert feature_on("gibtsnicht") is False


def test_manifest_ohne_geflaggte_tools():
    m = registry.manifest()
    for name in BUSINESS + RADAR + DESKTOP + ("append_file",):
        assert f"- {name} (" not in m, f"{name} sollte bei Flag aus nicht im Manifest stehen"
    # Alltags-Werkzeuge bleiben: Browser-Trio AN (nur Low-Level-Desktop ist geflaggt),
    # Lebens-Ziele AN (domain leben gehoert zum Coach).
    for name in ("browser_act", "screenshot_url", "browse", "objective_add", "write_file"):
        assert f"- {name} (" in m, f"{name} fehlt im Manifest"


def test_get_filtert_aber_registrierung_bleibt():
    assert registry.get("venture_add") is None
    assert registry.get("maus_klick") is None
    assert registry.get("append_file") is None
    # nichts geloescht: die volle Registry kennt die Werkzeuge weiterhin
    alle = {t.name for t in registry.all_tools(include_disabled=True)}
    assert set(BUSINESS + RADAR + DESKTOP) | {"append_file"} <= alle
    # all_tools() (Standard) ist die getrimmte Sicht — Lehr-Fehler + Tuning-Export nutzen sie
    aktiv = {t.name for t in registry.all_tools()}
    assert not (set(BUSINESS) & aktiv)


def test_toggle_reaktiviert_ohne_neustart(monkeypatch, tmp_path):
    # frische Override-Datei, damit der Test nichts Echtes umstellt; setitem verankert
    # den Ausgangswert False -> monkeypatch stellt ihn nach dem Test zurueck.
    monkeypatch.setattr(config, "_OVERRIDE_FILE", tmp_path / "ov.json")
    monkeypatch.setitem(config.CONFIG["features"], "business", False)
    assert registry.get("venture_add") is None
    config.set_override("features.business", True)
    assert registry.get("venture_add") is not None
    assert "- venture_add (" in registry.manifest()
    assert any(s["function"]["name"] == "venture_add" for s in registry.tool_schemas())


def test_manifest_ist_getrimmt():
    # ~80 registrierte, ~62 aktive Werkzeuge. MCP-Tools (Praefix mcp_) rausrechnen,
    # damit parallel laufende Bridge-Tests die Zaehlung nicht kippen.
    schemas = [s for s in registry.tool_schemas() if not s["function"]["name"].startswith("mcp_")]
    assert len(schemas) < 65
    zeilen = [z for z in registry.manifest().splitlines()
              if z.startswith("- ") and not z.startswith("- mcp_")]
    assert len(zeilen) == len(schemas)  # Prompt-Manifest und Schemata sehen dieselbe Flotte
