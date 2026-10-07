from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(load_source):
    prefix = load_source.__name__
    return (importlib.import_module(prefix + ".configuration"), importlib.import_module(prefix + ".managed_layout"))


def request(tmp_path):
    return {"target": {"config_root": str(tmp_path / "host")}, "configuration": {}, "managed": {
        "package_root": str(tmp_path / "store"),
        "runtimes": {"lingxi-advisor": {"kind": "python", "managed": True, "python": str(tmp_path / "runtime/bin/python")}},
        "config_ref": {"path": str(tmp_path / "config/binding.json")},
        "skill_activations": [{"id": name, "path": str(tmp_path / "host/skills" / name)}
                              for name in ("lingxi-advisor", "knowledge-preparation-operator")],
    }}


def test_managed_commands_share_runtime_and_have_no_secret_file(modules, tmp_path):
    _, layout_module = modules
    payload = request(tmp_path)
    python = Path(payload["managed"]["runtimes"]["lingxi-advisor"]["python"])
    python.parent.mkdir(parents=True)
    try:
        python.symlink_to(sys.executable)
    except OSError:
        # Windows may not grant symlink privileges in a normal developer shell.
        # The test only needs a concrete interpreter path for command assembly.
        shutil.copy2(sys.executable, python)
    layout = layout_module.ManagedLayout.from_request(payload)
    commands = [layout.mcp_command(profile) for profile in ("runtime", "operator")]
    assert commands[0][0] == commands[1][0] == str(python), "Resolving the interpreter symlink would bypass the venv"
    assert commands[0][:-1] == commands[1][:-1]
    assert commands[0][-1] == "runtime" and commands[1][-1] == "operator"
    assert not any("env-file" in item or "runtime.env" in item for command in commands for item in command)
    assert layout.data_root == tmp_path / "host/lingxi/advisor/data"
    assert not (tmp_path / "store").exists(), "Preview must not materialize managed assets"


def test_configuration_rejects_secret_storage_and_partial_model_options(modules, tmp_path):
    config, _ = modules
    for invalid in ({"api_key": "private-value"}, {"gate_model_name": "model"},
                    {"gate_model_name": "model", "gate_model_base_url": "https://user:password@example.test/v1"},
                    {"allow_preretrieved_updates": "maybe"}, {"data_root": "relative"}):
        with pytest.raises(config.InstallError):
            config.DeploymentConfiguration.from_mapping(invalid, default_data_root=tmp_path)


def test_runtime_mapping_supports_rotation_and_separate_model_credentials(modules, tmp_path):
    module, _ = modules
    config = module.DeploymentConfiguration.from_mapping({"gate_model_name": "test-model", "gate_model_base_url": "https://example.test/v1"}, default_data_root=tmp_path)
    source = {"PATH": "/bin", "HOME": str(tmp_path), "GITHUB_TOKEN_15": "last-token", "LINGXI_ADVISOR_MODEL_API_KEY": "shared-key",
              "LINGXI_ADVISOR_GENERATOR_API_KEY": "generator-key", "UNRELATED_API_KEY": "other-key",
              "LINGXI_ADVISOR_BATCH_INPUT_PATH": "/unmanaged/input", "LINGXI_ADVISOR_JUDGE_MODEL": "ambient-model"}
    config.validate_credentials(source, require_github=True)
    env = config.runtime_environment(source)
    assert env["GITHUB_TOKEN"] == "last-token"
    assert env["LINGXI_ADVISOR_JUDGE_API_KEY"] == "shared-key"
    assert env["LINGXI_ADVISOR_GENERATOR_API_KEY"] == "generator-key"
    assert env["LINGXI_ADVISOR_JUDGE_MODEL"] == "test-model"
    assert env["LINGXI_ADVISOR_GENERATOR_MAX_OUTPUT_TOKENS"] == "26000"
    assert env["LINGXI_ADVISOR_GENERATOR_TIMEOUT_SECONDS"] == "300"
    assert env["LINGXI_ADVISOR_RETRIEVAL_STRATEGY"] == "bounded"
    evaluation_env = config.runtime_environment(source, retrieval_strategy="evaluation")
    assert evaluation_env["LINGXI_ADVISOR_RETRIEVAL_STRATEGY"] == "evaluation"
    with pytest.raises(module.InstallError, match="retrieval_strategy"):
        config.runtime_environment(source, retrieval_strategy="ambient-value")
    assert "UNRELATED_API_KEY" not in env and "LINGXI_ADVISOR_BATCH_INPUT_PATH" not in env
    rotated = config.runtime_environment({**source, "GITHUB_TOKEN_15": "rotated-token", "LINGXI_ADVISOR_MODEL_API_KEY": "rotated-key"})
    assert rotated["GITHUB_TOKEN"] == "rotated-token"
    assert rotated["LINGXI_ADVISOR_JUDGE_API_KEY"] == "rotated-key"
    with pytest.raises(module.InstallError, match="Missing startup environment"):
        config.validate_credentials({}, require_github=False)
    assert "shared-key" not in repr(config)
    combined = config.runtime_environment({**source, "GITHUB_TOKEN": "first, second; first", "GITHUB_TOKEN_1": "second"})
    assert [combined[name] for name in module.GITHUB_VARIABLES if name in combined] == ["first", "second", "last-token"]


