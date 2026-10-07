from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from conftest import PLUGIN_ROOT, managed_request


def test_all_hosts_are_registered_in_the_normal_target_inventory() -> None:
    descriptor = json.loads(
        (PLUGIN_ROOT / "codehelix-plugin.json").read_text(encoding="utf-8")
    )
    assert descriptor["targets"] == [
        "targets/icode-chrys-0.28.json",
        "targets/opencode-1.x.json",
        "targets/pi-0.85.1.json",
        "targets/codex-native.json",
        "targets/claude-code-2.1.285.json",
        "targets/deepseek-harness-0.2.0-rc.2.json",
    ]
    pi = json.loads(
        (PLUGIN_ROOT / "targets/pi-0.85.1.json").read_text(encoding="utf-8")
    )
    codex = json.loads(
        (PLUGIN_ROOT / "targets/codex-native.json").read_text(encoding="utf-8")
    )
    assert pi["compatibility"]["agent_system"] == "pi"
    assert pi["managed_install"]["skills"] == [{
        "id": "lingxi-advisor",
        "source": "assets/skills/lingxi-advisor",
        "destination": "skills/lingxi-advisor",
    }]
    assert codex["execution"] == {
        "mode": "native",
        "adapter": "codex/native-plugins",
        "tool_timeout_sec": 1000,
    }
    assert codex["required_capabilities"] == ["skills", "mcp"]


def test_pi_plan_install_and_verify_use_owned_managed_paths(
    load_delivery, tmp_path, monkeypatch
) -> None:
    module = load_delivery("pi-0.85.1")
    request = managed_request(tmp_path, agent="pi")
    monkeypatch.setattr(
        module.pi,
        "probe",
        lambda *_args: ("0.85.1", tmp_path / "pi-package"),
    )
    context = module._prepare(request, require_secrets=False)
    activation = module.pi.activation_path(context["layout"].config_root)
    assert set(context["desired"]) == {activation, context["layout"].export_file}
    assert not activation.exists()

    layout = context["layout"]
    layout.python.parent.mkdir(parents=True)
    layout.python.write_text("python", encoding="utf-8")
    layout.binding_file.write_text("{}", encoding="utf-8")
    layout.package_root.mkdir(parents=True)
    (layout.package_root / "launcher.py").write_text("# fixture\n", encoding="utf-8")
    skill = layout.skill_path("pi", "lingxi-advisor")
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: lingxi_advisor\ndescription: fixture\n---\n")

    changes: list[dict[str, object]] = []
    module._install(context, changes)
    assert activation.read_bytes() == module.pi.render_activation(layout)
    assert all(item["path"] in {str(activation), str(layout.export_file)} for item in changes)

    monkeypatch.setattr(module, "_mcp_probe", lambda _layout: [{"kind": "mcp_server", "profile": "runtime"}])
    monkeypatch.setattr(
        module.pi,
        "verify_binding",
        lambda *_args: [{"kind": "pi_extension", "status": "loaded"}],
    )
    evidence = module._verify(context)
    assert {item["kind"] for item in evidence} >= {
        "mcp_server",
        "pi_extension",
        "capability_export",
    }


@pytest.mark.parametrize(
    ("executable", "package"),
    (
        (
            "windows-prefix/pi.cmd",
            "windows-prefix/node_modules/@earendil-works/pi-coding-agent",
        ),
        (
            "local/node_modules/.bin/pi",
            "local/node_modules/@earendil-works/pi-coding-agent",
        ),
        (
            "homebrew/bin/pi",
            "homebrew/lib/node_modules/@earendil-works/pi-coding-agent",
        ),
    ),
)
def test_pi_finds_package_behind_platform_npm_launchers(
    load_source, tmp_path, executable, package
) -> None:
    executable_path = tmp_path / executable
    executable_path.parent.mkdir(parents=True, exist_ok=True)
    executable_path.write_text("launcher", encoding="utf-8")
    package_path = tmp_path / package
    package_path.mkdir(parents=True)
    (package_path / "package.json").write_text(
        json.dumps({"name": load_source.pi.PI_PACKAGE}), encoding="utf-8"
    )

    assert load_source.pi.package_root(str(executable_path)) == package_path


