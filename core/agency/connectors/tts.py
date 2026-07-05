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
_DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs-Standardstimme (in config ueberschreibbar)


def _cfg() -> dict:
    tel = (CONFIG.get("channels", {}) or {}).get("telegram", {}) or {}
    t = tel.get("tts")
    return t if isinstance(t, dict) else {}


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
            vid = c.get("voice_id") or _DEFAULT_VOICE
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
