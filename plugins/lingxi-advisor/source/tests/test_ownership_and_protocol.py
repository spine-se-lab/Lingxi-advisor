from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import managed_request


def test_legacy_ownership_requires_matching_identity_and_file_hash(load_delivery, tmp_path):
    module = load_delivery("opencode-1.x")
    request = managed_request(tmp_path)
    target = tmp_path / "export.json"
    target.write_bytes(b"old-export")
    record = {"managed_files": {str(target): module.ownership.digest(target.read_bytes())}}
    module._assert_owned_file(request, target, b"new-export", record)
    target.write_bytes(b"user-edit")
    with pytest.raises(module.InstallError, match="Unowned or modified"):
        module._assert_owned_file(request, target, b"new-export", record)
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"plugin": "another-plugin", **record}))
    with pytest.raises(module.InstallError, match="another plugin"):
        module.ownership.read_record(path)


def test_plan_is_read_only_and_checks_capabilities_without_hard_version_gate(load_delivery, tmp_path, monkeypatch):
    module = load_delivery("opencode-1.x")
    request = managed_request(tmp_path)
    monkeypatch.setattr(module.opencode, "version", lambda *_: "2.0.0")
    monkeypatch.setattr(module.opencode, "_run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="help", stderr=""))
    payload, code = module.run_operation("plan", request)
    assert code == 0, payload
    assert any(item.get("version") == "2.0.0" for item in payload["evidence"])
    assert not Path(request["target"]["config_root"]).exists()
    assert not Path(request["managed"]["package_root"]).exists()
    monkeypatch.setattr(module.opencode, "_run", lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr=""))
    payload, code = module.run_operation("plan", request)
    assert code == 2 and payload["status"] == "blocked"
    assert not Path(request["target"]["config_root"]).exists()


def test_managed_refs_are_required_and_never_replaced_by_private_runtime(load_delivery, tmp_path):
    module = load_delivery("opencode-1.x")
    request = managed_request(tmp_path)
    del request["managed"]
    payload, code = module.run_operation("check", request)
    assert code == 2 and "request.managed" in payload["message"]
    assert not (tmp_path / "config").exists()


def test_install_failure_reports_actual_mutations(load_delivery, tmp_path, monkeypatch):
    module = load_delivery("icode-chrys-0.28")
    context = {"layout": object(), "target_version": "0.28.0", "root": tmp_path}
    def fail(_context, changes):
        changes.append({"kind": "file", "path": str(tmp_path / "partial")})
        raise module.InstallError("injected")
    monkeypatch.setattr(module, "_prepare", lambda *_a, **_k: context)
    monkeypatch.setattr(module, "_install", fail)
    payload, code = module.run_operation("install", {})
    assert code == 2 and payload["status"] == "failed"
    assert payload["changes"] == [{"kind": "file", "path": str(tmp_path / "partial")}]
    assert {"kind": "mutation_state", "state": "modified"} in payload["evidence"]


def test_install_requires_prepared_assets_before_writing_activation(load_delivery, tmp_path):
    module = load_delivery("opencode-1.x")
    layout = module.ManagedLayout.from_request(managed_request(tmp_path))
    desired = {tmp_path / "activation": b"do not write yet"}
    with pytest.raises(module.InstallError, match="must be prepared"):
        module._install({"layout": layout, "desired": desired}, [])
    assert not (tmp_path / "activation").exists()
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("value", ["{", "[]", '{"target":[]}', '{"managed":"bad"}'])
def test_invalid_protocol_input_returns_json_and_exit_one(load_delivery, monkeypatch, capsys, value):
    module = load_delivery("opencode-1.x")
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(value))
    assert module._protocol("check") == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_partial_custom_configuration_is_rejected_without_echoing_credentials(load_delivery, tmp_path, monkeypatch):
    module = load_delivery("opencode-1.x")
    request = managed_request(tmp_path)
    request["configuration"] = {"gate_model_name": "model"}
    monkeypatch.setenv("LINGXI_ADVISOR_MODEL_API_KEY", "test-private-key")
    payload, code = module.run_operation("check", request)
    assert code == 2 and "supplied together" in payload["message"]
    assert "test-private-key" not in json.dumps(payload)


def test_chrys_rejects_retired_host_before_loading_profile(load_delivery, tmp_path, monkeypatch):
    module = load_delivery("icode-chrys-0.28")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-no-network")
    request = managed_request(tmp_path, agent="icode")
    target = Path(request["target"]["root"])
    target.mkdir(parents=True, exist_ok=True)
    (target / "pyproject.toml").write_text('[project]\nname="chrys"\nversion="0.20.1"\n')
    def unexpected(*args, **kwargs):
        pytest.fail("retired host must be rejected before rendering a profile")
    monkeypatch.setattr(module.chrys, "managed_profile", unexpected)
    payload, code = module.run_operation("check", request)
    assert code == 2 and "requires Chrys 0.28.0" in payload["message"]
    assert not Path(request["target"]["config_root"]).exists()
