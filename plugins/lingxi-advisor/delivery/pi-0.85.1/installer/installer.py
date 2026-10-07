"""LingxiAdvisor-specific managed activation; CodeHelix owns deployment lifecycle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from . import exports, ownership
from .adapters import chrys, claude_code, deepseek_harness, opencode, pi
from .configuration import absolute_path, github_environment, redact
from .contracts import CORE_VERSION, OPERATOR_TOOLS, RUNTIME_TOOLS, InstallError, load_manifest, plugin_version, result
from .managed_layout import ManagedLayout
from .release import validate_release_directory


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _owned(request: dict[str, Any], path: Path) -> bool:
    return any(item.get("path") == str(path) for item in request["managed"].get("owned_activations", []))


def _assert_owned_file(request: dict[str, Any], path: Path, desired: bytes, legacy: dict[str, Any]) -> None:
    ownership._safe(path)
    if not path.exists():
        return
    if not path.is_file():
        raise InstallError("Activation path is not a regular file")
    current = path.read_bytes()
    if _owned(request, path) or current == desired:
        return
    if legacy.get("managed_files", {}).get(str(path)) == ownership.digest(current):
        return
    raise InstallError(f"Unowned or modified LingxiAdvisor activation: {path}")


def _executable(explicit: str | None, name: str) -> str | None:
    # Host commands run with cwd=<target>; a PATH-relative lookup must not
    # resolve against that directory.
    found = explicit or shutil.which(name)
    return os.path.abspath(found) if found else None


def _prepare(request: dict[str, Any], *, require_secrets: bool) -> dict[str, Any]:
    manifest = load_manifest(PACKAGE_ROOT)
    layout = ManagedLayout.from_request(request)
    agent = request["target"].get("agent_system") or manifest["compatibility"]["agent_system"]
    if agent != manifest["compatibility"]["agent_system"] or agent not in {
        "icode", "opencode", "pi", "claude-code", "deepseek-harness",
    }:
        raise InstallError("Target agent does not match this Delivery")
    root = absolute_path(request["target"].get("root"), "target.root")
    if not root.is_dir():
        raise InstallError("Target root must be an existing directory")
    if require_secrets:
        suggestion = opencode.suggest_model(root, layout.config_root) if agent == "opencode" else ""
        layout.configuration.require_model_for(agent, suggestion=suggestion)
    startup = github_environment(os.environ)
    layout.configuration.validate_credentials(startup, require_github=require_secrets)
    layout.configuration.runtime_environment(startup)
    release = validate_release_directory(PACKAGE_ROOT / "runtime" / f"lingxi-advisor-extension-{CORE_VERSION}")
    legacy = ownership.read_record(layout.root / "runtime/codehelix-install.json")
    executable = request["target"].get("executable")
    if executable is not None and not isinstance(executable, str):
        raise InstallError("target.executable must be a string")
    if agent == "opencode":
        executable = _executable(executable, "opencode")
        config_path = opencode.config_path(layout.config_root)
        ownership._safe(config_path)
        rendered = opencode.render_config(config_path, layout)
        registration_record = legacy
        if _owned(request, config_path):
            current = {name: value for name in ("lingxi-advisor", "lingxi-advisor-operator")
                       if (value := opencode._read_server(config_path, name)) is not None}
            registration_record = {"host_binding": {"mcp_servers_sha256": hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()}}
        evidence = opencode.probe(root, layout.config_root, executable, registration_record, layout)
        for arguments in (["mcp", "--help"], ["debug", "skill", "--help"]):
            probe = opencode._run(str(executable), arguments, cwd=root, config_root=layout.config_root)
            if probe.returncode:
                raise InstallError("OpenCode does not expose required MCP and Skill commands")
        if legacy.get("host_binding", {}).get("mcp_servers_sha256") and not _owned(request, config_path):
            # probe() just verified the legacy registration hash. Match the
            # framework's canonical field snapshot without backing up other MCPs.
            values = []
            for name in ("lingxi-advisor", "lingxi-advisor-operator"):
                server = opencode._read_server(config_path, name)
                item = {"path": ["mcp", name], "present": server is not None}
                if server is not None:
                    item["value"] = json.loads(json.dumps(server, sort_keys=True))
                values.append(item)
            snapshot = {"type": "jsonc", "values": values}
            digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            evidence.append({"kind": "activation_ownership", "path": str(config_path),
                "ownership": "legacy_codehelix", "snapshot_digest": digest})
        version = str(evidence[0]["target_version"])
        desired = {config_path: rendered}
    elif agent == "icode":
        version = chrys.version(root)
        profile = chrys.profile_path(layout.config_root)
        rendered = chrys.managed_profile(root, layout)
        _assert_owned_file(request, profile, rendered, legacy)
        desired = {profile: rendered}
        evidence = [{"kind": "capability_probe", "names": ["agent_profile", "skill", "mcp_stdio"], "loader": "passed"}]
        if profile.is_file() and legacy.get("managed_files", {}).get(str(profile)) == ownership.digest(profile.read_bytes()):
            evidence.append({"kind": "activation_ownership", "path": str(profile), "ownership": "legacy_codehelix", "sha256": ownership.digest(profile.read_bytes())})
    elif agent == "pi":
        executable = _executable(executable, "pi")
        version, host_root = pi.probe(root, layout.config_root, executable)
        activation = pi.activation_path(layout.config_root)
        rendered = pi.render_activation(layout)
        _assert_owned_file(request, activation, rendered, legacy)
        desired = {activation: rendered}
        evidence = [{
            "kind": "capability_probe",
            "names": ["skill", "mcp_stdio"],
            "target_version": version,
            "pi_package": str(host_root),
        }]
    elif agent == "claude-code":
        executable = _executable(executable, "claude")
        config_path = claude_code.config_path(root)
        ownership._safe(config_path)
        rendered = claude_code.render_config(config_path, layout)
        evidence = claude_code.probe(
            root, layout.config_root, executable, layout,
            owned=_owned(request, config_path),
        )
        version = str(evidence[0]["target_version"])
        desired = {config_path: rendered}
    else:
        executable = _executable(executable, "dsh")
        evidence = deepseek_harness.probe(
            root, layout.config_root, executable, layout,
        )
        version = str(evidence[0]["target_version"])
        desired = {
            deepseek_harness.package_path(layout): deepseek_harness.render_package(
                plugin_version(manifest)
            ),
            deepseek_harness.patch_path(layout): deepseek_harness.render_patch(
                layout, root
            ),
        }
    exported = exports.capability_export(layout=layout, agent_system=agent, target_version=version, plugin_version=plugin_version(manifest))
    export_bytes = (json.dumps(exported, ensure_ascii=False, indent=2) + "\n").encode()
    _assert_owned_file(request, layout.export_file, export_bytes, legacy)
    desired[layout.export_file] = export_bytes
    evidence.extend([
        {"kind": "target_identity", "version": version, "root": str(root)},
        {"kind": "model_capability", "runtime_backend": layout.configuration.model_backend,
         "operator_generation": "custom_model_required", "sampling": "negotiated_per_runtime_session"},
        {"kind": "data_location", "root": str(layout.data_root), "knowledge_cache": str(layout.data_root / "knowl_cache")},
    ])
    return {"layout": layout, "agent_system": agent, "root": root, "executable": executable,
            "manifest": manifest, "release": release, "target_version": version, "desired": desired, "evidence": evidence}


def _install(context: dict[str, Any], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    layout = context["layout"]
    if not layout.python.is_file() or not layout.binding_file.is_file() or not (layout.package_root / "launcher.py").is_file():
        raise InstallError("Managed Package, Runtime and Config must be prepared before activation")
    if any(not (path / "SKILL.md").is_file() for path in layout.skills.values()):
        raise InstallError("Managed LingxiAdvisor Skills must be projected before activation")
    for path, content in context["desired"].items():
        if not path.is_file() or path.read_bytes() != content:
            ownership.atomic_write(path, content, changes)
    if context["agent_system"] == "deepseek-harness":
        changes.append(deepseek_harness.install_bundle(
            context["root"], layout, str(context["executable"])
        ))
    return context["evidence"]


def _mcp_probe(layout: ManagedLayout) -> list[dict[str, Any]]:
    evidence = []
    profiles = [("runtime", RUNTIME_TOOLS)]
    if "knowledge-preparation-operator" in layout.skills:
        profiles.append(("operator", OPERATOR_TOOLS))
    for profile, expected in profiles:
        completed = subprocess.run([str(layout.python), "-B", "-m", "installer.mcp_probe",
            json.dumps(layout.mcp_command(profile)), json.dumps(list(expected))], cwd=layout.package_root,
            env=layout.configuration.runtime_environment(github_environment(os.environ)), capture_output=True, text=True, timeout=90, check=False)
        if completed.returncode:
            raise InstallError(f"LingxiAdvisor {profile} MCP initialize/tools-list failed")
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise InstallError("MCP probe returned invalid JSON") from exc
        if payload.get("tools") != list(expected):
            raise InstallError("MCP tool boundary mismatch")
        evidence.append({"kind": "mcp_server", "profile": profile, "tools": list(expected), "status": "connected"})
    return evidence


def _verify(context: dict[str, Any]) -> list[dict[str, Any]]:
    layout = context["layout"]
    export = json.loads(layout.export_file.read_text(encoding="utf-8"))
    exports.validate_export(export, layout=layout, agent_system=context["agent_system"])
    if context["agent_system"] == "icode":
        loaded = chrys.managed_profile(context["root"], layout, verify=True)
        host = [{"kind": "agent_profile", "status": "loaded", "path": str(chrys.profile_path(layout.config_root)), **loaded}]
    elif context["agent_system"] == "opencode":
        host = opencode.verify_binding(context["root"], layout, context["executable"], {})
    elif context["agent_system"] == "pi":
        host = pi.verify_binding(
            context["root"], layout, str(context["executable"])
        )
    elif context["agent_system"] == "claude-code":
        host = claude_code.verify_binding(
            context["root"], layout, str(context["executable"])
        )
    else:
        host = deepseek_harness.verify_binding(
            context["root"], layout, str(context["executable"])
        )
    return [*context["evidence"], *_mcp_probe(layout), *host,
            {"kind": "capability_export", "path": str(layout.export_file), "status": "resolved"}]


def run_operation(operation: str, request: dict[str, Any]) -> tuple[dict[str, Any], int]:
    changes: list[dict[str, Any]] = []
    started = False
    prepared = False
    try:
        if operation not in {"check", "plan", "install", "verify", "remove"}:
            return result("failed", "Unsupported installer operation"), 1
        context = _prepare(request, require_secrets=operation in {"check", "install"})
        prepared = True
        if operation in {"check", "plan"}:
            planned = [{"kind": "activation", "path": str(path)} for path in context["desired"]] if operation == "plan" else []
            return result("ok", "LingxiAdvisor managed activation preflight passed", changes=planned, evidence=context["evidence"]), 0
        if operation == "install":
            started = True
            evidence = _install(context, changes)
        elif operation == "remove":
            if context["agent_system"] != "deepseek-harness":
                return result("failed", "Remove is not implemented for this target"), 1
            started = True
            evidence = [deepseek_harness.remove_bundle(
                context["root"], context["layout"], str(context["executable"])
            )]
        else:
            evidence = _verify(context)
        message = {
            "install": "LingxiAdvisor activation written",
            "remove": "LingxiAdvisor host registration removed",
        }.get(operation, "LingxiAdvisor host and MCP verified")
        return result("ok", message, changes=changes, evidence=evidence), 0
    except InstallError as exc:
        status = "blocked" if not prepared or operation in {"check", "plan"} else "failed"
        evidence = [{"kind": "mutation_state", "state": "modified" if changes else "unknown" if started else "unchanged"}]
        return result(status, redact(str(exc), os.environ), changes=changes, evidence=evidence), 2
    except Exception as exc:
        detail = type(exc).__name__
        if isinstance(exc, FileNotFoundError) and exc.filename:
            detail += f": {exc.filename}"
        return result("failed", redact(f"LingxiAdvisor {operation} failed ({detail})", os.environ), changes=changes,
            evidence=[{"kind": "mutation_state", "state": "modified" if changes else "unknown" if started else "unchanged"}]), 2


def _protocol(operation: str) -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
        if not isinstance(request, dict) or any(key in request and not isinstance(request[key], dict) for key in ("target", "configuration", "managed")):
            raise ValueError("request fields must be objects")
    except (ValueError, json.JSONDecodeError):
        print(json.dumps(result("failed", "Invalid installer request JSON or shape")))
        return 1
    payload, code = run_operation(operation, request)
    print(json.dumps(payload, ensure_ascii=False))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="LingxiAdvisor managed activation protocol")
    parser.add_argument("mode", choices=("protocol",))
    parser.add_argument("operation", choices=("check", "plan", "install", "verify", "remove"))
    args = parser.parse_args()
    return _protocol(args.operation)


if __name__ == "__main__":
    raise SystemExit(main())
