"""Build the Codex host wheel from the locked Lingxi Advisor 0.8.6 wheel."""
from __future__ import annotations

import base64
import csv
import hashlib
from io import BytesIO, StringIO
from pathlib import Path
import re
import zipfile


CORE_VERSION = "0.8.6"
DISTRIBUTION = "lingxi_advisor_codehelix_host"
WHEEL_NAME = f"{DISTRIBUTION}-{CORE_VERSION}-py3-none-any.whl"
ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / f"lingxi-advisor-extension-{CORE_VERSION}.zip"
HOST_SOURCE = ROOT / "native_host" / "lingxi_advisor_codehelix_host"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _locked_wheel() -> bytes:
    with zipfile.ZipFile(ARCHIVE) as release:
        matches = [
            name
            for name in release.namelist()
            if name.endswith(f"/runtime/lingxi_advisor-{CORE_VERSION}-py3-none-any.whl")
        ]
        if len(matches) != 1:
            raise RuntimeError("Locked Lingxi Advisor release must contain exactly one core wheel")
        return release.read(matches[0])


def _record(rows: dict[str, bytes], record_name: str) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(rows):
        digest = base64.urlsafe_b64encode(hashlib.sha256(rows[name]).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={digest}", len(rows[name])))
    writer.writerow((record_name, "", ""))
    return output.getvalue().encode("utf-8")


def _metadata(original: bytes) -> bytes:
    updated, count = re.subn(
        br"(?m)^Name:[^\r\n]*\r?$",
        b"Name: lingxi-advisor-codehelix-host",
        original,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Locked Lingxi Advisor wheel has no distribution name")
    return updated.replace(b"\r\n", b"\n")


def build_wheel(wheel_directory: str, config_settings=None, metadata_directory=None) -> str:
    del config_settings, metadata_directory
    dist_info = f"{DISTRIBUTION}-{CORE_VERSION}.dist-info"
    rows: dict[str, bytes] = {}
    original_metadata = original_wheel = original_entries = None
    with zipfile.ZipFile(BytesIO(_locked_wheel())) as core:
        for info in core.infolist():
            name = info.filename
            if name.endswith(".dist-info/METADATA"):
                original_metadata = core.read(name)
            elif name.endswith(".dist-info/WHEEL"):
                original_wheel = core.read(name)
            elif name.endswith(".dist-info/entry_points.txt"):
                original_entries = core.read(name)
            elif ".dist-info/" not in name and not name.endswith("/"):
                rows[name] = core.read(name)
    if not all((original_metadata, original_wheel, original_entries)):
        raise RuntimeError("Locked Lingxi Advisor wheel metadata is incomplete")
    rows[f"{dist_info}/METADATA"] = _metadata(original_metadata)
    rows[f"{dist_info}/WHEEL"] = original_wheel
    entries = original_entries.decode("utf-8").rstrip() + (
        "\nlingxi-advisor-codehelix-runtime = "
        "lingxi_advisor_codehelix_host.codex:runtime_main\n"
    )
    rows[f"{dist_info}/entry_points.txt"] = entries.encode("utf-8")
    rows[f"{dist_info}/top_level.txt"] = b"lingxi_advisor\nlingxi_advisor_codehelix_host\n"
    for source in sorted(HOST_SOURCE.rglob("*.py")):
        relative = source.relative_to(HOST_SOURCE.parent).as_posix()
        rows[relative] = source.read_bytes()
    record_name = f"{dist_info}/RECORD"
    rows[record_name] = _record(rows, record_name)

    destination = Path(wheel_directory) / WHEEL_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as wheel:
        for name in sorted(rows):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            wheel.writestr(info, rows[name])
    return WHEEL_NAME
