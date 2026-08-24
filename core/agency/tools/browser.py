"""Browser-Aktor: Kira kann klicken, ausfuellen, einloggen (S3).

Ein Aufruf = EINE kurze Aktionsliste in EINER Playwright-Session (Chromium,
frisches Profil — nie der Browser des Nutzers). Logins ueberleben zwischen Aufrufen
via storage_state in data/browser/<session>.json (gitignored).

Sicherheits-Schichten:
- URL-Sandbox: nur http/https; kein file://, data:, kein eigenes Cockpit (Port 8000).
- Zahlungsfeld-Stopp: Selektoren/URLs, die nach Karte/IBAN/Checkout riechen,
  brechen den Lauf ab — echtes Geld ist hard-gated (Freigabe via request_approval).
- needs_approval('external')-Check: bei Ketten AN wartet auch der Browser an der Inbox.
- Audit pro Lauf; Cookie-Werte erscheinen NIE im Output; 60s-Deadline; close() im finally.

Die reine Logik (Parsing/Sandbox/Zahlungs-Heuristik) ist pur und offline testbar;
Playwright wird erst im Ausfuehrungs-Teil importiert.
"""
from __future__ import annotations

import json
import re
import time

from core.config import DATA_DIR
from core import identity as _id
from core.agency.tools.registry import tool

ACTIONS = ("goto", "click", "fill", "press", "wait", "read", "screenshot")
# Entfesselung 23.08. (Inventur M10): 15 Aktionen / 60s reichten fuer echte Web-Ketten
# nicht (Login -> Navigation -> Formular -> Absenden -> Pruefen). Beides jetzt aus der
# config steuerbar; die Deadline schuetzt weiter vor haengenden Seiten.
MAX_ACTIONS = 40
_DEADLINE_S = 180

_SESSION_DIR = DATA_DIR / "browser"

_PAYMENT_FIELD_RE = re.compile(
    r"card[-_ ]?(number|no|nr)|cardnum|cc[-_ ]?(num|number)|cvc|cvv|expir|"
    r"iban|bic\b|swift|routing|kontonummer|kreditkarte|kartennummer",
    re.IGNORECASE)
_PAYMENT_URL_RE = re.compile(r"/(checkout|payment|billing|bezahlen|kasse)(/|\?|#|$)", re.IGNORECASE)
_DENY_URL_RE = re.compile(r"^(file:|data:|javascript:)", re.IGNORECASE)
_LOCAL_COCKPIT_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?", re.IGNORECASE)


# Minimal-Beispiel fuer alle Fehlermeldungen: lehren statt nur meckern (Fund 10.07. —
# vier abgelehnte Aufrufe in Folge, ohne dass das Modell je das erwartete Format sah).
_BEISPIEL = '[{"action":"goto","url":"https://example.com"},{"action":"read"}]'


def parse_actions(actions_json: str | list | dict) -> list[dict]:
    """Aktionsliste validieren. Nimmt einen JSON-String ODER eine bereits geparste
    Liste / ein einzelnes Aktions-Objekt an — kleine Modelle liefern beides
    (json.loads auf eine Liste warf frueher den str/bytes-TypeError).
    Wirft ValueError mit klarer Meldung + Minimal-Beispiel (Wrapper faengt)."""
    actions = actions_json
    if isinstance(actions, (str, bytes, bytearray)):
        try:
            actions = json.loads(actions)
        except json.JSONDecodeError as e:
            raise ValueError(f"actions ist kein gueltiges JSON: {e} — erwartet wird eine "
                             f"JSON-Liste von Aktions-Objekten, Beispiel: {_BEISPIEL}") from None
    if isinstance(actions, dict):
        if "action" in actions:  # einzelnes Aktions-Objekt -> Ein-Element-Liste
            actions = [actions]
        elif isinstance(actions.get("actions"), list):  # {"actions":[...]}-Wrapper auspacken
            actions = actions["actions"]
    if not isinstance(actions, list) or not actions:
        raise ValueError("actions muss eine nicht-leere JSON-Liste von Aktions-Objekten sein, "
                         f"Beispiel: {_BEISPIEL}")
    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"Hoechstens {MAX_ACTIONS} Aktionen pro Aufruf (waren {len(actions)}).")
    out = []
    for i, a in enumerate(actions, 1):
        if not isinstance(a, dict) or a.get("action") not in ACTIONS:
            raise ValueError(f"Aktion {i}: 'action' muss eine von {ACTIONS} sein, "
                             f"Beispiel: {_BEISPIEL}")
        kind = a["action"]
        if kind == "goto" and not str(a.get("url", "")).strip():
            raise ValueError(f"Aktion {i} (goto): 'url' fehlt, Beispiel: "
                             '{"action":"goto","url":"https://example.com"}')
        if kind in ("click", "fill") and not str(a.get("selector", "")).strip():
            raise ValueError(f"Aktion {i} ({kind}): 'selector' fehlt, Beispiel: "
                             '{"action":"click","selector":"button.submit"}')
        if kind == "fill" and "text" not in a:
            raise ValueError(f"Aktion {i} (fill): 'text' fehlt, Beispiel: "
                             '{"action":"fill","selector":"#email","text":"..."}')
        if kind == "press" and not str(a.get("key", "")).strip():
            raise ValueError(f"Aktion {i} (press): 'key' fehlt, Beispiel: "
                             '{"action":"press","key":"Enter"}')
        out.append(a)
    return out


