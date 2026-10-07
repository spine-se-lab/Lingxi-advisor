from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from conftest import PLUGIN_ROOT


SOURCE_ROOT = PLUGIN_ROOT / "source"
sys.path.insert(0, str(SOURCE_ROOT))
SPEC = importlib.util.spec_from_file_location(
    "lingxi_advisor_managed_launcher", SOURCE_ROOT / "launcher.py"
)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_evaluation_server_requires_the_prepared_snapshot_unchanged(tmp_path):
    raw_path, metadata_path = launcher._evaluation_cache_files(tmp_path, "owner/repo")
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text('{"number": 1}\n', encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "schema": launcher.EVALUATION_PREPARATION_SCHEMA,
        "status": "completed",
        "retrieval_strategy": "evaluation",
        "scope": "repository_closed_issue_catalog",
        "repository": "owner/repo",
        "finished_at": now,
        "catalog_ttl_seconds": launcher.EVALUATION_CATALOG_TTL_SECONDS,
        "snapshot": {
            "fetched_at": now,
            "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
            "path": str(raw_path),
            "metadata_path": str(metadata_path),
        },
    }
    record_path = tmp_path / "outputs/evaluation_preparations/record.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps(record), encoding="utf-8")

    assert launcher.validate_evaluation_preparation(
        tmp_path, "owner/repo", record_path
    )["status"] == "completed"

    raw_path.write_text('{"number": 2}\n', encoding="utf-8")
    with pytest.raises(launcher.InstallError, match="missing or changed"):
        launcher.validate_evaluation_preparation(tmp_path, "owner/repo", record_path)


def test_evaluation_server_rejects_missing_preparation_record(tmp_path):
    with pytest.raises(launcher.InstallError, match="explicit pre-task preparation"):
        launcher.validate_evaluation_preparation(tmp_path, "owner/repo", None)
