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
