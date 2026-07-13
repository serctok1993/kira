"""des Nutzers Feedback 09.07.: Gedaechtnis-Diaet ('okay, super.' war ein Dauer-Fakt),
Lektionen in Klartext, Zentrale ohne Scrollfenster/tote Luecke, ehrlicher
Quellen-Knopf und web_search als Provider-Kette (Brave-Quota-Fix)."""
from __future__ import annotations

import inspect

from fastapi.testclient import TestClient

import core.api.server as s
from core.agency.tools import builtin
from core.api.ui.css import HEAD_AND_CSS as CSS
from core.api.ui.script import SCRIPT
from core.api.ui.views import VIEWS
from core.mind.memory import store


# ---------- Gedaechtnis-Diaet ----------

def test_zu_banal_erkennt_smalltalk():
    for t in ("okay, super.", "ok", "Danke!", "super nice 👍", "ja klar, passt gut",
              "alles klar, läuft", "  "):
        assert builtin._zu_banal(t) is True, f"sollte banal sein: {t!r}"
    for t in ("Mia mag dunkles UI-Design ohne Scrollbalken",
              "Geburtstag Mama: 14.03.1968", "Stammkunde zahlt monatlich 30 Euro"):
        assert builtin._zu_banal(t) is False, f"ist ein echter Fakt: {t!r}"


def test_remember_fact_wehrt_smalltalk_ab(monkeypatch):
    saved = []
    monkeypatch.setattr(store, "init_memory", lambda: None)
    monkeypatch.setattr(store, "find_duplicate", lambda text, kind="fact": None)
    monkeypatch.setattr(store, "remember", lambda *a, **k: saved.append(a[0]))
    out = builtin.remember_fact("okay, super.")
    assert "NICHT gespeichert" in out and saved == []          # Smalltalk kommt nicht rein
    out = builtin.remember_fact("Mia will Berichte immer mit Quellenliste am Ende")
    assert out.startswith("Dauerhaft gemerkt") and len(saved) == 1


def test_remember_fact_dedupe(monkeypatch):
    saved = []
    monkeypatch.setattr(store, "init_memory", lambda: None)
    monkeypatch.setattr(store, "find_duplicate", lambda text, kind="fact": "vorhandene-id")
    monkeypatch.setattr(store, "remember", lambda *a, **k: saved.append(a[0]))
    out = builtin.remember_fact("Mia arbeitet abends am liebsten mit Musik")
    assert "Schon im Gedaechtnis" in out and saved == []        # kein Duplikat-Stapel


def test_find_duplicate_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "mem.db"))
    store.init_memory()
    store.remember("Mia trinkt Kaffee schwarz", role="self", kind="fact")
    assert store.find_duplicate("  mia   trinkt kaffee SCHWARZ ") is not None
    assert store.find_duplicate("Mia trinkt Tee") is None


def test_gedaechtnis_ui_default_wichtig():
    # Standard-Filter zeigt nur bewusst Gemerktes; der rohe Chat-Verlauf ist seit der
    # Feedback-Runde 13.07. GANZ raus aus dem Tab (Verlauf lebt im Chat selbst)
    assert '<a data-mf="wichtig" class="on">' in VIEWS
    assert 'data-mf="episodic"' not in VIEWS and 'data-mf="all"' in VIEWS
    assert 'let memFilter="wichtig"' in SCRIPT
    assert 'MEM_WICHTIG=["fact","lesson","skill","semantic"]' in SCRIPT
    assert 'if(memFilter==="wichtig"){if(!MEM_WICHTIG.includes(m.kind||""))return false;}' in SCRIPT


# ---------- Lektionen in Klartext ----------

def test_reflexion_verlangt_klartext_lektionen():
    from core.mind import reflection
    src = inspect.getsource(reflection)
    assert src.count("vollstaendiger Satz Klartext") == 2      # beide Prompts (reflect + reflect_on)
    assert "ohne Kontext" in src and "Keine Stichworte" in src


# ---------- Zentrale-Politur ----------

def test_dir_row_fuellt_die_luecke():
    home = VIEWS.split('id="v-home"', 1)[1].split('id="v-chat"', 1)[0]
    # Befehl + Widget-Slot teilen sich eine Reihe, VOR dem cmd-grid
    assert home.index('class="dir-row"') < home.index('class="direktive"')
    assert home.index('class="direktive"') < home.index('id="widgets-home"') < home.index('class="cmd-grid"')
    # der Slot haengt nicht mehr in der Seitenspalte
    side = home.split('class="cmd-side"', 1)[1]
    assert 'id="widgets-home"' not in side
    assert ".dir-row{display:flex" in CSS


def test_digest_und_lektionen_einzeilig():
    assert ".clamp1{white-space:nowrap" in CSS
    assert SCRIPT.count('class="clamp1"') >= 2                 # Digest-Aufgaben + Zuletzt gelernt
    assert "Hier das Ergebnis" in SCRIPT                       # Floskel-Filter vorhanden


def test_hud_neue_zellen():
    assert 'cell("Freigaben"' in SCRIPT and 'id="hud-frei"' in SCRIPT
    assert 'cell("Naechste Routine"' in SCRIPT
    assert 'subnav("me","freigaben")' in SCRIPT                # Klick springt zur Inbox


def test_news_seed_fragt_erst():
    fn = SCRIPT.split("function bindNewsSeed()", 1)[1].split("function bindOpsFilter", 1)[0]
    assert "confirm(" in fn and "Standard-Quellen" in fn       # nichts wird still hinzugefuegt


# ---------- web_search Provider-Kette ----------

class _R:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_web_search_faellt_von_brave_auf_tavily(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "bravekey123")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc")
    monkeypatch.delenv("GOOGLE_CSE_KEY", raising=False)
    monkeypatch.delenv("SEARXNG_URL", raising=False)

    def fake_get(url, **kw):
        assert "brave" in url
        return _R(429)                                          # Quota aufgebraucht

    def fake_post(url, **kw):
        assert "tavily" in url
        return _R(200, {"results": [{"title": "Treffer A", "url": "https://a.de",
                                     "content": "Snippet A"}]})

    monkeypatch.setattr(builtin.httpx, "get", fake_get)
    monkeypatch.setattr(builtin.httpx, "post", fake_post)
    out = builtin.web_search("test anfrage")
    assert "Treffer A" in out and "https://a.de" in out         # Kette lief weiter statt Abbruch


def test_web_search_ddg_blockiert_nennt_gratis_alternativen(monkeypatch):
    for k in ("BRAVE_API_KEY", "TAVILY_API_KEY", "GOOGLE_CSE_KEY", "GOOGLE_CSE_ID", "SEARXNG_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(builtin.httpx, "post", lambda url, **kw: _R(202, text="anomaly"))
    out = builtin.web_search("irgendwas")
    assert "TAVILY_API_KEY" in out and "GOOGLE_CSE_KEY" in out  # klare, kostenlose Abhilfe


def test_secrets_schlagen_neue_keys_vor():
    r = TestClient(s.app).get("/api/secrets").json()
    for k in ("TAVILY_API_KEY", "GOOGLE_CSE_KEY", "GOOGLE_CSE_ID", "SEARXNG_URL"):
        assert k in r["suggested"]
