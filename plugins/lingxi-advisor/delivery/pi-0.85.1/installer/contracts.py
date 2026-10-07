from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PLUGIN_ID = "lingxi-advisor"
CORE_DISTRIBUTION = "lingxi-advisor"
CORE_VERSION = "0.8.6"
CAPABILITY_ID = "lingxi.advisor.runtime"
CAPABILITY_CONTRACT = "lingxi.advisor.runtime/v1"
RUNTIME_TOOLS = ("lingxi.advisor.search", "lingxi.advisor.apply")
OPERATOR_TOOLS = (
    "lingxi.advisor.knowledge_preparation_capabilities",
    "lingxi.advisor.prepare_historical_knowledge",
    "lingxi.advisor.start_preparation_batch",
    "lingxi.advisor.get_preparation_batch",
    "lingxi.advisor.get_preparation_result",
    "lingxi.advisor.read_prepared_knowledge",
)
PROFILE_NAME = "LingxiAdvisor"
PROFILE_ID = "7a51c0de0700"


class InstallError(RuntimeError):
    pass


def result(
    status: str,
    message: str,
    *,
    changes: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "changes": changes or [],
        "evidence": evidence or [],
    }


def load_manifest(package_root: Path) -> dict[str, Any]:
    packaged = package_root / "codehelix-plugin.json"
    if packaged.is_file():
        value = json.loads(packaged.read_text(encoding="utf-8"))
    else:
        plugin_root = package_root.parent
        descriptor = json.loads((plugin_root / "codehelix-plugin.json").read_text(encoding="utf-8"))
        candidates = [
            plugin_root / "targets" / "icode-chrys-0.28.json",
            plugin_root / "targets" / "opencode-1.x.json",
            plugin_root / "targets" / "pi-0.85.1.json",
            plugin_root / "targets" / "claude-code-2.1.285.json",
            plugin_root / "targets" / "deepseek-harness-0.2.0-rc.2.json",
        ]
        requested = __import__("os").environ.get("LINGXI_ADVISOR_TEST_TARGET", "icode")
        target_path = next(path for path in candidates if requested in path.name)
        target = json.loads(target_path.read_text(encoding="utf-8"))
        value = {
            "schema": "codehelix.plugin_package/v1",
            "plugin": descriptor["plugin"],
            **{key: item for key, item in target.items() if key not in {"schema", "profile"}},
        }
    if value.get("schema") != "codehelix.plugin_package/v1":
        raise InstallError("Delivery manifest schema is invalid")
    if value.get("plugin", {}).get("id") != PLUGIN_ID:
        raise InstallError("Delivery plugin identity is invalid")
    exports = value.get("capability_exports")
    expected = [{"id": CAPABILITY_ID, "contract": CAPABILITY_CONTRACT,
                 "schema": "contracts/lingxi-advisor-runtime-v1.schema.json"}]
    if exports != expected:
        raise InstallError("Delivery capability export declaration is invalid")
    if value.get("dependencies") != []:
        raise InstallError("Phase 1 dependencies must remain empty")
    return value


def plugin_version(manifest: dict[str, Any]) -> str:
    version = str(manifest.get("plugin", {}).get("version") or "")
    if not version:
        raise InstallError("Delivery plugin version is missing")
    return version
