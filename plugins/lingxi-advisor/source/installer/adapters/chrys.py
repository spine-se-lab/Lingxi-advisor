from __future__ import annotations

import json
import subprocess
import tomllib
import os
from pathlib import Path
from typing import Any

from ..contracts import (
    OPERATOR_TOOLS,
    PROFILE_ID,
    PROFILE_NAME,
    RUNTIME_TOOLS,
    InstallError,
)
from ..managed_layout import ManagedLayout


CODE_PROFILE = Path("src/chrys/service/profiles/agents/builtins/Code.yaml")


def _host_python(target: Path) -> list[str]:
    local = target / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return [str(local)] if local.is_file() else ["uv", "run", "--locked", "--no-sync", "python"]


_MANAGED_PROFILE_SCRIPT = r'''
import json, sys, tempfile
from pathlib import Path
import yaml
from chrys.service.profiles.agents.loader import load_profile_from_yaml
from chrys.service.skills.adapter import create_skills_provider
from chrys.service.mcp.adapter import MCPAdapter
payload = json.load(sys.stdin)
def check(path):
    profile = load_profile_from_yaml(path)
    assert profile.name == payload['name']
    assert all(item in profile.skills.paths for item in payload['skills'])
    actual = {item.name: item for item in profile.tools.mcp}
    for desired in payload['servers']:
        item = actual[desired['name']]
        assert item.command == desired['command']
        assert list(item.args) == desired['args']
        assert list(item.allowed_tools) == desired['allowed_tools']
        assert item.request_timeout == desired['request_timeout']
    return profile
if payload['operation'] == 'render':
    data = yaml.safe_load(Path(payload['template']).read_text())
    data.update(name=payload['name'], id=payload['id'], display_name='Code - Lingxi Advisor',
                description='Code Agent with Lingxi Advisor runtime and knowledge preparation')
    tools = data.setdefault('tools', {})
    names = {item['name'] for item in payload['servers']}
    tools['mcp'] = [item for item in (tools.get('mcp') or []) if item.get('name') not in names] + payload['servers']
    skills = data.setdefault('skills', {})
    skills['paths'] = list(dict.fromkeys([*(skills.get('paths') or []), *payload['skills']]))
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    with tempfile.TemporaryDirectory(prefix='lingxi_advisor-profile-check-') as directory:
        file = Path(directory) / 'profile.yaml'
        file.write_text(text)
        check(file)
    print(json.dumps({'profile': text}))
else:
    import asyncio
    profile = check(Path(payload['profile']))
    async def verify():
        provider, warnings = await create_skills_provider(profile.skills)
        assert provider is not None
        expected_skills = {'lingxi-advisor', 'knowledge-preparation-operator'}
        assert expected_skills <= set(provider.skill_names())
        adapter = MCPAdapter(stdio_cwd=payload['cwd'])
        try:
            names = {item['name'] for item in payload['servers']}
            await adapter.connect_all([item for item in profile.tools.mcp if item.name in names])
            assert not adapter.failures
            assert set(adapter.server_names) == names
            tools = adapter.tool_names_by_server
            for desired in payload['servers']:
                # Chrys maps dotted MCP names to provider-safe hyphen aliases;
                # normalize names for comparison with the MCP declaration.
                actual = {name.replace('.', '_').replace('-', '_') for name in tools[desired['name']]}
                assert actual == {name.replace('.', '_') for name in desired['allowed_tools']}
            return {'loaded': True, 'skills': sorted(expected_skills), 'servers': tools}
        finally:
            await adapter.disconnect_all()
    print(json.dumps(asyncio.run(verify())))
'''


def managed_profile(target: Path, layout, *, verify: bool = False) -> bytes | dict[str, Any]:
    servers = []
    for name, profile, tools in (("lingxi-advisor", "runtime", RUNTIME_TOOLS),
                                 ("lingxi-advisor-operator", "operator", OPERATOR_TOOLS)):
        command = layout.mcp_command(profile)
        if profile == "runtime":
            command.append("--compact-search-results")
        servers.append({"name": name, "transport": "stdio", "command": command[0], "args": command[1:],
                        "env": {}, "allowed_tools": list(tools), "enabled": True,
                        "request_timeout": layout.configuration.mcp_request_timeout_seconds})
    payload = {"operation": "verify" if verify else "render", "name": PROFILE_NAME, "id": PROFILE_ID,
               "template": str(target / CODE_PROFILE), "profile": str(profile_path(layout.config_root)),
               "skills": [str(layout.private_skill), str(layout.private_operator_skill)], "servers": servers, "cwd": str(target)}
    completed = subprocess.run([*_host_python(target), "-B", "-c", _MANAGED_PROFILE_SCRIPT],
        input=json.dumps(payload), cwd=target, capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if completed.returncode:
        raise InstallError("Chrys Profile loader lacks or rejected the required Skill/MCP schema")
    try:
        result = json.loads(completed.stdout)
        return result if verify else result["profile"].encode("utf-8")
    except (ValueError, AttributeError) as exc:
        raise InstallError("Chrys Profile loader returned invalid probe output") from exc


def version(target: Path, executable: str | None = None) -> str:
    try:
        with (target / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream).get("project", {})
    except OSError as exc:
        raise InstallError(f"Target is not a Chrys checkout: {exc}") from exc
    if project.get("name") != "chrys":
        raise InstallError("Target pyproject.toml is not the Chrys project")
    value = str(project.get("version") or "")
    if not value:
        raise InstallError("Chrys target version is missing")
    if value != "0.28.0":
        raise InstallError("LingxiAdvisor requires Chrys 0.28.0")
    return value


def profile_path(config_root: Path) -> Path:
    return config_root / "agents" / f"{PROFILE_NAME}.yaml"