def test_pi_extension_loads_provider_safe_search_apply_aliases(
    load_delivery, tmp_path
) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    module = load_delivery("pi-0.85.1")
    request = managed_request(tmp_path, agent="pi")
    request["managed"]["package_root"] = str(
        PLUGIN_ROOT / "delivery/pi-0.85.1"
    )
    layout = module.ManagedLayout.from_request(request)
    pi_root = tmp_path / "pi-host"
    loader = pi_root / "dist/core/extensions/loader.js"
    loader.parent.mkdir(parents=True)
    (pi_root / "package.json").write_text(
        json.dumps({"name": "@earendil-works/pi-coding-agent", "type": "module"})
    )
    loader.write_text(
        "export async function loadExtensions(entries) {\n"
        " const api={tools:new Map(),registerTool(tool){this.tools.set(tool.name,tool)},on(){}};\n"
        " try { const item=await import(new URL('file:///'+entries[0].replaceAll('\\\\','/'))); item.default(api);"
        " return {extensions:[api],errors:[]}; } catch(error) { return {extensions:[],errors:[String(error)]}; }\n"
        "}\n",
        encoding="utf-8",
    )
    dependency = pi_root / "node_modules/@earendil-works/pi-ai"
    dependency.mkdir(parents=True)
    (dependency / "package.json").write_text(
        json.dumps({"name": "@earendil-works/pi-ai", "type": "module", "exports": "./index.js"})
    )
    (dependency / "index.js").write_text(
        "const wrap=(kind)=>(...args)=>({kind,args});"
        "export const Type=new Proxy({}, {get:(_,name)=>wrap(name)});\n"
    )
    config = pi_root / "agent"
    entry = module.pi.activation_path(config)
    entry.parent.mkdir(parents=True)
    entry.write_bytes(module.pi.render_activation(layout))
    completed = subprocess.run(
        [
            node,
            str(PLUGIN_ROOT / "delivery/pi-0.85.1/pi/verify-load.mjs"),
            str(pi_root),
            str(entry),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "loaded": True,
        "tools": ["lingxi_advisor_search", "lingxi_advisor_apply"],
    }


def test_pi_extension_compacts_search_xml_but_keeps_artifact_refs() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    module = (PLUGIN_ROOT / "source/pi/extension.mjs").resolve().as_uri()
    script = (
        f"import {{compactSearchResult}} from {json.dumps(module)};"
        "const full={status:'completed',knowledge_matches:[{artifact_ref:{generation_mode:'light',"
        "knowledge_cache_key:'owner__repo__issue_1'},knowledge_xml:'x'.repeat(100000)}]};"
        "const compact=compactSearchResult(full);"
        "process.stdout.write(JSON.stringify(compact));"
    )

    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "status": "completed",
        "knowledge_matches": [{
            "artifact_ref": {
                "generation_mode": "light",
                "knowledge_cache_key": "owner__repo__issue_1",
            },
        }],
    }


