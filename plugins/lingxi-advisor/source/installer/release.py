from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contracts import CORE_VERSION, InstallError, OPERATOR_TOOLS, RUNTIME_TOOLS


@dataclass(frozen=True)
class ReleaseInfo:
    root: Path
    version: str
    digest: str
    wheel: Path
    skill: Path
    operator_skill: Path

    @property
    def release_key(self) -> str:
        return f"{self.version}-{self.digest[:12]}"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def tree_digest(root: Path) -> str:
    value = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        value.update(relative.encode())
        value.update(bytes([0]))
        value.update(path.read_bytes())
        value.update(bytes([0]))
    return value.hexdigest()


def _checksum_map(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        digest, separator, relative = raw.partition("  ")
        if not separator or len(digest) != 64 or relative in result:
            raise InstallError("LingxiAdvisor CHECKSUMS.sha256 is invalid")
        candidate = PurePosixPath(relative)
        if candidate.is_absolute() or ".." in candidate.parts or chr(92) in relative:
            raise InstallError("LingxiAdvisor checksum contains an unsafe path")
        result[relative] = digest
    return result


def validate_release_directory(root: Path) -> ReleaseInfo:
    root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise InstallError("LingxiAdvisor release root is missing or is a symlink")
    for item in root.rglob("*"):
        if item.is_symlink():
            raise InstallError(f"LingxiAdvisor release contains a symlink: {item}")
    bundle_path = root / "bundle.json"
    checksum_path = root / "CHECKSUMS.sha256"
    if not bundle_path.is_file() or not checksum_path.is_file():
        raise InstallError("LingxiAdvisor release metadata is incomplete")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    expected_wheel = f"runtime/lingxi_advisor-{CORE_VERSION}-py3-none-any.whl"
    if bundle != {
        "schema_version": 1,
        "id": "lingxi-advisor",
        "version": CORE_VERSION,
        "runtime_wheels": [expected_wheel],
    }:
        raise InstallError("LingxiAdvisor release identity or wheel declaration is invalid")
    checksums = _checksum_map(root)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if set(checksums) != actual:
        raise InstallError("LingxiAdvisor release is not closed-world")
    for relative, expected in checksums.items():
        if sha256(root / relative) != expected:
            raise InstallError(f"LingxiAdvisor release checksum mismatch: {relative}")
    runtime = json.loads((root / "packaging" / "runtime-server.json").read_text(encoding="utf-8"))
    if runtime.get("profile") != "runtime" or tuple(runtime.get("tools") or ()) != RUNTIME_TOOLS:
        raise InstallError("LingxiAdvisor runtime descriptor must expose exactly Search and Apply")
    operator = json.loads((root / "packaging" / "operator-server.json").read_text(encoding="utf-8"))
    if operator.get("profile") != "operator" or tuple(operator.get("tools") or ()) != OPERATOR_TOOLS:
        raise InstallError("LingxiAdvisor operator descriptor is invalid")
    wheel = root / expected_wheel
    skill = root / "skills" / "lingxi-advisor"
    operator_skill = root / "skills" / "knowledge-preparation-operator"
    if (
        not wheel.is_file()
        or not (skill / "SKILL.md").is_file()
        or not (operator_skill / "SKILL.md").is_file()
    ):
        raise InstallError("LingxiAdvisor wheel or Skills are missing")
    return ReleaseInfo(
        root=root,
        version=CORE_VERSION,
        digest=tree_digest(root),
        wheel=wheel,
        skill=skill,
        operator_skill=operator_skill,
    )


def validate_release_zip(archive: Path) -> tuple[str, str]:
    archive = archive.resolve()
    with zipfile.ZipFile(archive) as source:
        if not source.namelist():
            raise InstallError("LingxiAdvisor release archive is empty")
        roots: set[str] = set()
        for info in source.infolist():
            name = info.filename
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or chr(92) in name:
                raise InstallError(f"LingxiAdvisor archive contains an unsafe path: {name}")
            if info.external_attr and stat.S_ISLNK(info.external_attr >> 16):
                raise InstallError(f"LingxiAdvisor archive contains a symlink: {name}")
            if path.parts:
                roots.add(path.parts[0])
        expected_root = f"lingxi-advisor-extension-{CORE_VERSION}"
        if roots != {expected_root}:
            raise InstallError("LingxiAdvisor archive top-level directory is invalid")
        bundle = json.loads(source.read(f"{expected_root}/bundle.json").decode("utf-8"))
        if bundle.get("id") != "lingxi-advisor" or bundle.get("version") != CORE_VERSION:
            raise InstallError("LingxiAdvisor archive identity is invalid")
    return sha256(archive), expected_root


def extract_release_zip(archive: Path, destination: Path) -> ReleaseInfo:
    _digest, top = validate_release_zip(archive)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            relative = PurePosixPath(info.filename).relative_to(top)
            if not relative.parts:
                continue
            target = destination.joinpath(*relative.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(info))
    return validate_release_directory(destination)
