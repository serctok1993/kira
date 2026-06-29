"""Sprache -> Text, lokal via faster-whisper (CPU, 0 EUR).

Bewusst CPU: die GPU bleibt fuer Qwythos frei. Ein 'base'-Modell transkribiert
kurze Sprachmemos in ein bis zwei Sekunden. Das Modell wird beim ersten Aufruf
geladen (einmaliger Download ~150 MB) und dann gecacht.
"""
from __future__ import annotations

from core.config import CONFIG

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # lazy: nur noetig fuer Voice

        size = CONFIG.get("channels", {}).get("telegram", {}).get("whisper_model", "base")
        _model = WhisperModel(size, device="cpu", compute_type="int8")
    return _model


def transcribe(path: str, language: str | None = "de") -> str:
    model = _get_model()
    segments, _info = model.transcribe(path, language=language)
    return "".join(seg.text for seg in segments).strip()
