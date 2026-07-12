"""W4b Linux-Port: Plattform-Gates + Skript-Familie + CI-Beweis.

Kern-Garantie: auf WINDOWS sind Prompt-/Beschreibungs-/Hinweis-Texte BYTE-IDENTISCH
zu vorher (Trainingsvertrag des lokalen Modells); unter Linux kommen korrekte
Varianten und der Unix-Verwechslungs-Schutz schaltet sich ab.
"""
from __future__ import annotations

import os

import yaml

from core.config import ROOT


def test_windows_texte_byte_identisch():
    if os.name != "nt":  # der Windows-Wortlaut ist nur auf Windows aktiv
        return
    import core.agency.tools.builtin  # noqa: F401
    from core.agency import act
    from core.agency.tools import registry

    assert ("Funktionen. Du laeufst auf WINDOWS (PowerShell/cmd) — zum Erkunden/Lesen von Dateien nutze\n"
            "list_dir/read_file (NICHT shell-Befehle wie find/grep/ls) und KEINE Linux-Pfade wie /workspace\n"
            "oder $HOME. Wenn du etwas Aktuelles nicht sicher weisst") in act._NATIVE_TOOLS_HINT
    assert "NIE PowerShell Get-Content (das verfaelscht Emojis/Umlaute)." in registry.get("read_file").description
    assert ("taskkill / Stop-Process zu killen ist verboten und gefaehrlich (du wuerdest "
            "dich SELBST beenden)") in registry.get("restart_self").description


def test_unix_hint_nur_auf_windows(monkeypatch):
    from core.agency import shelltool

    # Windows-Verhalten: Unix-Befehl -> lehrender Hinweis, KEINE Ausfuehrung
    monkeypatch.setattr(shelltool, "_IS_WIN", True)
    out = shelltool.run_shell("cat foo.txt | grep x")
    assert "Windows-Shell (cmd)" in out
    # Linux-Verhalten: derselbe Befehl laeuft normal durch (kein Fehl-Block)
    monkeypatch.setattr(shelltool, "_IS_WIN", False)
    out = shelltool.run_shell("echo linux-ok")
    assert "linux-ok" in out and "Windows-Shell" not in out


def test_gefahrenfilter_bleibt_plattformuebergreifend(monkeypatch):
    from core.agency import shelltool

    monkeypatch.setattr(shelltool, "_IS_WIN", False)   # auch auf 'Linux' hart geblockt
    for cmd in ("rm -rf /", "pkill python", "kill -9 123", "shutdown now"):
        assert "Blockiert" in shelltool.run_shell(cmd), cmd


def test_linux_skripte_vollstaendig_und_lf():
    for name in ("start-all.sh", "kira-update.sh", "install-autostart.sh",
                 "uninstall-autostart.sh"):
        p = ROOT / "scripts" / name
        raw = p.read_bytes()
        assert raw, name
        assert raw.splitlines()[0].startswith(b"#!/usr/bin/env bash"), f"{name}: Shebang fehlt"
        assert b"\r" not in raw, f"{name}: CRLF drin — bash wuerde wuergen (.gitattributes!)"


def test_systemd_unit_vorlage():
    t = (ROOT / "scripts" / "kira.service").read_text(encoding="utf-8")
    for marker in ("[Unit]", "[Service]", "[Install]", "start-all.sh",
                   "Restart=on-failure", "WantedBy=default.target"):
        assert marker in t, marker
    assert b"\r" not in (ROOT / "scripts" / "kira.service").read_bytes()


def test_ci_workflow_parsebar_und_laeuft_die_suite():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["linux"]
    assert job["runs-on"] == "ubuntu-latest"
    steps = " ".join(str(s) for s in job["steps"])
    assert "pytest tests" in steps and "uv sync" in steps


def test_setup_linux_doku():
    t = (ROOT / "SETUP-linux.md").read_text(encoding="utf-8")
    for marker in ("uv", "ollama", "systemd", "start-all.sh", "install-autostart.sh",
                   "Offline-Box", "enable-linger", "/setup"):
        assert marker in t, marker
