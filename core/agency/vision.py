"""Bild-Erkennung fuer Kira: schickt ein Bild an ein Vision-Modell (Default GLM-4.6v
ueber OpenRouter) und gibt Kiras Beschreibung/Analyse zurueck. Wird vom Cockpit
(/api/vision) und vom Telegram-Bot (Fotos) genutzt.
"""
from __future__ import annotations

from core.config import CONFIG
from core.kernel import events

_SYSTEM = ("Du bist Kira (weiblich). Beschreibe und analysiere das Bild knapp, klar und "
           "hilfreich auf Deutsch, in der Ich-Form. Keine Sternchen.")


def describe(image_url: str, prompt: str = "") -> str:
    """image_url: 'data:image/...;base64,...' oder eine http(s)-URL."""
    import litellm

    litellm.drop_params = True
    litellm.suppress_debug_info = True
    model = CONFIG.get("models", {}).get("vision_model") or "openrouter/z-ai/glm-4.6v"
    r = litellm.completion(
        model=model,
        max_tokens=1000,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": prompt or "Was ist auf diesem Bild? Beschreibe es."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
    )
    txt = r.choices[0].message.content
    events.emit("vision", {"model": model, "prompt": prompt[:120]})
    return txt
