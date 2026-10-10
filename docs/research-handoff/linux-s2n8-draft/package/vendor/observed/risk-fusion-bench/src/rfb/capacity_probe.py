"""Read-only capacity probe used by the v6.13 segment gate."""

from __future__ import annotations
import os
import shutil
from numbers import Integral
from pathlib import Path
from typing import Any, Mapping
from .capacity import CapacityTelemetry


class ProbeUnavailable(RuntimeError):
    pass


def project_allocated_bytes(root: str | Path) -> int:
    root = Path(root).absolute()
    current = Path(root.anchor)
    for component in root.parts[1:]:
        current /= component
        if current.is_symlink():
            raise RuntimeError(
                f"cannot measure project allocation through symlink: {current}"
            )
    if not root.exists():
        raise FileNotFoundError(root)
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_symlink():
                raise RuntimeError(
                    f"cannot measure project allocation through symlink: {path}"
                )
            if not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError(f"project path escapes root: {path}")
            if path.is_file():
                st = path.stat()
                total += int(getattr(st, "st_blocks", (st.st_size + 511) // 512)) * 512
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise RuntimeError(f"cannot measure project allocation: {path}") from exc
    return total


def filesystem_used_bytes(path: str | Path) -> int:
    return int(shutil.disk_usage(str(Path(path))).used)


def open_deleted_bytes(
    *, trusted_open_deleted_bytes: int | None = None, proc_root: str | Path = "/proc"
) -> int:
    if trusted_open_deleted_bytes is not None:
        if (
            isinstance(trusted_open_deleted_bytes, bool)
            or not isinstance(trusted_open_deleted_bytes, Integral)
            or trusted_open_deleted_bytes < 0
        ):
            raise ValueError(
                "trusted_open_deleted_bytes must be a non-negative integer"
            )
        return int(trusted_open_deleted_bytes)
    if os.name != "posix":
        raise ProbeUnavailable("open-deleted bytes require trusted value on non-POSIX")
    proc = Path(proc_root)
    if not proc.exists():
        raise ProbeUnavailable("open-deleted bytes require trusted value on non-POSIX")
    total = 0
    try:
        with os.scandir(proc) as pids:
            for pid in pids:
                if not pid.name.isdigit() or not pid.is_dir(follow_symlinks=False):
                    continue
                with os.scandir(Path(pid.path) / "fd") as fds:
                    for fd in fds:
                        link = Path(fd.path)
                        if " (deleted)" in os.readlink(link):
                            total += int(os.stat(link).st_size)
    except (
        AttributeError,
        FileNotFoundError,
        PermissionError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProbeUnavailable(
            "cannot enumerate open-deleted files completely"
        ) from exc
    return total


def probe_capacity(
    project_root: str | Path,
    *,
    filesystem_baseline_bytes: int = 0,
    owned_external_layers_bytes: int | None = None,
    trusted_open_deleted_bytes: int | None = None,
    segment_state: str | None = None,
    sample_reason: str = "manual",
) -> CapacityTelemetry:
    if (
        isinstance(filesystem_baseline_bytes, bool)
        or not isinstance(filesystem_baseline_bytes, Integral)
        or filesystem_baseline_bytes < 0
    ):
        raise ValueError("filesystem_baseline_bytes must be a non-negative integer")
    if owned_external_layers_bytes is None:
        raise ProbeUnavailable("owned external layers must be measured explicitly")
    if (
        isinstance(owned_external_layers_bytes, bool)
        or not isinstance(owned_external_layers_bytes, Integral)
        or owned_external_layers_bytes < 0
    ):
        raise ValueError("owned_external_layers_bytes must be a non-negative integer")
    used_delta = max(
        0, filesystem_used_bytes(project_root) - int(filesystem_baseline_bytes)
    )
    return CapacityTelemetry(
        project_tree_allocated_bytes=project_allocated_bytes(project_root),
        filesystem_used_delta_bytes=used_delta,
        owned_external_layers_bytes=owned_external_layers_bytes,
        open_deleted_bytes=open_deleted_bytes(
            trusted_open_deleted_bytes=trusted_open_deleted_bytes
        ),
        segment_state=segment_state,
        sample_reason=sample_reason,
        segment_id=str(project_root),
    )


def append_telemetry_jsonl(
    path: str | Path, telemetry: CapacityTelemetry | Mapping[str, Any]
) -> None:
    from .contracts.canonical_json import canonical_bytes

    if isinstance(telemetry, CapacityTelemetry):
        record = telemetry.as_dict()
    elif isinstance(telemetry, Mapping):
        expected_keys = set(CapacityTelemetry.__dataclass_fields__) | {
            "schema_version",
            "capacity_bytes",
            "state",
            "reason",
            "sampling_interval_seconds",
            "formula",
            "subbudget_limits",
        }
        try:
            if set(telemetry) != expected_keys:
                raise ValueError("invalid capacity telemetry schema")
            candidate = CapacityTelemetry(
                project_tree_allocated_bytes=telemetry["project_tree_allocated_bytes"],
                filesystem_used_delta_bytes=telemetry["filesystem_used_delta_bytes"],
                owned_external_layers_bytes=telemetry["owned_external_layers_bytes"],
                open_deleted_bytes=telemetry["open_deleted_bytes"],
                sampled_at=telemetry["sampled_at"],
                segment_state=telemetry["segment_state"],
                sample_reason=telemetry["sample_reason"],
                segment_id=telemetry["segment_id"],
                subbudget_usage=telemetry["subbudget_usage"],
                planning_peak_bytes=telemetry["planning_peak_bytes"],
            )
            record = candidate.as_dict()
            if record != dict(telemetry):
                raise ValueError("invalid capacity telemetry values")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid capacity telemetry mapping") from exc
    else:
        raise TypeError("telemetry must be CapacityTelemetry or a mapping")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab") as handle:
        handle.write(canonical_bytes(record) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


measure_capacity = probe_capacity
__all__ = [
    "project_allocated_bytes",
    "filesystem_used_bytes",
    "open_deleted_bytes",
    "probe_capacity",
    "measure_capacity",
    "append_telemetry_jsonl",
    "ProbeUnavailable",
]
