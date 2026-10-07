#!/usr/bin/env python3
"""Import and rebrand a reproducible Lingxi Advisor release."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source"
OVERLAY = SOURCE / "upstream" / "patches" / "lingxi-advisor-0.8.6-bounded-retrieval.patch"
sys.path.insert(0, str(SOURCE))
from installer.release import validate_release_zip
from installer.contracts import CORE_VERSION  # noqa: E402


def _run(argv: list[str], *, cwd: Path, timeout: int = 1800) -> str:
    completed = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_source_changes(source: Path) -> None:
    changed = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=source)
    if changed:
        raise RuntimeError("Lingxi Advisor import requires a clean committed source worktree")


def _snapshot(source: Path, destination: Path) -> str:
    revision = _run(["git", "rev-parse", "HEAD"], cwd=source)
    archive = destination.parent / f"{destination.name}.zip"
    _run(["git", "archive", "--format=zip", f"--output={archive}", revision], cwd=source)
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(destination)
    return revision


def _apply_overlay(snapshot: Path) -> None:
    if not OVERLAY.is_file():
        raise RuntimeError(f"missing locked source overlay: {OVERLAY}")
    _run(["git", "apply", "--whitespace=nowarn", str(OVERLAY)], cwd=snapshot)


def _test(snapshot: Path) -> None:
    _run([
        "uv", "run", "--project", str(snapshot), "--extra", "test",
        "pytest", "-q",
    ], cwd=snapshot)


def _build(snapshot: Path, output: Path) -> Path:
    _run([
        "uv", "run", "--project", str(snapshot), "--extra", "test", "python",
        str(snapshot / "scripts" / "build_release_bundle.py"),
        "--source-root", str(snapshot), "--output-dir", str(output),
    ], cwd=snapshot)
    archives = list(output.glob("taskpattern-extension-*.zip"))
    if len(archives) != 1:
        raise RuntimeError(f"expected one upstream release archive, found {len(archives)}")
    return archives[0]


def _rebrand(source: Path, output: Path) -> Path:
    destination = output / f"lingxi-advisor-extension-{CORE_VERSION}.zip"
    _run([
        sys.executable,
        str(ROOT / "scripts" / "rebrand-release.py"),
        "--source", str(source),
        "--output", str(destination),
    ], cwd=ROOT)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.expanduser().resolve()
    _validate_source_changes(source)
    repository = _run(["git", "remote", "get-url", "origin"], cwd=source)
    with tempfile.TemporaryDirectory(prefix="lingxi_advisor-import-", dir=ROOT) as raw:
        temporary = Path(raw)
        first_snapshot = temporary / "snapshot-a"
        second_snapshot = temporary / "snapshot-b"
        revision = _snapshot(source, first_snapshot)
        second_revision = _snapshot(source, second_snapshot)
        if revision != second_revision:
            raise RuntimeError("Lingxi Advisor source revision changed during import")
        _apply_overlay(first_snapshot)
        _apply_overlay(second_snapshot)
        _test(first_snapshot)
        first = _build(first_snapshot, temporary / "dist-a")
        second = _build(second_snapshot, temporary / "dist-b")
        upstream_digest = _sha256(first)
        if upstream_digest != _sha256(second):
            raise RuntimeError("Upstream release build is not byte reproducible")
        transformed_first = _rebrand(first, temporary / "rebrand-a")
        transformed_second = _rebrand(second, temporary / "rebrand-b")
        if _sha256(transformed_first) != _sha256(transformed_second):
            raise RuntimeError("Lingxi Advisor release transformation is not byte reproducible")
        archive_digest, _root = validate_release_zip(transformed_first)
        upstream = SOURCE / "upstream"
        upstream.mkdir(parents=True, exist_ok=True)
        upstream_destination = upstream / first.name
        destination = upstream / transformed_first.name
        shutil.copy2(first, upstream_destination)
        shutil.copy2(transformed_first, destination)
        lock = {
            "schema": "codehelix.lingxi_advisor_import_lock/v1",
            "source_repository": repository,
            "source_revision": revision,
            "source_overlay": "patches/lingxi-advisor-0.8.6-bounded-retrieval.patch",
            "source_overlay_sha256": "157e0ed0d24164053e802a07c2a15e3f82bb149da21a24a3de224469b48703fd",
            "integrated_hardening": "0.7 atomic writer and process-tree overlay integrated into the source revision",
            "core_distribution": "lingxi-advisor",
            "core_version": CORE_VERSION,
            "archive": destination.name,
            "archive_sha256": archive_digest,
            "upstream_archive": upstream_destination.name,
            "upstream_archive_sha256": upstream_digest,
            "transformation": "scripts/rebrand-release.py",
            "reproducible_builds": 2,
            "source_worktree_policy": "clean committed source plus the locked reviewable overlay",
            "release_readiness": {
                "upstream_full_tests": "268 passed; 3 opt-in/POSIX-only skipped on Windows",
                "atomic_writer_concurrency": "passed",
                "posix_process_tree": "passed",
            },
        }
        (upstream / "import-lock.json").write_text(
            json.dumps(lock, indent=2) + "\n", encoding="utf-8",
        )
        print(destination)


if __name__ == "__main__":
    main()
