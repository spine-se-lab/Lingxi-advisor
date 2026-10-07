"""Hosts without MCP sampling, OpenCode timeouts and host-specific guidance."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from conftest import managed_request


MODEL = {
    "gate_model_name": "deepseek/deepseek-v4.1-flash",
    "gate_model_base_url": "https://openrouter.ai/api/v1",
}


@pytest.mark.parametrize(("agent", "profile"), [
    ("opencode", "opencode-1.x"), ("claude-code", "claude-code-2.1.285"),
])
def test_check_blocks_hosts_without_sampling_when_no_model_is_configured(
    load_delivery, tmp_path, monkeypatch, agent, profile
):
    module = load_delivery(profile)
    monkeypatch.setenv("GITHUB_TOKEN", "github")
    payload, code = module.run_operation("check", managed_request(tmp_path, agent=agent))
    assert code == 2 and payload["status"] == "blocked"
    assert "does not support MCP sampling" in payload["message"]
    assert "gate_model_name" in payload["message"]
    assert not (tmp_path / "config").exists()


def test_opencode_block_suggests_the_current_host_model(load_delivery, tmp_path, monkeypatch):
    module = load_delivery("opencode-1.x")
    monkeypatch.setenv("GITHUB_TOKEN", "github")
    (tmp_path / "opencode.json").write_text(
        json.dumps({"model": "openrouter/deepseek/deepseek-v4.1-flash"}), encoding="utf-8"
    )
    payload, _ = module.run_operation("check", managed_request(tmp_path))
    assert ("--set gate_model_name=deepseek/deepseek-v4.1-flash "
            "--set gate_model_base_url=https://openrouter.ai/api/v1") in payload["message"]


def test_configured_model_passes_the_sampling_requirement(load_source, tmp_path):
    configuration = load_source.ManagedLayout.from_request(
        {**managed_request(tmp_path), "configuration": MODEL}
    ).configuration
    configuration.require_model_for("opencode")
    configuration.require_model_for("claude-code")
    without_model = load_source.ManagedLayout.from_request(managed_request(tmp_path)).configuration
    without_model.require_model_for("icode")


def test_suggest_model_reads_project_then_global_config(load_source, tmp_path):
    opencode = load_source.opencode
    project, config_root = tmp_path / "project", tmp_path / "config"
    project.mkdir()
    config_root.mkdir()
    assert opencode.suggest_model(project, config_root) == ""
    (config_root / "opencode.jsonc").write_text(
        '{\n  // custom OpenAI-compatible provider\n  "model": "corp/coder-1",\n'
        '  "provider": {"corp": {"options": {"baseURL": "https://llm.example/v1"}}}\n}\n',
        encoding="utf-8",
    )
    assert "gate_model_base_url=https://llm.example/v1" in opencode.suggest_model(project, config_root)
    (project / "opencode.json").write_text(json.dumps({"model": "openai/gpt-x"}), encoding="utf-8")
    suggestion = opencode.suggest_model(project, config_root)
    assert "gate_model_name=gpt-x" in suggestion
    assert "gate_model_base_url=https://api.openai.com/v1" in suggestion
    (project / "opencode.json").write_text(json.dumps({"model": "unknown/model"}), encoding="utf-8")
    assert opencode.suggest_model(project, config_root) == ""


def test_opencode_servers_carry_the_configured_request_timeout(load_source, tmp_path):
    request = {**managed_request(tmp_path), "configuration": {**MODEL, "mcp_request_timeout_seconds": "900"}}
    layout = load_source.ManagedLayout.from_request(request)
    servers = load_source.opencode._desired_servers(layout)
    assert {server["timeout"] for server in servers.values()} == {900_000}


def test_host_executable_lookup_is_absolute(load_source, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(load_source.shutil, "which", lambda _name: "tools/bin/opencode")
    assert load_source._executable(None, "opencode") == str(tmp_path / "tools/bin/opencode")
    assert load_source._executable("bin/claude", "claude") == str(tmp_path / "bin/claude")
    monkeypatch.setattr(load_source.shutil, "which", lambda _name: None)
    assert load_source._executable(None, "opencode") is None


def test_missing_file_failures_name_the_file(load_source, monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "/missing/opencode")

    monkeypatch.setattr(load_source, "_prepare", missing)
    payload, code = load_source.run_operation("check", {})
    assert code == 2
    assert payload["message"] == "LingxiAdvisor check failed (FileNotFoundError: /missing/opencode)"


@pytest.mark.parametrize(("output", "next_step"), [
    ("lingxi-advisor:\n  Status: ✔ Connected\n", False),
    ("lingxi-advisor:\n  Status: ⏸ Pending approval (run `claude` to approve)\n", True),
])
def test_claude_pending_project_mcp_reports_the_approval_step(
    load_source, tmp_path, monkeypatch, output, next_step
):
    module = load_source
    layout = module.ManagedLayout.from_request(
        {**managed_request(tmp_path, agent="claude-code"), "configuration": MODEL}
    )
    monkeypatch.setattr(module.claude_code, "read_server", lambda _path: module.claude_code._desired(layout))
    monkeypatch.setattr(module.claude_code, "_run",
                        lambda _exe, args, **_kwargs: SimpleNamespace(returncode=0, stdout=output, stderr=""))
    evidence = module.claude_code.verify_binding(tmp_path, layout, "claude")
    steps = [item for item in evidence if item["kind"] == "next_step"]
    assert bool(steps) is next_step
    if next_step:
        assert str(tmp_path) in steps[0]["status"] and "claude -p" in steps[0]["status"]
