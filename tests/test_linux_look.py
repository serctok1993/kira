"""Linux-Feeling am Desktop: Ordner-Icon-Helfer + Anleitung sind vorhanden und vollstaendig.

Kein Laufzeit-Code (Windows-Einrichtung), aber die Kern-Schritte sollen nicht still verloren gehen —
und der Ordner-Icon-Weg soll SICHER bleiben (nur desktop.ini, kein System-Patch).
"""
from __future__ import annotations

from core.config import ROOT


def test_linux_look_skript_vorhanden_und_sicher():
    ps1 = (ROOT / "linux-look.ps1").read_text(encoding="utf-8")
    # zeichnet ein Icon selbst (kein Download) + setzt es sicher per desktop.ini je Ordner
    assert "System.Drawing" in ps1 and "New-FolderIcon" in ps1
    assert "desktop.ini" in ps1 and "IconResource=" in ps1
    assert "-Reset" in ps1 and "Reset-FolderIcon" in ps1           # reversibel
    assert "DesktopDirectory" in ps1                                # Standard: Desktop-Ordner
    # Doppelklick-Wrapper (anwenden + zurueck)
    assert (ROOT / "linux-look.bat").exists()
    assert (ROOT / "linux-look-zurueck.bat").exists()


def test_linux_look_doku_vollstaendig():
    doc = (ROOT / "docs" / "LINUX-LOOK.md").read_text(encoding="utf-8")
    # Cursor (der runde, glaenzende schwarze Look) -> Bibata; Hinweis, dass custom-cursor.com nur im Browser wirkt
    assert "Bibata" in doc and "custom-cursor.com" in doc and "Browser" in doc
    # Ordner-Icons ueber das Skript; Startmenue ueber Open-Shell (Open Source, kein System-Patch)
    assert "linux-look.bat" in doc and "Papirus" in doc
    assert "Open-Shell" in doc
