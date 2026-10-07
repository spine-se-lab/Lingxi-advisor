"""Pi 0.85.1 activation for the shared managed LingxiAdvisor Runtime."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from ..contracts import InstallError
from ..managed_layout import ManagedLayout


PI_PACKAGE = "@earendil-works/pi-coding-agent"


def _run(command: list[str], *, cwd: Path, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def package_root(executable: str) -> Path:
    try:
        current = Path(executable).resolve().parent
    except (OSError, RuntimeError) as exc:
        raise InstallError("Pi executable could not be resolved") from exc
    package_parts = tuple(PI_PACKAGE.split("/"))
    roots = (current, *current.parents)
    candidates = dict.fromkeys(
        candidate
        for root in roots
        for candidate in (
            root,
            root.joinpath(*package_parts),
            root.joinpath("node_modules", *package_parts),
            root.joinpath("lib", "node_modules", *package_parts),
        )
    )
    for candidate in candidates:
        package = candidate / "package.json"
        if not package.is_file():
            continue
        try:
            if json.loads(package.read_text(encoding="utf-8")).get("name") == PI_PACKAGE:
                return candidate
        except (OSError, ValueError):
            continue
    raise InstallError(
        "Pi npm installation not found; LingxiAdvisor requires the Pi 0.85.1 Node distribution"
    )


def version(target: Path, executable: str | None) -> tuple[str, Path]:
    command = str(executable or "").strip()
    if not command:
        raise InstallError("Pi executable is required; ensure pi is on PATH")
    completed = _run([command, "--version"], cwd=target)
    if completed.returncode:
        raise InstallError("Pi --version failed")
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", completed.stdout + completed.stderr)
    if not match:
        raise InstallError("Pi version could not be parsed")
    detected = match.group(1)
    if detected != "0.85.1":
        raise InstallError(f"This adapter supports Pi 0.85.1; found {detected}")
    return detected, package_root(command)


def activation_path(config_root: Path) -> Path:
    return config_root / "extensions" / "codehelix-lingxi-advisor.js"


def render_activation(layout: ManagedLayout) -> bytes:
    module = (layout.package_root / "pi" / "extension.mjs").resolve().as_uri()
    binding = {
        "python": str(layout.python),
        "packageRoot": str(layout.package_root),
        "config": str(layout.binding_file),
        "dataRoot": str(layout.data_root),
        "runtimeCommand": layout.mcp_command("runtime"),
    }
    text = (
        "// Managed by CodeHelix: lingxi-advisor.\n"
        "import { Type } from '@earendil-works/pi-ai';\n"
        f"import lingxi_advisor from {json.dumps(module)};\n"
        f"export default pi => lingxi_advisor(pi, {json.dumps(binding, ensure_ascii=False)}, Type);\n"
    )
    return text.encode("utf-8")


def probe(target: Path, config_root: Path, executable: str | None) -> tuple[str, Path]:
    del config_root
    return version(target, executable)


def verify_binding(
    target: Path,
    layout: ManagedLayout,
    executable: str,
) -> list[dict[str, object]]:
    detected, root = version(target, executable)
    entry = activation_path(layout.config_root)
    if not entry.is_file() or entry.read_bytes() != render_activation(layout):
        raise InstallError("Pi LingxiAdvisor activation is missing or drifted")
    expected_skill = layout.skill_path("pi", "lingxi-advisor") / "SKILL.md"
    if not expected_skill.is_file():
        raise InstallError("Pi did not discover the managed LingxiAdvisor Skill location")
    node = shutil.which("node")
    if not node:
        raise InstallError("Node is required to verify the Pi activation")
    probe_script = layout.package_root / "pi" / "verify-load.mjs"
    completed = _run(
        [node, str(probe_script), str(root), str(entry), str(target)],
        cwd=target,
        timeout=120,
    )
    try:
        loaded = json.loads(completed.stdout)
    except ValueError as exc:
        raise InstallError("Pi activation loader returned invalid probe output") from exc
    aliases = {"lingxi_advisor_search", "lingxi_advisor_apply"}
    if completed.returncode or not loaded.get("loaded") or not aliases.issubset(set(loaded.get("tools") or [])):
        raise InstallError("Pi failed to load the LingxiAdvisor Search/Apply tools")
    return [
        {
            "kind": "pi_extension",
            "status": "loaded",
            "path": str(entry),
            "version": detected,
            "tools": sorted(aliases),
        },
        {
            "kind": "skills",
            "names": ["lingxi-advisor"],
            "paths": [str(layout.skill_path("pi", "lingxi-advisor"))],
        },
    ]
