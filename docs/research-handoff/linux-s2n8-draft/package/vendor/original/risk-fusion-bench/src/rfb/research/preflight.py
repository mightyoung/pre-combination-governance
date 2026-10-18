"""Fresh read-only environment evidence for research execution."""

from __future__ import annotations

import hashlib
import importlib.metadata
import locale
import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from rfb.capacity_probe import (
    ProbeUnavailable,
    filesystem_used_bytes,
    open_deleted_bytes,
)
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

MIN_FREE_BYTES = 265_853_007_872
REMOTE_RESERVE_FLOOR_BYTES = 235_853_007_872
PLANNED_PEAK_BYTES = 22_000_000_000
DRAIN_THRESHOLD_BYTES = 24_000_000_000
HARD_PEAK_BYTES = 25_000_000_000
SUBBUDGETS_BYTES = {
    "ephemeral_dataset": 16_000_000_000,
    "durable_result_staging": 3_000_000_000,
    "scratch_partial": 2_000_000_000,
    "retry_quarantine_wal": 1_000_000_000,
    "emergency_reserve": 3_000_000_000,
}
_DATASET_MANIFEST_NAMES = (
    "SOURCE-MANIFEST.json",
    "CONTENT-SHA256.tsv",
    "EXTRACTION-MANIFEST.json",
)
_TEP_SOURCE_MANIFEST = "SOURCE-MANIFEST.txt"
_TEP_CHECKSUM_MANIFEST = "profbraatz-data-sha256.txt"
_TEP_ARCHIVE = "tep-profbraatz-master.zip"
_SHA256_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+(?:\*| )?(.+?)\s*$")
_ARCHIVE_SHA256 = re.compile(
    r"archive[_ -]?sha256\s*[:=]\s*([0-9a-fA-F]{64})", re.IGNORECASE
)


