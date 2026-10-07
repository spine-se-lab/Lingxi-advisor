"""Codex MCP entry point for the unchanged Lingxi Advisor runtime profile."""
from __future__ import annotations

import os
from pathlib import Path


GITHUB_VARIABLES = ("GITHUB_TOKEN", *(f"GITHUB_TOKEN_{index}" for index in range(1, 16)))


def _inject_github_tokens(data_root: Path) -> None:
    """Fill missing GitHub token variables from the selected workspace dotenv."""
    env_file = data_root / ".env"
    if not env_file.is_file():
        return
    from dotenv import dotenv_values

    values = dotenv_values(env_file)
    for name in GITHUB_VARIABLES:
        value = values.get(name)
        if value and not os.environ.get(name):
            os.environ[name] = value


def runtime_main() -> None:
    data_root = Path(os.environ.get("LINGXI_ADVISOR_DATA_ROOT", "")).expanduser()
    if not data_root.is_absolute() or not data_root.is_dir():
        raise SystemExit(
            "LINGXI_ADVISOR_DATA_ROOT must name the existing absolute data directory selected during installation"
        )
    _inject_github_tokens(data_root)
    from lingxi_advisor.adapters.mcp.gateway import MCPServerPolicy
    from lingxi_advisor.adapters.mcp.server import create_mcp_server
    from lingxi_advisor.config import ServerSettings

    resolved = data_root.resolve()
    create_mcp_server(
        profile="runtime",
        settings=ServerSettings(project_root=resolved),
        policy=MCPServerPolicy(
            allow_update_preretrieved=True,
            allow_live_search=True,
            allow_refresh=False,
            allow_clone=False,
            allow_fetch=False,
        ),
    ).run(transport="stdio")
