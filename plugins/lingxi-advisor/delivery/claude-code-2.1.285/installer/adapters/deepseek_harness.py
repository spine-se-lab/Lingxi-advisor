"""DeepSeek Harness 0.2.0-rc.2 profile-bundle activation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from ..contracts import InstallError
from ..managed_layout import ManagedLayout


DSH_VERSION = "0.2.0-rc.2"
DSH_PROFILE = "web"
BUNDLE_NAME = "codehelix-lingxi-advisor-dsh"
MCP_ENTRY_ID = "codehelix-lingxi-advisor-mcp"
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
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DSH_HOME": str(config_root), "NO_COLOR": "1"}
    return subprocess.run(
        [executable, *args], cwd=cwd, env=env, capture_output=True,
        text=True, check=False, timeout=timeout,
    )


def version(target: Path, config_root: Path, executable: str | None) -> str:
    command = str(executable or "").strip()
    if not command:
        raise InstallError("DeepSeek Harness executable is required; ensure dsh is on PATH")
    completed = _run(command, ["--version"], cwd=target, config_root=config_root)
    if completed.returncode:
        raise InstallError("DeepSeek Harness --version failed")
    match = re.search(
        r"(?<!\d)(\d+\.\d+\.\d+-rc\.\d+)(?!\d)",
        (completed.stdout or "") + (completed.stderr or ""),
    )
    if not match:
        raise InstallError("DeepSeek Harness version could not be parsed")
    detected = match.group(1)
    if detected != DSH_VERSION:
        raise InstallError(f"This adapter supports DeepSeek Harness {DSH_VERSION}; found {detected}")
    return detected


def bundle_root(layout: ManagedLayout) -> Path:
    return layout.config_root / "lingxi/advisor/deepseek-bundle"


def package_path(layout: ManagedLayout) -> Path:
    return bundle_root(layout) / "package.json"


def patch_path(layout: ManagedLayout) -> Path:
    return bundle_root(layout) / "cordis.patch.yml"


def profile_path(config_root: Path) -> Path:
    return config_root / "profiles" / DSH_PROFILE / "package.json"


def render_package(plugin_version: str) -> bytes:
    value = {
        "name": BUNDLE_NAME,
        "version": plugin_version,
        "private": True,
        "type": "module",
        "files": ["cordis.patch.yml"],
        "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
    }
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def render_patch(layout: ManagedLayout, target: Path) -> bytes:
    command = layout.mcp_command("runtime")
    lines = [
        "- insert:",
        f"    - id: {MCP_ENTRY_ID}",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        "        transport: stdio",
        "        serverName: lingxi_advisor",
        f"        command: {json.dumps(command[0])}",
        "        args:",
        *(f"          - {json.dumps(argument)}" for argument in command[1:]),
        "        env:",
        *(f"          {name}: !!js process.env.{name} ?? ''" for name in ENVIRONMENT),
        f"        cwd: {json.dumps(str(target))}",
        "        failOnStartupError: true",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _profile(config_root: Path) -> dict[str, Any] | None:
    path = profile_path(config_root)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError("DeepSeek Harness web profile package.json is invalid") from exc
    if not isinstance(value, dict):
        raise InstallError("DeepSeek Harness web profile package.json must be an object")
    return value


def _dependency(value: dict[str, Any] | None) -> str | None:
    dependencies = (value or {}).get("dependencies", {})
    return dependencies.get(BUNDLE_NAME) if isinstance(dependencies, dict) else None


def _bundles(value: dict[str, Any] | None) -> list[str]:
    profile = ((value or {}).get("dsh") or {}).get("profile", {})
    bundles = profile.get("bundles", []) if isinstance(profile, dict) else []
    return [str(item) for item in bundles] if isinstance(bundles, list) else []


def _dependency_matches(specifier: str | None, root: Path, profile: Path) -> bool:
    if not specifier:
        return False
    value = specifier
    for prefix in ("link:", "file:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = profile.parent / candidate
    try:
        return candidate.resolve() == root.resolve()
    except (OSError, RuntimeError):
        return False


def probe(
    target: Path,
    config_root: Path,
    executable: str | None,
    layout: ManagedLayout,
) -> list[dict[str, object]]:
    detected = version(target, config_root, executable)
    if not shutil.which("pnpm"):
        raise InstallError("DeepSeek Harness plugin lifecycle requires pnpm on PATH")
    current = _profile(config_root)
    dependency = _dependency(current)
    bundles = _bundles(current)
    if dependency and not _dependency_matches(dependency, bundle_root(layout), profile_path(config_root)):
        raise InstallError("DeepSeek Harness LingxiAdvisor bundle name is owned by another installation")
    if BUNDLE_NAME in bundles and not dependency:
        raise InstallError("DeepSeek Harness LingxiAdvisor bundle registration is incomplete or foreign")
    return [{
        "kind": "capability_probe",
        "names": ["skill", "mcp_stdio", "profile_bundle"],
        "target_version": detected,
        "profile": DSH_PROFILE,
    }]


def install_bundle(target: Path, layout: ManagedLayout, executable: str) -> dict[str, object]:
    current = _profile(layout.config_root)
    dependency = _dependency(current)
    if (
        _dependency_matches(dependency, bundle_root(layout), profile_path(layout.config_root))
        and BUNDLE_NAME in _bundles(current)
    ):
        return {
            "kind": "deepseek_bundle", "action": "install",
            "profile": DSH_PROFILE, "changed": False,
        }
    completed = _run(
        executable,
        ["plugin", "--profile", DSH_PROFILE, "add", str(bundle_root(layout))],
        cwd=target,
        config_root=layout.config_root,
    )
    if completed.returncode:
        raise InstallError("DeepSeek Harness failed to install the LingxiAdvisor profile bundle")
    return {
        "kind": "deepseek_bundle", "action": "install",
        "profile": DSH_PROFILE, "changed": True,
    }


def remove_bundle(target: Path, layout: ManagedLayout, executable: str) -> dict[str, object]:
    current = _profile(layout.config_root)
    dependency = _dependency(current)
    if not dependency and BUNDLE_NAME not in _bundles(current):
        return {"kind": "deepseek_bundle", "action": "remove", "profile": DSH_PROFILE, "changed": False}
    if not _dependency_matches(dependency, bundle_root(layout), profile_path(layout.config_root)):
        raise InstallError("Refusing to remove a foreign DeepSeek Harness LingxiAdvisor bundle")
    completed = _run(
        executable,
        ["plugin", "--profile", DSH_PROFILE, "remove", BUNDLE_NAME],
        cwd=target,
        config_root=layout.config_root,
    )
    if completed.returncode:
        raise InstallError("DeepSeek Harness failed to remove the LingxiAdvisor profile bundle")
    return {"kind": "deepseek_bundle", "action": "remove", "profile": DSH_PROFILE, "changed": True}


def verify_binding(target: Path, layout: ManagedLayout, executable: str) -> list[dict[str, object]]:
    current = _profile(layout.config_root)
    if not _dependency_matches(_dependency(current), bundle_root(layout), profile_path(layout.config_root)):
        raise InstallError("DeepSeek Harness LingxiAdvisor profile dependency is missing or drifted")
    if BUNDLE_NAME not in _bundles(current):
        raise InstallError("DeepSeek Harness LingxiAdvisor bundle is not enabled in the web profile")
    completed = _run(
        executable,
        ["--profile", DSH_PROFILE, "--dump-config"],
        cwd=target,
        config_root=layout.config_root,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode or MCP_ENTRY_ID not in output or "@deepseek-ai/dsh-mcp-client" not in output:
        raise InstallError("DeepSeek Harness did not compose the LingxiAdvisor MCP bundle")
    skill = layout.skill_path("deepseek-harness", "lingxi-advisor")
    if not (skill / "SKILL.md").is_file():
        raise InstallError("DeepSeek Harness LingxiAdvisor Skill is missing")
    return [
        {"kind": "skills", "names": ["lingxi-advisor"], "paths": [str(skill)]},
        {"kind": "deepseek_bundle", "status": "composed", "profile": DSH_PROFILE},
    ]
