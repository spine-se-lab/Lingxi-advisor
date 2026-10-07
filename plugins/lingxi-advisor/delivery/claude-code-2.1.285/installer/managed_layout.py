"""References to framework-managed assets; no private Runtime or install state."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .configuration import DeploymentConfiguration, absolute_path
from .contracts import InstallError


@dataclass(frozen=True)
class ManagedLayout:
    config_root: Path
    package_root: Path
    python: Path
    binding_file: Path
    configuration: DeploymentConfiguration
    skills: Mapping[str, Path]

    @classmethod
    def from_request(cls, request: Mapping[str, Any]) -> "ManagedLayout":
        managed = request.get("managed")
        if not isinstance(managed, Mapping):
            raise InstallError("Use the CodeHelix managed installation lifecycle; request.managed is required")
        try:
            root = absolute_path(request["target"]["config_root"], "config_root")
            package = absolute_path(managed["package_root"], "managed.package_root")
            runtime = managed["runtimes"]["lingxi-advisor"]
            if runtime.get("kind") != "python" or not runtime.get("managed"):
                raise InstallError("LingxiAdvisor requires one managed Python Runtime")
            config = DeploymentConfiguration.from_mapping(request.get("configuration", {}),
                default_data_root=root / "lingxi/advisor/data")
            if config.data_root == package or package in config.data_root.parents:
                raise InstallError("data_root must be outside the immutable PackageStore")
            agent = str(request.get("target", {}).get("agent_system") or "")
            expected_skills = (
                {"lingxi-advisor"}
                if agent in {"pi", "claude-code", "deepseek-harness"}
                else {"lingxi-advisor", "knowledge-preparation-operator"}
            )
            activations = managed["skill_activations"]
            skills = {}
            for item in activations:
                skill_id = item.get("id")
                # The shared inspect/remove context retains path and kind but
                # not the source declaration's id. A single-Skill target is
                # therefore unambiguous without a framework change.
                if not skill_id and len(activations) == 1 and len(expected_skills) == 1:
                    skill_id = next(iter(expected_skills))
                if not skill_id:
                    raise InstallError("Managed Skill activation id is missing")
                skills[str(skill_id)] = absolute_path(
                    item["path"], "skill activation", follow_symlinks=False
                )
            if set(skills) != expected_skills:
                raise InstallError(
                    "LingxiAdvisor managed Skill activations do not match the target"
                )
            return cls(config_root=root, package_root=package,
                       python=absolute_path(runtime["python"], "managed Runtime python", follow_symlinks=False),
                       binding_file=absolute_path(managed["config_ref"]["path"], "managed config_ref"),
                       configuration=config, skills=skills)
        except (KeyError, TypeError) as exc:
            raise InstallError("Incomplete managed Package/Runtime/Config/Skill references") from exc

    @property
    def root(self) -> Path:
        return self.config_root / "lingxi/advisor"

    @property
    def data_root(self) -> Path:
        return self.configuration.data_root

    @property
    def export_file(self) -> Path:
        return self.root / "exports/lingxi.advisor.runtime-v1.json"

    @property
    def private_skill(self) -> Path:
        return self.skills["lingxi-advisor"]

    @property
    def private_operator_skill(self) -> Path:
        return self.skills["knowledge-preparation-operator"]

    def skill_path(self, agent_system: str, name: str) -> Path:
        return self.skills[name]

    def skill_root(self, agent_system: str) -> Path:
        return self.private_skill

    def mcp_command(self, profile: str = "runtime") -> list[str]:
        if profile not in {"runtime", "operator"}:
            raise InstallError("Unknown LingxiAdvisor MCP profile")
        return [str(self.python), "-B", str(self.package_root / "launcher.py"),
                "--binding", str(self.binding_file), "--data-root", str(self.data_root), "--profile", profile]
