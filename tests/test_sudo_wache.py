"""Sudo-Wache (13.08.2026): Allowlist laesst System-Pflege durch, alles andere
wird erklaert statt ausgefuehrt — und Ketten-Tricks werden hart abgewiesen."""
from core.agency.shelltool import _sudo_wache


def test_ohne_sudo_kein_veto():
    assert _sudo_wache("uname -r") is None
    assert _sudo_wache("echo sudoku") is None   # Wortgrenze: 'sudoku' ist kein sudo


def test_allowlist_darf():
    assert _sudo_wache("sudo apt-get update") is None
    assert _sudo_wache("sudo apt-get upgrade -y") is None
    assert _sudo_wache("sudo kira-apt-install htop") is None
    assert _sudo_wache("sudo /usr/sbin/dmidecode -t memory") is None
    assert _sudo_wache("sudo journalctl -u ssh --since today") is None


def test_fremdes_sudo_wird_erklaert():
    veto = _sudo_wache("sudo rm -rf /var/log")
    assert veto and "Allowlist" in veto


def test_ketten_werden_blockiert():
    veto = _sudo_wache("sudo apt-get update; rm -rf ~")
    assert veto and "Befehlsketten" in veto
    veto2 = _sudo_wache("echo hi && sudo apt-get update")
    assert veto2 is not None


def test_options_schmuggel_faellt_durch():
    # Paket-Wrapper akzeptiert nur Paketnamen -> Optionen matchen die Allowlist nicht
    veto = _sudo_wache("sudo kira-apt-install -o APT::Update::Pre-Invoke::=/bin/sh")
    assert veto and "Allowlist" in veto
