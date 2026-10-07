"""Claude Code 2.1.285 Skill and project MCP activation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from . import opencode as jsonc
from ..contracts import InstallError
from ..managed_layout import ManagedLayout


CLAUDE_VERSION = "2.1.285"
ENVIRONMENT = (
    "GITHUB_TOKEN",
    *(f"GITHUB_TOKEN_{index}" for index in range(1, 16)),
    "LINGXI_ADVISOR_JUDGE_BASE_URL",
    "LINGXI_ADVISOR_JUDGE_API_KEY",
    "LINGXI_ADVISOR_JUDGE_MODEL",
    "LINGXI_ADVISOR_GENERATOR_BASE_URL",
    "LINGXI_ADVISOR_GENERATOR_API_KEY",
    "LINGXI_ADVISOR_GENERATOR_MODEL",
)


def _run(
    executable: str,
    args: list[str],
    *,
    cwd: Path,
    config_root: Path,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CLAUDE_CONFIG_DIR": str(config_root),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        [executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def version(target: Path, config_root: Path, executable: str | None) -> str:
    command = str(executable or "").strip()
    if not command:
        raise InstallError("Claude Code executable is required; ensure claude is on PATH")
    completed = _run(command, ["--version"], cwd=target, config_root=config_root)
    if completed.returncode:
        raise InstallError("Claude Code --version failed")
    match = re.search(
        r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)",
        (completed.stdout or "") + (completed.stderr or ""),
    )
    if not match:
        raise InstallError("Claude Code version could not be parsed")
    detected = match.group(1)
    if detected != CLAUDE_VERSION:
        raise InstallError(f"This adapter supports Claude Code {CLAUDE_VERSION}; found {detected}")
    return detected


def config_path(target: Path) -> Path:
    return target / ".mcp.json"


def _desired(layout: ManagedLayout) -> dict[str, Any]:
    command = [*layout.mcp_command("runtime"), "--compact-search-results"]
    return {
        "type": "stdio",
        "command": command[0],
        "args": command[1:],
        # Claude leaves an unset ${VAR} reference literal. The documented
        # empty fallback keeps optional credentials out of the child process
        # without placing a credential value in the project configuration.
        "env": {name: f"${{{name}:-}}" for name in ENVIRONMENT},
    }


def _parse(text: str) -> Any:
    def unique(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise InstallError(
                    f"Claude Code .mcp.json contains duplicate property: {name}"
                )
            value[name] = item
        return value

    return json.loads(jsonc._strip_jsonc(text), object_pairs_hook=unique)


def _root(path: Path) -> tuple[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8") if path.exists() else "{\n}\n"
    value = _parse(text)
    if not isinstance(value, dict):
        raise InstallError("Claude Code .mcp.json root must be an object")
    servers = value.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise InstallError("Claude Code mcpServers must be an object")
    return text, value


def read_server(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    text, _ = _root(path)
    properties, _close = jsonc._properties(text, jsonc._skip(text, 0))
    if "mcpServers" not in properties:
        return None
    _, start, end = properties["mcpServers"]
    servers = _parse(text[start:end])
    return servers.get("lingxi-advisor") if isinstance(servers, dict) else None


def render_config(path: Path, layout: ManagedLayout) -> bytes:
    text, _ = _root(path)
    properties, _close = jsonc._properties(text, jsonc._skip(text, 0))
    desired = _desired(layout)
    if "mcpServers" in properties:
        _, start, end = properties["mcpServers"]
        servers = jsonc._set_property(
            text[start:end], "lingxi-advisor", desired, indent="    "
        )
        text = text[:start] + servers + text[end:]
    else:
        text = jsonc._set_property(
            text, "mcpServers", {"lingxi-advisor": desired}, indent="  "
        )
    _root_text = _parse(text)
    if not isinstance(_root_text, dict):
        raise InstallError("Rendered Claude Code .mcp.json is invalid")
    return text.encode("utf-8")


def probe(
    target: Path,
    config_root: Path,
    executable: str | None,
    layout: ManagedLayout,
    *,
    owned: bool,
) -> list[dict[str, object]]:
    detected = version(target, config_root, executable)
    current = read_server(config_path(target))
    if current is not None and current != _desired(layout) and not owned:
        raise InstallError("Claude Code lingxi_advisor MCP name is owned by another installation")
    return [{
        "kind": "capability_probe",
        "names": ["skill", "mcp_stdio"],
        "target_version": detected,
        "config": str(config_path(target)),
    }]


def verify_binding(
    target: Path,
    layout: ManagedLayout,
    executable: str,
) -> list[dict[str, object]]:
    path = config_path(target)
    if read_server(path) != _desired(layout):
        raise InstallError("Claude Code LingxiAdvisor MCP registration is missing or drifted")
    skill = layout.skill_path("claude-code", "lingxi-advisor")
    validation = _run(
        executable,
        ["plugin", "validate", "--strict", str(layout.package_root)],
        cwd=target,
        config_root=layout.config_root,
    )
    if validation.returncode:
        raise InstallError("Claude Code rejected the managed LingxiAdvisor Skill")
    mcp = _run(
        executable,
        ["mcp", "get", "lingxi-advisor"],
        cwd=target,
        config_root=layout.config_root,
    )
    output = re.sub(
        r"\x1b\[[0-?]*[ -/]*[@-~]", "", (mcp.stdout or "") + (mcp.stderr or "")
    )
    if mcp.returncode:
        detail = " ".join(output.strip().split())[:500]
        raise InstallError(
            "Claude Code did not load the LingxiAdvisor MCP registration"
            + (f": {detail}" if detail else f" (exit {mcp.returncode})")
        )
    status = "connected" if "connected" in output.lower() else "registered"
    evidence = [
        {"kind": "skills", "names": ["lingxi-advisor"], "paths": [str(skill)]},
        {"kind": "claude_mcp", "path": str(path), "status": status},
    ]
    if status != "connected":
        # Claude Code keeps project .mcp.json servers pending until the user
        # trusts the project interactively; `claude -p` never loads them.
        evidence.append({"kind": "next_step", "status": (
            f"run `claude` once in {target}, trust the project and enable the "
            "lingxi-advisor MCP server; until then `claude -p` does not load Lingxi Advisor")})
    return evidence
