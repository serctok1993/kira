"""Vault-Werkzeuge (Phase 2): der aktive Griff des Agenten auf das Obsidian des Nutzers.

vault_note/vault_dossier schreiben ECHTE .md-Dateien in den Vault (der Nutzer sieht sie
sofort in Obsidian + im /wall-Graph). person_fakt pflegt den Stammbaum deterministisch.
Abgrenzung zu knowledge_note (durchsuchbares Archiv in der DB) steht in den
Beschreibungen — die Texte sind Trainingsmaterial fuer die LLM-Werkstatt.
"""
from __future__ import annotations

from core.agency.tools.registry import tool


@tool("vault_note",
      "Schreibt eine Markdown-Notiz in {{USER_NAME_S}} Obsidian-Vault (er sieht sie sofort). "
      "Existiert die Notiz, wird ein '## Update'-Abschnitt angehaengt — nichts geht "
      "verloren. Faellt im Gespraech Nuetzliches an (Ideen, Ergebnisse, Anleitungen), "
      "leg es VON DIR AUS hier ab. Fuers durchsuchbare Archiv nimm knowledge_note.",
      {"titel": "Notiz-Titel (wird Dateiname)",
       "text": "Markdown-Inhalt",
       "ordner": "optional: Unterordner im Vault, Standard notizen"})
def vault_note(titel: str = "", text: str = "", ordner: str = "", **falsche_args) -> str:
    from core.agency import vault_notes

    if falsche_args or not str(titel).strip() or not str(text).strip():
        return ("Fehler: vault_note braucht 'titel' und 'text'. Beispiel: "
                'ACT vault_note {"titel": "Video-Setup", "text": "## Kamera\\n..."}')
    res = vault_notes.write_note(titel, text, ordner=ordner or "notizen")
    if not res.get("ok"):
        return f"Fehler: {res.get('error')}"
    tat = "angelegt" if res.get("created") else "ergaenzt (## Update)"
    return f"Vault-Notiz {tat}: {res['path']}"


@tool("vault_dossier",
      "Legt ein Recherche-Dossier in {{USER_NAME_S}} Obsidian-Vault an (dossiers/<thema>.md) "
      "bzw. ergaenzt es um einen '## Update'-Abschnitt. Fuer selbststaendige Recherchen: "
      "web_search -> Top-Treffer mit web_fetch lesen -> Erkenntnisse MIT Quellen-Links "
      "hier ablegen (Playbook dossier-recherche).",
      {"thema": "Recherche-Thema, z.B. Social-Media-Hooks DACH",
       "text": "Markdown mit Kernaussagen + Quellen-Links"})
def vault_dossier(thema: str = "", text: str = "", **falsche_args) -> str:
    from core.agency import vault_notes

    if falsche_args or not str(thema).strip() or not str(text).strip():
        return ("Fehler: vault_dossier braucht 'thema' und 'text'. Beispiel: "
                'ACT vault_dossier {"thema": "Social-Media-Hooks", "text": "- Hook X ([Quelle](url))"}')
    res = vault_notes.write_dossier(thema, text)
    if not res.get("ok"):
        return f"Fehler: {res.get('error')}"
    tat = "angelegt" if res.get("created") else "um ein Update ergaenzt"
    return f"Dossier {tat}: {res['path']}"


@tool("person_fakt",
      "Merkt sich einen Fakt ueber eine Person DAUERHAFT im Stammbaum (Obsidian). "
      "Faellt im Gespraech ein Geburtstag, Wohnort, eine Vorliebe — trag es VON DIR AUS "
      "ein. feld=geburtstag (TT.MM.JJJJ) landet automatisch im TERMIN-RADAR der Briefings. "
      "Ersetzt ???-Luecken; legt fehlende Personen-Blaetter selbst an.",
      {"name": "Person, z.B. Mama oder Ali Tokgoez",
       "feld": "z.B. geburtstag, wohnort, beruf, mag",
       "wert": "der Wert; Datum als TT.MM.JJJJ"})
def person_fakt(name: str = "", feld: str = "", wert: str = "", **falsche_args) -> str:
    from core.agency import vault_notes

    if falsche_args or not str(name).strip() or not str(feld).strip() or not str(wert).strip():
        return ("Fehler: person_fakt braucht 'name', 'feld' und 'wert'. Beispiel: "
                'ACT person_fakt {"name": "Nichte", "feld": "geburtstag", "wert": "03.08.2019"}')
    res = vault_notes.person_fakt_upsert(name, feld, wert)
    if not res.get("ok"):
        return f"Fehler: {res.get('error')}"
    neu = " (Blatt neu angelegt)" if res.get("created") else ""
    hinweis = (" — Geburtstage sage ich im Briefing rechtzeitig von selbst an."
               if "geburtstag" in str(feld).lower() else "")
    return f"Gemerkt: {name} — {feld}: {wert}{neu}{hinweis}"
