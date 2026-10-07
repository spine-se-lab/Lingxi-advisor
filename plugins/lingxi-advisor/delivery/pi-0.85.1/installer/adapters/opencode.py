from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..contracts import InstallError
from ..managed_layout import ManagedLayout


def _run(executable: str, args: list[str], *, cwd: Path, config_root: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        # OpenCode 1.18.25 resolves global configuration and Skills from
        # XDG_CONFIG_HOME/opencode. The managed installer intentionally has a
        # filtered environment, so derive that standard root from the selected
        # host config directory instead of relying on an ambient XDG value.
        "XDG_CONFIG_HOME": str(config_root.parent),
        "OPENCODE_CONFIG_DIR": str(config_root),
    }
    if args == ["debug", "skill"]:
        # OpenCode 1.18.25 can exit before a large console.log drains to a pipe.
        # A regular, unnamed stdout file makes that write synchronous. The
        # temporary descriptor is closed immediately after parsing its output.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
            completed = subprocess.run([executable, *args], cwd=cwd, env=env,
                stdout=output, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                check=False, timeout=120)
            output.seek(0)
            return subprocess.CompletedProcess(completed.args, completed.returncode, output.read(), completed.stderr)
    return subprocess.run(
        [executable, *args], cwd=cwd, env=env, capture_output=True,
        text=True, encoding="utf-8", check=False, timeout=120,
    )


def version(target: Path, executable: str | None = None) -> str:
    command = str(executable or "").strip()
    if not command:
        raise InstallError("OpenCode executable is required")
    completed = _run(command, ["--version"], cwd=target, config_root=target)
    if completed.returncode:
        raise InstallError("OpenCode --version failed")
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", completed.stdout + completed.stderr)
    if not match:
        raise InstallError("OpenCode version could not be parsed")
    return match.group(1)


