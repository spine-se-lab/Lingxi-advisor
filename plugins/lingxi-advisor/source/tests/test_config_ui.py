from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from conftest import PLUGIN_ROOT


SOURCE_ROOT = PLUGIN_ROOT / "source"
sys.path.insert(0, str(SOURCE_ROOT))

import config_ui.server as config_server  # noqa: E402
from config_ui.server import ConfigStore, ConfigUIError, create_server  # noqa: E402


PLUGIN_VERSION = "0.3.13"
CUSTOM_DELIVERIES = (
    "icode-chrys-0.28",
    "opencode-1.x",
    "pi-0.85.1",
    "claude-code-2.1.285",
    "deepseek-harness-0.2.0-rc.2",
)


def _package_manifest(profile: str) -> dict:
    if profile == "codex-native":
        return json.loads(
            (PLUGIN_ROOT / "delivery" / profile / "codehelix-plugin.json").read_text(
                encoding="utf-8"
            )
        )
    descriptor = json.loads((PLUGIN_ROOT / "codehelix-plugin.json").read_text(encoding="utf-8"))
    target = json.loads((PLUGIN_ROOT / "targets" / f"{profile}.json").read_text(encoding="utf-8"))
    return {
        "schema": "codehelix.plugin_package/v1",
        "plugin": descriptor["plugin"],
        **{name: value for name, value in target.items() if name not in {"schema", "profile"}},
    }


def _installed(tmp_path: Path, *, profile: str = "opencode-1.x", environment=None, model=None):
    home = tmp_path / "codehelix home"
    package = tmp_path / "package store" / profile
    package.mkdir(parents=True)
    manifest = _package_manifest(profile)
    (package / "codehelix-plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (package / "source-lock.json").write_text(
        json.dumps({"schema": "codehelix.source_lock/v1", "target": profile}) + "\n",
        encoding="utf-8",
    )
    deployment_id = "0123456789abcdef01234567"
    binding_path = home / "config" / "plugins" / "lingxi-advisor" / f"{deployment_id}.json"
    data_root = tmp_path / "LingxiAdvisor data"
    configuration = {
        "issue_tracking_provider": "github",
        "data_root": str(data_root),
        "judge_max_output_tokens": "16384",
        "allow_preretrieved_updates": "true",
        "allow_live_search": "true",
        "allow_refresh": "false",
        "allow_clone": "false",
        "allow_fetch": "false",
    }
    # OpenCode and Claude Code cannot provide MCP sampling, so a valid
    # deployment for those hosts always carries a custom model.
    if model is None:
        model = manifest["compatibility"]["agent_system"] in {"opencode", "claude-code"}
    if model:
        configuration["gate_model_name"] = "deepseek/deepseek-v4.1-flash"
        configuration["gate_model_base_url"] = "https://openrouter.ai/api/v1"
    binding = {
        "schema": "codehelix.plugin_binding/v1",
        "home": str(home),
        "plugin_id": "lingxi-advisor",
        "deployment_id": deployment_id,
        "package_ref": {
            "plugin_id": "lingxi-advisor",
            "version": PLUGIN_VERSION,
            "root": str(package),
        },
        "configuration": configuration,
        "runtimes": {},
    }
    binding_path.parent.mkdir(parents=True)
    binding_bytes = (json.dumps(binding, ensure_ascii=False, indent=2) + "\n").encode()
    binding_path.write_bytes(binding_bytes)
    state_path = home / "state" / "lingxi-advisor.json"
    state_path.parent.mkdir(parents=True)
    state = {
        "schema": "codehelix.plugin_state/v2",
        "plugin_id": "lingxi-advisor",
        "unrelated_state": {"preserve": True},
        "deployments": [{
            "id": deployment_id,
            "status": "installed",
            "target": {
                "agent_system": manifest["compatibility"]["agent_system"],
                "harness": manifest["compatibility"]["harness"],
                "root": str(tmp_path),
                "config_root": str(tmp_path / "agent config"),
            },
            "config_ref": {"path": str(binding_path)},
            "config_digest": hashlib.sha256(binding_bytes).hexdigest(),
            "unrelated_deployment": ["preserve"],
        }],
    }
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return ConfigStore(binding_path, environment=environment or {}), binding_path, state_path, package


