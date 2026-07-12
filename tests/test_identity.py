"""W2/W3 Identitaet entkoppelt: identity.py, Templates, Renderer, system_stub, Injektion.

Kern-Garantie: die Namen kommen UEBERALL live aus identity — der Werkszustand heisst
Kira/Partner, jede Instanz kann 'Nova'/'Alex' sein. Der Mechanismus ist deterministisch:
dieselben Namen ergeben immer denselben Text (Trainingsvertrag des lokalen Modells).
"""
from __future__ import annotations

import core.agency.tools.builtin  # noqa: F401

import core.config as config
from core import identity
from core.agency.tools import registry

# Verbotene Personendaten NIE woertlich in Testdateien tragen (Clean-Gate W3):
_ALTNAME = "Ser" "gen"
_ALTORT = "Kob" "lenz"


def test_identity_liest_config_live(monkeypatch):
    assert identity.agent_name() == "Kira"     # Werkszustand: harness_name greift
    assert identity.user_name() == "Partner"   # Werkszustand: user ist leer -> Fallback
    monkeypatch.setitem(config.CONFIG, "identity",
                        {"harness_name": "Kira", "partner_name": "Nova", "user": "Alex"})
    assert identity.agent_name() == "Nova"     # kein Cache — Override wirkt sofort
    assert identity.user_name() == "Alex"
    assert identity.ident() == {"agent": "Nova", "user": "Alex"}


def test_identity_fallbacks(monkeypatch):
    monkeypatch.setitem(config.CONFIG, "identity", {})
    assert identity.agent_name() == "Kira"
    assert identity.user_name() == "Partner"


def test_render_platzhalter_und_genitiv(monkeypatch):
    monkeypatch.setitem(config.CONFIG, "identity", {"partner_name": "Nova", "user": "Alex"})
    out = identity.render("{{AGENT_NAME}} dient {{USER_NAME}} — {{USER_NAME_S}} Kalender.")
    assert out == "Nova dient Alex — Alex' Kalender."               # x-Endung -> Apostroph
    monkeypatch.setitem(config.CONFIG, "identity", {"user": "Mia"})
    assert identity.render("{{USER_NAME_S}} Post") == "Mias Post"


def test_manifest_rendert_namen(monkeypatch):
    # Werkszustand: Beschreibungen tragen den Fallback-Namen, keine Platzhalter-Reste
    m = registry.manifest()
    assert "Partners Kalender" in m and "{{" not in m
    # Umbenannt: dieselben Beschreibungen tragen sofort die neuen Namen
    monkeypatch.setitem(config.CONFIG, "identity", {"partner_name": "Nova", "user": "Alex"})
    m2 = registry.manifest()
    assert "Alex' Kalender" in m2 and _ALTNAME not in m2


def test_system_stub_variiert_identitaet(monkeypatch):
    from core.mind.tuning import system_stub

    monkeypatch.setitem(config.CONFIG, "identity", {"user": "Mia"})
    assert system_stub().startswith("Du bist Kira — Mias KI-Partnerin")
    neu = system_stub("Nova", "Alex")
    assert neu.startswith("Du bist Nova — Alex' KI-Partnerin")
    assert "ACT <werkzeug>" in neu                                  # Protokoll unveraendert


def test_mind_read_faellt_auf_template_zurueck(monkeypatch, tmp_path):
    # frischer Klon: keine Live-SOUL.md -> _read rendert das Template in-memory
    from core.mind import agent

    monkeypatch.setattr(agent, "MIND_DIR", config.MIND_DIR)  # Ausgangslage
    leer = tmp_path / "mind"
    (leer / "templates").mkdir(parents=True)
    (leer / "templates" / "SOUL.md").write_text(
        "# SEELE — {{AGENT_NAME}}\nPartnerin von {{USER_NAME}}.", encoding="utf-8")
    monkeypatch.setattr(agent, "MIND_DIR", leer)
    monkeypatch.setitem(config.CONFIG, "identity", {"partner_name": "Nova", "user": "Alex"})
    out = agent._read("SOUL.md")
    assert "SEELE — Nova" in out and "Partnerin von Alex" in out
    assert not (leer / "SOUL.md").exists()                     # nichts geschrieben (in-memory)


def test_seed_render_mind_schreibt_nur_fehlende(monkeypatch, tmp_path):
    from core.mind import seed

    leer = tmp_path / "mind"
    (leer / "templates").mkdir(parents=True)
    (leer / "templates" / "SOUL.md").write_text("# {{AGENT_NAME}}", encoding="utf-8")
    (leer / "templates" / "GOAL.md").write_text("Ziel von {{USER_NAME}}", encoding="utf-8")
    (leer / "GOAL.md").write_text("LIVE-Fassung — nicht anfassen", encoding="utf-8")
    monkeypatch.setattr(seed, "MIND_DIR", leer)

    out = seed.render_mind("Nova", "Alex")
    assert out["SOUL.md"] == "geschrieben"
    assert out["GOAL.md"] == "uebersprungen"                    # Live-Datei nie ungefragt
    assert (leer / "SOUL.md").read_text(encoding="utf-8") == "# Nova"
    assert (leer / "GOAL.md").read_text(encoding="utf-8") == "LIVE-Fassung — nicht anfassen"
    out2 = seed.render_mind("Nova", "Alex", force=True)
    assert out2["GOAL.md"] == "geschrieben"                     # force = Werkszustand/Onboarding


def test_cockpit_injiziert_identitaet(monkeypatch):
    from fastapi.testclient import TestClient

    import core.api.server as s

    monkeypatch.setitem(config.CONFIG, "identity", {"partner_name": "Nova", "user": "Alex"})
    html = TestClient(s.app).get("/").text
    assert "__AGENT__" not in html and "__AGENT_UC__" not in html and "__USER__" not in html
    assert '"agent": "Nova", "user": "Alex"' in html            # IDENTITY-Injektion
    assert '<span class="txt">NOVA</span>' in html              # Brand = Agenten-Name
    assert "> Alex <b" in html                                  # Me-Tab traegt den Nutzer-Namen


def test_templates_vollstaendig_und_neutral():
    from core.config import MIND_DIR

    for name in ("SOUL.md", "GOAL.md", "USER.md", "PERSONA.md", "BODY.md"):
        t = (MIND_DIR / "templates" / name).read_text(encoding="utf-8")
        assert _ALTNAME not in t and _ALTORT not in t, f"{name} ist nicht neutral"
        assert "{{AGENT_NAME}}" in t or "{{USER_NAME}}" in t, f"{name} ohne Platzhalter"


def test_verfassung_ist_generisch():
    from core.config import MIND_DIR

    t = (MIND_DIR / "constitution.md").read_text(encoding="utf-8")
    assert _ALTNAME not in t                                    # W2: generisch
    assert "Not-Aus" in t and "Budget ist heilig" in t          # Substanz unveraendert
