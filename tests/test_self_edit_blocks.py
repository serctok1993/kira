"""Tests fuer die block-basierte self_edit-Logik (SEARCH/REPLACE + APPEND).

Deterministisch, ohne LLM: prueft Parsing + Anwenden + die Truncation-Guards.
"""
from core.agency.selfdev import _apply_edits, _lost_defs, _parse_edit_blocks


def test_parse_replace_block():
    txt = "<<<<<<< SEARCH\nalt\n=======\nneu\n>>>>>>> REPLACE\n"
    assert _parse_edit_blocks(txt) == [("replace", "alt", "neu")]


def test_parse_append_block():
    txt = "<<<<<<< APPEND\ndef neu():\n    pass\n>>>>>>> APPEND"
    assert _parse_edit_blocks(txt) == [("append", "def neu():\n    pass")]


def test_parse_mixed_order():
    txt = ("<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
           "<<<<<<< APPEND\nc\n>>>>>>> APPEND\n")
    kinds = [b[0] for b in _parse_edit_blocks(txt)]
    assert kinds == ["replace", "append"]


def test_parse_none():
    assert _parse_edit_blocks("nur prosa, keine bloecke") == []


def test_apply_replace_unique():
    new, err = _apply_edits("a = 1\nb = 2\nc = 3\n", [("replace", "b = 2", "b = 20")])
    assert err is None
    assert "b = 20" in new and "b = 2\n" not in new


def test_apply_replace_not_found():
    new, err = _apply_edits("a = 1\n", [("replace", "x = 9", "y = 9")])
    assert new is None and "nicht gefunden" in err


def test_apply_replace_ambiguous():
    new, err = _apply_edits("x\nx\n", [("replace", "x", "y")])
    assert new is None and "nicht eindeutig" in err


def test_apply_append_at_end():
    new, err = _apply_edits("a = 1\n", [("append", "b = 2")])
    assert err is None and new.rstrip().endswith("b = 2")


def test_lost_defs_truncation_guard():
    old = "def a():\n    pass\n\n\ndef b():\n    pass\n"
    assert _lost_defs(old, "def a():\n    pass\n") == ["b"]
    assert _lost_defs(old, old + "\n\ndef c():\n    pass\n") == []
