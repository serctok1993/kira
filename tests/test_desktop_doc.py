"""Phase 3 — Desktop-Einrichtung: Anleitung + Taskleisten-Helfer sind vorhanden und komplett.

Kein Laufzeit-Code (Windows-Einrichtung), aber die Kern-Schritte sollen nicht still verloren gehen —
die Anleitung ist zugleich Teil des spaeteren Werkszustand-Onboardings (Phase 5).
"""
from __future__ import annotations

from core.config import ROOT


def test_desktop_anleitung_vollstaendig():
    doc = (ROOT / "docs" / "DESKTOP.md").read_text(encoding="utf-8")
    for m in ("/wall", "Lively", "127.0.0.1:8000/wall", "Taskleiste", "taskbar-autohide.ps1"):
        assert m in doc, f"DESKTOP.md fehlt: {m}"


def test_taskleisten_helfer_vorhanden():
    ps1 = (ROOT / "taskbar-autohide.ps1").read_text(encoding="utf-8")
    assert "StuckRects3" in ps1 and 'param(' in ps1        # An/Aus, reversibel
    assert '"on"' in ps1 and '"off"' in ps1


def test_taskleiste_dauerhaft_verstecken_helfer():
    # Variante 2: Taskleisten-Fenster wirklich verstecken (durchgaengiger Desktop), reversibel
    ps1 = (ROOT / "taskbar-hide.ps1").read_text(encoding="utf-8")
    assert "Shell_TrayWnd" in ps1 and "ShowWindow" in ps1
    assert '"hide"' in ps1 and '"show"' in ps1
    doc = (ROOT / "docs" / "DESKTOP.md").read_text(encoding="utf-8")
    assert "taskbar-hide.ps1" in doc


def test_alle_ps1_sind_ascii():
    # Windows PowerShell 5.1 liest .ps1 standardmaessig als ANSI -> Nicht-ASCII (Gedankenstrich —,
    # Umlaute, „Smart Quotes") zerschiesst das Parsen ("MissingEndCurlyBrace"). Deshalb muessen alle
    # Helfer-Skripte rein ASCII sein (Umlaute im Text ae/oe/ue schreiben).
    import glob

    bad = {}
    for f in sorted(glob.glob(str(ROOT / "*.ps1"))):
        txt = open(f, encoding="utf-8").read()
        nz = [i + 1 for i, line in enumerate(txt.splitlines()) if any(ord(c) > 127 for c in line)]
        if nz:
            bad[f.rsplit("/", 1)[-1]] = nz
    assert not bad, f"Nicht-ASCII in .ps1 (bricht Windows PowerShell): {bad}"


def test_desktop_setup_helfer_vorhanden():
    # Ein-Klick-Einrichtung: PNG->ICO, Desktop-Verknuepfung, Autostart der Desktop-App
    ps1 = (ROOT / "desktop-setup.ps1").read_text(encoding="utf-8")
    assert "kira-icon.png" in ps1 and "kira-icon.ico" in ps1          # Icon-Erzeugung
    assert "GetFolderPath(\"Desktop\")" in ps1 and "Kira.lnk" in ps1  # Desktop-Verknuepfung
    assert "GetFolderPath(\"Startup\")" in ps1 and "Kira Desktop.lnk" in ps1  # eigener Autostart
    assert "kira-desktop.bat" in ps1                                   # zeigt auf die App
    assert (ROOT / "kira-einrichten.bat").exists()                     # Doppelklick-Wrapper
    # Deinstallation raeumt den neuen Autostart-Eintrag mit weg
    un = (ROOT / "uninstall-autostart.ps1").read_text(encoding="utf-8")
    assert "Kira Desktop.lnk" in un
    doc = (ROOT / "docs" / "DESKTOP.md").read_text(encoding="utf-8")
    assert "kira-einrichten.bat" in doc


def test_cockpit_kopf_ist_wortmarke_nicht_logo():
    # der Nutzer wollte das Logo NICHT im Cockpit-Kopf: der Kopf zeigt den „KIRA"-Schriftzug,
    # kein /api/icon-Bild. Das Logo bleibt fuer Fenster-/Taskleisten-Symbol + /wall-Favicon.
    from core.api.ui.views import VIEWS
    from core.api.ui.script import SCRIPT
    assert '<h1 id="brand"><span class="txt">__AGENT_UC__</span></h1>' in VIEWS  # Wortmarke (W2: Token, Server injiziert Namen)
    assert 'id="brand"><img' not in VIEWS                                # kein Logo-Bild im Kopf
    # refreshLogo frischt nur Vorschau + Favicon, injiziert NICHTS mehr in den Kopf (#brand)
    assert "function refreshLogo(" in SCRIPT and "b.insertBefore(im" not in SCRIPT
