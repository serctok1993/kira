"""Text-zu-Sprache (TTS): Kira spricht zurueck. Anbieter-agnostisch — wie die Modell-Raenge.

Anbieter via config channels.telegram.tts.provider:
  elevenlabs  -> Cloud, emotionale Stimme (Key ELEVENLABS_API_KEY). Kostet pro Zeichen.
  off / leer  -> keine Sprachausgabe.
Spaeter einhaengbar ohne Aufruferaenderung: lokal (kokoro/xtts) = 0 EUR.

synthesize() liefert (audio_bytes, mime) ODER None. Bei JEDEM Fehler None — die Text-Antwort
haengt NIE an der Sprachausgabe. Ein max_chars-Deckel schuetzt die (Free-)Credits: Sprache
zahlt pro Zeichen, lange Antworten werden fuer die Stimme gekappt (der Volltext bleibt Text).
"""
from __future__ import annotations

import os

import httpx

from core.config import CONFIG
from core.kernel import events

_ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{vid}"
_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
_DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Notnagel; besser: eine echte Stimme des Kontos (unten)
_ACCOUNT_VOICE: dict = {"id": None}


def _cfg() -> dict:
    tel = (CONFIG.get("channels", {}) or {}).get("telegram", {}) or {}
    t = tel.get("tts")
    return t if isinstance(t, dict) else {}


def _account_voice(key: str) -> str | None:
    """Erste vom Konto per API nutzbare Stimme holen (gecacht). Free-Konten duerfen KEINE
    Library-Stimmen ueber die API — die fest verdrahtete Standard-ID kann je nach Konto
    gesperrt sein. Also fragen wir das Konto: bevorzugt 'premade', sonst die erste."""
    if _ACCOUNT_VOICE["id"]:
        return _ACCOUNT_VOICE["id"]
    try:
        r = httpx.get(_VOICES_URL, headers={"xi-api-key": key}, timeout=15)
        if r.status_code != 200:
            return None
        voices = r.json().get("voices", []) or []
        premade = [v for v in voices if (v.get("category") or "").lower() == "premade"]
        pick = premade or voices
        if pick:
            _ACCOUNT_VOICE["id"] = pick[0].get("voice_id")
            return _ACCOUNT_VOICE["id"]
    except Exception:  # noqa: BLE001
        pass
    return None


def _resolve_voice(c: dict, key: str) -> str:
    """Welche Stimme: bewusst gesetzte voice_id > eine freie Konto-Stimme > Notnagel."""
    vid = (c.get("voice_id") or "").strip()
    return vid or _account_voice(key) or _DEFAULT_VOICE


def enabled() -> bool:
    """True, wenn Sprachausgabe konfiguriert ist (Schalter an UND Anbieter gesetzt)."""
    c = _cfg()
    return bool(c.get("enabled")) and (c.get("provider") or "").lower() not in ("", "off")


def _cap(text: str) -> str:
    """Text fuer die Stimme deckeln (Credit-Schutz) — an Wortgrenze, mit … am Ende."""
    try:
        n = int(_cfg().get("max_chars", 600))
    except Exception:  # noqa: BLE001
        n = 600
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip() + " …"


def synthesize(text: str, session_id: str | None = None):
    """Text -> (audio_bytes, mime) oder None. Raist nie."""
    if not enabled() or not (text or "").strip():
        return None
    c = _cfg()
    provider = (c.get("provider") or "").lower()
    body = _cap(text)
    try:
        if provider == "elevenlabs":
            key = os.getenv("ELEVENLABS_API_KEY")
            if not key:
                events.emit("tts_no_key", {"provider": provider}, session_id=session_id)
                return None
            vid = _resolve_voice(c, key)
            model = c.get("model_id") or "eleven_multilingual_v2"
            r = httpx.post(
                _ELEVEN_URL.format(vid=vid),
                headers={"xi-api-key": key, "accept": "audio/mpeg", "content-type": "application/json"},
                params={"output_format": "mp3_44100_128"},
                json={"text": body, "model_id": model},
                timeout=30,
            )
            if r.status_code != 200:
                events.emit("tts_error", {"provider": provider, "status": r.status_code,
                                          "body": (r.text or "")[:200]}, session_id=session_id)
                return None
            events.emit("tts_ok", {"provider": provider, "chars": len(body)}, session_id=session_id)
            return (r.content, "audio/mpeg")
        events.emit("tts_error", {"provider": provider, "reason": "unbekannter Anbieter"}, session_id=session_id)
        return None
    except Exception as e:  # noqa: BLE001 — Sprachausgabe darf die Textantwort nie brechen
        events.emit("tts_error", {"provider": provider, "error": str(e)[:200]}, session_id=session_id)
        return None


def diagnose(sample: str = "Hallo Sergen, hier ist Kira — die Stimme funktioniert.") -> dict:
    """Testet die Sprachausgabe und liefert einen KLARTEXT-Grund (fuer den Cockpit-Test-Knopf).

    Laeuft im Cockpit-Prozess -> hat den frisch eingegebenen Key sofort (ohne Neustart).
    Rueckgabe: {ok: bool, reason: str, bytes?: int}."""
    c = _cfg()
    prov = (c.get("provider") or "").lower()
    if not bool(c.get("enabled")):
        return {"ok": False, "reason": "Sprachausgabe ist AUS — Haken 'Sprachantworten an' setzen und 'Uebernehmen' klicken."}
    if prov in ("", "off"):
        return {"ok": False, "reason": f"Kein Anbieter gewaehlt (provider='{prov}')."}
    if prov != "elevenlabs":
        return {"ok": False, "reason": f"Anbieter '{prov}' hat keine Test-Anbindung."}
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return {"ok": False, "reason": "Kein ELEVENLABS_API_KEY gefunden — Key in dieser Karte speichern."}
    _ACCOUNT_VOICE["id"] = None  # beim Test frisch aus dem Konto holen (nicht alten Cache nehmen)
    vid = _resolve_voice(c, key)
    model = c.get("model_id") or "eleven_multilingual_v2"
    try:
        r = httpx.post(
            _ELEVEN_URL.format(vid=vid),
            headers={"xi-api-key": key, "accept": "audio/mpeg", "content-type": "application/json"},
            params={"output_format": "mp3_44100_128"},
            json={"text": _cap(sample), "model_id": model},
            timeout=30,
        )
        if r.status_code == 200:
            return {"ok": True, "reason": f"Stimme erzeugt ✓ ({len(r.content)} Bytes, Stimme {vid}).",
                    "bytes": len(r.content)}
        detail = (r.text or "")[:300]
        hint = ""
        if r.status_code == 401:
            hint = " -> Key falsch oder abgelaufen."
        elif r.status_code in (400, 422):
            hint = " -> meist ungueltige Voice-ID (Feld leeren) oder Modell im Free-Plan gesperrt."
        elif r.status_code in (402, 403):
            hint = (" -> dein Free-Konto darf diese Stimme nicht per API. Falls das Feld leer war und "
                    "trotzdem gesperrt: dein Konto hat keine freie API-Stimme -> entweder auf ElevenLabs "
                    "eine 'premade'-Stimme zu 'My Voices' hinzufuegen, oder wir schalten auf lokale Stimme "
                    "(Kokoro, 0 EUR) um.")
        return {"ok": False, "reason": f"ElevenLabs-Fehler {r.status_code}{hint} Antwort: {detail}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"Netzwerk/Aufruf fehlgeschlagen: {str(e)[:200]}"}