def _source_tree_sha256() -> str:
    package_root = Path(__file__).resolve().parents[1]
    entries: dict[str, str] = {}
    for path in sorted(package_root.rglob("*.py")):
        entries[path.relative_to(package_root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return sha256_hex(canonical_bytes(entries))


def _package_inventory_sha256() -> str:
    inventory: dict[str, str] = {"python": platform.python_version()}
    for name in ("jsonschema", "numpy", "scipy"):
        try:
            inventory[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            inventory[name] = "absent"
    return sha256_hex(canonical_bytes(inventory))


def _process_snapshots() -> tuple[str, str]:
    proc = Path("/proc")
    if proc.is_dir():
        owned: list[str] = []
        foreign: list[str] = []
        current_uid = os.getuid() if hasattr(os, "getuid") else None
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text(encoding="utf-8").split()
                identity = f"{entry.name}:{stat[21]}"
                if current_uid is not None and entry.stat().st_uid == current_uid:
                    owned.append(identity)
                else:
                    foreign.append(identity)
            except (OSError, IndexError, UnicodeDecodeError):
                continue
        return (
            sha256_hex(canonical_bytes(sorted(owned))),
            sha256_hex(canonical_bytes(sorted(foreign))),
        )
    current = sha256_hex(canonical_bytes({"pid": os.getpid(), "ppid": os.getppid()}))
    return current, sha256_hex(canonical_bytes([]))


def _gpu_evidence() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        unavailable = sha256_hex(canonical_bytes({"nvidia_smi": "unavailable"}))
        return {
            "gpu_identity": "NVIDIA_SMI_UNAVAILABLE",
            "gpu_inventory_sha256": unavailable,
            "gpu_process_snapshot_sha256": unavailable,
            "gpu_process_snapshot": None,
            "gpu_probe_status": "NOT_APPLICABLE",
            "gpu_probe_reason": "NVIDIA_SMI_UNAVAILABLE",
        }
    inventory = subprocess.run(
        [
            executable,
            "--query-gpu=name,uuid,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        shell=False,
        capture_output=True,
        text=True,
        encoding=locale.getencoding(),
        check=False,
        timeout=15,
    )
    processes = subprocess.run(
        [
            executable,
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ],
        shell=False,
        capture_output=True,
        text=True,
        encoding=locale.getencoding(),
        check=False,
        timeout=15,
    )
    if inventory.returncode != 0 or processes.returncode != 0:
        raise ValueError("PREFLIGHT_BLOCKED: nvidia-smi query failed")
    inventory_lines = sorted(
        line.strip() for line in inventory.stdout.splitlines() if line.strip()
    )
    process_lines = sorted(
        line.strip() for line in processes.stdout.splitlines() if line.strip()
    )
    process_snapshot: list[dict[str, int]] = []
    for line in process_lines:
        fields = [part.strip() for part in line.split(",")]
        if len(fields) < 2:
            raise ValueError("PREFLIGHT_BLOCKED: malformed nvidia-smi process row")
        try:
            pid, memory = int(fields[0]), int(fields[1])
        except ValueError as exc:
            raise ValueError(
                "PREFLIGHT_BLOCKED: malformed nvidia-smi process row"
            ) from exc
        if pid <= 0 or memory < 0:
            raise ValueError("PREFLIGHT_BLOCKED: invalid nvidia-smi process row")
        process_snapshot.append({"pid": pid, "used_memory_mib": memory})
    identity = (
        ",".join(part.strip() for part in inventory_lines[0].split(",")[:2])
        if inventory_lines
        else "NO_NVIDIA_GPU"
    )
    return {
        "gpu_identity": identity,
        "gpu_inventory_sha256": sha256_hex(canonical_bytes(inventory_lines)),
        "gpu_process_snapshot_sha256": sha256_hex(canonical_bytes(process_lines)),
        "gpu_process_snapshot": process_snapshot,
        "gpu_probe_status": "OBSERVED_NOT_USED",
        "gpu_probe_reason": None,
    }


def _dataset_manifest_evidence(
    dataset_root: str | Path | None, *, fixture_only: bool
) -> tuple[str, bool, str, str | None]:
    if fixture_only:
        return (
            sha256_hex(canonical_bytes({"fixture_only": True})),
            False,
            "NOT_APPLICABLE",
            "EMBEDDED_FIXTURE_BOUND_TO_RUNTIME_HASH",
        )
    if dataset_root is None:
        return (
            sha256_hex(canonical_bytes({"dataset_manifest": "missing"})),
            False,
            "ERROR",
            "DATASET_ROOT_MISSING",
        )
    root = Path(dataset_root)
    if not root.is_dir() or root.is_symlink():
        return (
            sha256_hex(canonical_bytes({"dataset_manifest": "unavailable"})),
            False,
            "ERROR",
            "DATASET_ROOT_INVALID",
        )
    tep_roots = [root]
    if root.name == "data" and len(root.parents) >= 2:
        tep_roots.append(root.parents[1])
    for tep_root in tep_roots:
        tep_pair = (
            tep_root / _TEP_SOURCE_MANIFEST,
            tep_root / _TEP_CHECKSUM_MANIFEST,
        )
        if all(path.is_file() and not path.is_symlink() for path in tep_pair):
            return _tep_manifest_evidence(tep_root, *tep_pair)
    entries: dict[str, str] = {}
    for name in _DATASET_MANIFEST_NAMES:
        candidate = root / name
        if candidate.is_file() and not candidate.is_symlink():
            entries[name] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return sha256_hex(canonical_bytes(entries)), bool(entries), "OBSERVED", None


def _tep_manifest_evidence(
    root: Path, source_manifest: Path, checksum_manifest: Path
) -> tuple[str, bool, str, str | None]:
    """Verify the Profbraatz TEP archive and extracted-file checksum manifest.

    This path is deliberately strict: malformed rows, duplicate normalized paths,
    symlinks, path escapes, a missing archive, or any digest mismatch fail closed.
    The returned digest is over canonical verified facts and is stable across
    checksum-file ordering and line-ending changes.
    """

    def file_digest(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return "UNREADABLE"

    def failure(reason: str) -> tuple[str, bool, str, str]:
        raw = {
            "source_manifest_sha256": file_digest(source_manifest),
            "checksum_manifest_sha256": file_digest(checksum_manifest),
            "reason": reason,
        }
        return sha256_hex(canonical_bytes(raw)), False, "ERROR", reason

    archive = root / _TEP_ARCHIVE
    if not archive.is_file() or archive.is_symlink():
        return failure("TEP_ARCHIVE_MISSING_OR_INVALID")
    try:
        source_text = source_manifest.read_text(encoding="utf-8")
        checksum_text = checksum_manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return failure("TEP_MANIFEST_UNREADABLE")
    archive_match = _ARCHIVE_SHA256.search(source_text)
    if archive_match is None:
        # Also accept the common ``<sha256>  tep-profbraatz-master.zip`` form.
        for line in source_text.splitlines():
            match = _SHA256_LINE.match(line.strip())
            if match and Path(match.group(2)).name == _TEP_ARCHIVE:
                archive_match = match
                break
    if archive_match is None:
        return failure("TEP_ARCHIVE_SHA256_MISSING")
    expected_archive = archive_match.group(1).lower()
    actual_archive = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual_archive != expected_archive:
        return failure("TEP_ARCHIVE_SHA256_MISMATCH")

    rows: dict[str, str] = {}
    for number, raw_line in enumerate(checksum_text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SHA256_LINE.match(line)
        if match is None:
            return failure(f"TEP_CHECKSUM_ROW_INVALID:{number}")
        digest, raw_name = match.groups()
        name = raw_name.strip()
        # POSIX paths are the published format; reject Windows spellings too.
        posix = PurePosixPath(name)
        windows = PureWindowsPath(name)
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or ".." in posix.parts
        ):
            return failure(f"TEP_CHECKSUM_PATH_INVALID:{number}")
        normalized = posix.as_posix()
        if normalized in rows:
            return failure(f"TEP_CHECKSUM_DUPLICATE:{normalized}")
        rows[normalized] = digest.lower()
    if not rows:
        return failure("TEP_CHECKSUM_MANIFEST_EMPTY")

    verified_files: list[dict[str, Any]] = []
    root_resolved = root.resolve()
    for name, expected in sorted(rows.items()):
        candidate = root / Path(*name.split("/"))
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return failure(f"TEP_CHECKSUM_FILE_MISSING:{name}")
        if (
            root_resolved not in resolved.parents
            or candidate.is_symlink()
            or not resolved.is_file()
        ):
            return failure(f"TEP_CHECKSUM_FILE_UNSAFE:{name}")
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if actual != expected:
            return failure(f"TEP_CHECKSUM_FILE_SHA256_MISMATCH:{name}")
        verified_files.append(
            {"path": name, "size": resolved.stat().st_size, "sha256": actual}
        )
    facts = {
        "archive": {
            "path": _TEP_ARCHIVE,
            "size": archive.stat().st_size,
            "sha256": actual_archive,
        },
        "files": verified_files,
    }
    return sha256_hex(canonical_bytes(facts)), True, "OBSERVED", None


def _allocated_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                stat = item.stat()
                total += int(getattr(stat, "st_blocks", 0) * 512 or stat.st_size)
        except OSError:
            continue
    return total


def manifest_hashes(manifest: Mapping[str, Any]) -> dict[str, str]:
    return {
        "config_sha256": sha256_hex(
            canonical_bytes(
                {
                    "adapter_id": manifest.get("adapter_id"),
                    "adapter_params": manifest.get("adapter_params", {}),
                    "capacity": manifest.get("capacity", {}),
                    "resource_limits": manifest.get("resource_limits", {}),
                    "scorer_config": manifest.get("scorer_config", {}),
                }
            )
        ),
        "input_manifest_sha256": sha256_hex(
            canonical_bytes(
                {
                    "bundle_manifest": manifest.get("bundle_manifest", {}),
                    "method_panel": manifest.get("method_panel", []),
                    "seeds": manifest.get("seeds", []),
                    "algorithm_seed": manifest.get("algorithm_seed", 0),
                }
            )
        ),
    }


def collect_preflight(
    root: str | Path,
    *,
    dataset_root: str | Path | None = None,
    fixture_only: bool = False,
    manifest: Mapping[str, Any] | None = None,
    filesystem_baseline_bytes: int | None = None,
    owned_external_layers_bytes: int | None = None,
    trusted_open_deleted_bytes: int | None = None,
) -> dict[str, Any]:
    run_root = Path(root).resolve()
    if not run_root.is_dir() or run_root.is_symlink():
        raise ValueError("PREFLIGHT_BLOCKED: invalid root")
    usage = shutil.disk_usage(run_root)
    owned_processes, foreign_processes = _process_snapshots()
    dataset_hash, dataset_verified, dataset_status, dataset_reason = (
        _dataset_manifest_evidence(dataset_root, fixture_only=fixture_only)
    )
    mountinfo = Path("/proc/self/mountinfo")
    mountinfo_hash = (
        hashlib.sha256(mountinfo.read_bytes()).hexdigest()
        if mountinfo.is_file()
        else sha256_hex(canonical_bytes({"mountinfo": "unavailable"}))
    )
    boot_id_path = Path("/proc/sys/kernel/random/boot_id")
    boot_id = (
        boot_id_path.read_text(encoding="utf-8").strip()
        if boot_id_path.is_file()
        else "UNAVAILABLE"
    )
    project_allocated = _allocated_bytes(run_root)
    dataset_bytes = 0
    if dataset_root is not None:
        dataset_path = Path(dataset_root).resolve()
        if dataset_path == run_root or run_root in dataset_path.parents:
            dataset_bytes = _allocated_bytes(dataset_path)
    buckets = {
        "ephemeral_dataset": dataset_bytes,
        "durable_result_staging": sum(
            _allocated_bytes(path)
            for path in run_root.glob("*.results*")
            if path.is_dir() and not path.is_symlink()
        ),
        "scratch_partial": sum(
            _allocated_bytes(path)
            for path in run_root.rglob("*")
            if path.is_dir()
            and not path.is_symlink()
            and (path.name.endswith(".partial") or path.name == "scratch")
        ),
        "retry_quarantine_wal": sum(
            _allocated_bytes(path)
            for path in run_root.rglob("*")
            if path.is_dir()
            and not path.is_symlink()
            and path.name in {"retry", "quarantine", "wal"}
        ),
        "emergency_reserve": 0,
    }
    unavailable_fields: list[str] = []
    filesystem_delta: int | None = None
    if filesystem_baseline_bytes is None:
        unavailable_fields.append("filesystem_used_delta_bytes")
    elif (
        isinstance(filesystem_baseline_bytes, bool)
        or not isinstance(filesystem_baseline_bytes, int)
        or filesystem_baseline_bytes < 0
    ):
        raise ValueError("filesystem_baseline_bytes must be a non-negative integer")
    else:
        filesystem_delta = max(
            0, filesystem_used_bytes(run_root) - filesystem_baseline_bytes
        )
    owned_external: int | None = owned_external_layers_bytes
    if owned_external is None:
        unavailable_fields.append("owned_external_layers_bytes")
    elif (
        isinstance(owned_external, bool)
        or not isinstance(owned_external, int)
        or owned_external < 0
    ):
        raise ValueError("owned_external_layers_bytes must be a non-negative integer")
    try:
        open_deleted: int | None = open_deleted_bytes(
            trusted_open_deleted_bytes=trusted_open_deleted_bytes
        )
    except ProbeUnavailable:
        open_deleted = None
        unavailable_fields.append("open_deleted_bytes")
    if unavailable_fields:
        capacity_peak: int | None = None
        capacity_state = "UNAVAILABLE"
    else:
        assert filesystem_delta is not None
        assert owned_external is not None
        assert open_deleted is not None
        capacity_peak = max(
            project_allocated, filesystem_delta + owned_external + open_deleted
        )
        if any(buckets[name] > SUBBUDGETS_BYTES[name] for name in buckets):
            capacity_state = "SUBBUDGET_BREACH"
        elif capacity_peak > HARD_PEAK_BYTES:
            capacity_state = "SAFE_HALT_CAP_BREACH"
        elif capacity_peak >= DRAIN_THRESHOLD_BYTES:
            capacity_state = "DRAIN_AND_SEAL"
        elif capacity_peak > PLANNED_PEAK_BYTES:
            capacity_state = "PLANNED_CAP_EXCEEDED"
        else:
            capacity_state = "PLANNED"
    evidence: dict[str, Any] = {
        "collected_at_utc": datetime.now(UTC).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "boot_id": boot_id,
        "root": str(run_root),
        "approved_remote_parent": str(run_root.parent),
        "remote_run_root": str(run_root),
        "hostname": platform.node() or "unknown",
        "python_version": platform.python_version(),
        "source_tree_sha256": _source_tree_sha256(),
        "package_inventory_sha256": _package_inventory_sha256(),
        "owned_process_snapshot_sha256": owned_processes,
        "foreign_process_snapshot_sha256": foreign_processes,
        "mount_identity": f"{os.stat(run_root).st_dev}:{usage.total}",
        "mountinfo_sha256": mountinfo_hash,
        "filesystem_total_bytes": usage.total,
        "filesystem_used_bytes": usage.used,
        "filesystem_baseline_bytes": (
            filesystem_baseline_bytes
            if filesystem_baseline_bytes is not None
            else usage.used
        ),
        "filesystem_free_bytes": usage.free,
        "project_tree_allocated_bytes": project_allocated,
        "filesystem_used_delta_bytes": filesystem_delta,
        "owned_external_layers_bytes": owned_external,
        "open_deleted_bytes": open_deleted,
        "capacity_peak_bytes": capacity_peak,
        "capacity_state": capacity_state,
        "capacity_measurement_status": (
            "MEASURED" if not unavailable_fields else "UNAVAILABLE"
        ),
        "capacity_unavailable_fields": unavailable_fields,
        "capacity_buckets_bytes": buckets,
        "capacity_available": not unavailable_fields and usage.free >= MIN_FREE_BYTES,
        "remote_reserve_available": not unavailable_fields
        and usage.free >= REMOTE_RESERVE_FLOOR_BYTES,
        "dataset_manifest_sha256": dataset_hash,
        "dataset_manifest_verified": dataset_verified,
        "dataset_probe_status": dataset_status,
        "dataset_probe_reason": dataset_reason,
        "gpu_policy": "cpu_only",
        **_gpu_evidence(),
    }
    if manifest is not None:
        evidence.update(manifest_hashes(manifest))
    return evidence
