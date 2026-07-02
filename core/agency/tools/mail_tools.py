"""Email-Werkzeuge: Kiras Draht in die Postfach-Welt (S3).

Gate-Regel ('Ketten ab'): email_check ist rein lesend und laeuft frei.
email_send an Sergens eigene Adressen (own_addresses) = external -> laeuft
frei + Audit; an FREMDE = email_stranger -> stoppt an der Freigabe-Inbox.
"""
from __future__ import annotations

import json

from core.agency.tools.registry import tool


@tool("email_check",
      "Liest die juengsten Mails aus Kiras eigenem Posteingang (Absender, Betreff, Datum, Auszug).",
      {"limit": "wie viele Mails (Standard 10)"})
def email_check(limit: str = "10") -> str:
    from core.agency.connectors import mail

    try:
        n = max(1, min(50, int(limit)))
    except ValueError:
        n = 10
    res = mail.check(n)
    if isinstance(res, str):
        return res
    if not res:
        return "Posteingang ist leer."
    return "\n".join(f"- {m['date']} | {m['from']}\n  {m['subject']}\n  {m['snippet'][:200]}" for m in res)


@tool("email_send",
      "Sendet eine Email von Kiras eigenem Postfach. An Sergens eigene Adressen laeuft sie direkt "
      "(+ Audit); an fremde Empfaenger wartet sie in der Freigabe-Inbox (hard_gate email_stranger).",
      {"to": "Empfaenger-Adresse", "subject": "Betreff", "body": "Nachrichtentext"})
def email_send(to: str, subject: str, body: str) -> str:
    from core.agency.connectors import mail
    from core.governance import gate

    kind = "email_stranger" if mail.is_stranger(to) else "external"
    return gate.guarded(
        kind=kind,
        title=f"E-Mail an {to}: {subject[:80]}",
        detail=json.dumps({"to": to, "subject": subject, "body": body[:2000]},
                          indent=2, ensure_ascii=False),
        execute=lambda: mail.send(to, subject, body),
        target=to,
        action="email_send",
    )
