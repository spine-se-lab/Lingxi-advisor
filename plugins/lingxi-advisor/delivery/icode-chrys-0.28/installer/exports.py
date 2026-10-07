from __future__ import annotations

from typing import Any

from .contracts import (
    CAPABILITY_CONTRACT,
    CAPABILITY_ID,
    CORE_DISTRIBUTION,
    CORE_VERSION,
    PLUGIN_ID,
    RUNTIME_TOOLS,
)
from .managed_layout import ManagedLayout


def capability_export(
    *,
    layout: ManagedLayout,
    agent_system: str,
    target_version: str,
    plugin_version: str,
) -> dict[str, Any]:
    return {
        "schema": "codehelix.capability_export/v1",
        "capability": {"id": CAPABILITY_ID, "contract": CAPABILITY_CONTRACT},
        "provider": {
            "plugin_id": PLUGIN_ID,
            "plugin_version": plugin_version,
            "core_distribution": CORE_DISTRIBUTION,
            "core_version": CORE_VERSION,
        },
        "target": {
            "agent_system": agent_system,
            "target_version": target_version,
        },
        "agent_binding": {
            "schema": "codehelix.agent_binding/v1",
            "skills": [{"name": "lingxi-advisor", "root": str(layout.skill_root(agent_system).absolute())}],
            "mcp_servers": [{
                "name": "lingxi-advisor",
                "transport": "stdio",
                "command": layout.mcp_command(),
                "allowed_tools": list(RUNTIME_TOOLS),
            }],
        },
        "data": {
            "root": str(layout.data_root.resolve()),
            "knowledge_cache": str((layout.data_root / "knowl_cache").resolve()),
            "mode": "read_write",
        },
    }


def validate_export(value: dict[str, Any], *, layout: ManagedLayout, agent_system: str) -> None:
    if value.get("schema") != "codehelix.capability_export/v1":
        raise ValueError("capability export schema mismatch")
    if value.get("capability") != {"id": CAPABILITY_ID, "contract": CAPABILITY_CONTRACT}:
        raise ValueError("capability export identity mismatch")
    provider = value.get("provider") or {}
    if provider.get("plugin_id") != PLUGIN_ID or provider.get("core_version") != CORE_VERSION:
        raise ValueError("capability export provider mismatch")
    target = value.get("target") or {}
    if target.get("agent_system") != agent_system:
        raise ValueError("capability export target agent mismatch")
    target_version = target.get("target_version")
    if not isinstance(target_version, str) or not target_version.strip():
        raise ValueError("capability export target version is missing")
    binding = value.get("agent_binding") or {}
    servers = binding.get("mcp_servers") or []
    if len(servers) != 1 or servers[0].get("command") != layout.mcp_command():
        raise ValueError("capability export command mismatch")
    if servers[0].get("allowed_tools") != list(RUNTIME_TOOLS):
        raise ValueError("capability export tool boundary mismatch")
    skills = binding.get("skills") or []
    if len(skills) != 1 or skills[0].get("root") != str(layout.skill_root(agent_system).absolute()):
        raise ValueError("capability export skill root mismatch")
