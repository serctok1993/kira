"""Test fuer das Selbst-Report-Werkzeug harness_report (read-only DB-Report)."""
from core.agency.tools.builtin import harness_report


def test_harness_report_nonempty():
    out = harness_report("today")
    assert isinstance(out, str) and out.strip()
    assert "Harness-Report" in out
    assert "EUR" in out


def test_harness_report_all_windows_no_crash():
    # jedes Fenster + ein unbekannter Wert (Fallback auf 'today') liefert einen gueltigen String
    for w in ("today", "24h", "7d", "quatsch", ""):
        out = harness_report(w)
        assert isinstance(out, str) and out.strip()
        assert "Harness-Report" in out
