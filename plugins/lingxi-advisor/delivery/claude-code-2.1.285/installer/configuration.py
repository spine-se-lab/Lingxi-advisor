"""Non-secret deployment settings and explicit process-environment mapping.

This module is shared by preflight and the launcher. It neither reads dotenv
files nor writes configuration or credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit
import re
import os
import shutil
import subprocess

from .contracts import InstallError


GITHUB_VARIABLES = ("GITHUB_TOKEN", *(f"GITHUB_TOKEN_{i}" for i in range(1, 16)))
MODEL_VARIABLES = ("LINGXI_ADVISOR_MODEL_API_KEY", "LINGXI_ADVISOR_JUDGE_API_KEY", "LINGXI_ADVISOR_GENERATOR_API_KEY")
STARTUP_VARIABLES = (*GITHUB_VARIABLES, *MODEL_VARIABLES)
# Hosts whose MCP client does not advertise the sampling capability during
# initialize (recorded from OpenCode 1.18.34 and Claude Code 2.1.285). Runtime
# Search cannot borrow their model, so these targets require a custom model.
HOST_SAMPLING_UNSUPPORTED = {"opencode": "OpenCode", "claude-code": "Claude Code"}
PROCESS_VARIABLES = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    "TEMP", "TMP", "TMPDIR", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "NO_COLOR",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
}


def boolean(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise InstallError(f"{name} must be true or false")


def absolute_path(value: Any, name: str, *, follow_symlinks: bool = True) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
        raise InstallError(f"{name} must be an absolute directory or file path")
    result = Path(value).expanduser()
    if not result.is_absolute():
        raise InstallError(f"{name} must be an absolute directory or file path")
    return result.resolve() if follow_symlinks else Path(os.path.abspath(result))


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or any(c in value for c in ("\r", "\n", "\0")):
        raise InstallError(f"{name} must be a single-line string")
    return value.strip()


@dataclass(frozen=True)
class DeploymentConfiguration:
    data_root: Path
    model_name: str = ""
    model_base_url: str = ""
    judge_max_output_tokens: int = 32768
    generator_max_output_tokens: int = 26000
    generator_timeout_seconds: int = 300
    mcp_request_timeout_seconds: int = 600
    allow_preretrieved_updates: bool = True
    allow_live_search: bool = True
    allow_refresh: bool = False
    allow_clone: bool = False
    allow_fetch: bool = False
    batch_input_path: Path | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, default_data_root: Path) -> "DeploymentConfiguration":
        if not isinstance(raw, Mapping):
            raise InstallError("configuration must be an object")
        allowed = {"issue_tracking_provider", "data_root", "gate_model_name", "gate_model_base_url",
                   "model_name", "model_base_url", "allow_preretrieved_updates", "allow_live_search",
                   "allow_refresh", "allow_clone", "allow_fetch", "batch_input_path", "judge_max_output_tokens",
                   "generator_max_output_tokens", "generator_timeout_seconds", "mcp_request_timeout_seconds"}
        if set(raw) - allowed:
            # Do not echo unknown keys: malformed input can itself contain credentials.
            raise InstallError("Unsupported deployment configuration; credentials belong in the startup environment")
        if raw.get("issue_tracking_provider", "github") != "github":
            raise InstallError("Only GitHub issue tracking is supported")
        model = _text(raw.get("gate_model_name") or raw.get("model_name") or "", "gate_model_name")
        endpoint = _text(raw.get("gate_model_base_url") or raw.get("model_base_url") or "", "gate_model_base_url")
        if bool(model) != bool(endpoint):
            raise InstallError("gate_model_name and gate_model_base_url must be supplied together")
        if endpoint:
            try:
                url = urlsplit(endpoint)
                valid = url.scheme in {"http", "https"} and bool(url.hostname) and not any(
                    (url.username, url.password, url.query, url.fragment)
                ) and not re.search(r"\s", endpoint)
            except ValueError:
                valid = False
            if not valid:
                raise InstallError("gate_model_base_url must be an HTTP(S) endpoint without credentials, query or fragment")
        flags = {name: boolean(raw.get(name, default), name) for name, default in (
            ("allow_preretrieved_updates", True), ("allow_live_search", True),
            ("allow_refresh", False), ("allow_clone", False), ("allow_fetch", False),
        )}
        def bounded_integer(name: str, default: int, minimum: int, maximum: int) -> int:
            value = raw.get(name, default)
            if (isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value))
                    or not minimum <= int(value) <= maximum):
                raise InstallError(
                    f"{name} must be an integer from {minimum} to {maximum}"
                )
            return int(value)

        judge_tokens = bounded_integer("judge_max_output_tokens", 32768, 1024, 131072)
        generator_tokens = bounded_integer("generator_max_output_tokens", 26000, 1024, 131072)
        generator_timeout = bounded_integer("generator_timeout_seconds", 300, 30, 1800)
        mcp_timeout = bounded_integer("mcp_request_timeout_seconds", 600, 30, 1800)
        batch = raw.get("batch_input_path")
        return cls(data_root=absolute_path(raw.get("data_root") or default_data_root, "data_root"),
                   model_name=model, model_base_url=endpoint, judge_max_output_tokens=judge_tokens,
                   generator_max_output_tokens=generator_tokens,
                   generator_timeout_seconds=generator_timeout,
                   mcp_request_timeout_seconds=mcp_timeout,
                   batch_input_path=absolute_path(batch, "batch_input_path") if batch else None, **flags)

    @property
    def model_backend(self) -> str:
        return "custom" if self.model_name else "agent_host"

    def require_model_for(self, agent_system: str, *, suggestion: str = "") -> None:
        """Reject Agent Host sampling for hosts that cannot provide it."""
        host = HOST_SAMPLING_UNSUPPORTED.get(agent_system)
        if host and self.model_backend != "custom":
            raise InstallError(
                f"{host} does not support MCP sampling, so Lingxi Advisor needs its own model: "
                "set gate_model_name and gate_model_base_url (OpenAI-compatible endpoint) "
                "and provide LINGXI_ADVISOR_MODEL_API_KEY in the startup environment"
                + (f". {suggestion}" if suggestion else "")
            )

    def validate_credentials(self, environment: Mapping[str, str], *, require_github: bool) -> None:
        if require_github and not any(environment.get(name, "").strip() for name in GITHUB_VARIABLES):
            raise InstallError("Missing startup environment: GITHUB_TOKEN or GITHUB_TOKEN_1…15")
        if self.model_backend == "custom":
            missing = [name for name in MODEL_VARIABLES[1:]
                       if not (environment.get(name) or environment.get("LINGXI_ADVISOR_MODEL_API_KEY"))]
            if missing:
                raise InstallError("Missing startup environment: LINGXI_ADVISOR_MODEL_API_KEY or " + ", ".join(missing))

    def runtime_environment(
        self,
        environment: Mapping[str, str],
        *,
        retrieval_strategy: str = "bounded",
    ) -> dict[str, str]:
        if retrieval_strategy not in {"bounded", "evaluation"}:
            raise InstallError("retrieval_strategy must be bounded or evaluation")
        result = {name: value for name, value in environment.items()
                  if name in PROCESS_VARIABLES or name in STARTUP_VARIABLES}
        tokens = list(dict.fromkeys(token.strip() for name in GITHUB_VARIABLES
                                   for token in re.split(r"[,;\r\n]+", environment.get(name, "")) if token.strip()))
        if len(tokens) > len(GITHUB_VARIABLES):
            raise InstallError("At most 16 distinct GitHub startup tokens are supported")
        for name in GITHUB_VARIABLES:
            result.pop(name, None)
        result.update(zip(GITHUB_VARIABLES, tokens))
        for name in STARTUP_VARIABLES:
            if name in result and any(c in result[name] for c in ("\r", "\n", "\0")):
                raise InstallError(f"Invalid control character in startup environment: {name}")
        # Only selected model mode/configuration reaches the core. An unrelated
        # shell LINGXI_ADVISOR_* setting must not override the managed deployment.
        if self.model_backend == "custom":
            for role in ("JUDGE", "GENERATOR"):
                result[f"LINGXI_ADVISOR_{role}_API_KEY"] = environment.get(f"LINGXI_ADVISOR_{role}_API_KEY") or environment.get("LINGXI_ADVISOR_MODEL_API_KEY", "")
                result[f"LINGXI_ADVISOR_{role}_MODEL"] = self.model_name
                result[f"LINGXI_ADVISOR_{role}_BASE_URL"] = self.model_base_url
        else:
            for name in MODEL_VARIABLES:
                result.pop(name, None)
        result["PYTHONDONTWRITEBYTECODE"] = "1"
        result["LINGXI_ADVISOR_JUDGE_MAX_OUTPUT_TOKENS"] = str(self.judge_max_output_tokens)
        result["LINGXI_ADVISOR_GENERATOR_MAX_OUTPUT_TOKENS"] = str(self.generator_max_output_tokens)
        result["LINGXI_ADVISOR_GENERATOR_TIMEOUT_SECONDS"] = str(self.generator_timeout_seconds)
        # Ambient LINGXI_ADVISOR_* values remain untrusted.  The managed launcher
        # supplies this explicit, validated value; ordinary deployments keep
        # the bounded default while an evaluation adapter may opt in.
        result["LINGXI_ADVISOR_RETRIEVAL_STRATEGY"] = retrieval_strategy
        result["PYTHONIOENCODING"] = "utf-8"
        return result


def github_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Use environment tokens first, then the GitHub CLI credential store."""
    result = dict(environment)
    if any(result.get(name, "").strip() for name in GITHUB_VARIABLES):
        return result
    executable = shutil.which("gh", path=result.get("PATH"))
    if not executable:
        return result
    try:
        completed = subprocess.run(
            [executable, "auth", "token"],
            env=result,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return result
    token = completed.stdout.strip()
    if completed.returncode == 0 and token and not any(
        character in token for character in ("\r", "\n", "\0")
    ):
        result["GITHUB_TOKEN"] = token
    return result


def redact(message: str, environment: Mapping[str, str]) -> str:
    for value in sorted({v for k, v in environment.items() if v and re.search(r"TOKEN|KEY|SECRET|PASSWORD", k, re.I)}, key=len, reverse=True):
        message = message.replace(value, "[REDACTED]")
    return message
