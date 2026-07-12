"""S5.2: BODY.md — Anatomie-Selbstwissen, generiert statt halluziniert. Offline."""
from __future__ import annotations

from core.mind import body


def _use_tmp_body(monkeypatch, tmp_path, content: str):
    p = tmp_path / "BODY.md"
    p.write_text(content, encoding="utf-8")
    monkeypatch.setattr(body, "_PATH", p)
    return p


_MINI = """# KOERPER
Organe: Planner, Actor, Pruefer.
<!-- REFERENZ -->
## Referenz
<!-- AUTO:START -->
(alt)
<!-- AUTO:END -->
## Erzaehlung
Bleibt erhalten.
"""


def test_compact_reads_only_head(monkeypatch, tmp_path):
    _use_tmp_body(monkeypatch, tmp_path, _MINI)
    c = body.compact()
    assert "Organe" in c
    assert "Referenz" not in c and "AUTO" not in c  # nur der Kopf geht in den Prompt
    assert len(c) <= 1500


def test_compact_missing_file_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(body, "_PATH", tmp_path / "fehlt.md")
    assert body.compact() == ""  # fail-soft: Prompt-Bau bricht nie


def test_refresh_replaces_auto_block_idempotent(monkeypatch, tmp_path):
    # Registry explizit fuellen — sonst haengt der Test von der Import-Reihenfolge
    # anderer Testdateien ab (builtin registriert die Werkzeuge erst beim Import).
    from core.agency.tools import builtin  # noqa: F401

    p = _use_tmp_body(monkeypatch, tmp_path, _MINI)
    assert body.refresh()["ok"]
    text1 = p.read_text(encoding="utf-8")
    assert "(alt)" not in text1                      # ersetzt statt angehaengt
    assert "Werkzeuge (" in text1                    # aus der echten Registry abgeschrieben
    assert "todo_add" in text1                       # S5-Werkzeuge tauchen automatisch auf
    assert "Bleibt erhalten." in text1               # Erzaehl-Teil unangetastet
    assert text1.count("<!-- AUTO:START -->") == 1   # keine Marker-Duplikate

    assert body.refresh()["ok"]                      # zweiter Lauf: weiterhin genau ein Block
    text2 = p.read_text(encoding="utf-8")
    assert text2.count("<!-- AUTO:START -->") == 1
    assert "Bleibt erhalten." in text2


def test_refresh_without_markers_is_safe(monkeypatch, tmp_path):
    _use_tmp_body(monkeypatch, tmp_path, "# Koerper ohne Marker")
    res = body.refresh()
    assert res["ok"] is False and "Marker" in res["error"]


def test_real_body_md_structure():
    """BODY hat Kopf + Marker, der Kopf haelt die Kontext-Diaet — gelebte Datei, sonst
    (frischer Klon, W3: BODY.md ist Privatsache) das Template, wie body.compact()."""
    quelle = body._PATH if body._PATH.exists() else body._PATH.parent / "templates" / "BODY.md"
    real = quelle.read_text(encoding="utf-8")
    assert "<!-- REFERENZ -->" in real
    assert real.count("<!-- AUTO:START -->") == 1 and real.count("<!-- AUTO:END -->") == 1
    assert len(body.compact()) <= 1500
    for marker in ("Organe", "Kreislaeufe", "Haende", "Grenzen"):
        assert marker in body.compact()


def test_identity_and_system_prompt_carry_body(monkeypatch, tmp_path):
    from core.agency.act import _identity
    from core.mind import agent

    assert "DEIN KOERPER" in _identity()
    # build_system_prompt braucht Memory -> nur die Kopf-Funktion pruefen
    assert "Organe" in agent._body_compact()
