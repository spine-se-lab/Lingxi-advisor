from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .contracts import PLUGIN_ID, InstallError


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes, changes: list[dict[str, Any]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(100):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 99:
                    raise
                time.sleep(0.01)
        if changes is not None:
            changes.append({"kind": "file", "path": str(path), "action": "written"})
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_record(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if not path.is_file() or path.is_symlink():
        raise InstallError(f"Install record ownership cannot be established: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"Install record is invalid: {path}") from exc
    if not isinstance(value, dict) or value.get("plugin") != PLUGIN_ID:
        raise InstallError(f"Install record belongs to another plugin: {path}")
    if not isinstance(value.get("managed_files", {}), dict):
        raise InstallError("Install record managed_files is invalid")
    return value


def _safe(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise InstallError(f"Refusing to manage a symlink: {candidate}")
        if candidate != path and candidate.exists() and not candidate.is_dir():
            raise InstallError(f"Managed path parent is not a directory: {candidate}")
