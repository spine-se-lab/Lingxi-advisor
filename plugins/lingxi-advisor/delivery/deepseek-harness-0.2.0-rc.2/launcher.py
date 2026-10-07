"""Start the installed LingxiAdvisor profile from a non-secret managed binding.

Use the core server factory directly. Its CLI's implicit project-root/.env
loading is deliberately not part of the managed process lifecycle.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import time

from installer.configuration import DeploymentConfiguration, absolute_path, github_environment, redact
from installer.contracts import InstallError, PLUGIN_ID
from installer.runtime_compat import install_runtime_compatibility

logger = logging.getLogger(__name__)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
RETRIEVAL_STRATEGIES = ("bounded", "evaluation")
EVALUATION_PREPARATION_SCHEMA = "lingxi.advisor.evaluation_preparation/v1"
EVALUATION_CATALOG_TTL_SECONDS = 86400
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def load_configuration(binding: Path, data_root: Path) -> DeploymentConfiguration:
    try:
        value = json.loads(binding.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError("Managed binding is missing or invalid; inspect the LingxiAdvisor deployment") from exc
    if not isinstance(value, dict) or value.get("schema") != "codehelix.plugin_binding/v1" or value.get("plugin_id") != PLUGIN_ID:
        raise InstallError("Managed binding identity mismatch")
    if value.get("package_ref", {}).get("root") != str(Path(__file__).resolve().parent):
        raise InstallError("Managed binding refers to a different PackageStore release")
    config = DeploymentConfiguration.from_mapping(value.get("configuration", {}), default_data_root=data_root)
    if config.data_root != data_root.resolve():
        raise InstallError("Managed binding data root differs from the activation; reinstall to update the binding")
    return config


def create_server(
    config: DeploymentConfiguration,
    profile: str,
    *,
    compact_search_results: bool = False,
):
    from lingxi_advisor.adapters.mcp.server import create_mcp_server
    from lingxi_advisor.adapters.mcp.gateway import MCPServerPolicy
    from lingxi_advisor.config import ServerSettings

    server = create_mcp_server(profile=profile,
        settings=ServerSettings(project_root=config.data_root, batch_input_path=config.batch_input_path),
        policy=MCPServerPolicy(allow_update_preretrieved=config.allow_preretrieved_updates,
            allow_live_search=config.allow_live_search, allow_refresh=config.allow_refresh,
            allow_clone=config.allow_clone, allow_fetch=config.allow_fetch))
    if profile == "runtime":
        install_runtime_compatibility(
            server, compact_search=compact_search_results
        )
    return server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a managed LingxiAdvisor MCP profile")
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", choices=("runtime", "operator"), required=True)
    parser.add_argument("--log-level", choices=LOG_LEVELS, default="INFO")
    parser.add_argument(
        "--retrieval-strategy", choices=RETRIEVAL_STRATEGIES, default="bounded"
    )
    parser.add_argument("--prepare-evaluation", action="store_true")
    parser.add_argument("--evaluation-repository")
    parser.add_argument("--evaluation-preparation", type=Path)
    parser.add_argument("--compact-search-results", action="store_true")
    return parser.parse_args(argv)


def _evaluation_cache_files(data_root: Path, repository: str) -> tuple[Path, Path]:
    owner, name = repository.split("/", 1)

    def safe_part(value: str, max_len: int = 180) -> str:
        result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._") or "empty"
        if len(result) > max_len:
            digest = hashlib.sha256(result.encode("utf-8")).hexdigest()[:12]
            result = f"{result[: max_len - 13]}_{digest}"
        return result

    directory = (
        data_root.resolve()
        / "cache"
        / "closed_issues"
        / f"{safe_part(owner)}__{safe_part(name)}"
    )
    return directory / "raw_closed_items.jsonl", directory / "sync_state.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_evaluation_catalog(
    config: DeploymentConfiguration, repository: str
) -> Path:
    """Prepare the shared exhaustive catalog before any measured task starts."""
    if not _REPOSITORY_RE.fullmatch(repository):
        raise InstallError("Evaluation repository must be owner/repository")

    from lingxi_advisor.config import ServerSettings
    from lingxi_advisor.internal import github as github_api
    from lingxi_advisor.internal.io_utils import write_json_atomic
    from lingxi_advisor.internal.search_retrieval.closed_issues import ClosedIssueProvider

    settings = ServerSettings(project_root=config.data_root).resolved()
    if not settings.github_tokens:
        raise InstallError(
            "Evaluation preparation requires GITHUB_TOKEN or GITHUB_TOKEN_1…15"
        )
    assert settings.cache_root is not None
    client = github_api.GithubClient(
        token_rotator=github_api.GithubTokenRotator(settings.github_tokens),
        timeout=settings.github_timeout_seconds,
        verify_ssl=settings.verify_ssl,
        trust_env=settings.trust_env,
        max_retries=settings.github_max_retries,
    )
    request_count = 0
    http_request = client.client.request

    def counted_http_request(*args, **kwargs):
        nonlocal request_count
        request_count += 1
        logger.info(
            "Evaluation preparation GitHub request started: repository=%s request=%d",
            repository,
            request_count,
        )
        return http_request(*args, **kwargs)

    client.client.request = counted_http_request
    started_at = dt.datetime.now(dt.timezone.utc)
    started = time.perf_counter()
    logger.info(
        "Evaluation preparation started: repository=%s; this is outside measured task execution",
        repository,
    )
    try:
        catalog = ClosedIssueProvider(settings.cache_root).load(
            repo=repository,
            client=client,
            boundary_ts=float("inf"),
            target_issue_number=None,
            ttl_seconds=EVALUATION_CATALOG_TTL_SECONDS,
            refresh=False,
            enable_issue_number_guard=False,
        )
    finally:
        client.close()
    if catalog.stale_cache_used:
        raise InstallError(
            "Evaluation preparation could not refresh an expired catalog; task execution was not started"
        )

    raw_path, metadata_path = _evaluation_cache_files(config.data_root, repository)
    if not raw_path.is_file() or not metadata_path.is_file():
        raise InstallError("Evaluation preparation did not produce a complete catalog snapshot")
    finished_at = dt.datetime.now(dt.timezone.utc)
    snapshot_sha256 = _sha256(raw_path)
    record = {
        "schema": EVALUATION_PREPARATION_SCHEMA,
        "status": "completed",
        "retrieval_strategy": "evaluation",
        "scope": "repository_closed_issue_catalog",
        "repository": repository,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "github_request_count": request_count,
        "cache_status": "hit" if catalog.fetched_from_cache else "refreshed",
        "catalog_ttl_seconds": EVALUATION_CATALOG_TTL_SECONDS,
        "snapshot": {
            "fetched_at": catalog.fetched_at,
            "sha256": snapshot_sha256,
            "metadata_sha256": _sha256(metadata_path),
            "raw_item_count": catalog.raw_item_count,
            "closed_issue_count": catalog.closed_issue_count,
            "path": str(raw_path),
            "metadata_path": str(metadata_path),
        },
    }
    output = config.data_root / "outputs" / "evaluation_preparations"
    output.mkdir(parents=True, exist_ok=True)
    stamp = finished_at.strftime("%Y%m%dT%H%M%S%fZ")
    record_path = output / f"{repository.replace('/', '__')}--{stamp}.json"
    write_json_atomic(record_path, record)
    logger.info(
        "Evaluation preparation completed: repository=%s cache_status=%s requests=%d duration_ms=%d record=%s",
        repository,
        record["cache_status"],
        request_count,
        record["duration_ms"],
        record_path,
    )
    return record_path


def validate_evaluation_preparation(
    data_root: Path, repository: str, record_path: Path | None
) -> dict:
    """Require the exact pre-task snapshot instead of rebuilding during Search."""
    if not _REPOSITORY_RE.fullmatch(repository):
        raise InstallError("Evaluation repository must be owner/repository")
    if record_path is None:
        raise InstallError(
            "Evaluation retrieval requires an explicit pre-task preparation record"
        )
    root = data_root.resolve()
    record_path = record_path.expanduser().resolve()
    try:
        record_path.relative_to(root / "outputs" / "evaluation_preparations")
    except ValueError as exc:
        raise InstallError("Evaluation preparation record is outside the LingxiAdvisor data directory") from exc
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError("Evaluation preparation record is missing or invalid") from exc
    if (
        record.get("schema") != EVALUATION_PREPARATION_SCHEMA
        or record.get("status") != "completed"
        or record.get("retrieval_strategy") != "evaluation"
        or record.get("scope") != "repository_closed_issue_catalog"
        or record.get("repository") != repository
    ):
        raise InstallError("Evaluation preparation record does not match this repository and strategy")
    raw_path, metadata_path = _evaluation_cache_files(root, repository)
    snapshot = record.get("snapshot") or {}
    if (
        not raw_path.is_file()
        or not metadata_path.is_file()
        or snapshot.get("path") != str(raw_path)
        or snapshot.get("metadata_path") != str(metadata_path)
        or snapshot.get("sha256") != _sha256(raw_path)
        or snapshot.get("metadata_sha256") != _sha256(metadata_path)
    ):
        raise InstallError("Evaluation catalog snapshot is missing or changed; prepare it again")
    try:
        fetched = dt.datetime.fromisoformat(
            str(snapshot["fetched_at"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InstallError("Evaluation preparation record has no valid snapshot time") from exc
    age = (dt.datetime.now(dt.timezone.utc) - fetched).total_seconds()
    if age < 0 or age > int(record.get("catalog_ttl_seconds") or 0):
        raise InstallError("Evaluation catalog snapshot expired; prepare it again before running tasks")
    return record


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)
    startup = github_environment(os.environ)
    try:
        logger.info(
            "LingxiAdvisor managed launcher started: profile=%s log_level=%s",
            args.profile,
            args.log_level,
        )
        config = load_configuration(args.binding, absolute_path(args.data_root, "data_root"))
        config.validate_credentials(startup, require_github=False)
        environment = config.runtime_environment(
            startup, retrieval_strategy=args.retrieval_strategy
        )
        os.environ.clear()
        os.environ.update(environment)
        config.data_root.mkdir(parents=True, exist_ok=True)
        os.chdir(config.data_root)
        if args.prepare_evaluation:
            if args.retrieval_strategy != "evaluation" or not args.evaluation_repository:
                raise InstallError(
                    "--prepare-evaluation requires --retrieval-strategy evaluation and --evaluation-repository"
                )
            print(prepare_evaluation_catalog(config, args.evaluation_repository), flush=True)
            return 0
        if args.retrieval_strategy == "evaluation":
            if not args.evaluation_repository:
                raise InstallError(
                    "Evaluation retrieval requires --evaluation-repository"
                )
            validate_evaluation_preparation(
                config.data_root,
                args.evaluation_repository,
                args.evaluation_preparation,
            )
        create_server(
            config,
            args.profile,
            compact_search_results=args.compact_search_results,
        ).run(transport="stdio")
        return 0
    except InstallError as exc:
        logger.error(
            "LingxiAdvisor managed launcher failed: stage=startup reason=%s",
            redact(str(exc), startup),
        )
        return 2
    except Exception as exc:
        # Transport/library exceptions may contain HTTP headers or user input.
        # Report the failure class without echoing untrusted exception payloads.
        logger.error(
            "LingxiAdvisor managed launcher failed: stage=startup reason=%s; "
            "inspect the deployment and startup environment",
            type(exc).__name__,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
