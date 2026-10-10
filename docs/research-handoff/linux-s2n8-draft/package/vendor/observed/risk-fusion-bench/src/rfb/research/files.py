"""Crash-safe partial-file publication with directory durability."""

from __future__ import annotations
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateFileW(
            str(path),
            0x80000000 | 0x40000000,
            0x00000001 | 0x00000002 | 0x00000004,
            None,
            3,
            0x02000000,
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise RuntimeError("directory durability is unsupported")
        try:
            if not kernel32.FlushFileBuffers(handle):
                raise RuntimeError("directory durability is unsupported")
        finally:
            kernel32.CloseHandle(handle)
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise RuntimeError("directory durability is unsupported") from exc


def publish_bytes(
    destination: str | Path, data: bytes, *, expected_sha256: str | None = None
) -> str:
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("sha256 mismatch")
    fd, name = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".partial", dir=str(dest.parent)
    )
    partial = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(partial.read_bytes()).hexdigest() != digest:
            raise ValueError("partial verification failed")
        # Probe directory durability before publication; unsupported media must
        # fail closed without exposing the destination.
        _fsync_dir(dest.parent)
        os.replace(partial, dest)
        _fsync_dir(dest.parent)
    finally:
        if partial.exists():
            partial.unlink()
    return digest


def publish_json(
    destination: str | Path, value: Any, *, expected_sha256: str | None = None
) -> str:
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return publish_bytes(destination, data, expected_sha256=expected_sha256)


def publish_json_new(destination: str | Path, value: Any) -> str:
    """Durably publish canonical JSON without replacing an existing path."""
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    digest = hashlib.sha256(data).hexdigest()
    fd, name = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".partial", dir=str(dest.parent)
    )
    partial = Path(name)
    linked = False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(partial.read_bytes()).hexdigest() != digest:
            raise ValueError("partial verification failed")
        _fsync_dir(dest.parent)
        try:
            os.link(partial, dest)
            linked = True
        except FileExistsError as exc:
            raise ValueError("IMMUTABLE_RECEIPT_EXISTS") from exc
        _fsync_dir(dest.parent)
        return digest
    finally:
        if partial.exists():
            partial.unlink()
            if linked:
                _fsync_dir(dest.parent)