def _http(server, method="GET", payload=None):
    url = f"http://127.0.0.1:{server.server_port}/api/config"
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_descriptor_schema_maps_to_runtime_and_installation_fields(tmp_path):
    store, _, _, _ = _installed(tmp_path)
    payload = store.public_configuration()
    fields = {item["id"]: item for item in payload["fields"]}
    assert payload["plugin"] == {
        "id": "lingxi-advisor", "version": PLUGIN_VERSION, "core_version": "0.8.6"
    }
    assert fields["data_root"]["classification"] == "installation-only"
    assert fields["data_root"]["read_only"] is True
    assert fields["issue_tracking_provider"]["read_only"] is True
    assert fields["gate_model_name"]["classification"] == "runtime-editable"
    assert fields["allow_live_search"]["choices"] == ["true", "false"]
    assert fields["judge_max_output_tokens"]["value"] == "16384"
    assert fields["generator_max_output_tokens"]["value"] == "26000"
    assert fields["generator_timeout_seconds"]["value"] == "300"
    assert fields["mcp_request_timeout_seconds"]["classification"] == "installation-only"
    assert fields["mcp_request_timeout_seconds"]["read_only"] is True
    assert payload["deployment"]["profile"] == "opencode-1.x"
    assert payload["validation"] == {"valid": True, "message": "Configuration is valid"}
    assert payload["readiness"]["ready"] is False
    assert "GitHub" in payload["readiness"]["message"]


def test_default_data_root_matches_lingxi_managed_layout(tmp_path):
    store, _, _, _ = _installed(tmp_path)
    assert store._default_data_root(store._document()) == (
        tmp_path / "agent config" / "lingxi" / "advisor" / "data"
    )


def test_chrys_mcp_timeout_is_installation_only_and_cannot_be_saved(tmp_path):
    store, binding_path, _, _ = _installed(tmp_path, profile="icode-chrys-0.28")
    before = binding_path.read_bytes()
    payload = store.public_configuration()
    fields = {item["id"]: item for item in payload["fields"]}
    timeout = fields["mcp_request_timeout_seconds"]
    assert timeout["value"] == "600"
    assert timeout["classification"] == "installation-only"
    assert timeout["read_only"] is True
    assert "reinstall" in timeout["label"].lower()
    with pytest.raises(ConfigUIError, match="non-editable or unsupported"):
        store.update({"mcp_request_timeout_seconds": "900"}, payload["revision"])
    assert binding_path.read_bytes() == before


