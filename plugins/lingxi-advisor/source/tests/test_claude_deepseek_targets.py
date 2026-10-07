from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from conftest import PLUGIN_ROOT, managed_request


PROFILES = {
    "claude-code": "claude-code-2.1.285",
    "deepseek-harness": "deepseek-harness-0.2.0-rc.2",
}


def _prepared_assets(layout) -> None:
    layout.python.parent.mkdir(parents=True)
    layout.python.write_text("python", encoding="utf-8")
    layout.binding_file.write_text("{}", encoding="utf-8")
    layout.package_root.mkdir(parents=True)
    (layout.package_root / "launcher.py").write_text("# fixture\n", encoding="utf-8")
    skill = layout.skill_path("fixture", "lingxi-advisor")
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: lingxi_advisor\ndescription: fixture\n---\n",
        encoding="utf-8",
    )


def test_new_targets_are_runtime_only_and_declare_owned_host_paths() -> None:
    claude = json.loads(
        (PLUGIN_ROOT / "targets/claude-code-2.1.285.json").read_text(encoding="utf-8")
    )
    deepseek = json.loads(
        (PLUGIN_ROOT / "targets/deepseek-harness-0.2.0-rc.2.json").read_text(encoding="utf-8")
    )
    for manifest, agent, version in (
        (claude, "claude-code", "2.1.285"),
        (deepseek, "deepseek-harness", "0.2.0-rc.2"),
    ):
        assert manifest["compatibility"] == {
            "agent_system": agent,
            "harness": agent,
            "gate": "version",
            "target_version": version,
            "required_paths": [],
        }
        assert [item["name"] for item in manifest["components"]] == [
            "lingxi-advisor", "lingxi-advisor-runtime",
        ]
        assert manifest["managed_install"]["skills"] == [{
            "id": "lingxi-advisor",
            "source": "assets/skills/lingxi-advisor",
            "destination": "skills/lingxi-advisor",
        }]
        assert manifest["managed_install"]["verify_on_inspect"] is True
    mcp_path = claude["managed_install"]["target_paths"][1]
    assert mcp_path == {
        "root": "target",
        "path": ".mcp.json",
        "kind": "native_plugin",
        "json_paths": [["mcpServers", "lingxi-advisor"]],
    }
    assert "remove" in deepseek["installer"]["operations"]


