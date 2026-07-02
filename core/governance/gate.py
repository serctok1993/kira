"""Das Autonomie-Gate: 'Ketten ab' endlich im Vollzug (S3).

Bisher stand die Regel nur auf Papier (autonomy.needs_approval hatte keinen einzigen
Aufrufer). Ab jetzt laeuft JEDE Aussen-Aktion durch guarded():

  - hard_gate-Art (Default: money, email_stranger bei chains_off=True)
    -> Freigabe-Inbox-Eintrag, KEINE Ausfuehrung. Der Eintrag IST die Anfrage.
  - alles andere -> ausfuehren + lueckenlos ins Audit-Log.

Fehler-Regeln: Gate-Infrastruktur kaputt -> NICHT ausfuehren (sichere Richtung).
execute() wirft -> Fehler-String statt Exception (executor.run_tool retried
Exceptions 3x — eine raisende Aussen-Aktion wuerde mehrfach feuern).
"""
from __future__ import annotations

from typing import Any, Callable


def _council_kinds() -> set[str]:
    """Aktions-Arten, die vor dem Inbox-Eintrag eine Rats-Debatte bekommen (S4).

    Default: nur 'money' — selten genug fuer 4 reason-Calls, wichtig genug fuer
    Urteilsvermoegen. Konfigurierbar via config.yaml governance.council_gate."""
    try:
        from core.config import CONFIG

        kinds = (CONFIG.get("governance", {}) or {}).get("council_gate", ["money"])
        return set(kinds) if isinstance(kinds, (list, tuple)) else {"money"}
    except Exception:  # noqa: BLE001
        return {"money"}


def guarded(kind: str, title: str, detail: str, execute: Callable[[], Any],
            target: str = "", reversible: bool = False, action: str = "") -> str:
    from core.agency import approvals
    from core.governance import audit, autonomy

    try:
        if autonomy.needs_approval(kind):
            detail_full = (detail or "")[:4000]
            if kind in _council_kinds():
                # Council-als-Gate (S4): Kira debattiert den Zug ERST mit sich selbst
                # (Visionaer/Skeptiker/Macher + Judge) und legt Sergen das Urteil als
                # Entscheidungsgrundlage in die Inbox. Debatten-Ausfall blockiert nie
                # die Anfrage selbst.
                try:
                    from core.mind import council

                    verdict = council.deliberate(
                        f"Sollen wir diese Aktion jetzt ausfuehren: {title}?",
                        context=detail_full[:1500])["verdict"]
                    detail_full = (detail_full
                                   + "\n\n--- RATS-URTEIL (Kiras Selbst-Debatte) ---\n"
                                   + verdict)[:4000]
                except Exception as e:  # noqa: BLE001
                    detail_full = (detail_full + f"\n\n(Rats-Debatte fehlgeschlagen: {e})")[:4000]
            aid = approvals.create(title=title, kind=kind, detail=detail_full, source="kira")
            return (f"⏸️ Wartet auf Sergens Freigabe (id {aid[:8]}, Art '{kind}'): {title}. "
                    f"NICHT ausgefuehrt — der Inbox-Eintrag ist die Anfrage.")
    except Exception as e:  # noqa: BLE001 — Gate kaputt: fail-closed, nie blind ausfuehren
        return f"Gate-Fehler bei '{title}' — Aktion sicherheitshalber NICHT ausgefuehrt: {e}"

    try:
        result = execute()
    except Exception as e:  # noqa: BLE001
        return f"Fehler bei '{title}': {e}"

    try:
        audit.record(action or kind, target=target or title,
                     details={"detail": (detail or "")[:500]}, reversible=reversible)
    except Exception:  # noqa: BLE001 — Audit-Ausfall macht die getane Aktion nicht ungeschehen
        pass
    return str(result)
