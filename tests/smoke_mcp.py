"""Smoke-Test: Echter filesystem-MCP-Server via quick_call.

Startet npx @modelcontextprotocol/server-filesystem, listet Tools,
ruft EIN Tool auf, zeigt die Ergebnisse.
"""

import asyncio
import os
import sys

# Windows: Konsolen-Encoding auf UTF-8 zwingen
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agency.mcp.client import quick_call


async def main():
    target_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"[Zielverzeichnis] {target_dir}")
    print("[Start] Starte filesystem-MCP-Server ...\n")

    result = await quick_call(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", target_dir],
        tool_name="read_text_file",
        tool_args={"path": "README.md"},
    )

    print("=" * 60)
    print("GELISTETE TOOLS:")
    print("=" * 60)
    for tool in result["tools"]:
        print(f"  * {tool['name']}")
        if tool["description"]:
            print(f"    {tool['description'][:120]}")

    print("\n" + "=" * 60)
    print("AUFRUF: read_text_file('README.md')")
    print("=" * 60)
    call = result["call"]
    if call is None:
        print("FEHLER: Kein Call-Ergebnis!")
    elif call["isError"]:
        print(f"FEHLER: {call['content']}")
    else:
        for block in call["content"]:
            if block["type"] == "text":
                text = block["text"]
                if len(text) > 1500:
                    text = text[:1500] + "\n\n... (gekuerzt)"
                print(text)

    print("\nSmoke-Test abgeschlossen.")


if __name__ == "__main__":
    asyncio.run(main())