"""Probe the exact activation command, including its startup environment."""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def probe(command: list[str], expected: list[str]) -> None:
    async with asyncio.timeout(60):
        async with stdio_client(StdioServerParameters(command=command[0], args=command[1:], env=dict(os.environ))) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                names = [tool.name for tool in response.tools]
                if names != expected:
                    raise RuntimeError("Unexpected LingxiAdvisor MCP tools")
    print(json.dumps({"tools": names}))


if __name__ == "__main__":
    asyncio.run(probe(json.loads(sys.argv[1]), json.loads(sys.argv[2])))