def test_load_and_valid_update_preserve_supported_and_unrelated_state(tmp_path):
    store, binding_path, state_path, _ = _installed(tmp_path)
    before = store.public_configuration()
    assert "batch_input_path" in {field["id"] for field in before["fields"]}
    result = store.update({
        "judge_max_output_tokens": "32768",
        "allow_live_search": "false",
        "batch_input_path": str(tmp_path / "batch inputs" / "tasks.jsonl"),
    }, before["revision"])
    saved = json.loads(binding_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["configuration"]["judge_max_output_tokens"] == "32768"
    assert saved["configuration"]["allow_live_search"] == "false"
    assert saved["configuration"]["issue_tracking_provider"] == "github"
    assert saved["configuration"]["data_root"] == str(tmp_path / "LingxiAdvisor data")
    assert state["unrelated_state"] == {"preserve": True}
    assert state["deployments"][0]["unrelated_deployment"] == ["preserve"]
    assert state["deployments"][0]["config_digest"] == hashlib.sha256(binding_path.read_bytes()).hexdigest()
    assert result["validation"]["valid"] is True
    assert "Restart or reload" in result["message"]


@pytest.mark.parametrize("profile", ["icode-chrys-0.28", "opencode-1.x"])
def test_operator_deliveries_show_and_accept_batch_input_path(tmp_path, profile):
    store, binding_path, _, _ = _installed(tmp_path, profile=profile)
    loaded = store.public_configuration()
    assert "batch_input_path" in {field["id"] for field in loaded["fields"]}
    batch = tmp_path / profile / "batch.jsonl"
    result = store.update({"batch_input_path": str(batch)}, loaded["revision"])
    saved = json.loads(binding_path.read_text(encoding="utf-8"))
    assert saved["configuration"]["batch_input_path"] == str(batch)
    assert result["validation"]["valid"] is True


@pytest.mark.parametrize(
    "profile",
    ["pi-0.85.1", "codex-native", "claude-code-2.1.285", "deepseek-harness-0.2.0-rc.2"],
)
def test_runtime_only_deliveries_hide_and_reject_batch_input_path(tmp_path, profile):
    store, binding_path, _, _ = _installed(tmp_path, profile=profile)
    before = binding_path.read_bytes()
    server = create_server(store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, loaded = _http(server)
        assert "batch_input_path" not in {field["id"] for field in loaded["fields"]}
        status, rejected = _http(server, "POST", {
            "values": {"batch_input_path": str(tmp_path / "not-applicable.jsonl")},
            "revision": loaded["revision"],
        })
        assert status == 400
        assert "non-editable or unsupported" in rejected["error"]
        assert binding_path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_invalid_update_is_rejected_without_replacing_binding(tmp_path):
    store, binding_path, state_path, _ = _installed(tmp_path)
    before_binding = binding_path.read_bytes()
    before_state = state_path.read_bytes()
    revision = store.public_configuration()["revision"]
    with pytest.raises(ConfigUIError) as error:
        store.update({"judge_max_output_tokens": "7"}, revision)
    assert error.value.fields == {
        "judge_max_output_tokens": "judge_max_output_tokens must be an integer from 1024 to 131072"
    }
    assert binding_path.read_bytes() == before_binding
    assert state_path.read_bytes() == before_state


def test_secret_values_never_reach_api_html_logs_or_binding(tmp_path, capsys):
    secret = "github-token-that-must-not-leak"
    store, binding_path, _, _ = _installed(tmp_path, environment={
        "GITHUB_TOKEN_1": secret,
        "LINGXI_ADVISOR_MODEL_API_KEY": "model-secret-that-must-not-leak",
    })
    server = create_server(store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _http(server)
        with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
            html = response.read().decode()
        serialized = json.dumps(payload)
        assert status == 200
        assert secret not in serialized and "model-secret-that-must-not-leak" not in serialized
        assert secret not in html and "model-secret-that-must-not-leak" not in html
        statuses = {item["env"]: item["present"] for item in payload["credentials"]}
        assert statuses == {
            "GITHUB_TOKEN": True,
            "LINGXI_ADVISOR_JUDGE_API_KEY": True,
            "LINGXI_ADVISOR_GENERATOR_API_KEY": True,
        }
        status, saved = _http(server, "POST", {
            "values": {"allow_clone": "true"}, "revision": payload["revision"]
        })
        assert status == 200
        serialized = json.dumps(saved)
        persisted = binding_path.read_text(encoding="utf-8")
        assert secret not in serialized and "model-secret-that-must-not-leak" not in serialized
        assert secret not in persisted and "model-secret-that-must-not-leak" not in persisted
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    logs = capsys.readouterr().err
    assert secret not in logs and "model-secret-that-must-not-leak" not in logs


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        (
            {"GITHUB_TOKEN_15": "github", "LINGXI_ADVISOR_MODEL_API_KEY": "unified"},
            {"GITHUB_TOKEN": True, "LINGXI_ADVISOR_JUDGE_API_KEY": True, "LINGXI_ADVISOR_GENERATOR_API_KEY": True},
        ),
        (
            {
                "GITHUB_TOKEN": "github",
                "LINGXI_ADVISOR_JUDGE_API_KEY": "judge",
                "LINGXI_ADVISOR_GENERATOR_API_KEY": "generator",
            },
            {"GITHUB_TOKEN": True, "LINGXI_ADVISOR_JUDGE_API_KEY": True, "LINGXI_ADVISOR_GENERATOR_API_KEY": True},
        ),
        (
            {},
            {"GITHUB_TOKEN": False, "LINGXI_ADVISOR_JUDGE_API_KEY": False, "LINGXI_ADVISOR_GENERATOR_API_KEY": False},
        ),
    ],
)
def test_credential_status_matches_runtime_fallbacks(tmp_path, environment, expected):
    store, _, _, _ = _installed(tmp_path, environment=environment)
    statuses = {
        credential["env"]: credential["present"]
        for credential in store.public_configuration()["credentials"]
    }
    assert statuses == expected


def test_http_valid_and_invalid_save_path(tmp_path):
    store, binding_path, _, _ = _installed(tmp_path)
    server = create_server(store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, loaded = _http(server)
        status, invalid = _http(server, "POST", {
            "values": {"gate_model_base_url": ""}, "revision": loaded["revision"]
        })
        assert status == 400
        assert set(invalid["fields"]) == {"gate_model_name", "gate_model_base_url"}
        status, saved = _http(server, "POST", {
            "values": {"allow_refresh": "true"}, "revision": loaded["revision"]
        })
        assert status == 200 and saved["validation"]["valid"] is True
        assert json.loads(binding_path.read_text(encoding="utf-8"))["configuration"]["allow_refresh"] == "true"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_custom_model_configuration_is_valid_but_not_ready_without_keys(tmp_path):
    store, _, _, _ = _installed(tmp_path, environment={"GITHUB_TOKEN": "github"})
    before = store.public_configuration()
    result = store.update(
        {
            "gate_model_name": "custom-model",
            "gate_model_base_url": "https://example.test/v1",
        },
        before["revision"],
    )

    assert result["validation"]["valid"] is True
    assert result["readiness"]["ready"] is False
    assert "Judge model credential" in result["readiness"]["message"]


def test_agent_host_configuration_reports_sampling_as_runtime_pending(tmp_path):
    store, _, _, _ = _installed(
        tmp_path, profile="icode-chrys-0.28", environment={"GITHUB_TOKEN": "github"}
    )
    result = store.public_configuration()

    assert result["validation"]["valid"] is True
    assert result["readiness"]["ready"] is None
    assert "will be checked when the MCP session starts" in result["readiness"]["message"]
    assert "not preflighted" in result["readiness"]["sampling"]


@pytest.mark.parametrize("profile", ["opencode-1.x", "claude-code-2.1.285"])
def test_hosts_without_sampling_require_a_custom_model(tmp_path, profile):
    store, binding_path, _, _ = _installed(tmp_path, profile=profile, model=False)
    result = store.public_configuration()
    assert result["validation"]["valid"] is False
    assert "does not support MCP sampling" in result["validation"]["message"]

    configured, binding_path, _, _ = _installed(tmp_path / "configured", profile=profile)
    loaded = configured.public_configuration()
    assert loaded["validation"]["valid"] is True
    before = binding_path.read_bytes()
    with pytest.raises(ConfigUIError, match="does not support MCP sampling") as error:
        configured.update({"gate_model_name": "", "gate_model_base_url": ""}, loaded["revision"])
    assert set(error.value.fields) == {"gate_model_name", "gate_model_base_url"}
    assert binding_path.read_bytes() == before


def test_stale_revision_is_rejected_without_writing(tmp_path):
    store, binding_path, state_path, _ = _installed(tmp_path)
    stale = store.public_configuration()["revision"]
    store.update({"allow_refresh": "true"}, stale)
    current_binding = binding_path.read_bytes()
    current_state = state_path.read_bytes()
    with pytest.raises(ConfigUIError, match="changed after this page loaded"):
        store.update({"allow_clone": "true"}, stale)
    assert binding_path.read_bytes() == current_binding
    assert state_path.read_bytes() == current_state


def test_state_write_failure_rolls_back_binding_atomically(tmp_path, monkeypatch):
    store, binding_path, state_path, _ = _installed(tmp_path)
    binding_before = binding_path.read_bytes()
    state_before = state_path.read_bytes()
    revision = store.public_configuration()["revision"]
    real_atomic_write = config_server.atomic_write

    def fail_state_write(path, content):
        if Path(path) == state_path:
            raise OSError("simulated state write failure")
        real_atomic_write(path, content)

    monkeypatch.setattr(config_server, "atomic_write", fail_state_write)
    with pytest.raises(ConfigUIError, match="safely save"):
        store.update({"allow_fetch": "true"}, revision)
    assert binding_path.read_bytes() == binding_before
    assert state_path.read_bytes() == state_before


def test_server_default_is_ipv4_loopback_only(tmp_path):
    store, _, _, _ = _installed(tmp_path)
    server = create_server(store)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
    with pytest.raises(ConfigUIError, match="loopback"):
        create_server(store, host="0.0.0.0")


def test_saved_configuration_is_read_by_existing_launcher(tmp_path):
    store, binding_path, _, package = _installed(tmp_path)
    shutil.copy2(SOURCE_ROOT / "launcher.py", package / "launcher.py")
    revision = store.public_configuration()["revision"]
    store.update({"allow_fetch": "true", "judge_max_output_tokens": "24576"}, revision)
    spec = importlib.util.spec_from_file_location("lingxi_advisor_config_ui_launcher", package / "launcher.py")
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    config = launcher.load_configuration(binding_path, tmp_path / "LingxiAdvisor data")
    assert config.allow_fetch is True
    assert config.judge_max_output_tokens == 24576


def test_all_release_metadata_and_generated_deliveries_are_0_3_9():
    descriptor = json.loads((PLUGIN_ROOT / "codehelix-plugin.json").read_text(encoding="utf-8"))
    package = json.loads((PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    source_package = json.loads((SOURCE_ROOT / "package.json").read_text(encoding="utf-8"))
    source_lock = json.loads((SOURCE_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    claude_source = json.loads(
        (SOURCE_ROOT / "claude-plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert descriptor["plugin"]["version"] == PLUGIN_VERSION
    assert package["version"] == PLUGIN_VERSION
    assert source_package["version"] == PLUGIN_VERSION
    assert source_lock["version"] == source_lock["packages"][""]["version"] == PLUGIN_VERSION
    assert claude_source["version"] == PLUGIN_VERSION

    for profile in CUSTOM_DELIVERIES:
        root = PLUGIN_ROOT / "delivery" / profile
        manifest = json.loads((root / "codehelix-plugin.json").read_text(encoding="utf-8"))
        delivery_package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        delivery_lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
        assert manifest["plugin"]["version"] == PLUGIN_VERSION
        assert delivery_package["version"] == PLUGIN_VERSION
        assert delivery_lock["version"] == delivery_lock["packages"][""]["version"] == PLUGIN_VERSION
        assert (root / "config_ui" / "server.py").is_file()

    claude_delivery = json.loads(
        (PLUGIN_ROOT / "delivery" / "claude-code-2.1.285" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    codex_root = PLUGIN_ROOT / "delivery" / "codex-native"
    codex_manifest = json.loads((codex_root / "codehelix-plugin.json").read_text(encoding="utf-8"))
    codex_plugin = json.loads(
        (codex_root / "plugins" / "lingxi-advisor" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert claude_delivery["version"] == PLUGIN_VERSION
    assert codex_manifest["plugin"]["version"] == PLUGIN_VERSION
    assert codex_plugin["version"] == PLUGIN_VERSION
    assert not (codex_root / "config_ui").exists()
    assert "LingxiAdvisorConfigUI/0.3." not in (SOURCE_ROOT / "config_ui" / "server.py").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="native Windows path acceptance")
def test_windows_paths_with_spaces_round_trip(tmp_path):
    store, binding_path, _, _ = _installed(tmp_path)
    batch = tmp_path / "Windows path with spaces" / "batch.jsonl"
    revision = store.public_configuration()["revision"]
    store.update({"batch_input_path": str(batch)}, revision)
    saved = json.loads(binding_path.read_text(encoding="utf-8"))
    assert saved["configuration"]["batch_input_path"] == str(batch)
    assert store.public_configuration()["validation"]["valid"] is True
