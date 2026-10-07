from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def managed_request(tmp_path, *, agent="opencode", config_root=None):
    config = config_root or tmp_path / "config"
    skill_names = (
        ("lingxi-advisor",)
        if agent in {"pi", "claude-code", "deepseek-harness"}
        else ("lingxi-advisor", "knowledge-preparation-operator")
    )
    return {"target": {"agent_system": agent, "root": str(tmp_path), "config_root": str(config), "executable": agent},
            "configuration": {}, "managed": {"package_root": str(tmp_path / "store"),
            "runtimes": {"lingxi-advisor": {"kind": "python", "managed": True, "python": str(tmp_path / "runtime/bin/python")}},
            "config_ref": {"path": str(tmp_path / "binding.json")}, "owned_activations": [],
            "skill_activations": [{"id": name, "path": str(config / "skills" / name)}
                                  for name in skill_names]}}


@pytest.fixture
def load_delivery():
    loaded: list[str] = []

    def load(profile: str):
        package = f"lingxi_advisor_advisor_{profile.replace('-', '_').replace('.', '_')}"
        path = PLUGIN_ROOT / "delivery" / profile / "installer" / "installer.py"
        spec = importlib.util.spec_from_file_location(
            package,
            path,
            submodule_search_locations=[str(path.parent)],
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        loaded.append(package)
        spec.loader.exec_module(module)
        return module

    yield load
    for package in loaded:
        for name in list(sys.modules):
            if name == package or name.startswith(package + "."):
                sys.modules.pop(name, None)


@pytest.fixture
def load_source():
    """Exercise maintainer source before rebuilding immutable Deliveries."""
    package = "lingxi_advisor_advisor_source"
    path = PLUGIN_ROOT / "source" / "installer" / "installer.py"
    spec = importlib.util.spec_from_file_location(
        package, path, submodule_search_locations=[str(path.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    yield module
    for name in list(sys.modules):
        if name == package or name.startswith(package + "."):
            sys.modules.pop(name, None)
