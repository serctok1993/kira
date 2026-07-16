"""Schnelle, offline Selbst-Tests fuer Kiras Kern. Laeuft nach jedem self_edit
(selfdev.verify_cmd) -> faellt einer durch, wird die Aenderung automatisch zurueckgerollt.
Bewusst ohne Netz/LLM, damit es schnell + deterministisch ist.
"""
import core.agency.tools.builtin  # noqa: F401  -> registriert die Tools


def test_tools_registered():
    from core.agency.tools.registry import all_tools

    names = {t.name for t in all_tools()}
    for n in ("web_fetch", "read_file", "run_command", "self_edit",
              "plan_and_execute", "learn_skill", "cron_add"):
        assert n in names, f"Tool {n} fehlt"


def test_tool_schemas_valid():
    from core.agency.tools.registry import tool_schemas

    sch = tool_schemas()
    assert sch
    for s in sch:
        assert s["type"] == "function"
        assert s["function"]["name"]
        assert s["function"]["parameters"]["type"] == "object"


def test_parse_act():
    from core.agency.act import _parse_act

    assert _parse_act('ACT web_fetch {"url": "https://x"}') == ("web_fetch", {"url": "https://x"})
    assert _parse_act("nur normaler text ohne werkzeug") is None


def test_parse_act_leak_recovery():
    # c4-Vorfall (16.07., Telegram-Live-Chat): Tool-Calls als Code-Fence OHNE
    # ACT-Praefix gingen als ANTWORT raus. Beide Leaks woertlich aus der events-DB:
    from core.agency.act import _parse_act

    assert _parse_act('🔍 **Check** – ich pruefe mein aktueller Status:\n\n'
                      '```bash\nhealth {}\n```') == ("health", {})
    assert _parse_act('🚀 **Gehen wir an**:\n\n```bash\n'
                      'telegram {"action": "status"}\n```') == ("telegram", {"action": "status"})
    # unbekannter Name im Fence -> trotzdem Call: der Dispatcher LEHRT dann
    # ("existiert nicht. Verfuegbar: ..."), statt den Leak durchzureichen
    # Prosa mit Python-Codebeispiel bleibt Prosa (Fence-Sprache nicht neutral)
    assert _parse_act('So gehts in Python:\n```python\nd = {"a": 1}\n```') is None
    # ACT-Zeile gewinnt weiterhin vor jedem Fence
    assert _parse_act('```bash\nfoo {}\n```\nACT health {}') == ("health", {})


def test_shell_danger_filter():
    from core.agency.shelltool import _is_dangerous

    assert _is_dangerous("rm -rf /")
    assert _is_dangerous("taskkill /PID 123 /F")
    assert _is_dangerous("format c:")
    assert not _is_dangerous("python --version")


def test_shell_exec_and_sandbox():
    from core.agency.shelltool import run_shell

    out = run_shell("echo hallo-test-123")
    assert "[exit 0]" in out and "hallo-test-123" in out
    # Sandbox: Ausbruch aus Repo/Desktop wird abgelehnt (Befehl laeuft NICHT)
    escaped = run_shell("echo x", cwd="../../../..")
    assert "erlaubt" in escaped and "[exit 0]" not in escaped


def test_cron_schedule_parsing():
    from core.agency.missions import cron

    assert cron.parse_schedule("08:00") == {"type": "daily", "time": "08:00"}
    assert cron.parse_schedule("30m")["minutes"] == 30
    assert cron.parse_schedule("2h")["minutes"] == 120


def test_server_boots():
    from fastapi.testclient import TestClient

    import core.api.server as s

    c = TestClient(s.app)
    r = c.get("/")
    assert r.status_code == 200 and "KIRA" in r.text


def test_skills_roundtrip():
    from core.mind.memory import store as m

    m.init_memory()
    m.remember("SKILL [pytest-temp]: nur ein test", role="self", kind="skill")
    assert any("pytest-temp" in s for s in m.recall_skills(50))
    for s in m.all_skills():
        if "pytest-temp" in s["text"]:
            m.delete(s["id"])