def test_codex_native_package_uses_shared_adapter_and_exact_locked_core() -> None:
    delivery = PLUGIN_ROOT / "delivery/codex-native"
    manifest = json.loads(
        (delivery / "codehelix-plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["execution"] == {
        "mode": "native",
        "adapter": "codex/native-plugins",
        "tool_timeout_sec": 1000,
    }
    assert [item["name"] for item in manifest["components"] if item["kind"] == "mcp_server"] == ["lingxi-advisor"]
    plugin_root = delivery / "plugins/lingxi-advisor"
    plugin = json.loads(
        (plugin_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    assert plugin["skills"] == "./skills/"
    assert plugin["mcpServers"] == "./.mcp.json"
    mcp = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert mcp["lingxi-advisor"]["args"][1] == "lingxi-advisor"
    assert "LINGXI_ADVISOR_DATA_ROOT" in mcp["lingxi-advisor"]["env_vars"]
    assert mcp["lingxi-advisor"]["tool_timeout_sec"] == 1000

    wheels = list((plugin_root / "runtime/lingxi-advisor").glob("*.whl"))
    assert len(wheels) == 1
    release = PLUGIN_ROOT / "source/upstream/lingxi-advisor-extension-0.8.6.zip"
    with zipfile.ZipFile(release) as bundle:
        core_name = next(name for name in bundle.namelist() if name.endswith("lingxi_advisor-0.8.6-py3-none-any.whl"))
        core_bytes = bundle.read(core_name)
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(core_bytes)) as core, zipfile.ZipFile(wheels[0]) as host:
        core_files = {
            name: core.read(name)
            for name in core.namelist()
            if name.startswith("lingxi_advisor/") and not name.endswith("/")
        }
        assert core_files
        assert all(host.read(name) == value for name, value in core_files.items())
        host_entry = "lingxi_advisor_codehelix_host/codex.py"
        assert host.read(host_entry) == (
            PLUGIN_ROOT
            / "source/upstream/native_host/lingxi_advisor_codehelix_host/codex.py"
        ).read_bytes()


def test_codex_native_host_injects_missing_github_tokens_from_workspace_dotenv(
    tmp_path, monkeypatch
) -> None:
    source = (
        PLUGIN_ROOT
        / "source/upstream/native_host/lingxi_advisor_codehelix_host/codex.py"
    )
    spec = importlib.util.spec_from_file_location("lingxi_advisor_codex_host", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    (tmp_path / ".env").write_text(
        "GITHUB_TOKEN=workspace-token\n"
        "GITHUB_TOKEN_1=rotated-token\n"
        "UNRELATED_SECRET=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_TOKEN", "startup-token")
    monkeypatch.delenv("GITHUB_TOKEN_1", raising=False)
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)

    module._inject_github_tokens(tmp_path)

    assert os.environ["GITHUB_TOKEN"] == "startup-token"
    assert os.environ["GITHUB_TOKEN_1"] == "rotated-token"
    assert "UNRELATED_SECRET" not in os.environ


def test_locked_core_rejects_client_without_advertised_sampling(tmp_path) -> None:
    release = PLUGIN_ROOT / "source/upstream/lingxi-advisor-extension-0.8.6.zip"
    with zipfile.ZipFile(release) as bundle:
        core_name = next(
            name
            for name in bundle.namelist()
            if name.endswith("lingxi_advisor-0.8.6-py3-none-any.whl")
        )
        core = tmp_path / "lingxi_advisor.whl"
        core.write_bytes(bundle.read(core_name))
    extracted = tmp_path / "core"
    with zipfile.ZipFile(core) as wheel:
        wheel.extractall(extracted)

    script = """
import asyncio
from types import SimpleNamespace
from lingxi_advisor.adapters.mcp.host_sampling import (
    AgentHostModelUnavailableError,
    HostSamplingBridge,
)

session = SimpleNamespace(
    create_message=lambda **kwargs: None,
    client_params=SimpleNamespace(
        capabilities=SimpleNamespace(sampling=None),
    ),
)
loop = asyncio.new_event_loop()
try:
    try:
        HostSamplingBridge(
            session=session,
            event_loop=loop,
            related_request_id=None,
        )
    except AgentHostModelUnavailableError as error:
        assert "did not advertise MCP sampling" in str(error)
    else:
        raise AssertionError("missing sampling capability was accepted")
finally:
    loop.close()
"""
    completed = subprocess.run(
        [shutil.which("python") or "python", "-c", script],
        env={**os.environ, "PYTHONPATH": str(extracted)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
