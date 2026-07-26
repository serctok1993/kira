"""P5 (Rolle=Toolset=Modell): die Pyramiden-Etagen als abfragbare Datenstruktur.

Werkstatt-Vertrag: pro Rang (reflex/arbeiter/denker/richter) sind Toolset,
Routing und Manifest aus rollen.py / GET /api/rollen abfragbar; der Prompt eines
Unteragenten nennt NUR die eigenen Werkzeuge; delegate eskaliert bei hartem
Fehlschlag GENAU EINMAL eine Etage hoeher. Offline, ohne LLM.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from core.agency import rollen
from core.agency.tools import builtin, todo_tools  # noqa: F401 -> registriert
from core.agency.tools import registry


def test_jedes_rollen_tool_existiert_wirklich():
    # Wache gegen Tippfehler/Leichen: jede Namensliste zeigt auf echte Registry-Eintraege
    alle = {t.name for t in registry.all_tools(include_disabled=True)}
    for rang, d in rollen.ROLLEN.items():
        fehlt = set(d["tools"]) - alle
        assert not fehlt, f"Rolle {rang} nennt unbekannte Werkzeuge: {fehlt}"
        assert len(d["tools"]) == len(set(d["tools"])), f"Rolle {rang} hat Doppler"


def test_etagen_schnitt_und_schreibschutz():
    assert rollen.toolset("reflex") < rollen.toolset("arbeiter") < rollen.toolset("denker")
    # UNTERAGENTEN fassen Kiras Stores und die Aussenwirkung nicht an ("haupt" ist
    # bewusst KEIN Unteragent — Kiras eigener Chat-Hut darf delegieren/mailen/merken)
    verboten = {"delegate", "schwarm", "restart_self", "email_send", "bluesky_post",
                "todo_plan", "todo_update", "remember_fact", "request_secret", "switch_model"}
    for rang in ("reflex", "arbeiter", "denker", "richter"):
        schnitt = verboten & rollen.toolset(rang)
        assert not schnitt, f"Rolle {rang} traegt verbotene Werkzeuge: {schnitt}"
    assert "self_edit" not in rollen.toolset("reflex") | rollen.toolset("arbeiter")


def test_hauptrolle_fuer_den_lokalen_chat():
    # "haupt" = kuratiertes Alltags-Manifest fuer Kiras lokalen Chat (c5-Hebel):
    # klein genug fuer kleine Modelle, traegt aber Delegation + Aussenwirkung.
    ts = rollen.toolset("haupt")
    assert 20 <= len(ts) <= 48
    for muss in ("web_search", "erinnerung", "cron_add", "todo_stand", "todo_list",
                 "delegate", "schwarm", "email_send", "remember_fact", "request_approval",
                 "watch_add", "watch_list", "screenshot_url", "read_logs"):   # c5b-Befund (1)
        assert muss in ts, f"haupt braucht {muss}"
    # Datei-Familie KOMPLETT (Live-Fund 22.07.): make_dir fehlte -> "erstell einen Ordner"
    # wurde per write_file eine DATEI. Wer schreiben darf, muss auch anlegen, finden,
    # umbenennen und wegraeumen koennen.
    for muss in ("read_file", "list_dir", "write_file", "make_dir", "datei_finden",
                 "move_file", "delete_file"):
        assert muss in ts, f"haupt braucht {muss} (Datei-Familie bleibt vollstaendig)"
    # code_suche bewusst NICHT: die Coding-Familie bleibt KOMPLETT im code:-Modus —
    # halbe Werkzeug-Familien verwirren kleine Modelle (todo_list-Lehre).
    for nie in ("restart_self", "request_secret", "run_command", "edit_datei",
                "self_edit", "db_query", "code_suche"):
        assert nie not in ts, f"{nie} gehoert nicht in den Plain-Chat (Coding/System via code:)"
    # kein delegierbarer Rang, keine Eskalationsstufe, aber voll in der Uebersicht
    from core.agency.tools import delegate_tools as dt
    assert "haupt" not in dt._RANG
    assert rollen.eskalation("haupt") is None
    assert rollen.ROLLEN["haupt"].get("unteragent") is False
    assert rollen.uebersicht()["haupt"]["schritte"] is None
    # der Richter urteilt READONLY (+ Tests via run_command), er schreibt keine Dateien
    for schreib in ("write_file", "edit_datei", "make_dir", "knowledge_note"):
        assert schreib not in rollen.toolset("richter")
    assert "run_command" in rollen.toolset("richter")
    assert rollen.toolset("kira-selbst-unbekannt") is None      # kein Filter = volle Flotte


def test_manifest_und_schemas_pro_etage():
    m = rollen.manifest("reflex")
    assert "- read_file (" in m and "- web_search (" in m
    assert "- edit_datei (" not in m and "- delegate (" not in m
    namen = {s["function"]["name"] for s in rollen.schemas("richter")}
    assert namen == rollen.toolset("richter")
    # ohne Filter bleibt die Vollflotte BYTE-identisch (kein Drift im Kira-Prompt)
    assert registry.manifest() == registry.manifest(nur=None)


def test_act_gate_verweigert_fremde_werkzeuge_lehrend():
    out = rollen.verweigert("edit_datei", "reflex")
    assert "gehoert nicht zu deinem Rang 'reflex'" in out
    assert "read_file" in out and "edit_datei" not in out.split("Deine Werkzeuge:")[1].split(".")[0]


def test_delegate_eskaliert_genau_einmal(monkeypatch):
    from core.agency.tools import delegate_tools as dt

    laeufe: list[str] = []

    def fake_run(auftrag, rang, session_id, schritte=""):
        laeufe.append(rang)
        return {"sid": f"sub-x-{len(laeufe)}", "rang": rang,
                "text": "kaputt" if rang == "arbeiter" else "Ergebnis", "ok": rang != "arbeiter"}

    monkeypatch.setattr(dt, "_run_agent", fake_run)
    monkeypatch.setattr(dt.events, "emit", lambda *a, **k: None)
    out = dt._delegiere("Probe", "arbeiter", None)
    assert laeufe == ["arbeiter", "denker"]                     # genau EIN Retry, eine Etage hoeher
    assert "eskaliert von arbeiter" in out and "Ergebnis" in out
    # der Richter hat keine Etage mehr ueber sich
    laeufe.clear()
    monkeypatch.setattr(dt, "_run_agent",
                        lambda a, r, s, sc="": (laeufe.append(r) or
                                                {"sid": "s", "rang": r, "text": "kaputt", "ok": False}))
    dt._delegiere("Probe", "richter", None)
    assert laeufe == ["richter"]


def test_api_rollen_traegt_die_etagen():
    import core.api.server as s

    r = TestClient(s.app).get("/api/rollen").json()["rollen"]
    assert set(r) == {"reflex", "arbeiter", "denker", "richter", "haupt"}
    for rang, d in r.items():
        assert d["tools"] and d["manifest"] and d["schemas"]
        assert {s2["function"]["name"] for s2 in d["schemas"]} == set(d["tools"])
    assert r["richter"]["escalate"] is True and r["richter"]["eskalation"] is None
    assert r["reflex"]["eskalation"] == "arbeiter"
