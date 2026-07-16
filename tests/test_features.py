"""Feature-Flags (S12, nach W1 eingedampft): nur noch desktop_low_level + linkedin.

Flag aus = Werkzeug fliegt aus manifest()/tool_schemas()/get()/all_tools(), Code und
Registrierung bleiben (all_tools(include_disabled=True) sieht alles). Toggle via
set_override wirkt sofort, ohne Neustart.
"""
import core.agency.tools.builtin  # noqa: F401  -> registriert die Tools

import core.config as config
from core.agency.tools import registry
from core.config import feature_on

DESKTOP = ("bildschirm_foto", "maus_klick", "maus_bewegen", "tippen", "taste",
           "fenster_liste", "fenster_fokus")


def test_feature_defaults_alles_aus():
    f = config.CONFIG.get("features") or {}
    assert {"desktop_low_level", "linkedin"} <= set(f)
    assert "business" not in f and "radar" not in f      # W1: keine Flags mehr, Code ist WEG
    for name in ("desktop_low_level", "linkedin"):
        assert feature_on(name) is False
    # fail-closed: unbekannte Namen (z.B. 'legacy') sind AUS, ohne Config-Eintrag
    assert feature_on("legacy") is False
    assert feature_on("gibtsnicht") is False


def test_manifest_ohne_geflaggte_tools():
    m = registry.manifest()
    for name in DESKTOP + ("append_file",):
        assert f"- {name} (" not in m, f"{name} sollte bei Flag aus nicht im Manifest stehen"
    # Alltags-Werkzeuge bleiben: Browser-Trio AN (nur Low-Level-Desktop ist geflaggt)
    for name in ("browser_act", "screenshot_url", "browse", "objective_add", "write_file"):
        assert f"- {name} (" in m, f"{name} fehlt im Manifest"


def test_get_filtert_aber_registrierung_bleibt():
    assert registry.get("maus_klick") is None
    assert registry.get("append_file") is None
    # nichts geloescht: die volle Registry kennt die Werkzeuge weiterhin
    alle = {t.name for t in registry.all_tools(include_disabled=True)}
    assert set(DESKTOP) | {"append_file"} <= alle
    # all_tools() (Standard) ist die getrimmte Sicht — Lehr-Fehler + Tuning-Export nutzen sie
    aktiv = {t.name for t in registry.all_tools()}
    assert not (set(DESKTOP) & aktiv)


def test_toggle_reaktiviert_ohne_neustart(monkeypatch, tmp_path):
    # frische Override-Datei, damit der Test nichts Echtes umstellt; setitem verankert
    # den Ausgangswert False -> monkeypatch stellt ihn nach dem Test zurueck.
    monkeypatch.setattr(config, "_OVERRIDE_FILE", tmp_path / "ov.json")
    monkeypatch.setitem(config.CONFIG["features"], "desktop_low_level", False)
    assert registry.get("maus_klick") is None
    config.set_override("features.desktop_low_level", True)
    assert registry.get("maus_klick") is not None
    assert "- maus_klick (" in registry.manifest()
    assert any(s["function"]["name"] == "maus_klick" for s in registry.tool_schemas())


def test_manifest_ist_getrimmt():
    # W1: Venture (5) + Radar (5) sind GELOESCHT (waren als Flags schon aus dem Manifest,
    # jetzt auch aus der Registry). Aktiv: 71 (Alltagskern + P1 todo-Trio + P4 Navigation).
    # MCP-Tools (Praefix mcp_) rausrechnen, damit parallel laufende Bridge-Tests die
    # Zaehlung nicht kippen. Obergrenze = Wachstums-Wache gegen schleichende Aufblaehung;
    # Anheben ist eine BEWUSSTE Entscheidung je Fahrplan-Baustein (P5 trimmt pro Rolle).
    schemas = [s for s in registry.tool_schemas() if not s["function"]["name"].startswith("mcp_")]
    assert len(schemas) < 75
    zeilen = [z for z in registry.manifest().splitlines()
              if z.startswith("- ") and not z.startswith("- mcp_")]
    assert len(zeilen) == len(schemas)  # Prompt-Manifest und Schemata sehen dieselbe Flotte


def test_keine_venture_radar_reste_in_der_registry():
    # W1-DoD auf Registry-Ebene: kein Werkzeug traegt mehr venture/radar/opportunity/stripe
    alle = {t.name for t in registry.all_tools(include_disabled=True)}
    verboten = [n for n in alle
                if any(w in n for w in ("venture", "radar", "opportunity", "stripe"))
                and not n.startswith("mcp_")]
    assert verboten == [], f"Business-Reste in der Registry: {verboten}"
