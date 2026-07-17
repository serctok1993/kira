"""Charakter-Dateien (SOUL/GOAL/USER/PERSONA): editierbare Textdateien (kein Code), alle an
EINEM Ort — Kira -> Seele & Dateien (des Nutzers Wunsch: ein Tab zum Durcharbeiten, der separate
Charakter-Reiter wurde entfernt). PERSONA wird frisch pro Turn gelesen (Aenderung wirkt sofort).
"""
from __future__ import annotations


def test_persona_datei_existiert_mit_markern():
    # Werkszustand-Kontrakt: das TEMPLATE traegt die Struktur-Marker; auf frischen
    # Klonen rendert agent._read() genau dieses Template in-memory (W3). Die gelebte
    # PERSONA.md ist Nutzer-/Agenten-Eigentum und darf frei umgeschrieben werden —
    # die Suite haengt nie an Live-Daten (W0, Praxis-Fund 17.07.).
    from core.config import MIND_DIR
    t = (MIND_DIR / "templates" / "PERSONA.md").read_text(encoding="utf-8")
    for m in ("WER DU BIST", "WIE DU MITDENKST", "WO DU NACHSCHAUST", "WIE DU SPRICHST"):
        assert m in t, m


def test_persona_text_liest_frisch(monkeypatch):
    from core.mind import agent
    # nur Mechanik, kein Content-Marker: die Live-PERSONA.md darf frei umgeschrieben
    # sein (W0) — hier zaehlt, DASS etwas kommt und dass Aenderungen sofort wirken.
    assert agent.persona_text()
    # simuliert eine Charakter-Aenderung in der Datei -> wirkt sofort (kein Neustart)
    monkeypatch.setattr(agent, "_read",
                        lambda name: "NEUER TON" if name == "PERSONA.md" else "")
    assert agent.persona_text() == "NEUER TON"


def test_persona_directive_bleibt_string():
    # Rueckwaerts-kompatibel: der Modul-Konstante-Zugriff funktioniert weiter (Tests/_identity)
    from core.mind import agent
    assert isinstance(agent.PERSONA_DIRECTIVE, str) and len(agent.PERSONA_DIRECTIVE) > 100


def test_files_hat_persona_editierbar():
    from core.api import server
    assert "PERSONA.md" in server.FILES and server.FILES["PERSONA.md"]["editable"] is True


def test_charakter_reiter_ist_weg_dateien_ist_der_eine_ort():
    """bewusste Entscheidung: EIN Tab fuer alle editierbaren Prompt-Dateien (Seele & Dateien);
    der separate Charakter-Reiter ist entfernt."""
    from fastapi.testclient import TestClient
    import core.api.server as s
    html = TestClient(s.app).get("/").text
    assert 'id="v-charakter"' not in html and 'data-s="charakter"' not in html
    assert "loadCharakter" not in html


def test_neue_subtabs_sind_in_kira_gruppen_sichtbar():
    """Regressionsschutz (Fable-Review-Fund): syncKiraGroup blendet jeden Subtab aus, der in
    KEINER KIRA_GROUPS-Gruppe steht — neue Reiter muessen dort eingetragen sein, sonst sind
    sie im Cockpit unsichtbar, obwohl HTML/Loader existieren."""
    import re
    from core.api.ui import script
    m = re.search(r"const KIRA_GROUPS=\[(.*?)\];", script.SCRIPT, re.DOTALL)
    assert m, "KIRA_GROUPS nicht gefunden"
    gruppen = m.group(1)
    # JEDER data-s-Subtab der Kira-Leiste muss in einer Gruppe auftauchen
    from core.api.ui import views
    bar = re.search(r'id="kira-tabs".*?</div>', views.VIEWS if hasattr(views, "VIEWS") else "", re.DOTALL)
    subs = re.findall(r'data-s="([a-z]+)"', bar.group(0)) if bar else []
    if not subs:  # Fallback: bekannte Pflicht-Subtabs pruefen
        subs = ["bench", "files"]
    fehlend = [s2 for s2 in subs if f'"{s2}"' not in gruppen]
    assert not fehlend, f"Subtabs ohne Gruppe (unsichtbar!): {fehlend}"


def test_fable_review_notiz_vorhanden():
    from core.config import ROOT
    t = (ROOT / "docs" / "FABLE-REVIEW.md").read_text(encoding="utf-8")
    for m in ("Modell-Setup", "Coding-Basis", "Persona-Kohärenz", "Report-", "Audit-Reste"):
        assert m in t, m


def test_dateien_liste_hat_alle_charakter_dateien():
    """Alle vier Charakter-Dateien leben in der EINEN Dateien-Liste, mit erklaerenden Labels."""
    from fastapi.testclient import TestClient
    import core.api.server as s
    c = TestClient(s.app)
    eintraege = {f["name"]: f for f in c.get("/api/files").json()}
    for name in ("SOUL.md", "GOAL.md", "USER.md", "PERSONA.md"):
        assert name in eintraege and eintraege[name]["editable"]
    assert "wirkt sofort" in eintraege["SOUL.md"]["label"]          # Erklaertext zog mit um
    assert "constitution.md" in eintraege and "HANDBUCH.md" in eintraege
    r = c.get("/api/file?name=SOUL.md").json()
    assert "content" in r and not r.get("error")


def test_persona_traegt_kommandeurs_prinzip():
    # Werkszustand statt persona_text(): die Live-Persona darf das Prinzip
    # umformulieren, ohne dass die Suite kippt (W0 — siehe Marker-Test oben).
    from core.config import MIND_DIR
    t = (MIND_DIR / "templates" / "PERSONA.md").read_text(encoding="utf-8")
    assert "Kommandeurin" in t and "schwarm" in t


def test_update_script_schuetzt_charakter_dateien():
    # W3: die Charakter-Dateien sind gitignored — git fasst sie beim Update NIE an.
    # Das Skript legt nur noch die getrackten Notiz-Anteile beiseite und erklaert warum.
    from pathlib import Path
    bat = Path("scripts/kira-update.bat").read_text(encoding="utf-8", errors="replace")
    assert "git stash push --quiet -- gedaechtnis playbooks" in bat
    assert "core/mind/SOUL.md" not in bat          # Alt-Verhalten (Stash der Seele) ist raus
    assert "gitignored" in bat                     # der Schutz-Grund steht im Skript


def test_onboarding_playbooks_parsen_und_router_zeigt_sie():
    """des Nutzers Onboarding-Wunsch: 'neues Projekt' und 'Hallo/Tagesstart' fuehren durch
    Playbooks. Frontmatter muss parsen, Router-Zeile (wann) vorhanden, Grad entwurf."""
    from core.mind import playbooks
    alle = {p["name"]: p for p in playbooks.list_playbooks()}
    for name in ("projekt-onboarding", "tages-einstieg"):
        assert name in alle, name
        assert alle[name]["reifegrad"] == "entwurf"
        assert alle[name]["wann"]
