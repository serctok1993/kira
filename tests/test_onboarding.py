"""W3 Onboarding: First-Run-Gate, Auto-Migration (Lockout-Schutz), /setup-Wizard,
Werkszustand-Scopes (identitaet / persoenliche-daten / alles).

Kern-Garantie: eine EINGERICHTETE Instanz (USER.md + gesetzter Nutzer-Name) sieht
den Wizard NIE — ein Pull darf niemanden aussperren.
"""
from __future__ import annotations

import copy
import json

import core.config as config
from core.kernel import onboarding


def _flag_umleiten(monkeypatch, tmp_path):
    """Onboarding-Flag in einen Wegwerf-Pfad umleiten (das Suite-Flag bleibt unberuehrt)."""
    f = tmp_path / "onboarded.flag"
    monkeypatch.setattr(onboarding, "flag_path", lambda: f)
    return f


def test_flag_logik(monkeypatch, tmp_path):
    f = _flag_umleiten(monkeypatch, tmp_path)
    assert not onboarding.is_onboarded()
    onboarding.complete("wizard")
    assert onboarding.is_onboarded()
    assert f.read_text(encoding="utf-8").startswith("wizard ")


def test_auto_migration_stempelt_bestandsinstanz(monkeypatch, tmp_path):
    # Lockout-Schutz: USER.md liegt + Nutzer-Name gesetzt -> still 'migrated', NIE Wizard
    f = _flag_umleiten(monkeypatch, tmp_path)
    mind = tmp_path / "mind"
    mind.mkdir()
    (mind / "USER.md").write_text("gelebte Instanz", encoding="utf-8")
    monkeypatch.setattr(config, "MIND_DIR", mind)
    monkeypatch.setitem(config.CONFIG, "identity", {"user": "Mia"})
    assert onboarding.auto_migrate() is True
    assert f.read_text(encoding="utf-8").startswith("migrated ")
    assert onboarding.auto_migrate() is False        # idempotent


def test_auto_migration_stempelt_frischen_klon_nicht(monkeypatch, tmp_path):
    _flag_umleiten(monkeypatch, tmp_path)
    mind = tmp_path / "mind-leer"
    mind.mkdir()
    monkeypatch.setattr(config, "MIND_DIR", mind)    # keine USER.md
    monkeypatch.setitem(config.CONFIG, "identity", {"user": ""})
    assert onboarding.auto_migrate() is False
    assert not onboarding.is_onboarded()


