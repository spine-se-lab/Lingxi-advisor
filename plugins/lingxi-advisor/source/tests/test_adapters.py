from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace
import pytest
from conftest import managed_request


def test_opencode_jsonc_preserves_comments_and_unknown_fields(load_delivery, tmp_path):
    module = load_delivery("opencode-1.x")
    layout = module.ManagedLayout.from_request(managed_request(tmp_path))
    layout.config_root.mkdir()
    path = layout.config_root / "opencode.jsonc"
    path.write_text('{\n // keep this comment\n "theme":"dark", "mcp":{"other":{"type":"remote","url":"https://example.test"},},\n}\n')
    rendered = module.opencode.render_config(path, layout).decode()
    assert "// keep this comment" in rendered
    parsed = json.loads(module.opencode._strip_jsonc(rendered))
    assert parsed["theme"] == "dark"
    assert parsed["mcp"]["other"]["url"] == "https://example.test"
    assert parsed["mcp"]["lingxi-advisor"]["command"] == [
        *layout.mcp_command(),
        "--compact-search-results",
    ]
    assert parsed["mcp"]["lingxi-advisor-operator"]["command"] == layout.mcp_command("operator")


def test_chrys_compacts_only_runtime_search(load_source, tmp_path, monkeypatch):
    layout = load_source.ManagedLayout.from_request(
        managed_request(tmp_path, agent="icode")
    )
    captured = {}

    def run(*_args, **kwargs):
        captured.update(json.loads(kwargs["input"]))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"profile": "profile"}), stderr="")

    monkeypatch.setattr(load_source.chrys.subprocess, "run", run)
    load_source.chrys.managed_profile(tmp_path, layout)
    servers = {item["name"]: item for item in captured["servers"]}
    assert servers["lingxi-advisor"]["args"][-1] == "--compact-search-results"
    assert "--compact-search-results" not in servers["lingxi-advisor-operator"]["args"]


def test_opencode_refuses_foreign_registration(load_delivery, tmp_path, monkeypatch):
    module = load_delivery("opencode-1.x")
    layout = module.ManagedLayout.from_request(managed_request(tmp_path))
    layout.config_root.mkdir()
    (layout.config_root / "opencode.json").write_text(json.dumps({"mcp":{"lingxi-advisor":{"type":"remote","url":"https://foreign.test"}}}))
    monkeypatch.setattr(module.opencode, "version", lambda *_: "1.18.25")
    with pytest.raises(module.InstallError, match="owned by another"):
        module.opencode.probe(tmp_path, layout.config_root, "opencode", {}, layout)


def test_opencode_launch_uses_selected_standard_config_root(
    load_source, tmp_path, monkeypatch
):
    captured = {}

    def run(command, *, cwd, env, **kwargs):
        captured.update(command=command, cwd=cwd, env=env, kwargs=kwargs)
        return SimpleNamespace(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(load_source.opencode.subprocess, "run", run)
    config_root = tmp_path / "isolated-xdg" / "opencode"
    executable = str(tmp_path / "host tools" / "opencode.cmd")
    load_source.opencode._run(
        executable, ["mcp", "list"], cwd=tmp_path, config_root=config_root
    )

    assert captured["command"] == [executable, "mcp", "list"]
    assert captured["cwd"] == tmp_path
    assert captured["env"]["XDG_CONFIG_HOME"] == str(config_root.parent)
    assert captured["env"]["OPENCODE_CONFIG_DIR"] == str(config_root)
    assert captured["kwargs"]["encoding"] == "utf-8"


def test_legacy_adoption_verifies_new_binding_without_rewriting_old_record(load_delivery, tmp_path, monkeypatch):
    module = load_delivery("opencode-1.x")
    layout = module.ManagedLayout.from_request(managed_request(tmp_path))
    layout.config_root.mkdir()
    path = layout.config_root / "opencode.jsonc"
    old = {name: {"type": "local", "command": ["old-runtime", "--env-file", "old.env"]}
           for name in ("lingxi-advisor", "lingxi-advisor-operator")}
    record = {"host_binding": {"mcp_servers_sha256": hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()}}
    path.write_text(json.dumps({"mcp": old}))
    monkeypatch.setattr(module.opencode, "version", lambda *_: "1.18.25")
    module.opencode.probe(tmp_path, layout.config_root, "opencode", record, layout)
    path.write_bytes(module.opencode.render_config(path, layout))
    module.opencode.probe(tmp_path, layout.config_root, "opencode", record, layout)
    modified = json.loads(path.read_text())
    modified["mcp"]["lingxi-advisor"]["command"] = ["foreign-command"]
    path.write_text(json.dumps(modified))
    with pytest.raises(module.InstallError, match="drifted"):
        module.opencode.probe(tmp_path, layout.config_root, "opencode", record, layout)


@pytest.mark.parametrize("runtime,operator,accepted", [("connected","connected",True),("failed","connected",False),("connected","disabled",False)])
def test_host_verify_requires_loaded_skill_paths_and_connected_servers(load_delivery, tmp_path, monkeypatch, runtime, operator, accepted):
    module = load_delivery("opencode-1.x")
    layout = module.ManagedLayout.from_request(managed_request(tmp_path))
    layout.config_root.mkdir()
    path = layout.config_root / "opencode.jsonc"
    path.write_bytes(module.opencode.render_config(path, layout))
    def run(_command, args, **_kwargs):
        if args == ["debug", "skill"]:
            text = json.dumps([{"name": name,"location":str(root / "SKILL.md")} for name,root in layout.skills.items()])
        else:
            text = f"● ✓ lingxi-advisor \x1b[90m{runtime}\n● ✓ lingxi-advisor-operator {operator}\n"
        return SimpleNamespace(returncode=0, stdout=text, stderr="")
    monkeypatch.setattr(module.opencode, "_run", run)
    if accepted:
        assert module.opencode.verify_binding(tmp_path, layout, "opencode", {})[-1]["mcp_status"] == "connected"
    else:
        with pytest.raises(module.InstallError, match="did not connect"):
            module.opencode.verify_binding(tmp_path, layout, "opencode", {})
