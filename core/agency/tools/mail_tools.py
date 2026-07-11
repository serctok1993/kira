"""Email-Werkzeuge: Kiras Draht in die Postfach-Welt (S3).

Gate-Regel ('Ketten ab'): email_check ist rein lesend und laeuft frei.
email_send an Sergens eigene Adressen (own_addresses) = external -> laeuft
frei + Audit; an FREMDE = email_stranger -> stoppt an der Freigabe-Inbox.
"""
from __future__ import annotations

import json

from core.agency.tools.registry import tool


@tool("email_check",
      "Liest die juengsten Mails aus Kiras eigenem Posteingang — nummerierte Liste mit "
      "Absender, Betreff, Auszug und message_id. Zum Antworten im selben Gespraechsfaden "
      "die message_id an email_reply geben.",
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
    lines = []
    for i, m in enumerate(res, 1):
        mid = f"\n   message_id: {m['message_id']}" if m.get("message_id") else ""
        lines.append(f"{i}) {m['date']} | {m['from']}\n   Betreff: {m['subject']}\n"
                     f"   {m['snippet'][:200]}{mid}")
    lines.append('Antworten (haelt den Gespraechsfaden): ACT email_reply '
                 '{"an": "<Absender>", "betreff": "<Betreff>", "text": "...", '
                 '"message_id": "<aus der Liste>"}')
    return "\n".join(lines)


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


@tool("email_reply",
      "Beantwortet eine Mail aus dem Posteingang IM GESPRAECHSFADEN (Threading via "
      "message_id aus email_check; 'Re: ' wird ergaenzt). Gleiche Gate-Regel wie "
      "email_send: an Fremde wartet die Antwort in der Freigabe-Inbox.",
      {"an": "Empfaenger-Adresse (der Absender der Original-Mail)",
       "betreff": "Betreff der Original-Mail (Re: wird ergaenzt)",
       "text": "Antworttext",
       "message_id": "optional: aus email_check — haelt den Gespraechsfaden (Threading)"})
def email_reply(an: str = "", betreff: str = "", text: str = "", message_id: str = "",
                **falsche_args) -> str:
    from core.agency.connectors import mail
    from core.governance import gate

    if falsche_args or not str(an).strip() or not str(text).strip():
        return ("Fehler: email_reply braucht 'an' und 'text'. Beispiel: "
                'ACT email_reply {"an": "max@firma.de", "betreff": "Angebot", '
                '"text": "Hallo ...", "message_id": "<abc@mail>"}')
    an = str(an).strip()
    kind = "email_stranger" if mail.is_stranger(an) else "external"
    # in_reply_to steckt mit im detail-JSON -> approvals.decide kann die Freigabe
    # deterministisch als reply() nachziehen (Threading ueberlebt das Gate).
    return gate.guarded(
        kind=kind,
        title=f"Antwort an {an}: {mail.reply_subject(betreff)[:80]}",
        detail=json.dumps({"to": an, "subject": betreff, "body": str(text)[:2000],
                           "in_reply_to": str(message_id).strip()},
                          indent=2, ensure_ascii=False),
        execute=lambda: mail.reply(an, betreff, text, in_reply_to=message_id),
        target=an,
        action="email_reply",
    )