def test_gate_leitet_frischen_klon_um(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import core.api.server as s

    _flag_umleiten(monkeypatch, tmp_path)            # kein Flag -> Gate aktiv
    c = TestClient(s.app, follow_redirects=False)
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 302 and r.headers["location"] == "/setup"
    r = c.get("/api/status")
    assert r.status_code == 503 and r.json()["error"] == "setup_required"
    # Ausnahmen bleiben frei: /setup selbst, /health, /api/icon
    assert c.get("/setup").status_code == 200
    assert c.get("/health").status_code == 200
    assert c.get("/api/icon").status_code in (200, 404)


def test_gate_ist_no_op_wenn_eingerichtet():
    from fastapi.testclient import TestClient

    import core.api.server as s

    # Suite-Flag (conftest) vorhanden -> Cockpit laedt normal, kein Redirect
    r = TestClient(s.app, follow_redirects=False).get("/", headers={"accept": "text/html"})
    assert r.status_code == 200


def test_setup_wizard_personalisiert(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import core.api.server as s
    from core.mind import seed

    _flag_umleiten(monkeypatch, tmp_path)
    # Wegwerf-Welt: Mind-Templates + Stammbaum-Vorlage + ROOT (restart.flag)
    mind = tmp_path / "mind"
    (mind / "templates").mkdir(parents=True)
    (mind / "templates" / "SOUL.md").write_text(
        "# {{AGENT_NAME}}, Partnerin von {{USER_NAME}}", encoding="utf-8")
    monkeypatch.setattr(seed, "MIND_DIR", mind)
    (tmp_path / "gedaechtnis" / "stammbaum").mkdir(parents=True)
    (tmp_path / "gedaechtnis" / "stammbaum" / "_WURZEL_VORLAGE.md").write_text(
        "# {{USER_NAME}} — Wurzel", encoding="utf-8")
    monkeypatch.setattr(s, "ROOT", tmp_path)

    cfg_backup = copy.deepcopy(config.CONFIG)
    ov_file = config._OVERRIDE_FILE
    ov_backup = ov_file.read_text(encoding="utf-8") if ov_file.exists() else None
    try:
        r = TestClient(s.app).post("/api/setup", json={
            "agent": "Nova", "user": "Alex", "telegram_chat_id": "12345"})
        d = r.json()
        assert d.get("ok") is True, d
        # Namen sitzen live in CONFIG + persistiert in den Overrides
        assert config.CONFIG["identity"]["partner_name"] == "Nova"
        assert config.CONFIG["identity"]["user"] == "Alex"
        assert config.CONFIG["channels"]["telegram"]["allowed_chat_id"] == 12345
        ov = json.loads(ov_file.read_text(encoding="utf-8"))
        assert ov["identity.user"] == "Alex"
        # Mind gerendert, Wurzel angelegt, Flag + Bounce gesetzt
        assert (mind / "SOUL.md").read_text(encoding="utf-8") == "# Nova, Partnerin von Alex"
        assert (tmp_path / "gedaechtnis" / "stammbaum" / "ALEX.md").read_text(
            encoding="utf-8") == "# Alex — Wurzel"
        assert onboarding.is_onboarded()
        assert (tmp_path / "data" / "restart.flag").read_text(encoding="utf-8") == "bot,runner"
        # Zweiter Lauf prallt ab (Flag-Guard)
        r2 = TestClient(s.app).post("/api/setup", json={"agent": "X", "user": "Y"})
        assert r2.json().get("ok") is False
    finally:
        config.CONFIG.clear()
        config.CONFIG.update(cfg_backup)
        if ov_backup is None:
            ov_file.unlink(missing_ok=True)
        else:
            ov_file.write_text(ov_backup, encoding="utf-8")


def test_werkszustand_identitaet(monkeypatch, tmp_path):
    from core.kernel import factory
    from core.mind import seed

    flag = _flag_umleiten(monkeypatch, tmp_path)
    flag.write_text("test", encoding="utf-8")
    # Wegwerf-Welt: gelebte Mind-Dateien + Templates + Stammbaum mit Blatt + Vorlage
    mind = tmp_path / "mind"
    (mind / "templates").mkdir(parents=True)
    (mind / "templates" / "SOUL.md").write_text("# {{AGENT_NAME}} (neutral)", encoding="utf-8")
    (mind / "SOUL.md").write_text("# Persoenliche Seele von Mia", encoding="utf-8")
    monkeypatch.setattr(seed, "MIND_DIR", mind)
    baum = tmp_path / "stammbaum"
    (baum / "leben").mkdir(parents=True)
    (baum / "MIA.md").write_text("Wurzel", encoding="utf-8")
    (baum / "leben" / "_VORLAGE.md").write_text("Vorlage bleibt", encoding="utf-8")
    monkeypatch.setattr(factory, "_stammbaum_dir", lambda: baum)

    cfg_backup = copy.deepcopy(config.CONFIG)
    ov_file = config._OVERRIDE_FILE
    ov_backup = ov_file.read_text(encoding="utf-8") if ov_file.exists() else None
    ov_file.write_text(json.dumps({"identity.user": "Mia", "governance.trust_level": 3}),
                       encoding="utf-8")
    try:
        assert factory._cnt_identitaet() >= 3       # SOUL + Blatt + Override + Flag
        n = factory._clear_identitaet()
        assert n >= 4
        # Blatt weg (im Backup), Vorlage bleibt, Mind neutral neu, Flag weg
        assert not (baum / "MIA.md").exists()
        assert (baum / "leben" / "_VORLAGE.md").exists()
        assert "neutral" in (mind / "SOUL.md").read_text(encoding="utf-8")
        assert not flag.exists()
        ov = json.loads(ov_file.read_text(encoding="utf-8"))
        assert "identity.user" not in ov and ov["governance.trust_level"] == 3
        # Backup existiert und enthaelt die alte Seele + das Blatt
        backups = sorted((config.DATA_DIR / "backups").glob("werkszustand-*"))
        assert backups, "kein Werkszustand-Backup angelegt"
        assert (backups[-1] / "mind" / "SOUL.md").read_text(encoding="utf-8").startswith(
            "# Persoenliche Seele")
        assert (backups[-1] / "stammbaum" / "MIA.md").exists()
    finally:
        config.CONFIG.clear()
        config.CONFIG.update(cfg_backup)
        if ov_backup is None:
            ov_file.unlink(missing_ok=True)
        else:
            ov_file.write_text(ov_backup, encoding="utf-8")


def test_werkszustand_persoenliche_daten(tmp_path, monkeypatch):
    from core.kernel import factory

    d = tmp_path / "daten"
    d.mkdir()
    (d / "kalender.json").write_text("[]", encoding="utf-8")
    (d / "briefing_2026-07-01.txt").write_text("alt", encoding="utf-8")
    (d / "tuning").mkdir()
    (d / "tuning" / "episodes.jsonl").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(factory, "_data_dir", lambda: d)

    assert len(factory._persoenlich_vorhanden()) == 3
    n = factory._clear_persoenlich()
    assert n == 3
    assert not (d / "kalender.json").exists() and not (d / "tuning").exists()
    b = sorted((d / "backups").glob("werkszustand-*"))[-1] / "persoenlich"
    assert (b / "kalender.json").exists() and (b / "tuning" / "episodes.jsonl").exists()


def test_werkszustand_alles_expandiert(monkeypatch):
    from core.kernel import factory

    aufgerufen: list[str] = []
    defs = [{"key": k, "label": k, "desc": "", "standard": std,
             "count": lambda: 0, "clear": (lambda kk: (lambda: aufgerufen.append(kk) or 0))(k)}
            for k, std in (("chats", True), ("wissen", False),
                           ("identitaet", False), ("persoenliche-daten", False))]
    monkeypatch.setattr(factory, "_cat_defs", lambda: defs)
    out = factory.reset(["alles"], confirm="WERKSZUSTAND")
    assert out["ok"] is True
    # Meta-Scope: Standard (chats) + identitaet + persoenliche-daten — wissen bleibt aussen vor
    assert set(aufgerufen) == {"chats", "identitaet", "persoenliche-daten"}
