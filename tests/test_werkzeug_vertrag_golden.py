"""Der Werkzeug-Vertrag ist eingefroren — Werkstatt-Hebel der Generalinventur (27.07.2026).

WARUM ES DIESE DATEI GIBT

Zwei Spuren arbeiten parallel: der Harness (dieser Code) und die Werkstatt (Training der
lokalen Modelle). Was das Modell lernt, ist der VERTRAG des Harness — Werkzeugnamen,
Argumentnamen, welche Rolle welches Werkzeug sieht, die ACT-Syntax und die Form, in der
ein Werkzeug-Ergebnis zurueckkommt. Aendert der Harness davon etwas, ohne dass die
Werkstatt nachzieht, ruft das Modell Werkzeuge auf, die es nicht mehr gibt, oder benutzt
Argumentnamen, die abgelehnt werden.

Genau das ist passiert: Zwischen dem Stand, auf dem c5b generiert wurde (19.07.), und dem
27.07. hat sich der Vertrag an NEUN Stellen geaendert, ohne dass eine Meldung an die
Werkstatt ging. Die Prosa in act.py war durch test_trainingsvertrag.py geschuetzt — die
Werkzeug- und Argumentnamen durch nichts ausser einer Obergrenze auf die Gesamtzahl.

WAS ZU TUN IST, WENN DIESER TEST ROT WIRD

Er ist kein Verbot, sondern eine Quittung. Wenn die Aenderung gewollt ist:
  1. `python -m tests.test_werkzeug_vertrag_golden --schreiben` aktualisiert die Datei.
  2. Die ausgegebene Differenz woertlich an die Werkstatt weiterleiten.
  3. Die Werkstatt entscheidet, ob ein neues Training noetig ist (Faustregel unten).

FAUSTREGEL — WANN MUSS DIE WERKSTATT NEU TRAINIEREN?

  Training noetig:      Werkzeug kommt dazu, faellt weg oder wird umbenannt · Argumentname
                        aendert sich · ein Werkzeug wandert in eine andere Rolle · ACT-Syntax
                        oder Ergebnis-Wrapper aendern sich.
  Kein Training noetig: Beschreibungstexte praezisieren (das Modell liest sie zur Laufzeit
                        im Manifest) · Fehlertexte · interne Umbauten ohne Signaturaenderung ·
                        alles unterhalb der Werkzeug-Ebene.
"""
from __future__ import annotations

import json
import pathlib

GOLDEN = pathlib.Path(__file__).parent / "golden_werkzeug_vertrag.json"


def _vertrag() -> dict:
    """Alles, was das Modell ueber den Harness gelernt hat — maschinell abgegriffen."""
    import core.agency.tools.builtin  # noqa: F401 — Registrierung ausloesen
    import core.agency.tools.termin_tools  # noqa: F401
    from core.agency import rollen
    from core.agency.act import ACT_ZEILE, obs_wrapper
    from core.agency.tools import registry

    # Selbstgebaute Werkzeuge (data/tools/*.py) und die MCP-Bruecke gehoeren dem
    # jeweiligen Rechner, nicht dem Produkt — sie wuerden die Datei bei jedem Nutzer
    # anders aussehen lassen und den Vertrag verrauschen.
    from core.config import DATA_DIR

    eigenbau = {p.stem for p in (DATA_DIR / "tools").glob("*.py")}

    werkzeuge = {}
    for s in registry.tool_schemas():
        f = s["function"]
        if f["name"].startswith("mcp_") or f["name"] in eigenbau:
            continue
        p = f.get("parameters") or {}
        werkzeuge[f["name"]] = {
            "args": sorted((p.get("properties") or {}).keys()),
            "pflicht": sorted(p.get("required") or []),
        }
    rollenbild = {}
    for rang in sorted(rollen.ROLLEN):
        ts = rollen.toolset(rang)
        rollenbild[rang] = sorted(ts) if ts else None    # None = volle Flotte
    return {
        "act_zeile": ACT_ZEILE,
        "ergebnis_form": obs_wrapper("<name>", "<ergebnis>"),
        "werkzeuge": dict(sorted(werkzeuge.items())),
        "rollen": rollenbild,
    }


def _differenz(alt: dict, neu: dict) -> list[str]:
    zeilen: list[str] = []
    for feld in ("act_zeile", "ergebnis_form"):
        if alt.get(feld) != neu.get(feld):
            zeilen.append(f"{feld}: {alt.get(feld)!r} -> {neu.get(feld)!r}")
    a, n = alt.get("werkzeuge", {}), neu.get("werkzeuge", {})
    for name in sorted(set(n) - set(a)):
        zeilen.append(f"NEU:  {name}({', '.join(n[name]['args'])})")
    for name in sorted(set(a) - set(n)):
        zeilen.append(f"WEG:  {name}")
    for name in sorted(set(a) & set(n)):
        if a[name] != n[name]:
            zeilen.append(f"ARGS: {name}: {a[name]} -> {n[name]}")
    ar, nr = alt.get("rollen", {}), neu.get("rollen", {})
    for rang in sorted(set(ar) | set(nr)):
        if ar.get(rang) != nr.get(rang):
            dazu = sorted(set(nr.get(rang) or []) - set(ar.get(rang) or []))
            weg = sorted(set(ar.get(rang) or []) - set(nr.get(rang) or []))
            zeilen.append(f"ROLLE {rang}: +{dazu} -{weg}")
    return zeilen


def test_werkzeug_vertrag_unveraendert():
    """Faellt um, sobald sich etwas aendert, das die Werkstatt wissen MUSS."""
    assert GOLDEN.exists(), (
        "Vertragsdatei fehlt — einmalig erzeugen mit:\n"
        "  uv run python -m tests.test_werkzeug_vertrag_golden --schreiben")
    alt = json.loads(GOLDEN.read_text(encoding="utf-8"))
    neu = _vertrag()
    if alt == neu:
        return
    diff = _differenz(alt, neu) or ["(Struktur geaendert)"]
    raise AssertionError(
        "Der WERKZEUG-VERTRAG hat sich geaendert — die Werkstatt trainiert auf genau "
        "diese Namen:\n  " + "\n  ".join(diff)
        + "\n\nWenn das gewollt ist:\n"
          "  1. uv run python -m tests.test_werkzeug_vertrag_golden --schreiben\n"
          "  2. die Zeilen oben woertlich an die Werkstatt weiterleiten\n"
          "  3. Faustregel im Modul-Docstring entscheidet, ob neu trainiert werden muss")


def test_vertrag_enthaelt_die_tragenden_familien():
    """Schutz gegen ein versehentlich leeres oder halbes Abgriff-Ergebnis."""
    v = _vertrag()
    for name in ("cron_add", "cron_list", "cron_update", "cron_remove",
                 "erinnerung", "erinnerung_list", "erinnerung_remove",
                 "termin_add", "termin_update", "termin_remove"):
        assert name in v["werkzeuge"], name
    assert v["rollen"]["haupt"], "haupt-Rolle ohne Toolset"
    assert v["act_zeile"].startswith("ACT ")


if __name__ == "__main__":  # pragma: no cover — Pflege-Werkzeug
    import sys

    if "--schreiben" in sys.argv:
        GOLDEN.write_text(json.dumps(_vertrag(), indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        print(f"Vertragsstand geschrieben: {GOLDEN}")
    else:
        print(json.dumps(_vertrag(), indent=2, ensure_ascii=False))
