from __future__ import annotations

from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from conftest import PLUGIN_ROOT, managed_request


SCHEMA_PATH = PLUGIN_ROOT / "contracts" / "lingxi-advisor-runtime-v1.schema.json"
EXPORT_PRODUCERS = (
    ("icode-chrys-0.28", "icode"),
    ("opencode-1.x", "opencode"),
    ("pi-0.85.1", "pi"),
    ("claude-code-2.1.285", "claude-code"),
    ("deepseek-harness-0.2.0-rc.2", "deepseek-harness"),
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _export(module, tmp_path, *, agent_system="icode", target_version="0.28.0") -> dict:
    layout = module.ManagedLayout.from_request(managed_request(tmp_path, agent=agent_system))
    return module.exports.capability_export(
        layout=layout,
        agent_system=agent_system,
        target_version=target_version,
        plugin_version="0.3.11",
    )


def test_source_icode_export_matches_published_schema(load_source, tmp_path) -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_export(load_source, tmp_path))


@pytest.mark.parametrize(("profile", "agent_system"), EXPORT_PRODUCERS)
def test_each_managed_delivery_export_matches_same_schema(
    load_delivery, tmp_path, profile, agent_system
) -> None:
    schema = _schema()
    descriptor = json.loads((PLUGIN_ROOT / "targets" / f"{profile}.json").read_text(encoding="utf-8"))
    target_version = descriptor["compatibility"]["target_version"]
    expected_declaration = [{
        "id": "lingxi.advisor.runtime",
        "contract": "lingxi.advisor.runtime/v1",
        "schema": "contracts/lingxi-advisor-runtime-v1.schema.json",
    }]
    assert descriptor["capability_exports"] == expected_declaration
    assert {
        "root": "config",
        "path": "lingxi/advisor/exports/lingxi.advisor.runtime-v1.json",
        "kind": "capability_export",
    } in descriptor["managed_install"]["target_paths"]

    delivery_root = PLUGIN_ROOT / "delivery" / profile
    delivery_schema = json.loads(
        (delivery_root / "contracts" / "lingxi-advisor-runtime-v1.schema.json").read_text(encoding="utf-8")
    )
    assert delivery_schema == schema
    manifest = json.loads((delivery_root / "codehelix-plugin.json").read_text(encoding="utf-8"))
    assert manifest["capability_exports"] == expected_declaration
    assert {
        "root": "config",
        "path": "lingxi/advisor/exports/lingxi.advisor.runtime-v1.json",
        "kind": "capability_export",
    } in manifest["managed_install"]["target_paths"]

    module = load_delivery(profile)
    exported = _export(module, tmp_path / profile, agent_system=agent_system, target_version=target_version)
    Draft202012Validator(delivery_schema).validate(exported)


def test_codex_native_does_not_claim_managed_capability_export() -> None:
    descriptor = json.loads((PLUGIN_ROOT / "targets" / "codex-native.json").read_text(encoding="utf-8"))
    assert "capability_exports" not in descriptor
    assert "managed_install" not in descriptor
    manifest = json.loads(
        (PLUGIN_ROOT / "delivery" / "codex-native" / "codehelix-plugin.json").read_text(encoding="utf-8")
    )
    assert "capability_exports" not in manifest
    assert "managed_install" not in manifest
    assert not (
        PLUGIN_ROOT / "delivery" / "codex-native" / "contracts" / "lingxi-advisor-runtime-v1.schema.json"
    ).exists()


def test_schema_rejects_contract_boundary_changes(load_source, tmp_path) -> None:
    validator = Draft202012Validator(_schema())
    exported = _export(load_source, tmp_path)

    invalid_exports = []
    for path, replacement in (
        (("provider", "core_version"), "0.7.0"),
        (("target", "agent_system"), "codex"),
        (("capability", "id"), "lingxi.advisor.other"),
        (("capability", "contract"), "lingxi.advisor.runtime/v2"),
        (("data", "mode"), "read_only"),
    ):
        invalid = deepcopy(exported)
        invalid[path[0]][path[1]] = replacement
        invalid_exports.append(invalid)

    extra_tool = deepcopy(exported)
    extra_tool["agent_binding"]["mcp_servers"][0]["allowed_tools"].append("lingxi.advisor.delete")
    invalid_exports.append(extra_tool)

    for missing_tool in ("lingxi.advisor.search", "lingxi.advisor.apply"):
        invalid = deepcopy(exported)
        invalid["agent_binding"]["mcp_servers"][0]["allowed_tools"].remove(missing_tool)
        invalid_exports.append(invalid)

    for invalid in invalid_exports:
        with pytest.raises(ValidationError):
            validator.validate(invalid)


def test_validate_export_checks_callers_target(load_source, tmp_path) -> None:
    layout = load_source.ManagedLayout.from_request(managed_request(tmp_path, agent="icode"))
    exported = load_source.exports.capability_export(
        layout=layout,
        agent_system="icode",
        target_version="0.28.0",
        plugin_version="0.3.11",
    )
    with pytest.raises(ValueError, match="target agent mismatch"):
        load_source.exports.validate_export(exported, layout=layout, agent_system="opencode")


@pytest.mark.parametrize("target_version", ["", "   ", 1, None])
def test_validate_export_rejects_missing_target_version(load_source, tmp_path, target_version) -> None:
    layout = load_source.ManagedLayout.from_request(managed_request(tmp_path, agent="icode"))
    exported = load_source.exports.capability_export(
        layout=layout,
        agent_system="icode",
        target_version="0.28.0",
        plugin_version="0.3.11",
    )
    exported["target"]["target_version"] = target_version
    with pytest.raises(ValueError, match="target version is missing"):
        load_source.exports.validate_export(exported, layout=layout, agent_system="icode")
