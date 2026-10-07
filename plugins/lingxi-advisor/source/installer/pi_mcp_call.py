"""Invoke one managed LingxiAdvisor MCP tool for the Pi extension bridge."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _content(response: Any) -> Any:
    structured = getattr(response, "structuredContent", None)
    if structured is not None:
        return structured
    values = []
    for item in getattr(response, "content", ()):
        if getattr(item, "type", None) == "text":
            text = str(getattr(item, "text", ""))
            try:
                values.append(json.loads(text))
            except ValueError:
                values.append(text)
        elif hasattr(item, "model_dump"):
            values.append(item.model_dump(mode="json"))
    return values[0] if len(values) == 1 else values


def _response(response: Any) -> dict[str, Any]:
    payload = _content(response)
    if getattr(response, "isError", False):
        return {"ok": False, "error": payload}
    return {"ok": True, "result": payload}


async def serve(command: list[str]) -> None:
    """Keep one MCP session alive for all calls made by a Pi session."""
    async with stdio_client(
        StdioServerParameters(command=command[0], args=command[1:], env=dict(os.environ))
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            while line := await asyncio.to_thread(sys.stdin.readline):
                request = json.loads(line)
                response = await session.call_tool(request["tool"], request["arguments"])
                print(json.dumps({"id": request["id"], **_response(response)}), flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(serve(json.loads(sys.argv[1])))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"LingxiAdvisor MCP call failed ({type(exc).__name__})"}))
        raise SystemExit(2) from None
