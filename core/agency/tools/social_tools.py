"""Social-Werkzeuge: Posten nach draussen — IMMER durchs Gate (Aussenwirkung).

Bluesky war der Inventur-Fund ('kein Post-Kanal existiert'): jetzt gibt es einen.
Das publish-Gate legt den Post in die Freigabe-Inbox; Sergens GO fuehrt ihn
deterministisch aus (approvals.decide re-dispatcht, wie bei Fremd-Mails).
"""
from __future__ import annotations

import json

from core.agency.tools.registry import tool


@tool("bluesky_post",
      "Postet einen Text auf Bluesky (max 300 Zeichen). Aussenwirkung: wartet in der "
      "Freigabe-Inbox auf Sergens GO — die Freigabe sendet dann wirklich.",
      {"text": "der Post-Text (max 300 Zeichen, Hashtags erlaubt)"})
def bluesky_post(text: str) -> str:
    from core.agency.connectors import bluesky
    from core.governance import gate

    return gate.guarded(
        kind="publish",
        title=f"Bluesky-Post: {(text or '')[:70]}",
        detail=json.dumps({"platform": "bluesky", "text": (text or "")[:300]},
                          indent=2, ensure_ascii=False),
        execute=lambda: bluesky.post(text),
        target="bluesky",
        action="bluesky_post",
    )
