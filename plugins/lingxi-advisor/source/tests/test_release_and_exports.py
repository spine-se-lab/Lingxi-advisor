from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from conftest import PLUGIN_ROOT, managed_request


def test_built_locks_survive_a_git_checkout_with_autocrlf(tmp_path) -> None:
    """Hash the bytes users receive, including npm files imported with CRLF."""
    if not shutil.which("node") or not shutil.which("git"):
        pytest.skip("Node and Git are required")
    repository = tmp_path / "repository"
    plugin = repository / "plugins" / PLUGIN_ROOT.name
    ignore = shutil.ignore_patterns("delivery", "node_modules", "__pycache__", "*.pyc", ".pytest_cache", "docs")
    shutil.copytree(PLUGIN_ROOT, plugin, ignore=ignore)
    shutil.copytree(PLUGIN_ROOT.parents[1] / "plugin-kit", repository / "plugin-kit", ignore=ignore)
    attributes = PLUGIN_ROOT.parents[1] / ".gitattributes"
    if attributes.exists():
        shutil.copy2(attributes, repository / ".gitattributes")
    license_file = plugin / "source/vendor/npm/jsonc-parser/LICENSE.md"
    license_file.write_bytes(license_file.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    def run(*args, cwd=repository):
        return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=90)

    run(sys.executable, str(plugin / "build-delivery"))
    run("git", "init", "--quiet")
    run("git", "config", "core.longpaths", "true")
    run("git", "config", "core.autocrlf", "true")
    run("git", "add", "--all")
    checkout = tmp_path / "checkout"
    run("git", "checkout-index", "--all", f"--prefix={checkout.as_posix()}/")
    checked_plugin = checkout / "plugins" / PLUGIN_ROOT.name
    run("node", "-e", """
const fs = require('node:fs'), path = require('node:path');
const {validateSourceLock, validateDeliveryLock} = require(process.argv[1]);
const plugin = process.argv[2];
for (const profile of fs.readdirSync(path.join(plugin, 'delivery'))) {
    const delivery = path.join(plugin, 'delivery', profile);
    validateSourceLock(delivery, profile, path.join(plugin, 'source'));
    validateDeliveryLock(delivery, profile);
}
""", str(checkout / "plugin-kit/model/plugin.js"), str(checked_plugin))


def test_detached_delivery_resolves_worker_and_interactive_dependencies(tmp_path) -> None:
    """Local npx symlinks must not need a prior npm ci in the Delivery."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    copied = tmp_path / "detached"
    shutil.copytree(PLUGIN_ROOT / "delivery" / "opencode-1.x", copied)
    script = copied / "kit" / "probe.cjs"
    script.write_text("require('./plugin-kit/installation/orchestrator.js'); "
                      "import('@clack/prompts').then(() => console.log('ready'));\n")
    completed = subprocess.run([node, str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ready"


def test_delivery_locks_use_platform_neutral_path_order() -> None:
    for lock_path in sorted((PLUGIN_ROOT / "delivery").glob("*/delivery-lock.json")):
        files = json.loads(lock_path.read_text(encoding="utf-8"))["files"]
        assert list(files) == sorted(files), lock_path


def test_release_is_closed_world_and_export_is_resolvable(load_delivery, tmp_path) -> None:
    module = load_delivery("icode-chrys-0.28")
    info = module.validate_release_directory(
        PLUGIN_ROOT / "delivery" / "icode-chrys-0.28" / "runtime" / "lingxi-advisor-extension-0.8.6"
    )
    assert info.version == "0.8.6"
    layout = module.ManagedLayout.from_request(managed_request(tmp_path, agent="icode"))
    exported = module.exports.capability_export(
        layout=layout,
        agent_system="icode",
        target_version="0.28.0",
        plugin_version="0.1.0",
    )
    module.exports.validate_export(exported, layout=layout, agent_system="icode")
    assert exported["agent_binding"]["mcp_servers"][0]["allowed_tools"] == [
        "lingxi.advisor.search",
        "lingxi.advisor.apply",
    ]
    assert "--allow-update-preretrieved" not in exported["agent_binding"]["mcp_servers"][0]["command"]


def test_export_points_to_managed_launcher_without_changing_v1_tool_boundary(load_delivery, tmp_path) -> None:
    module = load_delivery("opencode-1.x")
    request = managed_request(tmp_path)
    request["configuration"] = {"allow_preretrieved_updates": True, "data_root": str(tmp_path / "chosen-data")}
    layout = module.ManagedLayout.from_request(request)
    exported = module.exports.capability_export(layout=layout, agent_system="opencode", target_version="1.18.25", plugin_version="0.3.11")
    module.exports.validate_export(exported, layout=layout, agent_system="opencode")
    command = exported["agent_binding"]["mcp_servers"][0]["command"]
    assert command == layout.mcp_command("runtime")
    assert len(exported["agent_binding"]["mcp_servers"]) == 1
    assert "--binding" in command and "--env-file" not in command
    assert exported["data"]["root"] == str(tmp_path / "chosen-data")


def test_release_tamper_is_rejected(load_delivery, tmp_path) -> None:
    module = load_delivery("opencode-1.x")
    source = PLUGIN_ROOT / "delivery" / "opencode-1.x" / "runtime" / "lingxi-advisor-extension-0.8.6"
    copied = tmp_path / "release"
    shutil.copytree(source, copied)
    (copied / "bundle.json").write_text("{}", encoding="utf-8")
    with pytest.raises(module.InstallError):
        module.validate_release_directory(copied)


def test_import_lock_records_clean_reproducible_release() -> None:
    lock = json.loads((PLUGIN_ROOT / "source" / "upstream" / "import-lock.json").read_text(encoding="utf-8"))
    assert lock["reproducible_builds"] == 2
    assert lock["source_overlay"] == "patches/lingxi-advisor-0.8.6-bounded-retrieval.patch"
    assert len(lock["source_overlay_sha256"]) == 64
    assert lock["release_readiness"] == {
        "upstream_full_tests": "268 passed; 3 opt-in/POSIX-only skipped on Windows",
        "atomic_writer_concurrency": "passed",
        "posix_process_tree": "passed",
    }


def test_deliveries_share_core_owned_knowledge_template_configuration() -> None:
    wheels = [
        PLUGIN_ROOT
        / "delivery"
        / profile
        / "runtime"
        / "lingxi-advisor-extension-0.8.6"
        / "runtime"
        / "lingxi_advisor-0.8.6-py3-none-any.whl"
        for profile in (
            "icode-chrys-0.28",
            "opencode-1.x",
            "pi-0.85.1",
            "claude-code-2.1.285",
            "deepseek-harness-0.2.0-rc.2",
        )
    ]
    assert all(isinstance(wheel, Path) and wheel.is_file() for wheel in wheels)
    assert wheels[0].read_bytes() == wheels[1].read_bytes()

    members = (
        "lingxi_advisor/internal/knowledge_template.py",
        (
            "lingxi_advisor/internal/grounded_analysis/profiles/"
            "LingxiKnowledgeAnalyst.yaml"
        ),
        (
            "lingxi_advisor/internal/grounded_analysis/profiles/"
            "LingxiKnowledgeSummarizer.yaml"
        ),
    )
    with zipfile.ZipFile(wheels[0]) as packaged:
        payloads = {member: packaged.read(member) for member in members}

    assert b"FINE_GRAINED_TAGS" in payloads[members[0]]
    assert b"GENERAL_SUMMARY_TAGS" in payloads[members[0]]
    assert b"Output ONLY XML" in payloads[members[1]]
    assert b"Output ONLY XML" in payloads[members[2]]
