"""Loopback-only LingxiAdvisor configuration editor.

The managed binding remains the runtime source of truth.  A successful edit
also advances the binding digest in CodeHelix PluginState so inspect, update,
and removal continue to see an owned, drift-free deployment.
"""
from __future__ import annotations

import argparse
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Mapping
import webbrowser

from installer.configuration import (
    DeploymentConfiguration,
    GITHUB_VARIABLES,
    MODEL_VARIABLES,
    github_environment,
)
from installer.contracts import CORE_VERSION, InstallError, OPERATOR_TOOLS, PLUGIN_ID
from installer.ownership import atomic_write


LOOPBACK_HOST = "127.0.0.1"
MAX_REQUEST_BYTES = 64 * 1024
EDITABLE_FIELDS = {
    "gate_model_name",
    "gate_model_base_url",
    "judge_max_output_tokens",
    "generator_max_output_tokens",
    "generator_timeout_seconds",
    "allow_preretrieved_updates",
    "batch_input_path",
    "allow_live_search",
    "allow_refresh",
    "allow_clone",
    "allow_fetch",
}
INSTALLATION_ONLY_FIELDS = {
    "issue_tracking_provider",
    "data_root",
    "workbench_workspace",
    "mcp_request_timeout_seconds",
}
FIELD_PRESENTATION = {
    "issue_tracking_provider": ("Issue tracking provider", "Installation"),
    "data_root": ("LingxiAdvisor data directory", "Installation"),
    "workbench_workspace": ("LingxiAdvisor data directory", "Installation"),
    "gate_model_name": ("Custom model name", "Model and generation"),
    "gate_model_base_url": ("Custom model endpoint", "Model and generation"),
    "judge_max_output_tokens": ("Judge output token limit", "Model and generation"),
    "generator_max_output_tokens": ("Generator output token limit", "Model and generation"),
    "generator_timeout_seconds": ("Generator timeout (seconds)", "Model and generation"),
    "mcp_request_timeout_seconds": ("MCP request timeout (seconds; reinstall to change)", "Installation"),
    "batch_input_path": ("Operator batch input path", "Paths"),
    "allow_preretrieved_updates": ("Allow pre-retrieved updates", "Retrieval policy"),
    "allow_live_search": ("Allow live search", "Retrieval policy"),
    "allow_refresh": ("Allow repository refresh", "Retrieval policy"),
    "allow_clone": ("Allow repository clone", "Retrieval policy"),
    "allow_fetch": ("Allow repository fetch", "Retrieval policy"),
}
ALIASES = {
    "gate_model_name": "model_name",
    "gate_model_base_url": "model_base_url",
}


class ConfigUIError(RuntimeError):
    """A safe, user-facing configuration UI error."""

    def __init__(self, message: str, *, fields: Mapping[str, str] | None = None):
        super().__init__(message)
        self.fields = dict(fields or {})


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigUIError(f"{label} is missing or invalid") from exc
    if not isinstance(value, dict):
        raise ConfigUIError(f"{label} must contain a JSON object")
    return value


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _state_path(home: Path) -> Path:
    current = home / "state" / f"{PLUGIN_ID}.json"
    legacy = home / "plugins" / "state" / f"{PLUGIN_ID}.json"
    return current if current.exists() or not legacy.exists() else legacy


def resolve_binding(
    *, home: Path | None = None, binding: Path | None = None, deployment_id: str | None = None
) -> Path:
    """Resolve one installed binding using the existing PluginState identity."""
    if binding is not None:
        result = binding.expanduser().absolute()
        if not result.is_file():
            raise ConfigUIError("The selected managed binding does not exist")
        return result
    selected_home = (home or Path(os.environ.get("CODEHELIX_HOME") or Path.home() / ".codehelix")).expanduser().absolute()
    state = _read_json(_state_path(selected_home), "LingxiAdvisor PluginState")
    if state.get("schema") != "codehelix.plugin_state/v2" or state.get("plugin_id") != PLUGIN_ID:
        raise ConfigUIError("LingxiAdvisor PluginState identity is invalid")
    active = [item for item in state.get("deployments", []) if item.get("status") != "removed"]
    if deployment_id:
        active = [item for item in active if item.get("id") == deployment_id]
    if not active:
        raise ConfigUIError("No matching installed LingxiAdvisor deployment was found")
    if len(active) != 1:
        ids = ", ".join(str(item.get("id") or "unknown") for item in active)
        raise ConfigUIError(f"Multiple LingxiAdvisor deployments are installed; use --deployment-id ({ids})")
    try:
        return Path(active[0]["config_ref"]["path"]).absolute()
    except (KeyError, TypeError) as exc:
        raise ConfigUIError("Installed LingxiAdvisor deployment has no managed binding") from exc


