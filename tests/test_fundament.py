"""Fundament-Paket: Stammbaum-Logbuch-Frage, Fakten-Treue-Brief, Checkliste, Vault-Dateien."""
from __future__ import annotations


# ---- Logbuch-Frage (standup) ----------------------------------------------------------

def _stammbaum(tmp_path, monkeypatch):
    from core.agency.missions import standup
    monkeypatch.setattr(standup, "ROOT", tmp_path)
    base = tmp_path / "gedaechtnis" / "stammbaum" / "leben"
    base.mkdir(parents=True)
    return base


def test_logbuch_frage_findet_luecke(tmp_path, monkeypatch):
    from core.agency.missions import standup
    base = _stammbaum(tmp_path, monkeypatch)
    (base / "daten.md").write_text("# Daten\n- geburtsdatum: ???\n- ort: Berlin\n", encoding="utf-8")

    q = standup._stammbaum_question("2026-07-04")
    assert "LOGBUCH-FRAGE" in q
    assert "geburtsdatum" in q
    assert "daten.md" in q
    assert "1 Luecken offen" in q


def test_logbuch_frage_rotiert_und_verstummt(tmp_path, monkeypatch):
    from core.agency.missions import standup
    base = _stammbaum(tmp_path, monkeypatch)
    (base / "daten.md").write_text("- a: ???\n- b: ???\n- c: ???\n", encoding="utf-8")

    fragen = {standup._stammbaum_question(f"2026-07-{t:02d}") for t in range(1, 15)}
    assert len(fragen) > 1  # Tages-Rotation trifft verschiedene Felder

    # alles gefuellt -> keine Frage mehr
    (base / "daten.md").write_text("- a: 1\n- b: 2\n- c: 3\n", encoding="utf-8")
    assert standup._stammbaum_question("2026-07-04") == ""


def test_logbuch_frage_ignoriert_vorlagen_und_raist_nie(tmp_path, monkeypatch):
    from core.agency.missions import standup
    base = _stammbaum(tmp_path, monkeypatch)
    (base / "_VORLAGE.md").write_text("- feld: ???\n", encoding="utf-8")
    assert standup._stammbaum_question("2026-07-04") == ""  # nur Vorlagen -> still
    # kein gedaechtnis-Ordner -> still, kein Crash
    monkeypatch.setattr(standup, "ROOT", tmp_path / "gibtsnicht")
    assert standup._stammbaum_question("2026-07-04") == ""


# ---- Fakten-Treue in der Delegation ----------------------------------------------------

def test_delegation_brief_traegt_berichtsformat(tmp_path, monkeypatch):
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    from core.agency import act as act_mod
    from core.agency.tools import delegate_tools as dt
    seen: dict = {}

    def fake_act(task, session_id=None, max_steps=None, escalate=False, task_type="reason", rolle=""):
        seen["task"] = task
        seen["rolle"] = rolle
        return {"text": "FAKT: x (Quelle y). VERMUTUNG: keine.", "steps": 1}

    monkeypatch.setattr(act_mod, "act", fake_act)
    dt.delegate("recherchiere Betrieb X", rang="arbeiter")
    assert "BERICHTSFORMAT" in seen["task"]
    assert "NIE erfinden" in seen["task"]
    assert seen["rolle"] == "arbeiter"      # P5: der Rang reicht sein Toolset an act durch


# ---- /api/checkliste + FILES -----------------------------------------------------------