def test_host_model_mode_cannot_pick_up_ambient_custom_model(modules, tmp_path):
    module, _ = modules
    config = module.DeploymentConfiguration.from_mapping({}, default_data_root=tmp_path)
    env = config.runtime_environment({"LINGXI_ADVISOR_MODEL_API_KEY": "old-key", "LINGXI_ADVISOR_JUDGE_MODEL": "old-model", "GITHUB_TOKEN": "token"})
    assert {key for key in env if key.startswith("LINGXI_ADVISOR_")} == {
        "LINGXI_ADVISOR_JUDGE_MAX_OUTPUT_TOKENS",
        "LINGXI_ADVISOR_GENERATOR_MAX_OUTPUT_TOKENS",
        "LINGXI_ADVISOR_GENERATOR_TIMEOUT_SECONDS",
        "LINGXI_ADVISOR_RETRIEVAL_STRATEGY",
    }
    assert env["LINGXI_ADVISOR_JUDGE_MAX_OUTPUT_TOKENS"] == "32768"


def test_managed_layout_rejects_data_inside_store_and_incomplete_references(modules, tmp_path):
    _, module = modules
    payload = request(tmp_path)
    payload["configuration"]["data_root"] = str(tmp_path / "store/data")
    with pytest.raises(module.InstallError, match="immutable"):
        module.ManagedLayout.from_request(payload)
    payload["configuration"] = {}
    del payload["managed"]["runtimes"]["lingxi-advisor"]
    with pytest.raises(module.InstallError, match="Incomplete"):
        module.ManagedLayout.from_request(payload)


@pytest.mark.parametrize("value", [True, 0, 1023, 131073, "1.5", "-1", "invalid"])
def test_invalid_judge_token_budget_is_rejected(modules, tmp_path, value):
    module, _ = modules
    with pytest.raises(module.InstallError, match="judge_max_output_tokens"):
        module.DeploymentConfiguration.from_mapping({"judge_max_output_tokens": value}, default_data_root=tmp_path)


def test_judge_budget_configuration_overrides_ambient_environment(modules, tmp_path):
    module, _ = modules
    config = module.DeploymentConfiguration.from_mapping({"judge_max_output_tokens": "32768"}, default_data_root=tmp_path)
    assert config.runtime_environment({"LINGXI_ADVISOR_JUDGE_MAX_OUTPUT_TOKENS": "4096"})["LINGXI_ADVISOR_JUDGE_MAX_OUTPUT_TOKENS"] == "32768"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("generator_max_output_tokens", 1023),
        ("generator_timeout_seconds", 29),
        ("mcp_request_timeout_seconds", 1801),
    ],
)
def test_invalid_generation_and_mcp_limits_are_rejected(modules, tmp_path, name, value):
    module, _ = modules
    with pytest.raises(module.InstallError, match=name):
        module.DeploymentConfiguration.from_mapping({name: value}, default_data_root=tmp_path)


def test_github_cli_credential_store_is_used_without_persisting_a_token(
    modules, monkeypatch
):
    module, _ = modules
    monkeypatch.setattr(module.shutil, "which", lambda *args, **kwargs: "/usr/bin/gh")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="secure-cli-token\n", stderr=""
        ),
    )

    environment = module.github_environment({"PATH": "/usr/bin"})

    assert environment["GITHUB_TOKEN"] == "secure-cli-token"