def test_existing_selector_consumes_each_new_delivery() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r"""
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.argv[1],cli=require(path.join(root,'..','..','plugin-kit','cli','plugin-cli.js'));
const profiles={'claude-code':'claude-code-2.1.285','deepseek-harness':'deepseek-harness-0.2.0-rc.2'};
const deliveries=Object.values(profiles).map(profile=>({root:path.join(root,'delivery',profile),manifest:JSON.parse(fs.readFileSync(path.join(root,'delivery',profile,'codehelix-plugin.json'),'utf8'))}));
for(const [agent,profile] of Object.entries(profiles)) assert.equal(path.basename(cli.deliveryForAgent(deliveries,agent).root),profile);
process.stdout.write('selected');
"""
    completed = subprocess.run(
        [node, "-e", script, str(PLUGIN_ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout == "selected"


def test_claude_plan_install_and_verify_preserve_unrelated_mcp_fields(
    load_delivery, tmp_path, monkeypatch
) -> None:
    module = load_delivery("claude-code-2.1.285")
    request = managed_request(tmp_path, agent="claude-code")
    request["target"]["executable"] = "claude"
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        '{\n  // owned by the user\n  "projectSetting": true,\n'
        '  "mcpServers": {"other": {"command": "other"}}\n}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module.claude_code,
        "probe",
        lambda *_args, **_kwargs: [{
            "kind": "capability_probe", "target_version": "2.1.285",
        }],
    )
    context = module._prepare(request, require_secrets=False)
    rendered = context["desired"][config_path].decode("utf-8")
    assert "owned by the user" in rendered
    assert '"projectSetting": true' in rendered
    assert '"other"' in rendered and '"lingxi-advisor"' in rendered

    _prepared_assets(context["layout"])
    changes: list[dict[str, object]] = []
    module._install(context, changes)
    assert module.claude_code.read_server(config_path) == module.claude_code._desired(
        context["layout"]
    )
    monkeypatch.setattr(module, "_mcp_probe", lambda _layout: [{"kind": "mcp_server"}])
    monkeypatch.setattr(
        module.claude_code,
        "verify_binding",
        lambda *_args: [{"kind": "claude_mcp", "status": "registered"}],
    )
    assert any(item["kind"] == "claude_mcp" for item in module._verify(context))


def test_claude_rejects_duplicate_mcp_properties(load_source, tmp_path) -> None:
    module = load_source
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        '{"mcpServers": {}, "mcpServers": {}}\n',
        encoding="utf-8",
    )
    with pytest.raises(module.InstallError, match="duplicate property: mcpServers"):
        module.claude_code.read_server(config_path)


def test_claude_optional_environment_falls_back_without_token_placeholders(
    load_source, tmp_path
) -> None:
    module = load_source
    request = managed_request(tmp_path, agent="claude-code")
    layout = module.ManagedLayout.from_request(request)
    desired = module.claude_code._desired(layout)
    assert desired["args"][-1] == "--compact-search-results"
    assert set(desired["env"]) == set(module.claude_code.ENVIRONMENT)
    assert all(
        value == f"${{{name}:-}}"
        for name, value in desired["env"].items()
    )

    # This is the environment Claude produces from the documented empty
    # fallback when only the primary GitHub token is configured.
    expanded = {
        name: "configured-token" if name == "GITHUB_TOKEN" else ""
        for name in module.claude_code.ENVIRONMENT
    }
    runtime = layout.configuration.runtime_environment(expanded)
    tokens = [
        runtime[name]
        for name in module.claude_code.ENVIRONMENT
        if name == "GITHUB_TOKEN" or name.startswith("GITHUB_TOKEN_")
        if name in runtime
    ]
    assert tokens == ["configured-token"]
    assert not any("${" in value for value in runtime.values())
    assert not any(name.startswith("LINGXI_ADVISOR_") and name.endswith("API_KEY")
                   for name in runtime)


def test_deepseek_plan_install_verify_and_remove_use_official_bundle_lifecycle(
    load_delivery, tmp_path, monkeypatch
) -> None:
    module = load_delivery("deepseek-harness-0.2.0-rc.2")
    request = managed_request(tmp_path, agent="deepseek-harness")
    request["target"]["executable"] = "dsh"
    monkeypatch.setattr(
        module.deepseek_harness,
        "probe",
        lambda *_args, **_kwargs: [{
            "kind": "capability_probe", "target_version": "0.2.0-rc.2",
        }],
    )
    context = module._prepare(request, require_secrets=False)
    package = module.deepseek_harness.package_path(context["layout"])
    patch = module.deepseek_harness.patch_path(context["layout"])
    assert set(context["desired"]) == {package, patch, context["layout"].export_file}
    assert b"@deepseek-ai/dsh-mcp-client" in context["desired"][patch]
    assert b"lingxi.advisor.search" not in context["desired"][patch]

    _prepared_assets(context["layout"])
    calls: list[str] = []
    monkeypatch.setattr(
        module.deepseek_harness,
        "install_bundle",
        lambda *_args: calls.append("install") or {"kind": "deepseek_bundle"},
    )
    changes: list[dict[str, object]] = []
    module._install(context, changes)
    assert calls == ["install"] and package.is_file() and patch.is_file()
    monkeypatch.setattr(module, "_mcp_probe", lambda _layout: [{"kind": "mcp_server"}])
    monkeypatch.setattr(
        module.deepseek_harness,
        "verify_binding",
        lambda *_args: [{"kind": "deepseek_bundle", "status": "composed"}],
    )
    assert any(item["kind"] == "deepseek_bundle" for item in module._verify(context))

    monkeypatch.setattr(
        module.deepseek_harness,
        "remove_bundle",
        lambda *_args: calls.append("remove") or {"kind": "deepseek_bundle"},
    )
    payload, code = module.run_operation("remove", request)
    assert code == 0, payload
    assert calls[-1] == "remove"


def test_deepseek_bundle_refuses_foreign_dependency(load_source, tmp_path) -> None:
    module = load_source
    config = tmp_path / "dsh-home"
    profile = module.deepseek_harness.profile_path(config)
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({
        "dependencies": {
            module.deepseek_harness.BUNDLE_NAME: "link:../../foreign",
        },
        "dsh": {"profile": {"bundles": [module.deepseek_harness.BUNDLE_NAME]}},
    }))
    request = managed_request(tmp_path, agent="deepseek-harness", config_root=config)
    layout = module.ManagedLayout.from_request(request)
    with pytest.raises(module.InstallError, match="foreign"):
        module.deepseek_harness.remove_bundle(
            tmp_path, layout, "dsh"
        )


def test_exact_host_version_gates(load_source, tmp_path, monkeypatch) -> None:
    module = load_source
    completed = SimpleNamespace(returncode=0, stdout="2.1.285 (Claude Code)\n", stderr="")
    monkeypatch.setattr(module.claude_code, "_run", lambda *_a, **_k: completed)
    assert module.claude_code.version(tmp_path, tmp_path, "claude") == "2.1.285"
    completed = SimpleNamespace(returncode=0, stdout="0.2.0-rc.2\n", stderr="")
    monkeypatch.setattr(module.deepseek_harness, "_run", lambda *_a, **_k: completed)
    assert module.deepseek_harness.version(tmp_path, tmp_path, "dsh") == "0.2.0-rc.2"


@pytest.mark.parametrize("agent", ["claude-code", "deepseek-harness"])
def test_single_skill_inspect_context_recovers_framework_omitted_id(
    load_source, tmp_path, agent
) -> None:
    module = load_source
    request = managed_request(tmp_path, agent=agent)
    request["managed"]["skill_activations"][0].pop("id")
    layout = module.ManagedLayout.from_request(request)
    assert set(layout.skills) == {"lingxi-advisor"}
