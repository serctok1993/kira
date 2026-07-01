"""Test: als TEXT geleakte Tool-Calls (DeepSeek-DSML-Format) werden geparst + ausfuehrbar.

Der Parser macht guenstige Modelle (DeepSeek V4 Flash) fuer die agentische Schleife nutzbar,
auch wenn sie Tool-Calls nicht als strukturierte tool_calls, sondern als Markup-Text liefern.
"""
from core.agency.act import _parse_leaked_tool_calls

# Echtes DeepSeek-Format mit fullwidth-Pipe ｜ (U+FF5C), wie im Live-Trace beobachtet.
_DSML = (
    "<｜｜DSML｜｜tool_calls>\n"
    '<｜｜DSML｜｜invoke name="db_query">\n'
    '<｜｜DSML｜｜parameter name="sql" string="true">SELECT type FROM events LIMIT 3</｜｜DSML｜｜parameter>\n'
    "</｜｜DSML｜｜invoke>\n"
    '<｜｜DSML｜｜invoke name="read_file">\n'
    '<｜｜DSML｜｜parameter name="path">core/x.py</｜｜DSML｜｜parameter>\n'
    "</｜｜DSML｜｜invoke>\n"
    "</｜｜DSML｜｜tool_calls>"
)


def test_parse_leaked_dsml_two_calls():
    calls = _parse_leaked_tool_calls(_DSML)
    assert len(calls) == 2
    assert calls[0]["name"] == "db_query"
    assert "SELECT type" in calls[0]["args"]["sql"]
    assert calls[1]["name"] == "read_file"
    assert calls[1]["args"]["path"] == "core/x.py"


def test_parse_leaked_typing_number():
    txt = '<invoke name="read_file"><parameter name="offset">40</parameter></invoke>'
    calls = _parse_leaked_tool_calls(txt)
    assert calls[0]["args"]["offset"] == 40  # numerisch getypt via json


def test_parse_leaked_none_on_normal_text():
    assert _parse_leaked_tool_calls("Hallo, hier ist deine Antwort. Kein Tool noetig.") == []
    assert _parse_leaked_tool_calls("") == []