def _inputs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    declarations = manifest.get("configuration") or {}
    if isinstance(declarations, Mapping) and isinstance(declarations.get("inputs"), list):
        return [dict(item) for item in declarations["inputs"] if isinstance(item, Mapping)]
    if isinstance(declarations, Mapping):
        return [{"id": name, **dict(item)} for name, item in declarations.items() if isinstance(item, Mapping)]
    return []


def _has_operator(manifest: Mapping[str, Any]) -> bool:
    """Use packaged capabilities, rather than host names, to detect Operator."""
    expected = set(OPERATOR_TOOLS)
    for component in manifest.get("components") or []:
        if not isinstance(component, Mapping) or component.get("kind") != "mcp_server":
            continue
        tools = {
            tool.get("name")
            for tool in component.get("tools") or []
            if isinstance(tool, Mapping) and isinstance(tool.get("name"), str)
        }
        if expected.issubset(tools):
            return True
    return False


def _editable_fields(manifest: Mapping[str, Any]) -> set[str]:
    fields = set(EDITABLE_FIELDS)
    if not _has_operator(manifest):
        fields.discard("batch_input_path")
    return fields


def _visible_inputs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    operator_enabled = _has_operator(manifest)
    return [
        declaration
        for declaration in _inputs(manifest)
        if declaration.get("id") != "batch_input_path" or operator_enabled
    ]


