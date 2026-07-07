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


def test_cockpit_kopf_nutzt_app_logo():
    # Der Kopf oben links zeigt das App-Logo (/api/icon); fehlt es, faellt onerror auf "KIRA" zurueck
    from core.api.ui.views import VIEWS
    from core.api.ui.css import HEAD_AND_CSS
    assert 'id="brand"' in VIEWS and 'src="/api/icon"' in VIEWS and "onerror=" in VIEWS
    assert 'class="txt">KIRA<' in VIEWS                    # Text-Fallback bleibt erhalten
    assert "#side h1:has(img) .txt{display:none}" in HEAD_AND_CSS