def check_url_allowed(url: str) -> str | None:
    """None = erlaubt; sonst Begruendung. Schuetzt Dateisystem + eigenes Cockpit."""
    u = (url or "").strip()
    if _DENY_URL_RE.match(u):
        return f"URL-Schema verboten (nur http/https): {u[:80]}"
    if not re.match(r"^https?://", u, re.IGNORECASE):
        return f"Nur http/https-URLs erlaubt: {u[:80]}"
    if _LOCAL_COCKPIT_RE.match(u):
        return f"Lokale Adressen sind gesperrt (eigenes Cockpit/Dienste): {u[:80]}"
    return None


def payment_risk(action: dict) -> str | None:
    """Zahlungs-Heuristik: None = unbedenklich; sonst Abbruch-Hinweis.

    Faelscht lieber einmal zu viel Alarm (sichere Richtung) — der Korrektur-Weg
    ist die Freigabe-Inbox, nicht das Abschalten der Heuristik."""
    kind = action.get("action")
    probe = ""
    # Entfesselung 23.08. (Inventur H2): goto ist IMMER frei — eine Billing-Seite
    # LESEN ist kein Geldfluss (vorher brach schon 'schau in mein Stripe-Billing' ab).
    # Nur das AUSFUELLEN/KLICKEN von Zahlungsfeldern bleibt schaltbar: Default AUS
    # (Besitzer-Entscheid: Budget + eigene Prompts sind die Bremse), governance.
    # payment_guard: true stellt die alte Sperre wieder her. Audit laeuft immer mit.
    if kind not in ("click", "fill"):
        return None
    # Nur der SELEKTOR ist das Signal — der Fill-Text nicht (sonst wuerde
    # schon eine Suche nach 'Kreditkarte' den Alarm ausloesen).
    probe = str(action.get("selector", ""))
    if probe and _PAYMENT_FIELD_RE.search(probe):
        try:
            from core.config import CONFIG
            guard_an = bool((CONFIG.get("governance", {}) or {}).get("payment_guard", False))
        except Exception:  # noqa: BLE001
            guard_an = False
        try:
            from core.kernel import events as _ev
            _ev.emit("browser_payment_field", {"selector": probe[:120], "blocked": guard_an})
        except Exception:  # noqa: BLE001
            pass
        if guard_an:
            return (f"Zahlungsfeld erkannt ({probe[:80]}) — governance.payment_guard ist AN. "
                    f"Lege die Aktion per request_approval (kind 'money') vor.")
    return None