def test_api_checkliste_und_files(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from core.kernel import events
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    from core.api import server

    client = TestClient(server.app)
    ck = client.get("/api/checkliste").json()
    assert set(ck) >= {"journal_heute", "stammbaum_luecken", "stammbaum_dateien", "handbuch"}
    assert ck["handbuch"] is True  # HANDBUCH.md existiert im Repo
    # Stammbaum-Zaehler sind INSTANZ-Werte (W3: Blaetter sind Privatsache, nicht im
    # Repo) — hier zaehlt nur, dass die Checkliste sie liefert, nicht wie viele es sind.
    assert isinstance(ck["stammbaum_dateien"], int) and isinstance(ck["stammbaum_luecken"], int)

    files = {f["name"] for f in client.get("/api/files").json()}
    from core import identity
    wurzel = f"{identity.user_name().upper()}.md"   # Werkszustand: PARTNER.md
    assert {"HANDBUCH.md", wurzel, "INDEX.md"} <= files
    hb = client.get("/api/file", params={"name": "HANDBUCH.md"}).json()
    assert "Gesetzbuch" in hb["content"] and hb["editable"] is True


# ---- Vault-Dateien + Playbooks ---------------------------------------------------------

def test_vault_und_playbooks_vorhanden():
    from core.config import ROOT
    for rel in ("gedaechtnis/LIES-MICH.md", "gedaechtnis/stammbaum/_WURZEL_VORLAGE.md",
                "gedaechtnis/stammbaum/leben/menschen/_VORLAGE.md",
                "gedaechtnis/stammbaum/business/_VORLAGE.md",
                "gedaechtnis/journal/LIES-MICH.md", "docs/HANDBUCH.md"):
        assert (ROOT / rel).exists(), rel

    from core.mind import playbooks as pb
    for name in ("tages-journal", "wochen-verdichtung", "monats-verdichtung", "logbuch-pflege"):
        p = ROOT / "playbooks" / f"{name}.md"
        assert p.exists(), name
        meta, _body = pb._parse_meta(p.read_text(encoding="utf-8"))
        assert meta["reifegrad"] == "entwurf", name
        assert meta["titel"], name

    # akquise-email traegt jetzt Fakten-Treue
    akq = (ROOT / "playbooks" / "akquise-email.md").read_text(encoding="utf-8")
    assert "Fakten-Treue" in akq and "NIE" in akq


def test_index_ist_tief_nummerierte_karte():
    """Schritt 3: INDEX.md ist die punktgenaue Karte (Malen nach Zahlen) und behaelt
    genau EINEN Auto-Block (der Regenerator darf den nummerierten Kopf nicht zerstoeren)."""
    from core.config import ROOT
    idx = (ROOT / "INDEX.md").read_text(encoding="utf-8")
    assert idx.count("<!-- AUTO:START -->") == 1 and idx.count("<!-- AUTO:END -->") == 1
    assert "Malen nach Zahlen" in idx
    for adr in ("**1a**", "**4c**", "**5.1a**", "**5.1d**", "**5.2a**"):
        assert adr in idx, adr
    assert "docs/CODING" in idx  # die Coding-Disziplin ist adressiert (4c)


def test_index_regenerierung_erhaelt_nummerierten_kopf(tmp_path, monkeypatch):
    """refresh_index() schreibt NUR den Auto-Block neu — der nummerierte Kopf bleibt."""
    from core.config import ROOT
    from core.mind import playbooks
    idx = tmp_path / "INDEX.md"
    idx.write_text((ROOT / "INDEX.md").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(playbooks, "INDEX_PATH", idx)
    playbooks.refresh_index()
    out = idx.read_text(encoding="utf-8")
    assert "Malen nach Zahlen" in out and "**5.1a**" in out  # Kopf ueberlebt
    assert out.count("<!-- AUTO:START -->") == 1


def test_identitaet_schlank_mit_platz_fuer_den_nutzer():
    """SOUL/GOAL/USER-TEMPLATES sind entschlackt (werden bei JEDEM Turn injiziert) und
    lassen dem Nutzer je einen eigenen, unangetasteten Platz. (W3: die gelebten .md
    sind Privatsache — geprueft wird das Template, gerendert mit den Werks-Namen.)"""
    from core import identity
    from core.config import MIND_DIR
    def t(name):
        return identity.render((MIND_DIR / "templates" / name).read_text(encoding="utf-8"))
    soul, goal, user = t("SOUL.md"), t("GOAL.md"), t("USER.md")
    # Owner-Platz in allen dreien (VON-<Nutzer>-Block mit ???-Zeilen)
    assert "VON Partner" in soul and "VON Partner" in user
    assert "VON Partner" in goal and "Meilenstein 1" in goal
    # schlank geblieben (Effizienz: injiziert pro Turn)
    assert len(soul) < 2300 and len(goal) < 2300
    # Kern-Substanz bleibt erhalten
    assert "Gegengewicht" in soul and "docs/CODING.md" in soul
    assert "Partner dienen" in goal and "Nordstern" in goal


def test_coding_disziplin_dokument():
    """Coding-Regeln sind fest dokumentiert (fuer Kira UND Nachfolger)."""
    from core.config import ROOT
    doc = (ROOT / "docs" / "CODING.md").read_text(encoding="utf-8")
    for marker in ("_is_code_step", "self_edit", "GLM", "py_compile", "Verfassung", "Not-Aus"):
        assert marker in doc, marker
    # SOUL-Template traegt die Disziplin als Selbstwissen + Verweis (W3: gelebte
    # SOUL.md ist Privatsache; das Uebergabe-Dossier KIRA-IST.md ebenso)
    soul = (ROOT / "core" / "mind" / "templates" / "SOUL.md").read_text(encoding="utf-8")
    assert "docs/CODING.md" in soul
