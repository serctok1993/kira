"""Freigabe-Runde (Audit-Funde 27.07.): eine Freigabe muss auch VOLLZOGEN werden.

Vier belegte Luecken im Weg nach draussen — genau der Pfad, den der geplante
Lead-Flow (400 Akquise-Mails) gehen soll:
S12  Freigabe-Art 'email' hatte KEINEN Ausfuehrungs-Zweig in decide(). Eine so
     freigegebene Akquise-Mail wurde nie gesendet (Live-Eintrag, Status approved).
     Der Trainings-Seed brachte dem Modell genau diese tote Art bei.
S13  hard_gate wurde als Top-Level-Merge geladen: data/autonomy.json vom 02.07.
     kannte kein 'publish' und ueberschrieb damit den erweiterten Default —
     needs_approval('publish') war False, waehrend das Post-Werkzeug dem Modell
     "wartet in der Freigabe-Inbox" versprach.
S14  bool({'email_sent': False, 'error': ...}) ist True — ein gescheiterter
     Versand stand im Ereignis als Erfolg, beide Oberflaechen lasen es nie.
S15  dream nahm LIMIT 4 in SQL und filterte Test-Sessions erst danach in Python:
     die Liste war immer leer (1 Lauf in 27 Tagen bei 408 rohen Episoden).
"""
from __future__ import annotations

import json

from core.agency import approvals


def _tmp_db(monkeypatch, tmp_path):
    from core.kernel import events

    monkeypatch.setattr(approvals, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(events, "DB_PATH", str(tmp_path / "state.db"))
    events.init_db()
    approvals.init_approvals()


# --- S12: 'email' ist kein totes Gleis mehr ------------------------------------------

def test_email_wird_zu_email_stranger_normalisiert(monkeypatch, tmp_path):
    _tmp_db(monkeypatch, tmp_path)
    aid = approvals.create("Absage-Mail", kind="email", detail=json.dumps(
        {"to": "kunde@example.com", "subject": "Absage", "body": "Leider nein."}))
    assert approvals.get(aid)["kind"] == "email_stranger", \
        "'email' muss auf die Art mit Vollzugs-Zweig zeigen"


def test_freigegebene_mail_wird_wirklich_gesendet(monkeypatch, tmp_path):
    _tmp_db(monkeypatch, tmp_path)
    gesendet = []
    import core.agency.connectors.mail as mail

    monkeypatch.setattr(mail, "send", lambda to, subj, body: gesendet.append((to, subj)) or "ok")
    aid = approvals.create("Akquise", kind="email", detail=json.dumps(
        {"to": "lead@example.com", "subject": "Hallo", "body": "Text"}))
    res = approvals.decide(aid, True)
    assert gesendet == [("lead@example.com", "Hallo")], "Freigabe war ein No-Op"
    assert res["vollzug"] == "sent"


def test_alt_eintrag_mit_kind_email_wird_auch_vollzogen(monkeypatch, tmp_path):
    """Bestandsschutz: in der Live-DB steht ein Eintrag noch mit der alten Art."""
    _tmp_db(monkeypatch, tmp_path)
    gesendet = []
    import core.agency.connectors.mail as mail

    monkeypatch.setattr(mail, "send", lambda to, subj, body: gesendet.append(to) or "ok")
    aid = approvals.create("Alt", kind="email_stranger", detail=json.dumps(
        {"to": "alt@example.com", "subject": "S", "body": "B"}))
    with approvals._conn() as c:            # Zustand von vor dem Fix nachstellen
        c.execute("UPDATE approvals SET kind='email' WHERE id=?", (aid,))
    approvals.decide(aid, True)
    assert gesendet == ["alt@example.com"]


# --- S14: ehrlicher Vollzugs-Status ---------------------------------------------------

def test_gescheiterter_versand_ist_kein_erfolg(monkeypatch, tmp_path):
    _tmp_db(monkeypatch, tmp_path)
    import core.agency.connectors.mail as mail

    def kaputt(*a, **k):
        raise RuntimeError("SMTP nicht erreichbar")

    monkeypatch.setattr(mail, "send", kaputt)
    aid = approvals.create("Mail", kind="email_stranger", detail=json.dumps(
        {"to": "x@example.com", "subject": "S", "body": "B"}))
    res = approvals.decide(aid, True)
    assert res["vollzug"] == "failed"
    assert res["applied"]["email_sent"] is False


def test_vollzug_unterscheidet_die_drei_faelle():
    assert approvals._vollzug({"email_sent": True, "result": "ok"}) == "sent"
    assert approvals._vollzug({"posted": True}) == "sent"
    assert approvals._vollzug({"email_sent": False, "error": "SMTP"}) == "failed"
    assert approvals._vollzug({"posted": False, "error": "429"}) == "failed"
    assert approvals._vollzug({"hint": "Kira muss es erneut anstossen"}) == "none"
    assert approvals._vollzug(None) == "none"
    assert approvals._vollzug({}) == "none"


def test_geld_freigabe_behauptet_keinen_vollzug(monkeypatch, tmp_path):
    _tmp_db(monkeypatch, tmp_path)
    aid = approvals.create("Rechnung zahlen", kind="money")
    res = approvals.decide(aid, True)
    assert res["vollzug"] == "none" and "hint" in res["applied"]


# --- S13: das publish-Gate lebt wieder ------------------------------------------------

def test_nutzer_gates_bleiben_auch_ohne_default_gates(monkeypatch, tmp_path):
    """Voll-Entfesselung 23.08.: der Default bringt KEINE Gates mehr mit — aber was der
    Besitzer selbst in data/autonomy.json eingetragen hat, gilt weiterhin exakt."""
    from core.governance import autonomy

    alt = tmp_path / "autonomy.json"
    alt.write_text(json.dumps({"chains_off": True,
                               "hard_gate": ["email_stranger"]}), encoding="utf-8")
    monkeypatch.setattr(autonomy, "_PATH", alt)
    assert autonomy.needs_approval("email_stranger"), "Nutzer-Eintrag muss bestehen bleiben"
    assert not autonomy.needs_approval("money"), "kein Default-Gate mehr"
    assert not autonomy.needs_approval("publish")


def test_bewusste_abwahl_bleibt_moeglich(monkeypatch, tmp_path):
    from core.governance import autonomy

    pfad = tmp_path / "autonomy.json"
    pfad.write_text(json.dumps({"chains_off": True, "hard_gate": ["money"]}), encoding="utf-8")
    monkeypatch.setattr(autonomy, "_PATH", pfad)
    autonomy.set_config(hard_gate=["money"])          # ausdrueckliche Abwahl
    assert not autonomy.needs_approval("publish")
    assert autonomy.needs_approval("money")


def test_ketten_an_verlangt_weiterhin_alles(monkeypatch, tmp_path):
    from core.governance import autonomy

    pfad = tmp_path / "autonomy.json"
    pfad.write_text(json.dumps({"chains_off": False}), encoding="utf-8")
    monkeypatch.setattr(autonomy, "_PATH", pfad)
    assert autonomy.needs_approval("generic")


# --- S15: dream sieht echte Sessions wieder -------------------------------------------

def test_dream_findet_echte_sessions_hinter_test_sessions(monkeypatch, tmp_path):
    """Der Live-Fall: die vier aeltesten reifen Sessions waren alle Bench-Sessions."""
    import time

    from core.mind import dream
    from core.mind.memory import store

    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "state.db"))
    store.init_memory()
    alt = time.time() - 90 * 3600
    with store._conn() as c:
        for i in range(6):                                    # 6 ephemere zuerst (aelter)
            c.execute("INSERT INTO memory (id, ts, role, text, kind, session_id) "
                      "VALUES (?,?,?,?,?,?)",
                      (f"e{i}", alt + i, "user", "test", "episodic", f"test-kat-lauf-{i}"))
        c.execute("INSERT INTO memory (id, ts, role, text, kind, session_id) VALUES (?,?,?,?,?,?)",
                  ("r1", alt + 50, "user", "echtes Gespraech", "episodic", "cockpit-echt-1"))

    reif = dream._reife_sessions(48 * 3600, 4)
    assert "cockpit-echt-1" in reif, "echte Session blieb hinter den Test-Sessions verborgen"
    assert not any(s.startswith("test-") for s in reif)


