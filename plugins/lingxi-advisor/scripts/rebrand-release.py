#!/usr/bin/env python3
"""Create a deterministic Lingxi Advisor archive from the locked upstream release.

The upstream archive is retained as provenance. This transformation changes names
and public protocol identifiers only; it does not change retrieval, generation,
storage, or safety behavior.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
import zipfile


CORE_VERSION = "0.8.6"
ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "source" / "upstream" / f"taskpattern-extension-{CORE_VERSION}.zip"
DESTINATION = ROOT / "source" / "upstream" / f"lingxi-advisor-extension-{CORE_VERSION}.zip"
OLD_ROOT = f"taskpattern-extension-{CORE_VERSION}"
NEW_ROOT = f"lingxi-advisor-extension-{CORE_VERSION}"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

OPERATOR_TOOLS = (
    "knowledge_preparation_capabilities",
    "prepare_historical_knowledge",
    "start_preparation_batch",
    "get_preparation_batch",
    "get_preparation_result",
    "read_prepared_knowledge",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(rows: dict[str, bytes], record_name: str) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(rows):
        digest = base64.urlsafe_b64encode(hashlib.sha256(rows[name]).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={digest}", len(rows[name])))
    writer.writerow((record_name, "", ""))
    return output.getvalue().encode("utf-8")


def _transform_text(data: bytes) -> bytes:
    text = data.decode("utf-8")
    for name in OPERATOR_TOOLS:
        text = text.replace(f"'{name}'", f"'lingxi.advisor.{name}'")
        text = text.replace(f'"{name}"', f'"lingxi.advisor.{name}"')
        text = text.replace(f"`{name}`", f"`lingxi.advisor.{name}`")
    replacements = (
        ("taskpattern.search", "lingxi.advisor.search"),
        ("taskpattern.apply", "lingxi.advisor.apply"),
        ("taskpattern://", "lingxi.advisor://"),
        ("TASK_PATTERN_", "LINGXI_ADVISOR_"),
        ("TASKPATTERN_", "LINGXI_ADVISOR_"),
        ("TASKPATTERN", "LINGXI_ADVISOR"),
        ("Task Pattern Advisor", "Lingxi Advisor"),
        ("Task Pattern", "Lingxi Advisor"),
        ("TaskPattern", "LingxiAdvisor"),
        ("task_pattern", "lingxi_advisor"),
        ("task-pattern", "lingxi-advisor"),
        ("taskpattern", "lingxi_advisor"),
        ("lingxi_advisor-mcp", "lingxi-advisor-mcp"),
        ("lingxi_advisor-generate", "lingxi-advisor-generate"),
        ("lingxi_advisor-prepare", "lingxi-advisor-prepare"),
        ("lingxi_advisor-candidate-search", "lingxi-advisor-candidate-search"),
        ("Name: lingxi_advisor", "Name: lingxi-advisor"),
        ('"id": "lingxi_advisor"', '"id": "lingxi-advisor"'),
        ("name: lingxi_advisor", "name: lingxi-advisor"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text.replace("\r\n", "\n").encode("utf-8")


def _transform_path(name: str) -> str:
    transformed = (
        name.replace("taskpattern-extension", "lingxi-advisor-extension")
        .replace("taskpattern_codehelix_host", "lingxi_advisor_host")
        .replace("task_pattern", "lingxi_advisor")
        .replace("task-pattern", "lingxi-advisor")
        .replace("taskpattern", "lingxi_advisor")
    )
    if transformed.startswith("skills/lingxi_advisor/"):
        transformed = transformed.replace("skills/lingxi_advisor/", "skills/lingxi-advisor/", 1)
    return transformed


def _transform_wheel(data: bytes) -> bytes:
    rows: dict[str, bytes] = {}
    with zipfile.ZipFile(BytesIO(data)) as wheel:
        for info in wheel.infolist():
            if info.is_dir() or info.filename.endswith(".dist-info/RECORD"):
                continue
            name = _transform_path(info.filename)
            payload = wheel.read(info)
            if not name.endswith((".pyc", ".png", ".jpg", ".jpeg", ".gif")):
                payload = _transform_text(payload)
            rows[name] = payload
    record_name = f"lingxi_advisor-{CORE_VERSION}.dist-info/RECORD"
    rows[record_name] = _record(rows, record_name)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as wheel:
        for name in sorted(rows):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            wheel.writestr(info, rows[name])
    return output.getvalue()


def build(source_archive: Path = UPSTREAM, destination: Path = DESTINATION) -> Path:
    """Transform one upstream archive without altering runtime behavior."""
    if not source_archive.is_file():
        raise SystemExit(f"Missing locked upstream archive: {source_archive}")
    rows: dict[str, bytes] = {}
    with zipfile.ZipFile(source_archive) as source:
        names = [PurePosixPath(info.filename) for info in source.infolist() if not info.is_dir()]
        if not names or {name.parts[0] for name in names} != {OLD_ROOT}:
            raise SystemExit("Unexpected upstream archive root")
        for path in names:
            relative = path.relative_to(OLD_ROOT).as_posix()
            if relative == "CHECKSUMS.sha256":
                continue
            payload = source.read(path.as_posix())
            transformed = _transform_path(relative)
            if relative.endswith(".whl"):
                payload = _transform_wheel(payload)
            else:
                payload = _transform_text(payload)
            rows[transformed] = payload
    checksums = "\n".join(f"{_sha256(rows[name])}  {name}" for name in sorted(rows)) + "\n"
    rows["CHECKSUMS.sha256"] = checksums.encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for relative in sorted(rows):
            info = zipfile.ZipInfo(f"{NEW_ROOT}/{relative}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, rows[relative])
    print(f"{destination} sha256={_sha256(destination.read_bytes())}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=UPSTREAM)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    args = parser.parse_args()
    build(args.source.expanduser().resolve(), args.output.expanduser().resolve())


if __name__ == "__main__":
    main()