def _credential_statuses(
    manifest: Mapping[str, Any], environment: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Return boolean-only status using the launcher's existing fallback rules."""
    declared_credentials = [
        credential
        for credential in manifest.get("requires", {}).get("credentials", [])
        if isinstance(credential, Mapping) and isinstance(credential.get("env"), str)
    ]
    declared_environment = {
        name
        for name in manifest.get("requires", {}).get("environment", [])
        if isinstance(name, str)
    }
    credentials: list[dict[str, Any]] = []
    model_names = set(MODEL_VARIABLES)
    model_credential: Mapping[str, Any] | None = None
    for credential in declared_credentials:
        name = credential["env"]
        if name in model_names:
            model_credential = model_credential or credential
            continue
        names = list(GITHUB_VARIABLES) if name == "GITHUB_TOKEN" else [name]
        credentials.append({
            "provider": str(credential.get("provider") or "Credential"),
            "label": _english(credential.get("label"), name),
            "env": name,
            "required": bool(credential.get("required")),
            "present": any(bool(environment.get(candidate, "").strip()) for candidate in names),
        })

    if model_credential is not None or declared_environment.intersection(model_names):
        unified = bool(environment.get("LINGXI_ADVISOR_MODEL_API_KEY", "").strip())
        provider = str(
            (model_credential or {}).get("provider") or "LingxiAdvisor custom model"
        )
        required = bool((model_credential or {}).get("required"))
        for role, name in (
            ("Judge", "LINGXI_ADVISOR_JUDGE_API_KEY"),
            ("Generator", "LINGXI_ADVISOR_GENERATOR_API_KEY"),
        ):
            credentials.append({
                "provider": provider,
                "label": f"{role} model credential (or unified key)",
                "env": name,
                "required": required,
                "present": bool(environment.get(name, "").strip()) or unified,
            })
    return credentials


def _english(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        for key in ("en", "zh-CN"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
    return fallback


def _field_error(message: str) -> dict[str, str]:
    names = [name for name in (*EDITABLE_FIELDS, *INSTALLATION_ONLY_FIELDS) if name in message]
    if "supplied together" in message:
        names = ["gate_model_name", "gate_model_base_url"]
    return {name: message for name in names}


class ConfigStore:
    """Load, validate, and atomically update one managed binding."""

    def __init__(self, binding_path: Path, *, environment: Mapping[str, str] | None = None):
        self.binding_path = binding_path.absolute()
        self.environment = (
            github_environment(os.environ)
            if environment is None
            else dict(environment)
        )

    def _document(self) -> dict[str, Any]:
        try:
            binding_bytes = self.binding_path.read_bytes() if self.binding_path.is_file() else b""
        except OSError as exc:
            raise ConfigUIError("Managed LingxiAdvisor binding could not be read") from exc
        if not binding_bytes:
            raise ConfigUIError("Managed LingxiAdvisor binding is missing")
        try:
            binding = json.loads(binding_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ConfigUIError("Managed LingxiAdvisor binding is invalid") from exc
        if not isinstance(binding, dict) or binding.get("schema") != "codehelix.plugin_binding/v1" or binding.get("plugin_id") != PLUGIN_ID:
            raise ConfigUIError("Managed LingxiAdvisor binding identity is invalid")
        try:
            home = Path(binding["home"]).absolute()
            deployment_id = str(binding["deployment_id"])
            package_root = Path(binding["package_ref"]["root"]).absolute()
        except (KeyError, TypeError) as exc:
            raise ConfigUIError("Managed LingxiAdvisor binding is incomplete") from exc
        manifest = _read_json(package_root / "codehelix-plugin.json", "Installed LingxiAdvisor Delivery descriptor")
        source_lock = _read_json(package_root / "source-lock.json", "Installed LingxiAdvisor Delivery source lock")
        if manifest.get("plugin", {}).get("id") != PLUGIN_ID or manifest.get("plugin", {}).get("version") != binding.get("package_ref", {}).get("version"):
            raise ConfigUIError("Installed LingxiAdvisor Delivery identity differs from the binding")
        state_path = _state_path(home)
        state = _read_json(state_path, "LingxiAdvisor PluginState")
        deployments = state.get("deployments") if isinstance(state.get("deployments"), list) else []
        matches = [item for item in deployments if item.get("id") == deployment_id and item.get("status") != "removed"]
        if len(matches) != 1:
            raise ConfigUIError("Managed binding does not identify one active LingxiAdvisor deployment")
        deployment = matches[0]
        try:
            recorded_binding = deployment["config_ref"]["path"]
        except (KeyError, TypeError) as exc:
            raise ConfigUIError("LingxiAdvisor PluginState has no binding reference") from exc
        if not _same_path(recorded_binding, self.binding_path):
            raise ConfigUIError("Selected binding does not match LingxiAdvisor PluginState")
        revision = _digest_bytes(binding_bytes)
        if deployment.get("config_digest") != revision:
            raise ConfigUIError("Managed configuration has drift; inspect the deployment before editing")
        configuration = binding.get("configuration")
        if not isinstance(configuration, dict):
            raise ConfigUIError("Managed LingxiAdvisor configuration must be an object")
        return {
            "binding": binding,
            "binding_bytes": binding_bytes,
            "configuration": configuration,
            "deployment": deployment,
            "manifest": manifest,
            "home": home,
            "package_root": package_root,
            "profile": source_lock.get("target"),
            "revision": revision,
            "state": state,
            "state_path": state_path,
        }

    @staticmethod
    def _default_data_root(document: Mapping[str, Any]) -> Path:
        target = document["deployment"].get("target") or {}
        config_root = target.get("config_root")
        if not isinstance(config_root, str) or not Path(config_root).is_absolute():
            raise ConfigUIError("Installed deployment has no absolute configuration directory")
        return Path(config_root) / "lingxi" / "advisor" / "data"

    def _validate(self, document: Mapping[str, Any], configuration: Mapping[str, Any]) -> None:
        if document["manifest"].get("schema") == "codehelix.native_package/v1":
            return
        target = document["deployment"].get("target") or {}
        try:
            DeploymentConfiguration.from_mapping(
                configuration, default_data_root=self._default_data_root(document)
            ).require_model_for(str(target.get("agent_system") or ""))
        except InstallError as exc:
            message = str(exc)
            raise ConfigUIError(message, fields=_field_error(message)) from exc

    def public_configuration(self) -> dict[str, Any]:
        document = self._document()
        configuration = document["configuration"]
        manifest = document["manifest"]
        validation = {"valid": True, "message": "Configuration is valid"}
        try:
            self._validate(document, configuration)
        except ConfigUIError as exc:
            validation = {"valid": False, "message": str(exc), "fields": exc.fields}
        fields = []
        editable_fields = _editable_fields(manifest)
        for declaration in _visible_inputs(manifest):
            name = declaration.get("id")
            if not isinstance(name, str) or not name:
                continue
            label, group = FIELD_PRESENTATION.get(
                name, (name.replace("_", " ").title(), "Other")
            )
            value = configuration.get(name)
            if value is None and name in ALIASES:
                value = configuration.get(ALIASES[name])
            if value is None and "default" in declaration:
                value = declaration["default"]
            classification = "runtime-editable" if name in editable_fields else "installation-only"
            fields.append({
                "id": name,
                "type": declaration.get("type", "string"),
                "label": _english(declaration.get("label"), label),
                "description": _english(declaration.get("description"), str(declaration.get("note") or "")),
                "group": group,
                "required": bool(declaration.get("required")),
                "choices": list(declaration.get("choices") or []),
                "value": value if value is not None else "",
                "classification": classification,
                "read_only": classification != "runtime-editable",
            })
        credentials = _credential_statuses(manifest, self.environment)
        parsed_configuration: DeploymentConfiguration | None = None
        try:
            parsed_configuration = DeploymentConfiguration.from_mapping(
                configuration, default_data_root=self._default_data_root(document)
            )
        except InstallError:
            pass
        missing_required = [
            item["label"]
            for item in credentials
            if item["required"] and not item["present"]
        ]
        missing_custom_model = []
        if parsed_configuration is not None and parsed_configuration.model_backend == "custom":
            missing_custom_model = [
                item["label"]
                for item in credentials
                if item["env"] in {"LINGXI_ADVISOR_JUDGE_API_KEY", "LINGXI_ADVISOR_GENERATOR_API_KEY"}
                and not item["present"]
            ]
        readiness_issues = [*missing_required, *missing_custom_model]
        uses_host_sampling = (
            parsed_configuration is not None
            and parsed_configuration.model_backend != "custom"
        )
        structurally_ready = validation["valid"] and not readiness_issues
        readiness = {
            "ready": None if structurally_ready and uses_host_sampling else structurally_ready,
            "message": (
                "Credentials are ready; host sampling capability will be checked when the MCP session starts"
                if structurally_ready and uses_host_sampling
                else "Ready after restart"
                if structurally_ready
                else "Missing runtime credential(s): " + ", ".join(readiness_issues)
                if validation["valid"]
                else "Configuration must be corrected before restart"
            ),
            "sampling": (
                "custom model credentials"
                if parsed_configuration is not None and parsed_configuration.model_backend == "custom"
                else "host sampling is not preflighted; configure a custom model if the host does not provide it"
            ),
        }
        target = document["deployment"].get("target") or {}
        return {
            "schema": "lingxi.advisor.configuration_ui/v1",
            "plugin": {
                "id": PLUGIN_ID,
                "version": manifest.get("plugin", {}).get("version"),
                "core_version": CORE_VERSION,
            },
            "deployment": {
                "id": document["binding"].get("deployment_id"),
                "status": document["deployment"].get("status"),
                "agent_system": target.get("agent_system"),
                "harness": target.get("harness"),
                "profile": document.get("profile"),
                "target_version": manifest.get("compatibility", {}).get("target_version"),
                "package_root": str(document["package_root"]),
                "binding_path": str(self.binding_path),
            },
            "fields": fields,
            "credentials": credentials,
            "validation": validation,
            "readiness": readiness,
            "revision": document["revision"],
            "restart_required": True,
        }

    @staticmethod
    def _lock(home: Path):
        root = home / "state" / ".transactions"
        root.mkdir(parents=True, exist_ok=True)
        lock = root / f"{PLUGIN_ID}.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            active = True
            try:
                pid = int(_read_json(lock, "LingxiAdvisor operation lock").get("pid"))
                os.kill(pid, 0)
            except ProcessLookupError:
                active = False
            except (ConfigUIError, OSError, TypeError, ValueError):
                active = True
            if active:
                raise ConfigUIError("Another LingxiAdvisor installation or configuration update is active")
            lock.unlink()
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise ConfigUIError("Another LingxiAdvisor installation or configuration update is active") from exc
        try:
            os.write(descriptor, json.dumps({"pid": os.getpid()}).encode("ascii"))
        finally:
            os.close(descriptor)
        return lock

    def update(self, values: Any, revision: Any) -> dict[str, Any]:
        if not isinstance(values, dict) or not isinstance(revision, str):
            raise ConfigUIError("Save request must include configuration values and revision")
        document = self._document()
        invalid = set(values) - _editable_fields(document["manifest"])
        if invalid:
            raise ConfigUIError("Save request contains a non-editable or unsupported setting")
        if revision != document["revision"]:
            raise ConfigUIError("Configuration changed after this page loaded; reload before saving")
        lock = self._lock(document["home"])
        try:
            # Re-read after acquiring the shared operation lock to close the
            # prepare/save race with install, inspect, update, or removal.
            document = self._document()
            invalid = set(values) - _editable_fields(document["manifest"])
            if invalid:
                raise ConfigUIError("Save request contains a non-editable or unsupported setting")
            if revision != document["revision"]:
                raise ConfigUIError("Configuration changed while waiting to save; reload and try again")
            updated = dict(document["configuration"])
            declarations = {item.get("id"): item for item in _inputs(document["manifest"])}
            for name, value in values.items():
                if name not in declarations:
                    raise ConfigUIError("Save request contains a setting absent from this Delivery")
                if value is None or isinstance(value, str) and not value.strip():
                    updated.pop(name, None)
                    if name in ALIASES:
                        updated.pop(ALIASES[name], None)
                    continue
                if not isinstance(value, (str, bool, int)) or isinstance(value, float):
                    raise ConfigUIError("Save request contains an invalid setting value", fields={name: "Use the declared field type"})
                updated[name] = value.strip() if isinstance(value, str) else value
                if name in ALIASES:
                    updated.pop(ALIASES[name], None)
            self._validate(document, updated)
            new_binding = {**document["binding"], "configuration": updated}
            binding_bytes = (json.dumps(new_binding, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            new_digest = _digest_bytes(binding_bytes)
            document["deployment"]["config_digest"] = new_digest
            state_bytes = (json.dumps(document["state"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            atomic_write(self.binding_path, binding_bytes)
            try:
                atomic_write(document["state_path"], state_bytes)
            except Exception:
                atomic_write(self.binding_path, document["binding_bytes"])
                raise
        except ConfigUIError:
            raise
        except OSError as exc:
            raise ConfigUIError("Could not safely save the managed configuration") from exc
        finally:
            lock.unlink(missing_ok=True)
        result = self.public_configuration()
        result["message"] = "Configuration saved. Restart or reload the host runtime to apply it."
        return result


def _static_html() -> bytes:
    return (Path(__file__).parent / "static" / "index.html").read_bytes()


class _Handler(BaseHTTPRequestHandler):
    # The installed Delivery manifest is the version authority exposed by the
    # API.  Keep the generic HTTP product header free of a second version.
    server_version = "LingxiAdvisorConfigUI"

    def log_message(self, format: str, *args: object) -> None:
        # Request bodies and environment values are intentionally never logged.
        sys.stderr.write(f"LingxiAdvisor configuration UI: {format % args}\n")

    def _headers(self, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()

    def _json(self, status: int, value: Mapping[str, Any]) -> None:
        payload = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        self._headers(status, "application/json; charset=utf-8")
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8")
            self.wfile.write(_static_html())
            return
        if self.path == "/api/config":
            try:
                self._json(HTTPStatus.OK, self.server.store.public_configuration())  # type: ignore[attr-defined]
            except ConfigUIError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc), "fields": exc.fields})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/config":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Use application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ConfigUIError("Save request size is invalid")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ConfigUIError("Save request must be a JSON object")
            result = self.server.store.update(payload.get("values"), payload.get("revision"))  # type: ignore[attr-defined]
            self._json(HTTPStatus.OK, result)
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Save request is invalid JSON"})
        except ConfigUIError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "fields": exc.fields})


class ConfigHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: ConfigStore):
        self.store = store
        super().__init__(address, _Handler)


def create_server(store: ConfigStore, *, host: str = LOOPBACK_HOST, port: int = 0) -> ConfigHTTPServer:
    try:
        if not socket.inet_aton(host) or not host.startswith("127."):
            raise OSError
    except OSError as exc:
        raise ConfigUIError("The LingxiAdvisor configuration UI only binds to IPv4 loopback") from exc
    return ConfigHTTPServer((host, port), store)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the local LingxiAdvisor configuration page")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--binding", type=Path, help="explicit managed binding path")
    source.add_argument("--home", type=Path, help="CodeHelix home (defaults to CODEHELIX_HOME or ~/.codehelix)")
    parser.add_argument("--deployment-id", help="select one active deployment from CodeHelix home")
    parser.add_argument("--port", type=int, default=0, help="loopback port (default: choose an available port)")
    parser.add_argument("--no-browser", action="store_true", help="print the URL without opening a browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        binding = resolve_binding(home=args.home, binding=args.binding, deployment_id=args.deployment_id)
        store = ConfigStore(binding)
        store.public_configuration()
        server = create_server(store, port=args.port)
    except ConfigUIError as exc:
        print(f"LingxiAdvisor configuration UI could not start: {exc}", file=sys.stderr)
        return 2
    url = f"http://{LOOPBACK_HOST}:{server.server_port}/"
    print(f"LingxiAdvisor configuration UI: {url}")
    print(f"Managed binding: {binding}")
    print("Press Ctrl+C to stop. Secrets remain in the startup environment and are never displayed.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
