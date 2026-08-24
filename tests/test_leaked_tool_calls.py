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


# --- Hermes-Stil (Qwen/Nemotron) -----------------------------------------------------
# Echter Endtext des Terminal-Bench-Laufs 'mailman' (24.08.2026): der Lauf endete nach
# 4,68 Mio. Token mit genau diesem Block als "Ergebnis" — ein Befehl, der nie lief.
_HERMES = (
    "<tool_call>\n"
    "<function=terminal>\n"
    "<parameter=befehl>\n"
    "python3 /app/eval.py 2>&1\n"
    "</parameter>\n"
    "<parameter=timeout_sek>\n"
    "120\n"
    "</parameter>\n"
    "</function>\n"
    "</tool_call>"
)


def test_parse_leaked_hermes_function_style():
    calls = _parse_leaked_tool_calls(_HERMES)
    assert len(calls) == 1
    assert calls[0]["name"] == "terminal"
    assert calls[0]["args"]["befehl"] == "python3 /app/eval.py 2>&1"
    assert calls[0]["args"]["timeout_sek"] == 120  # numerisch getypt


def test_parse_leaked_hermes_json_style():
    txt = '<tool_call>{"name": "read_file", "arguments": {"path": "core/x.py"}}</tool_call>'
    calls = _parse_leaked_tool_calls(txt)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"
    assert calls[0]["args"]["path"] == "core/x.py"


def test_parse_leaked_hermes_json_arguments_als_string():
    """Manche Anbieter verschachteln arguments als JSON-String — auch das ist ein Aufruf."""
    txt = '<tool_call>{"name": "terminal", "arguments": "{\\"befehl\\": \\"ls /app\\"}"}</tool_call>'
    calls = _parse_leaked_tool_calls(txt)
    assert calls[0]["args"]["befehl"] == "ls /app"


def test_parse_leaked_kaputtes_json_wirft_nicht():
    assert _parse_leaked_tool_calls('<tool_call>{"name": "x", "argu</tool_call>') == []
