from __future__ import annotations

import json
from pathlib import Path

from conftest import PLUGIN_ROOT


PROFILES = (
    "icode-chrys-0.28",
    "opencode-1.x",
    "pi-0.85.1",
    "claude-code-2.1.285",
    "deepseek-harness-0.2.0-rc.2",
)
RUNTIME_ONLY = {
    "pi-0.85.1",
    "claude-code-2.1.285",
    "deepseek-harness-0.2.0-rc.2",
}
TOOLS = ["lingxi.advisor.search", "lingxi.advisor.apply"]
OPERATOR_TOOLS = [
    "lingxi.advisor.knowledge_preparation_capabilities",
    "lingxi.advisor.prepare_historical_knowledge",
    "lingxi.advisor.start_preparation_batch",
    "lingxi.advisor.get_preparation_batch",
    "lingxi.advisor.get_preparation_result",
    "lingxi.advisor.read_prepared_knowledge",
]


def test_delivery_contract_is_independent_and_exact() -> None:
    for profile in PROFILES:
        manifest = json.loads(
            (PLUGIN_ROOT / "delivery" / profile / "codehelix-plugin.json").read_text(encoding="utf-8")
        )
        assert manifest["plugin"]["id"] == "lingxi-advisor"
        assert manifest["dependencies"] == []
        assert manifest["installation"]["patches"] == []
        assert manifest["capability_exports"] == [{
            "id": "lingxi.advisor.runtime",
            "contract": "lingxi.advisor.runtime/v1",
            "schema": "contracts/lingxi-advisor-runtime-v1.schema.json",
        }]
        servers = {
            item["name"]: [tool["name"] for tool in item["tools"]]
            for item in manifest["components"]
            if item["kind"] == "mcp_server"
        }
        expected = {"lingxi-advisor-runtime": TOOLS}
        if profile not in RUNTIME_ONLY:
            expected["lingxi-advisor-operator"] = OPERATOR_TOOLS
        assert servers == expected
        update_input = next(
            item for item in manifest["configuration"]["inputs"]
            if item["id"] == "allow_preretrieved_updates"
        )
        assert update_input["type"] == "choice"
        assert update_input["default"] == "true"
        assert update_input["required"] is False
        assert update_input["prompt"] is False
        assert update_input["choices"] == ["true", "false"]
        assert not any(
            item["id"] == "repository"
            for item in manifest["configuration"]["inputs"]
        )
        github_credential = next(
            item for item in manifest["requires"]["credentials"]
            if item["env"] == "GITHUB_TOKEN"
        )
        assert github_credential["repeatable"] is True
        assert github_credential["max_entries"] == 16
        assert github_credential["prompt_before_configuration"] is True
        model_credential = next(
            item for item in manifest["requires"]["credentials"]
            if item["env"] == "LINGXI_ADVISOR_MODEL_API_KEY"
        )
        assert model_credential["required"] is False
        assert model_credential["prompt"] is True
        gate_inputs = [
            item for item in manifest["configuration"]["inputs"]
            if item["id"] in {"gate_model_name", "gate_model_base_url"}
        ]
        assert [item["id"] for item in gate_inputs] == [
            "gate_model_name", "gate_model_base_url",
        ]
        assert all(item["prompt"] is True for item in gate_inputs)
        assert all(
            item.get("prompt") is False
            for item in manifest["configuration"]["inputs"]
            if item["id"] not in {"gate_model_name", "gate_model_base_url"}
        )


def test_icode_has_one_profile_and_opencode_has_none() -> None:
    icode = json.loads(
        (PLUGIN_ROOT / "delivery" / PROFILES[0] / "codehelix-plugin.json").read_text(encoding="utf-8")
    )
    opencode = json.loads(
        (PLUGIN_ROOT / "delivery" / PROFILES[1] / "codehelix-plugin.json").read_text(encoding="utf-8")
    )
    profiles = [item for item in icode["components"] if item["kind"] == "agent_profile"]
    assert profiles == [{"kind": "agent_profile", "name": "LingxiAdvisor", "count": 1}]
    assert not [item for item in opencode["components"] if item["kind"] == "agent_profile"]


def test_owned_host_identifiers_match_installer_adapters(load_source, tmp_path) -> None:
    manifests = {
        profile: json.loads(
            (PLUGIN_ROOT / "targets" / f"{profile}.json").read_text(encoding="utf-8")
        )
        for profile in (
            "icode-chrys-0.28",
            "pi-0.85.1",
            "deepseek-harness-0.2.0-rc.2",
        )
    }

    icode = manifests["icode-chrys-0.28"]
    profile = next(
        item
        for item in icode["installation"]["registrations"]
        if item["kind"] == "agent_profile"
    )
    assert load_source.chrys.PROFILE_NAME == profile["name"] == "LingxiAdvisor"
    assert load_source.chrys.profile_path(tmp_path) == (
        tmp_path / "agents" / "LingxiAdvisor.yaml"
    )

    pi = manifests["pi-0.85.1"]
    declared_pi_paths = {
        item["path"]
        for item in pi["installation"]["registrations"]
        if item["kind"] == "plugin"
    } | {
        item["path"]
        for item in pi["managed_install"]["target_paths"]
        if item["kind"] == "plugin"
    }
    config_root = Path("config")
    actual_pi_path = load_source.pi.activation_path(config_root).relative_to(
        config_root
    ).as_posix()
    assert declared_pi_paths == {actual_pi_path} == {
        "extensions/codehelix-lingxi-advisor.js"
    }

    deepseek = manifests["deepseek-harness-0.2.0-rc.2"]
    bundle = next(
        item
        for item in deepseek["installation"]["registrations"]
        if item["kind"] == "profile_bundle"
    )
    assert load_source.deepseek_harness.BUNDLE_NAME == bundle["name"]
    assert bundle["name"] == "codehelix-lingxi-advisor-dsh"


def test_skill_provider_aliases_match_pi_bridge() -> None:
    skill_files = (
        PLUGIN_ROOT / "source/assets/skills/lingxi-advisor/SKILL.md",
        PLUGIN_ROOT / "source/assets/skills/lingxi-advisor/references/mcp-tools.md",
    )
    extension = (PLUGIN_ROOT / "source/pi/extension.mjs").read_text(encoding="utf-8")
    for alias in ("lingxi_advisor_search", "lingxi_advisor_apply"):
        assert all(alias in path.read_text(encoding="utf-8") for path in skill_files)
        assert f'alias: "{alias}"' in extension
    assert all(
        "lingxi-advisor_search" not in path.read_text(encoding="utf-8")
        and "lingxi-advisor_apply" not in path.read_text(encoding="utf-8")
        for path in skill_files
    )