def _skip(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith("//", index):
            index = text.find("\n", index)
            if index < 0:
                return len(text)
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise InstallError("OpenCode JSONC contains an unterminated comment")
            index = end + 2
        else:
            break
    return index


def _string_end(text: str, index: int) -> int:
    index += 1
    while index < len(text):
        if ord(text[index]) == 92:
            index += 2
        elif text[index] == '"':
            return index + 1
        else:
            index += 1
    raise InstallError("OpenCode JSONC contains an unterminated string")


def _container_end(text: str, index: int) -> int:
    pairs = {"{": "}", "[": "]"}
    stack = [pairs[text[index]]]
    index += 1
    while index < len(text):
        if text[index] == '"':
            index = _string_end(text, index)
            continue
        if text.startswith("//", index) or text.startswith("/*", index):
            index = _skip(text, index)
            continue
        if text[index] in pairs:
            stack.append(pairs[text[index]])
        elif text[index] == stack[-1]:
            stack.pop()
            if not stack:
                return index + 1
        index += 1
    raise InstallError("OpenCode JSONC contains an unterminated object")


def _value_end(text: str, index: int) -> int:
    index = _skip(text, index)
    if index >= len(text):
        raise InstallError("OpenCode JSONC property has no value")
    if text[index] == '"':
        return _string_end(text, index)
    if text[index] in "[{":
        return _container_end(text, index)
    end = index
    while end < len(text) and not text[end].isspace() and text[end] not in ",}]/":
        end += 1
    return end


def _properties(text: str, object_start: int) -> tuple[dict[str, tuple[int, int, int]], int]:
    if object_start >= len(text) or text[object_start] != "{":
        raise InstallError("OpenCode JSONC root must be an object")
    close = _container_end(text, object_start) - 1
    result: dict[str, tuple[int, int, int]] = {}
    index = object_start + 1
    while True:
        index = _skip(text, index)
        while index < close and text[index] == ",":
            index = _skip(text, index + 1)
        if index >= close:
            break
        if text[index] != '"':
            raise InstallError("OpenCode JSONC object keys must be quoted")
        key_start = index
        key_end = _string_end(text, index)
        key = json.loads(text[key_start:key_end])
        colon = _skip(text, key_end)
        if colon >= close or text[colon] != ":":
            raise InstallError("OpenCode JSONC property is missing ':'")
        value_start = _skip(text, colon + 1)
        value_end = _value_end(text, value_start)
        result[str(key)] = (key_start, value_start, value_end)
        index = value_end
    return result, close


def _set_property(text: str, key: str, value: dict[str, Any], *, indent: str) -> str:
    start = _skip(text, 0)
    properties, close = _properties(text, start)
    rendered = json.dumps(value, ensure_ascii=False, indent=2)
    rendered = rendered.replace("\n", "\n" + indent)
    if key in properties:
        _, value_start, value_end = properties[key]
        return text[:value_start] + rendered + text[value_end:]
    if properties:
        last_end = next(reversed(properties.values()))[2]
        following = _skip(text, last_end)
        if following >= len(text) or text[following] != ",":
            # Place the separator before trailing comments, including // comments.
            text = text[:last_end] + "," + text[last_end:]
            close += 1
    addition = f'\n{indent}"{key}": {rendered}\n'
    return text[:close] + addition + text[close:]


def _strip_jsonc(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == '"':
            end = _string_end(text, index)
            output.append(text[index:end])
            index = end
        elif text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            output.append(" ")
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise InstallError("OpenCode JSONC contains an unterminated comment")
            index = end + 2
            output.append(" ")
        elif text[index] == ",":
            following = _skip(text, index + 1)
            if following >= len(text) or text[following] not in "}]":
                output.append(",")
            index += 1
        else:
            output.append(text[index])
            index += 1
    return "".join(output)


def _parse_config(text: str) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise InstallError(f"OpenCode JSONC contains duplicate property: {name}")
            value[name] = item
        return value

    value = json.loads(_strip_jsonc(text), object_pairs_hook=unique)
    if not isinstance(value, dict) or ("mcp" in value and not isinstance(value["mcp"], dict)):
        raise InstallError("OpenCode configuration and mcp must be objects")
    return value


def _timeout_ms(layout: ManagedLayout) -> int:
    # OpenCode applies a 60 s default to MCP tool calls; Search with knowledge
    # generation routinely runs for several minutes.
    return layout.configuration.mcp_request_timeout_seconds * 1000


def _desired(layout: ManagedLayout) -> dict[str, Any]:
    return {
        "type": "local",
        "command": [*layout.mcp_command(), "--compact-search-results"],
        "enabled": True,
        "timeout": _timeout_ms(layout),
    }


def _operator_desired(layout: ManagedLayout) -> dict[str, Any]:
    return {
        "type": "local",
        "command": layout.mcp_command("operator"),
        "enabled": True,
        "timeout": _timeout_ms(layout),
    }


# OpenAI-compatible endpoints of OpenCode's built-in providers.
_PROVIDER_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
}


def suggest_model(target: Path, config_root: Path) -> str:
    """Describe --set values matching the host model, or "" when unknown.

    Only the non-secret model id and endpoint are read; the API key always
    comes from the startup environment.
    """
    for root in (target, config_root):
        try:
            config = _parse_config(config_path(root).read_text(encoding="utf-8"))
        except (OSError, ValueError, InstallError):
            continue
        model = config.get("model")
        if not isinstance(model, str) or "/" not in model:
            continue
        provider, name = model.split("/", 1)
        providers = config.get("provider")
        entry = providers.get(provider) if isinstance(providers, dict) else None
        options = entry.get("options") if isinstance(entry, dict) else None
        endpoint = options.get("baseURL") if isinstance(options, dict) else None
        endpoint = endpoint if isinstance(endpoint, str) else _PROVIDER_ENDPOINTS.get(provider)
        if endpoint:
            return (f"OpenCode currently uses {model}; to reuse it pass "
                    f"--set gate_model_name={name} --set gate_model_base_url={endpoint}")
        return ""
    return ""


def _desired_servers(layout: ManagedLayout) -> dict[str, dict[str, Any]]:
    return {
        "lingxi-advisor": _desired(layout),
        "lingxi-advisor-operator": _operator_desired(layout),
    }


def config_path(config_root: Path) -> Path:
    json_file = config_root / "opencode.json"
    jsonc_file = config_root / "opencode.jsonc"
    if json_file.exists() and jsonc_file.exists():
        raise InstallError("Both opencode.json and opencode.jsonc exist; select one before installation")
    return jsonc_file if jsonc_file.exists() or not json_file.exists() else json_file


def _read_server(path: Path, name: str = "lingxi-advisor") -> dict[str, Any] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    properties, _close = _properties(text, _skip(text, 0))
    if "mcp" not in properties:
        return None
    _, value_start, value_end = properties["mcp"]
    mcp = json.loads(_strip_jsonc(text[value_start:value_end]))
    return mcp.get(name) if isinstance(mcp, dict) else None


def probe(
    target: Path,
    config_root: Path,
    executable: str | None,
    record: dict[str, Any],
    layout: ManagedLayout,
) -> list[dict[str, Any]]:
    detected = version(target, executable)
    path = config_path(config_root)
    desired = _desired_servers(layout)
    expected_hash = record.get("host_binding", {}).get("mcp_servers_sha256")
    current = {
        name: server
        for name in desired
        if (server := _read_server(path, name)) is not None
    }
    # After a successful adoption write, verify sees the new managed commands
    # while the untouched legacy record still describes the old commands.
    # Exact desired content already proves this binding; otherwise require the
    # legacy hash before replacing anything.
    if expected_hash and current != desired:
        current_hash = hashlib.sha256(
            json.dumps(current, sort_keys=True).encode()
        ).hexdigest()
        if current_hash != expected_hash:
            raise InstallError("OpenCode LingxiAdvisor MCP registrations drifted")
    elif any(current[name] != desired[name] for name in current):
        raise InstallError("An OpenCode LingxiAdvisor MCP name is owned by another installation")
    return [{"kind": "capability_probe", "names": ["skill", "mcp_stdio"],
             "target_version": detected, "config": str(path)}]


def render_config(path: Path, layout: ManagedLayout) -> bytes:
    text = path.read_text(encoding="utf-8") if path.exists() else "{\n}\n"
    _parse_config(text)
    properties, _close = _properties(text, _skip(text, 0))
    desired = _desired_servers(layout)
    if "mcp" in properties:
        _, value_start, value_end = properties["mcp"]
        updated = text[value_start:value_end]
        for name, server in desired.items():
            updated = _set_property(updated, name, server, indent="    ")
        text = text[:value_start] + updated + text[value_end:]
    else:
        text = _set_property(text, "mcp", desired, indent="  ")
    _parse_config(text)
    return text.encode("utf-8")


def verify_binding(target: Path, layout: ManagedLayout, executable: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    path = config_path(layout.config_root)
    desired = _desired_servers(layout)
    if any(_read_server(path, name) != server for name, server in desired.items()):
        raise InstallError("OpenCode LingxiAdvisor MCP registration is missing or drifted")
    skill = _run(executable, ["debug", "skill"], cwd=target, config_root=layout.config_root)
    try:
        skills = json.loads(skill.stdout)
        discovered = {item["name"]: item.get("location") for item in skills if isinstance(item, dict)}
    except (ValueError, KeyError, TypeError):
        discovered = {}
    if skill.returncode or any(not discovered.get(name) or
        Path(discovered[name]).resolve() != (layout.skill_path("opencode", name) / "SKILL.md").resolve()
        for name in ("lingxi-advisor", "knowledge-preparation-operator")):
        raise InstallError("OpenCode did not discover both LingxiAdvisor Skills")
    mcp = _run(executable, ["mcp", "list"], cwd=target, config_root=layout.config_root)
    mcp_output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", mcp.stdout + mcp.stderr)
    if mcp.returncode or any(
        re.search(r"(?m)^[^\w\r\n]*" + re.escape(name) + r"[ \t]+connected[ \t]*$", mcp_output) is None
        for name in ("lingxi-advisor", "lingxi-advisor-operator")
    ):
        raise InstallError("OpenCode did not connect to both LingxiAdvisor MCP servers")
    return [
        {
            "kind": "skills",
            "names": ["lingxi-advisor", "knowledge-preparation-operator"],
            "paths": [
                str(layout.skill_root("opencode")),
                str(layout.skill_path("opencode", "knowledge-preparation-operator")),
            ],
        },
        {"kind": "opencode_config", "path": str(path), "status": "loadable", "mcp_status": "connected"},
    ]