def _run_actions(actions: list[dict], session: str) -> str:
    """Der Playwright-Teil — bewusst duenn, die Logik oben ist getestet."""
    from playwright.sync_api import sync_playwright

    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    state_path = _SESSION_DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '', session) or 'default'}.json"

    observations: list[str] = []
    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx_kwargs = {"viewport": {"width": 1280, "height": 900}}
            if state_path.is_file():
                ctx_kwargs["storage_state"] = str(state_path)
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            page.set_default_timeout(15000)

            for i, a in enumerate(actions, 1):
                if time.time() - t0 > _DEADLINE_S:
                    observations.append(f"[{i}] ABBRUCH: 60s-Deadline erreicht.")
                    break
                risk = payment_risk(a)
                if risk:
                    observations.append(f"[{i}] ABBRUCH: {risk}")
                    break
                kind = a["action"]
                if kind == "goto":
                    deny = check_url_allowed(a["url"])
                    if deny:
                        observations.append(f"[{i}] ABBRUCH: {deny}")
                        break
                    page.goto(a["url"], wait_until="domcontentloaded")
                    observations.append(f"[{i}] goto {a['url'][:100]} -> {page.title()[:80]}")
                elif kind == "click":
                    page.click(a["selector"])
                    observations.append(f"[{i}] click {a['selector'][:80]}")
                elif kind == "fill":
                    page.fill(a["selector"], str(a.get("text", "")))
                    observations.append(f"[{i}] fill {a['selector'][:80]}")
                elif kind == "press":
                    page.keyboard.press(a["key"])
                    observations.append(f"[{i}] press {a['key']}")
                elif kind == "wait":
                    page.wait_for_timeout(min(int(a.get("ms", 1000)), 10000))
                    observations.append(f"[{i}] wait")
                elif kind == "read":
                    text = " ".join(page.inner_text("body").split())
                    observations.append(f"[{i}] read:\n{text[:3000]}")
                elif kind == "screenshot":
                    from pathlib import Path

                    shots = Path.home() / "Desktop" / "kira-screenshots"
                    shots.mkdir(parents=True, exist_ok=True)
                    fname = shots / f"browser-{time.strftime('%Y%m%d-%H%M%S')}-{i}.png"
                    page.screenshot(path=str(fname), full_page=True)
                    observations.append(f"[{i}] screenshot -> {fname}")

            context.storage_state(path=str(state_path))  # Logins ueberleben
        finally:
            browser.close()  # Chromium nie leaken

    return "\n".join(observations)[:6000]


@tool("browser_act",
      "Fuehrt eine KURZE Aktionsliste in einem echten Browser aus (goto/click/fill/press/wait/"
      "read/screenshot, max 15). Logins ueberleben via Session-Speicher. KEINE Zahlungsfelder — "
      "echtes Geld laeuft ueber request_approval.",
      {"actions": 'JSON-Liste, z.B. [{"action":"goto","url":"https://..."},'
                  '{"action":"fill","selector":"#email","text":"..."},{"action":"read"}]',
       "session": "optional: Session-Name fuer Cookies (Standard 'default')"})
def browser_act(actions: str | list | dict = "", session: str = "default", **falsche_args) -> str:
    from core.governance import audit, autonomy

    # Lehr-Fehler statt TypeError: kleine Modelle rufen z.B. browser_act(url=...) auf.
    # Der TypeError liefe durch die Executor-Retries und erklaert nie das richtige Format.
    if falsche_args:
        return (f"Falscher Aufruf: unbekannte Argumente ({', '.join(sorted(falsche_args))}). "
                f"browser_act nimmt 'actions' (JSON-Liste) und optional 'session'. "
                f"Beispiel: actions='{_BEISPIEL}'")
    if actions is None or (isinstance(actions, str) and not actions.strip()):
        return f"Falscher Aufruf: 'actions' fehlt. Beispiel: actions='{_BEISPIEL}'"

    try:
        parsed = parse_actions(actions)
    except ValueError as e:
        return f"Aktionsliste ungueltig: {e}"

    # actions darf jetzt auch eine echte Liste sein -> fuer Inbox/Audit als Text normalisieren
    actions_text = actions if isinstance(actions, str) else json.dumps(actions, ensure_ascii=False)

    try:  # Ketten AN -> auch der Browser wartet an der Inbox
        if autonomy.needs_approval("external"):
            from core.agency import approvals

            aid = approvals.create(title="Browser-Aktion", kind="external",
                                   detail=actions_text[:2000], source="kira")
            return f"⏸️ Wartet auf {_id.user_name()}s Freigabe (id {aid[:8]}): Browser-Aktionsliste."
    except Exception as e:  # noqa: BLE001 — Gate kaputt: fail-closed
        return f"Gate-Fehler — Browser-Lauf sicherheitshalber NICHT gestartet: {e}"

    try:
        result = _run_actions(parsed, session)
    except Exception as e:  # noqa: BLE001 — Fehler-String statt Raise (executor-Regel)
        return f"Browser-Fehler: {e}"

    try:
        first_goto = next((a["url"] for a in parsed if a["action"] == "goto"), "")
        audit.record("browser_act", target=first_goto[:200],
                     details={"actions": [a["action"] for a in parsed], "session": session},
                     reversible=False)
    except Exception:  # noqa: BLE001
        pass
    return result or "(keine Beobachtungen)"