# --- Das Versprechen muss einloesbar sein (Live-Fall 05.07.) --------------------------
# Die Akquise-Mail an einen echten Empfaenger lag als MARKDOWN im detail-Feld. Sie wurde
# freigegeben — und ging nie raus, weil der Vollzug ein JSON-Payload braucht. Das
# Werkzeug versprach trotzdem "ich fuehre es aus, sobald du freigibst".

def test_mail_ohne_payload_wird_ehrlich_als_entwurf_gemeldet(monkeypatch, tmp_path):
    from core.agency.tools import builtin

    _tmp_db(monkeypatch, tmp_path)
    out = builtin.request_approval(
        "Akquise-Mail: Beispiel GmbH",
        detail="**Playbook-Durchlauf**\n\nGuten Tag, auf Ihrer Website ...",
        kind="email")
    assert "ENTWURF" in out and "NICHT selbst verschicken" in out
    assert "detail=" in out, "der Rueckweg zum echten Versand fehlt"


def test_mail_mit_payload_verspricht_vollzug(monkeypatch, tmp_path):
    from core.agency.tools import builtin

    _tmp_db(monkeypatch, tmp_path)
    out = builtin.request_approval(
        "Akquise-Mail: Beispiel GmbH",
        detail=json.dumps({"to": "info@example.com", "subject": "Hallo", "body": "Text"}),
        kind="email")
    assert "Zur Freigabe vorgelegt" in out and "ENTWURF" not in out


def test_normale_entwuerfe_bleiben_unveraendert(monkeypatch, tmp_path):
    """generic-Vorlagen sind Entwuerfe — da verspricht niemand automatischen Vollzug."""
    from core.agency.tools import builtin

    _tmp_db(monkeypatch, tmp_path)
    out = builtin.request_approval("Idee zur Website", detail="Freitext", kind="generic")
    assert "Zur Freigabe vorgelegt" in out


def test_werkzeug_nennt_keine_tote_freigabe_art():
    """Manifest-Vertrag: 'email' hat keinen Vollzugs-Zweig und darf nicht beworben werden."""
    from core.agency.tools import builtin  # noqa: F401
    from core.agency.tools import registry

    t = registry.get("request_approval")
    assert "email_stranger" in t.params["kind"]
    assert "| email |" not in t.params["kind"]
