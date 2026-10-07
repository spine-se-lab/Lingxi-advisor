from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

INSTALL_RECORD = ".lingxi_advisor-install.json"


def _absolute_executable(path: Path) -> Path:
    """Make an interpreter path absolute without resolving a venv symlink."""

    expanded = path.expanduser()
    if not expanded.is_absolute() and expanded.parent == Path("."):
        discovered = shutil.which(str(expanded))
        if discovered:
            return Path(os.path.abspath(discovered))
    return Path(os.path.abspath(expanded))


def _default_bundle_root() -> Path:
    return Path(__file__).resolve().parent


def _default_install_root() -> Path:
    configured = str(os.environ.get("LINGXI_ADVISOR_EXTENSION_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    data_home = str(os.environ.get("XDG_DATA_HOME") or "").strip()
    base = (
        Path(data_home).expanduser()
        if data_home
        else Path.home() / ".local" / "share"
    )
    return (base / "lingxi_advisor-extension").resolve()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_bundle(root: Path) -> tuple[str, Path]:
    metadata = _load_json(root / "bundle.json")
    if metadata.get("id") != "lingxi_advisor":
        raise RuntimeError("bundle id must be lingxi_advisor")
    version = str(metadata.get("version") or "").strip()
    if not version:
        raise RuntimeError("bundle version is missing")
    checksum_file = root / "CHECKSUMS.sha256"
    expected: dict[str, str] = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64:
            raise RuntimeError("invalid CHECKSUMS.sha256 entry")
        expected[relative] = digest
    for relative, digest in expected.items():
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise RuntimeError(f"bundle file is missing: {relative}")
        if _sha256(path) != digest:
            raise RuntimeError(f"bundle checksum mismatch: {relative}")
    wheels = [
        (root / str(relative)).resolve()
        for relative in metadata.get("runtime_wheels") or ()
    ]
    if len(wheels) != 1 or root not in wheels[0].parents:
        raise RuntimeError("bundle must declare exactly one runtime wheel")
    if not wheels[0].is_file():
        raise RuntimeError("declared runtime wheel does not exist")
    return version, wheels[0]


def _run_package_install(python: Path, wheel: Path) -> None:
    uv = shutil.which("uv")
    wheel_with_extra = str(wheel) + "[mcp]"
    if uv:
        command = [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--upgrade",
            wheel_with_extra,
        ]
    else:
        command = [
            str(python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            wheel_with_extra,
        ]
    subprocess.run(command, check=True)


def _run_package_uninstall(python: Path) -> None:
    uv = shutil.which("uv")
    if uv:
        command = [
            uv,
            "pip",
            "uninstall",
            "--python",
            str(python),
            "lingxi_advisor",
        ]
    else:
        command = [
            str(python),
            "-m",
            "pip",
            "uninstall",
            "-y",
            "lingxi_advisor",
        ]
    subprocess.run(command, check=True)


def _copy_file(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.as_posix()


def _copy_tree(source: Path, destination: Path) -> list[str]:
    installed: list[str] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name in {".DS_Store"}:
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        target = destination / path.relative_to(source)
        installed.append(_copy_file(path, target))
    return installed


def _host_descriptors(root: Path, python: Path) -> list[str]:
    installed: list[str] = []
    for profile in ("runtime", "operator"):
        value = _target_server_descriptor(python, profile)
        value["command"] = str(python)
        value["args"] = [
            "-m",
            "lingxi_advisor.adapters.mcp.server",
            *value["args"],
        ]
        path = root / "host" / f"{profile}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        installed.append(path.as_posix())
    return installed


def _target_server_descriptor(python: Path, profile: str) -> dict[str, Any]:
    """Read descriptor facts from the package installed in target Python."""

    script = (
        "import json, sys; "
        "from lingxi_advisor.adapters.mcp.descriptors import server_descriptor; "
        "print(json.dumps(server_descriptor(sys.argv[1])))"
    )
    completed = subprocess.run(
        [str(python), "-I", "-c", script, profile],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid {profile} descriptor from target Python")
    return value


def _remove_previous_contribution(install_root: Path) -> None:
    record_path = install_root / INSTALL_RECORD
    if not record_path.is_file():
        return
    record = _load_json(record_path)
    if record.get("id") != "lingxi_advisor":
        raise RuntimeError("existing install record is not LingxiAdvisor")
    recorded_root = Path(str(record.get("install_root") or "")).resolve()
    if recorded_root != install_root:
        raise RuntimeError("existing install record has a different root")
    for raw_path in record.get("installed_files") or ():
        path = Path(str(raw_path)).resolve()
        if path == install_root or install_root not in path.parents:
            raise RuntimeError(
                "existing install record contains a path outside its root"
            )
        if path.is_file():
            path.unlink()
            _remove_empty_parents(path.parent, install_root)


def install(
    *,
    bundle_root: Path,
    install_root: Path,
    python: Path,
) -> dict[str, Any]:
    bundle_root = bundle_root.expanduser().resolve()
    install_root = install_root.expanduser().resolve()
    python = _absolute_executable(python)
    if not python.is_file():
        raise FileNotFoundError(python)
    version, wheel = _verify_bundle(bundle_root)
    _run_package_install(python, wheel)
    install_root.mkdir(parents=True, exist_ok=True)
    _remove_previous_contribution(install_root)

    installed: list[str] = []
    installed.extend(
        _copy_tree(bundle_root / "skills", install_root / "skills")
    )
    installed.extend(
        _copy_tree(bundle_root / "packaging", install_root / "packaging")
    )
    installed.extend(_copy_tree(bundle_root / "docs", install_root / "docs"))
    installed.extend(_host_descriptors(install_root, python))
    record = {
        "schema_version": 1,
        "id": "lingxi-advisor",
        "version": version,
        "python": str(python),
        "install_root": str(install_root),
        "installed_files": installed,
        "preserved_user_data": [
            "knowledge cache",
            "repository cache",
            "run outputs",
        ],
    }
    record_path = install_root / INSTALL_RECORD
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    smoke_test(install_root=install_root, python=python)
    return record


def smoke_test(*, install_root: Path, python: Path) -> None:
    subprocess.run(
        [
            str(_absolute_executable(python)),
            "-m",
            "lingxi_advisor.release_smoke",
            "--bundle-root",
            str(install_root.expanduser().resolve()),
        ],
        check=True,
    )


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def uninstall(*, install_root: Path, python: Path | None) -> dict[str, Any]:
    install_root = install_root.expanduser().resolve()
    record_path = install_root / INSTALL_RECORD
    record = _load_json(record_path)
    if record.get("id") != "lingxi_advisor":
        raise RuntimeError("install record does not belong to lingxi_advisor")
    recorded_root = Path(str(record.get("install_root") or "")).resolve()
    if recorded_root != install_root:
        raise RuntimeError("install record root does not match --install-root")
    recorded_python = _absolute_executable(
        Path(str(record.get("python") or ""))
    )
    selected_python = (
        _absolute_executable(python)
        if python is not None
        else recorded_python
    )
    _run_package_uninstall(selected_python)

    removed: list[str] = []
    files = [
        Path(str(item)).resolve()
        for item in record.get("installed_files") or ()
    ]
    for path in files:
        if path == install_root or install_root not in path.parents:
            raise RuntimeError("install record contains a path outside its root")
        if path.is_file():
            path.unlink()
            removed.append(str(path))
            _remove_empty_parents(path.parent, install_root)
    record_path.unlink(missing_ok=True)
    _remove_empty_parents(install_root, install_root.parent)
    return {
        "status": "completed",
        "version": record.get("version"),
        "removed_file_count": len(removed),
        "user_data_removed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install, validate, or uninstall a LingxiAdvisor extension bundle."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument(
        "--bundle-root", type=Path, default=_default_bundle_root()
    )
    install_parser.add_argument(
        "--install-root", type=Path, default=_default_install_root()
    )
    install_parser.add_argument(
        "--python", type=Path, default=Path(sys.executable)
    )
    smoke_parser = subparsers.add_parser("smoke-test")
    smoke_parser.add_argument(
        "--install-root", type=Path, default=_default_install_root()
    )
    smoke_parser.add_argument(
        "--python", type=Path, default=Path(sys.executable)
    )
    uninstall_parser = subparsers.add_parser("uninstall")
    uninstall_parser.add_argument(
        "--install-root", type=Path, default=_default_install_root()
    )
    uninstall_parser.add_argument("--python", type=Path)
    args = parser.parse_args()

    if args.command == "install":
        result = install(
            bundle_root=args.bundle_root,
            install_root=args.install_root,
            python=args.python,
        )
    elif args.command == "smoke-test":
        smoke_test(install_root=args.install_root, python=args.python)
        result = {"status": "completed"}
    else:
        result = uninstall(
            install_root=args.install_root,
            python=args.python,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
