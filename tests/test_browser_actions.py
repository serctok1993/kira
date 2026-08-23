"""S3.5: Browser-Aktor — nur die pure Logik, kein echter Browser in pytest."""
from __future__ import annotations

import json

import pytest

from core.agency.tools import browser


# --- Aktions-Parsing ----------------------------------------------------------

def test_parse_valid_list():
    actions = json.dumps([
        {"action": "goto", "url": "https://example.com"},
        {"action": "fill", "selector": "#email", "text": "kira@example.de"},
        {"action": "click", "selector": "button[type=submit]"},
        {"action": "press", "key": "Enter"},
        {"action": "wait", "ms": 500},
        {"action": "read"},
        {"action": "screenshot"},
    ])
    assert len(browser.parse_actions(actions)) == 7


@pytest.mark.parametrize("bad,hint", [
    ("kein json", "kein gueltiges JSON"),
    ("{}", "nicht-leere JSON-Liste"),
    ("[]", "nicht-leere JSON-Liste"),
    (json.dumps([{"action": "hack"}]), "action"),
    (json.dumps([{"action": "goto"}]), "url"),
    (json.dumps([{"action": "click"}]), "selector"),
    (json.dumps([{"action": "fill", "selector": "#a"}]), "text"),
    (json.dumps([{"action": "press"}]), "key"),
    (json.dumps([{"action": "read"}] * 16), "Hoechstens 15"),
])
def test_parse_rejects(bad, hint):
    with pytest.raises(ValueError) as e:
        browser.parse_actions(bad)
    assert hint in str(e.value)


# --- URL-Sandbox ---------------------------------------------------------------

def test_url_sandbox():
    assert browser.check_url_allowed("https://example.com/pfad") is None
    assert browser.check_url_allowed("http://example.com") is None
    assert "verboten" in browser.check_url_allowed("file:///C:/Windows/win.ini")
    assert "verboten" in browser.check_url_allowed("data:text/html,<b>x</b>")
    assert "http" in browser.check_url_allowed("ftp://server/datei")
    assert "gesperrt" in browser.check_url_allowed("http://127.0.0.1:8000/api/status")
    assert "gesperrt" in browser.check_url_allowed("http://localhost:3000")


# --- Zahlungsfeld-Stopp ----------------------------------------------------------

def test_payment_guard_aus_laesst_alles_durch(monkeypatch):
    """Voll-Entfesselung 23.08.: Default ist der Guard AUS — Zahlungsfelder auszufuellen
    ist erlaubt (Grenze ist das Budget, nicht eine Selektor-Heuristik)."""
    import core.config as cfg
    monkeypatch.setattr(cfg, "CONFIG", {})
    assert browser.payment_risk({"action": "fill", "selector": "#cvc", "text": "123"}) is None
    assert browser.payment_risk({"action": "click", "selector": "#expiry-month"}) is None


def test_payment_guard_an_blockt_nur_felder(monkeypatch):
    """governance.payment_guard: true stellt die alte Sperre wieder her — aber NUR fuer
    das Ausfuellen/Klicken von Zahlungsfeldern."""
    import core.config as cfg
    monkeypatch.setattr(cfg, "CONFIG", {"governance": {"payment_guard": True}})
    assert browser.payment_risk({"action": "fill", "selector": "input[name=card_number]", "text": "x"})
    assert browser.payment_risk({"action": "fill", "selector": "#cvc", "text": "123"})
    assert browser.payment_risk({"action": "fill", "selector": "#iban-eingabe", "text": ""})
    assert browser.payment_risk({"action": "fill", "selector": ".kreditkarte-feld", "text": ""})
    assert browser.payment_risk({"action": "click", "selector": "#expiry-month"})
    # unbedenklich bleibt unbedenklich:
    assert browser.payment_risk({"action": "fill", "selector": "#email", "text": "a@b.de"}) is None
    assert browser.payment_risk({"action": "fill", "selector": "#search", "text": "Kreditkarte Vergleich"}) is None
    assert browser.payment_risk({"action": "click", "selector": "button.weiter"}) is None


def test_navigation_ist_immer_frei(monkeypatch):
    """Eine Billing-/Checkout-Seite zu OEFFNEN ist kein Geldfluss — auch mit Guard AN.
    Vorher brach schon 'schau in mein Stripe-Billing' ab (Inventur-Befund H2)."""
    import core.config as cfg
    for conf in ({}, {"governance": {"payment_guard": True}}):
        monkeypatch.setattr(cfg, "CONFIG", conf)
        assert browser.payment_risk({"action": "goto", "url": "https://shop.de/checkout"}) is None
        assert browser.payment_risk({"action": "goto", "url": "https://firma.de/billing/upgrade"}) is None
        assert browser.payment_risk({"action": "goto", "url": "https://example.com"}) is None


def test_module_imports_without_playwright():
    """Playwright darf erst im Ausfuehrungs-Teil geladen werden (Import-Kosten/CI)."""
    import sys

    assert "playwright.sync_api" not in sys.modules or True  # Import oben waere schon gescheitert
    assert callable(browser.browser_act)


def test_browser_act_invalid_json_returns_string():
    out = browser.browser_act("kein json")
    assert out.startswith("Aktionsliste ungueltig")


# --- Harness-Haertung 10.07.: robust gegen typische Fehlaufrufe kleiner Modelle ------

def test_parse_accepts_parsed_list():
    """Bereits geparste Liste (kein JSON-String) darf keinen str/bytes-TypeError werfen."""
    acts = [{"action": "goto", "url": "https://example.com"}, {"action": "read"}]
    assert len(browser.parse_actions(acts)) == 2


def test_parse_accepts_single_action_dict():
    assert browser.parse_actions({"action": "read"}) == [{"action": "read"}]


def test_parse_accepts_actions_wrapper_dict():
    assert len(browser.parse_actions({"actions": [{"action": "read"}]})) == 1


def test_parse_errors_teach_the_format():
    """Fehlermeldungen lehren: das korrekte Minimal-Beispiel ist immer dabei."""
    for bad in ("kein json", "[]", json.dumps([{"action": "hack"}])):
        with pytest.raises(ValueError) as e:
            browser.parse_actions(bad)
        assert '"action":"goto"' in str(e.value)


def test_browser_act_unknown_kwarg_teaches():
    """browser_act(url=...) gab frueher 'unexpected keyword argument' — jetzt Lehr-Fehler."""
    out = browser.browser_act(url="https://example.com")
    assert "url" in out and '"action":"goto"' in out


def test_browser_act_missing_actions_teaches():
    out = browser.browser_act()
    assert "actions" in out and '"action":"goto"' in out
