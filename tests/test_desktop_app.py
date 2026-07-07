"""Desktop-App (Stufe 1): Cockpit als natives Fenster + Tray-Symbol.

Getestet wird der GUI-FREIE Kern (Server-Bootstrap, Restart-Flag, Port-Konsistenz).
Das Fenster selbst (pywebview/pystray) ist optional und wird lazy importiert — diese
Tests laufen bewusst headless, ohne GUI-Libs.
"""
from __future__ import annotations

import sys

from core.desktop import app


def test_import_bleibt_gui_frei():
    # Der Import darf KEINE GUI-Lib mitziehen (sonst braeche der Kern auf Servern ohne Display)
    assert "webview" not in sys.modules
    assert "pystray" not in sys.modules


def test_cockpit_url():
    assert app.cockpit_url() == "http://127.0.0.1:8000/"


def test_port_passt_zum_supervisor():
    # Drift-Schutz: die Desktop-App muss denselben Port ansprechen, den der Supervisor startet
    from core.kernel import supervisor
    cockpit_cmd = supervisor.COMPONENTS["cockpit"]
    assert str(app.COCKPIT_PORT) in cockpit_cmd
    assert "127.0.0.1" == app.COCKPIT_HOST


def test_request_restart_schreibt_flag(tmp_path, monkeypatch):
    flag = tmp_path / "restart.flag"
    monkeypatch.setattr(app, "RESTART_FLAG", flag)
    app.request_restart()
    assert flag.read_text(encoding="utf-8") == "all"   # wie kira-update.bat -> Supervisor bounced sauber


def test_window_icon_nur_ico(tmp_path, monkeypatch):
    # Regressionsschutz: das Fenster-Icon ist NUR .ico (ein .jpg/.png liess die App beim Start crashen)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(app, "ROOT", tmp_path)
    assert app._window_icon() is None                       # nichts da -> None (App startet ohne Icon)
    (data / "kira-icon.jpeg").write_bytes(b"x")             # nur ein JPEG -> trotzdem KEIN Fenster-Icon
    assert app._window_icon() is None
    (data / "kira-icon.ico").write_bytes(b"x")              # erst mit .ico kommt ein Fenster-Icon
    assert app._window_icon() == str(data / "kira-icon.ico")


def test_ensure_cockpit_startet_nicht_wenn_schon_oben(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(app, "is_cockpit_up", lambda timeout=1.0: True)
    monkeypatch.setattr(app, "start_supervisor", lambda: calls.__setitem__("n", calls["n"] + 1))
    assert app.ensure_cockpit() is True
    assert calls["n"] == 0                              # laeuft schon -> KEIN zweiter Supervisor


def test_ensure_cockpit_startet_supervisor_wenn_unten(monkeypatch):
    calls = {"n": 0}
    seq = iter([False, True])   # erst unten, nach dem Start oben

    def fake_up(timeout=1.0):
        try:
            return next(seq)
        except StopIteration:
            return True

    monkeypatch.setattr(app, "is_cockpit_up", fake_up)
    monkeypatch.setattr(app, "start_supervisor", lambda: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr(app.time, "sleep", lambda *_: None)
    assert app.ensure_cockpit(wait=2.0) is True
    assert calls["n"] == 1                              # genau EIN Supervisor-Start
