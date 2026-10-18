"""Deterministic, dependency-free research runtime bundles.

Only the fixture adapter has a closed stdlib-only dependency surface.  The
real TEP adapter remains fail-closed until its numpy/scipy/rfb closure can be
made portable and pinned.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes

from .files import _fsync_dir


class RuntimeBundleError(RuntimeError):
    """Raised when an adapter has no approved portable runtime closure."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PinnedRuntimeBundle:
    """Content-addressed archive of a controller-approved pinned runtime.

    The archive is transportable evidence only; launch remains blocked unless
    a remote materializer explicitly verifies and exposes the selected
    interpreter path.
    """

    path: Path
    manifest_path: Path
    file_sha256: str
    manifest_sha256: str
    closure_fingerprint: str
    interpreter_relative_path: str
    pinned_manifest: dict[str, Any]
    format: str = "python_pinned_venv_v1"

    @property
    def remote_name(self) -> str:
        return f"{self.file_sha256}.pinned.tar"

    @property
    def source_sha256(self) -> str:
        return self.closure_fingerprint.removeprefix("sha256:")

    @property
    def manifest(self) -> dict[str, str]:
        return {
            "runtime_format": self.format,
            "runtime_dependency_profile": "tep_nonconfirmatory_v1",
            "file_sha256": self.file_sha256,
            "manifest_sha256": self.manifest_sha256,
            "closure_fingerprint": self.closure_fingerprint,
            "interpreter_relative_path": self.interpreter_relative_path,
        }

    def verify(self) -> None:
        if (
            self.path.is_symlink()
            or not self.path.is_file()
            or self.manifest_path.is_symlink()
        ):
            raise RuntimeBundleError("PINNED_RUNTIME_BUNDLE_INVALID")
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.file_sha256:
            raise RuntimeBundleError("PINNED_RUNTIME_BUNDLE_HASH_MISMATCH")
        if self.manifest_path.read_bytes() != canonical_bytes(self.manifest):
            raise RuntimeBundleError("PINNED_RUNTIME_MANIFEST_MISMATCH")


def build_pinned_runtime_bundle(
    root: str | Path,
    pinned_manifest: dict,
    output_dir: str | Path,
) -> PinnedRuntimeBundle:
    """Build a deterministic zip archive from a verified pinned root."""
    from .pinned_runtime import verify_controller_staging

    root_path = Path(root).resolve()
    verify_controller_staging(pinned_manifest, root_path)
    interpreter = str(pinned_manifest["interpreter"]["relative_path"])
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=".pinned-runtime-", suffix=".partial", dir=str(destination)
    )
    partial = Path(name)
    try:
        with os.fdopen(fd, "w+b") as stream:
            with zipfile.ZipFile(
                stream, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True
            ) as archive:
                for item in sorted(
                    root_path.rglob("*"),
                    key=lambda p: p.relative_to(root_path).as_posix(),
                ):
                    if item.is_file() and not item.is_symlink():
                        relative = item.relative_to(root_path).as_posix()
                        info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_STORED
                        # Preserve executable bits.  A Linux venv interpreter copied
                        # into a tar/zip payload must remain launchable after remote
                        # materialization; the old fixed 0644 mode produced a bundle
                        # that could be verified but not executed.
                        info.create_system = 3
                        mode = item.stat().st_mode & 0o7777
                        # Windows source trees do not retain POSIX executable bits;
                        # the selected interpreter is nevertheless required to be
                        # executable on the reviewed Linux target.
                        if relative == interpreter:
                            mode |= 0o755
                        info.external_attr = mode << 16
                        with (
                            item.open("rb") as source,
                            archive.open(info, "w") as target,
                        ):
                            shutil.copyfileobj(source, target, length=1024 * 1024)
            stream.flush()
            os.fsync(stream.fileno())
        file_hash = _sha256_file(partial)
        path = destination / f"{file_hash}.pinned.tar"
        if path.exists() and (
            path.is_symlink() or not path.is_file() or _sha256_file(path) != file_hash
        ):
            raise RuntimeBundleError("PINNED_RUNTIME_CACHE_CORRUPT")
        if not path.exists():
            _fsync_dir(destination)
            try:
                os.link(partial, path)
            except FileExistsError as exc:
                raise RuntimeBundleError("PINNED_RUNTIME_CACHE_CORRUPT") from exc
            _fsync_dir(destination)
    finally:
        if partial.exists():
            partial.unlink()
            _fsync_dir(destination)
    manifest = {
        "runtime_format": "python_pinned_venv_v1",
        "runtime_dependency_profile": "tep_nonconfirmatory_v1",
        "file_sha256": file_hash,
        "closure_fingerprint": pinned_manifest["closure_fingerprint"],
        "interpreter_relative_path": interpreter,
    }
    manifest_hash = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    manifest["manifest_sha256"] = manifest_hash
    manifest_path = destination / f"{file_hash}.pinned.manifest.json"
    if manifest_path.exists():
        with manifest_path.open("rb") as stream:
            if stream.read() != canonical_bytes(manifest):
                raise RuntimeBundleError("PINNED_RUNTIME_CACHE_CORRUPT")
    if not manifest_path.exists():
        manifest_path.write_bytes(canonical_bytes(manifest))
    return PinnedRuntimeBundle(
        path,
        manifest_path,
        file_hash,
        manifest_hash,
        pinned_manifest["closure_fingerprint"],
        interpreter,
        dict(pinned_manifest),
    )


def materialize_pinned_runtime_bundle(
    bundle: PinnedRuntimeBundle, destination: str | Path
) -> Path:
    """Safely extract a verified pinned archive into a new root."""
    bundle.verify()
    target = Path(destination).resolve()
    partial = target.with_name(f".{target.name}.partial")
    if (
        target.exists()
        or target.is_symlink()
        or partial.exists()
        or partial.is_symlink()
    ):
        raise RuntimeBundleError("PINNED_MATERIALIZATION_COLLISION")
    partial.mkdir(parents=True)
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(bundle.path) as archive:
            for info in archive.infolist():
                rel = PurePosixPath(info.filename)
                if not info.filename or rel.is_absolute() or ".." in rel.parts:
                    raise RuntimeBundleError("PINNED_ARCHIVE_PATH_ESCAPE")
                name = rel.as_posix()
                if name in seen:
                    raise RuntimeBundleError("PINNED_ARCHIVE_DUPLICATE")
                seen.add(name)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeBundleError("PINNED_ARCHIVE_SYMLINK")
                out = (partial / Path(*rel.parts)).resolve()
                if partial not in out.parents:
                    raise RuntimeBundleError("PINNED_ARCHIVE_PATH_ESCAPE")
                if info.is_dir():
                    out.mkdir(parents=True, exist_ok=False)
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists() or out.is_symlink():
                    raise RuntimeBundleError("PINNED_ARCHIVE_DUPLICATE")
                data = archive.read(info)
                if len(data) != info.file_size:
                    raise RuntimeBundleError("PINNED_ARCHIVE_MEMBER_TRUNCATED")
                out.write_bytes(data)
                mode = (info.external_attr >> 16) & 0o7777
                if mode:
                    out.chmod(mode)
        interpreter = (
            partial / Path(*PurePosixPath(bundle.interpreter_relative_path).parts)
        ).resolve()
        if (
            partial not in interpreter.parents
            or not interpreter.is_file()
            or interpreter.is_symlink()
        ):
            raise RuntimeBundleError("PINNED_INTERPRETER_MISSING")
        partial.rename(target)
        return target
    except Exception:
        import shutil

        shutil.rmtree(partial, ignore_errors=True)
        raise


@dataclass(frozen=True)
class RuntimeBundle:
    adapter_id: str
    path: Path
    manifest_path: Path
    file_sha256: str
    source_sha256: str
    manifest_sha256: str
    shared_source_inventory: dict[str, str]
    shared_source_inventory_sha256: str
    format: str = "python_zipapp_stdlib_v1"

    @property
    def remote_name(self) -> str:
        return f"{self.file_sha256}.pyz"

    @property
    def sha256(self) -> str:
        """Compatibility spelling for the content-addressing file hash."""

        return self.file_sha256

    @property
    def manifest(self) -> dict[str, str]:
        return {
            "adapter_id": self.adapter_id,
            "runtime_format": self.format,
            "entrypoint": "__main__.py",
            "dependency_profile": "stdlib_only",
            "source_sha256": self.source_sha256,
            "file_sha256": self.file_sha256,
            "shared_source_inventory": self.shared_source_inventory,
            "shared_source_inventory_sha256": self.shared_source_inventory_sha256,
            "manifest_sha256": self.manifest_sha256,
        }

    def verify(self) -> None:
        """Fail closed if any cached runtime binding has drifted."""

        if (
            self.path.is_symlink()
            or not self.path.is_file()
            or self.manifest_path.is_symlink()
            or not self.manifest_path.is_file()
            or hashlib.sha256(self.path.read_bytes()).hexdigest() != self.file_sha256
            or self.manifest_path.read_bytes() != canonical_bytes(self.manifest)
        ):
            raise RuntimeBundleError("RUNTIME_BUNDLE_HASH_MISMATCH")
        unsigned = {k: v for k, v in self.manifest.items() if k != "manifest_sha256"}
        if (
            hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
            != self.manifest_sha256
        ):
            raise RuntimeBundleError("RUNTIME_MANIFEST_HASH_MISMATCH")
        with zipfile.ZipFile(self.path) as archive:
            if (
                archive.namelist() != ["__main__.py"]
                or hashlib.sha256(archive.read("__main__.py")).hexdigest()
                != self.source_sha256
            ):
                raise RuntimeBundleError("RUNTIME_SOURCE_HASH_MISMATCH")


_PORTABLE_ADAPTERS = frozenset({"tep_fixture"})

_SHARED_SOURCE_FILES = {
    "models": "models.py",
    "events": "trace.py",
    "lock": "lock.py",
    "probes": "preflight.py",
    "classification": "models.py",
    "result": "receipts.py",
    "receipt": "receipts.py",
    "publication": "files.py",
    "capacity": "adapters.py",
}


def shared_source_inventory() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {
        component: hashlib.sha256((root / filename).read_bytes()).hexdigest()
        for component, filename in sorted(_SHARED_SOURCE_FILES.items())
    }


def shared_conformance_outcome(kind: str, value):
    """Normalize cross-runtime contract vectors to stable values/failure codes."""
    if kind == "classification":
        return value == {
            "execution_lane": "RESEARCH",
            "classification": "DEVELOPMENT_NONCONFIRMATORY",
            "formal_gate_effect": "NONE",
            "formal_admission_eligible": False,
            "shk001b_eligible": False,
            "contains_formal_claims": False,
        }
    if kind == "capacity":
        peak, subbudget_breach = value
        if subbudget_breach:
            return "SUBBUDGET_BREACH"
        if peak > 25_000_000_000:
            return "SAFE_HALT_CAP_BREACH"
        if peak >= 24_000_000_000:
            return "DRAIN_AND_SEAL"
        if peak > 22_000_000_000:
            return "PLANNED_CAP_EXCEEDED"
        return "PLANNED"
    if kind == "no_replace":
        return "DESTINATION_EXISTS" if value else "PUBLISHED_NEW"
    if kind == "trace_binding":
        return "TRACE_PREFIX_MANIFEST_BINDING_MISMATCH" if not value else "BOUND"
    if kind == "receipt_order":
        receipt_published, lock_released, proof_published = value
        if lock_released and not receipt_published:
            return "RECEIPT_ORDER_VIOLATION"
        if proof_published and not lock_released:
            return "RELEASE_PROOF_VIOLATION"
        return "ORDERED"
    raise ValueError("UNKNOWN_CONFORMANCE_VECTOR")


# This source is deliberately standalone: `python3 -I -S <bundle>.pyz` must
# work on a host with no installed rfb package and no third-party packages.
_MAIN_SOURCE = r"""from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
import secrets
from pathlib import Path
import shutil
import socket
import stat
import locale
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone

CLASSIFICATION = {
    "execution_lane": "RESEARCH",
    "classification": "DEVELOPMENT_NONCONFIRMATORY",
    "formal_gate_effect": "NONE",
    "formal_admission_eligible": False,
    "shk001b_eligible": False,
    "contains_formal_claims": False,
}

def conformance_outcome(kind, value):
    if kind == "classification":
        return value == CLASSIFICATION
    if kind == "capacity":
        peak, subbudget_breach = value
        if subbudget_breach:
            return "SUBBUDGET_BREACH"
        if peak > HARD_PEAK_BYTES:
            return "SAFE_HALT_CAP_BREACH"
        if peak >= DRAIN_THRESHOLD_BYTES:
            return "DRAIN_AND_SEAL"
        if peak > PLANNED_PEAK_BYTES:
            return "PLANNED_CAP_EXCEEDED"
        return "PLANNED"
    if kind == "no_replace":
        return "DESTINATION_EXISTS" if value else "PUBLISHED_NEW"
    if kind == "trace_binding":
        return "TRACE_PREFIX_MANIFEST_BINDING_MISMATCH" if not value else "BOUND"
    if kind == "receipt_order":
        receipt_published, lock_released, proof_published = value
        if lock_released and not receipt_published:
            return "RECEIPT_ORDER_VIOLATION"
        if proof_published and not lock_released:
            return "RELEASE_PROOF_VIOLATION"
        return "ORDERED"
    raise ValueError("UNKNOWN_CONFORMANCE_VECTOR")
SEGMENT_START_FREE_MIN_BYTES = 265853007872
REMOTE_RESERVE_FLOOR_BYTES = 235853007872
PLANNED_PEAK_BYTES = 22000000000
DRAIN_THRESHOLD_BYTES = 24000000000
HARD_PEAK_BYTES = 25000000000
CAPACITY_CONTRACT = {
    "planned_peak_bytes": PLANNED_PEAK_BYTES,
    "drain_threshold_bytes": DRAIN_THRESHOLD_BYTES,
    "hard_peak_bytes": HARD_PEAK_BYTES,
    "segment_start_free_min_bytes": SEGMENT_START_FREE_MIN_BYTES,
    "remote_reserve_floor_bytes": REMOTE_RESERVE_FLOOR_BYTES,
    "subbudgets_bytes": {
        "ephemeral_dataset": 16000000000,
        "durable_result_staging": 3000000000,
        "scratch_partial": 2000000000,
        "retry_quarantine_wal": 1000000000,
        "emergency_reserve": 3000000000,
    },
}
PANEL = ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"]
EVENT_ACTOR_TABLE = (
    (1, "LOCAL_MANIFEST_VALIDATED", "controller"),
    (2, "LOCAL_RUNTIME_BUILT", "controller"),
    (3, "HOST_KEY_VERIFIED", "controller"),
    (4, "BOOTSTRAP_PARENT_PREFLIGHT_OBSERVED", "bootstrap_transport"),
    (5, "RUN_ROOT_CREATED_DURABLE", "bootstrap_transport"),
    (6, "RUNTIME_PARTIALS_UPLOADED", "controller"),
    (7, "RUNTIME_SEALED_DURABLE", "bootstrap_transport"),
    (8, "RUNTIME_FULL_PREFLIGHT_OBSERVED", "sealed_runtime"),
    (9, "EXECUTION_MANIFEST_CONSTRUCTED", "controller"),
    (10, "EXECUTION_MANIFEST_SEALED_DURABLE", "sealed_runtime"),
    (11, "WORKER_FIXED_ARGV_LAUNCHED", "controller"),
    (12, "EXECUTION_MANIFEST_VERIFIED_BEFORE_PARSE", "sealed_runtime"),
    (13, "PARENT_WIDE_LOCK_ACQUIRED", "sealed_runtime"),
    (14, "LAUNCH_RECHECK_ACCEPTED", "sealed_runtime"),
    (15, "ADAPTER_EXIT_AND_POST_RECHECK_ACCEPTED", "sealed_runtime"),
    (16, "RESULT_TREE_SEALED_DURABLE", "sealed_runtime"),
    (17, "REMOTE_RECEIPT_SEALED_READBACK_VERIFIED", "sealed_runtime"),
    (18, "LOCK_RELEASED_AFTER_RECEIPT", "sealed_runtime"),
    (19, "REMOTE_EVIDENCE_REVERIFIED_AND_LOCAL_COPY_SEALED", "controller"),
    (20, "COPY_AND_FINAL_RECEIPTS_SEALED_VERIFIED", "controller"),
)

def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

def digest(value):
    if not isinstance(value, (bytes, bytearray)):
        value = canonical(value)
    return hashlib.sha256(value).hexdigest()

def load_trace_prefix(args):
    raw = Path(args.trace_prefix)
    if not raw.is_absolute() or ".." in raw.parts or raw.is_symlink():
        raise ValueError("TRACE_PREFIX_INVALID")
    fd = os.open(raw, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("TRACE_PREFIX_INVALID")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    payload = b"".join(chunks)
    if hashlib.sha256(payload).hexdigest() != args.trace_prefix_sha256:
        raise ValueError("TRACE_PREFIX_HASH_MISMATCH")
    prefix = json.loads(payload.decode("utf-8"))
    expected = {
        key: getattr(args, key, None)
        for key in (
            "run_id", "approved_remote_parent", "remote_run_root",
            "execution_manifest_sha256", "execution_lane", "classification",
            "formal_gate_effect", "formal_admission_eligible",
            "shk001b_eligible", "contains_formal_claims",
        )
        if getattr(args, key, None) is not None
    }
    for key, value in expected.items():
        if prefix.get(key) != value:
            if key in {"run_id", "approved_remote_parent", "remote_run_root"}:
                raise ValueError(key + " mismatch")
            raise ValueError("TRACE_PREFIX_MANIFEST_BINDING_MISMATCH:" + key)
    records = list(prefix.get("records", []))
    previous = "0" * 64
    for index, record in enumerate(records, 1):
        step, event, actor = EVENT_ACTOR_TABLE[index - 1]
        if (record.get("step_id"), record.get("event"), record.get("actor")) != (step, event, actor):
            raise ValueError("TRACE_PREFIX_SEQUENCE_MISMATCH")
        if record.get("previous_trace_hash") != previous:
            raise ValueError("TRACE_PREFIX_CHAIN_MISMATCH")
        body = {k: v for k, v in record.items() if k != "trace_hash"}
        if record.get("trace_hash") != digest(body):
            raise ValueError("TRACE_PREFIX_HASH_MISMATCH")
        if not record.get("input_hashes") or not record.get("output_hashes"):
            raise ValueError("TRACE_PREFIX_PROOF_MISSING")
        previous = record["trace_hash"]
    if len(records) != 11 or prefix.get("trace_head_sha256") != previous:
        raise ValueError("TRACE_PREFIX_INCOMPLETE")
    return prefix, records

def append_trace(records, prefix, input_hashes, output_hashes):
    step_id = len(records) + 1
    step, event, actor = EVENT_ACTOR_TABLE[step_id - 1]
    body = {
        "run_id": prefix["run_id"],
        "step_id": step,
        "event": event,
        "actor": actor,
        "approved_remote_parent": prefix["approved_remote_parent"],
        "remote_run_root": prefix["remote_run_root"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "monotonic_ns": time.monotonic_ns(),
        "input_hashes": dict(input_hashes),
        "output_hashes": dict(output_hashes),
        "status": "SUCCEEDED",
        "failure": None,
        "previous_trace_hash": records[-1]["trace_hash"] if records else "0" * 64,
        **CLASSIFICATION,
    }
    body["trace_hash"] = digest(body)
    records.append(body)
    return body

def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def publish_new(path, value):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError("IMMUTABLE_RECEIPT_EXISTS")
    fd, name = tempfile.mkstemp(
        prefix="." + path.name + ".", suffix=".partial", dir=str(path.parent)
    )
    partial = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        _fsync(path.parent)
        os.link(partial, path)
        _fsync(path.parent)
    finally:
        if partial.exists():
            partial.unlink()
            _fsync(path.parent)

def _fsync(path):
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateFileW(
            str(path), 0x80000000 | 0x40000000,
            0x00000001 | 0x00000002 | 0x00000004,
            None, 3, 0x02000000, None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise RuntimeError("directory durability is unsupported")
        try:
            if not kernel32.FlushFileBuffers(handle):
                raise RuntimeError("directory durability is unsupported")
        finally:
            kernel32.CloseHandle(handle)
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def rename_dir_new(source, destination):
    source = Path(source)
    destination = Path(destination)
    if os.name == "nt":
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("atomic no-replace directory publication unsupported")
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        error = ctypes.get_errno()
        # NFSv4 may provide atomic rename while rejecting Linux's
        # RENAME_NOREPLACE extension with EINVAL/EOPNOTSUPP.  This worker
        # already owns the parent-wide research lock and operates inside a
        # controller-created unique run root, so a second absence check plus
        # same-directory rename retains atomic publication in the declared
        # trusted-code/accidental-safety threat model.
        if error in {22, 38, 95}:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(str(destination))
            os.rename(source, destination)
            return
        raise OSError(error, os.strerror(error), str(destination))

def confined(path, root):
    path = Path(path).resolve()
    root = Path(root).resolve()
    if path != root and root not in path.parents:
        raise ValueError("PATH_OUTSIDE_ROOT")
    return path

def tree_manifest(root):
    root = Path(root).resolve()
    entries = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("RESULT_SYMLINK_REJECTED")
        if path.is_file():
            data = path.read_bytes()
            entries[path.relative_to(root).as_posix()] = {
                "size": len(data),
                "sha256": digest(data),
            }
    return entries

def process_snapshots():
    proc = Path("/proc")
    if proc.is_dir():
        owned = []
        foreign = []
        current_uid = os.getuid()
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text(encoding="utf-8").split()
                identity = entry.name + ":" + stat[21]
                (owned if entry.stat().st_uid == current_uid else foreign).append(identity)
            except (OSError, IndexError, UnicodeDecodeError):
                continue
        return digest(sorted(owned)), digest(sorted(foreign))
    current = {"pid": os.getpid(), "ppid": os.getppid()}
    return digest(current), digest([])

def dataset_evidence(args):
    if args.fixture_only:
        return (
            digest({"adapter_id": "tep_fixture", "runtime_source_sha256": args.runtime_source_sha256}),
            False,
            "NOT_APPLICABLE",
            "EMBEDDED_FIXTURE_BOUND_TO_RUNTIME_HASH",
        )
    if not args.dataset_root:
        return digest({"dataset_root": None}), False, "ERROR", "DATASET_ROOT_MISSING"
    root = Path(args.dataset_root).resolve()
    if not root.is_dir() or root.is_symlink():
        return digest({"dataset_root": str(root), "missing": True}), False, "ERROR", "DATASET_ROOT_INVALID"
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("DATASET_SYMLINK_REJECTED")
        if path.is_file():
            entries.append({
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": file_digest(path),
            })
    return digest(entries), bool(entries), "OBSERVED", None

def gpu_evidence():
    executable = shutil.which("nvidia-smi")
    if executable is None:
        marker = digest({"nvidia_smi": "unavailable"})
        return {
            "gpu_identity": "NVIDIA_SMI_UNAVAILABLE",
            "gpu_inventory_sha256": marker,
            "gpu_process_snapshot_sha256": marker,
            "gpu_probe_status": "NOT_APPLICABLE",
            "gpu_probe_reason": "NVIDIA_SMI_UNAVAILABLE",
        }
    inventory = subprocess.run(
        [executable, "--query-gpu=name,uuid,memory.total", "--format=csv,noheader,nounits"],
        shell=False,
        capture_output=True,
        text=True,
        encoding=locale.getencoding(),
        check=False,
        timeout=15,
    )
    processes = subprocess.run(
        [executable, "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
        shell=False,
        capture_output=True,
        text=True,
        encoding=locale.getencoding(),
        check=False,
        timeout=15,
    )
    if inventory.returncode != 0 or processes.returncode != 0:
        raise ValueError("GPU_PROBE_FAILED")
    inventory_lines = sorted(line.strip() for line in inventory.stdout.splitlines() if line.strip())
    process_lines = sorted(line.strip() for line in processes.stdout.splitlines() if line.strip())
    return {
        "gpu_identity": inventory_lines[0] if inventory_lines else "NO_NVIDIA_GPU",
        "gpu_inventory_sha256": digest(inventory_lines),
        "gpu_process_snapshot_sha256": digest(process_lines),
        "gpu_probe_status": "OBSERVED_NOT_USED",
        "gpu_probe_reason": None,
    }

def collect_probe(root, args):
    root = Path(root).resolve()
    usage = shutil.disk_usage(root)
    observed_free = int(
        getattr(
            args,
            "fake_available_bytes",
            os.environ.get("RFB_RESEARCH_FAKE_AVAILABLE_BYTES", usage.free),
        )
    )
    owned, foreign = process_snapshots()
    dataset_hash, dataset_verified, dataset_status, dataset_reason = dataset_evidence(args)
    stat = root.stat()
    mountinfo = Path("/proc/self/mountinfo")
    mountinfo_hash = file_digest(mountinfo) if mountinfo.is_file() else digest({"mountinfo": "unavailable"})
    boot_id_path = Path("/proc/sys/kernel/random/boot_id")
    boot_id = boot_id_path.read_text(encoding="utf-8").strip() if boot_id_path.is_file() else "UNAVAILABLE"
    def allocated_bytes(path):
        total = 0
        for item in path.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    stat_result = item.stat()
                    total += int(getattr(stat_result, "st_blocks", 0) * 512 or stat_result.st_size)
            except OSError:
                continue
        return total
    project_allocated = allocated_bytes(root)
    dataset_root = getattr(args, "dataset_root", None)
    dataset_bytes = 0
    if dataset_root:
        dataset_path = Path(dataset_root).resolve()
        if dataset_path == root or root in dataset_path.parents:
            dataset_bytes = allocated_bytes(dataset_path)
    durable_bytes = sum(
        allocated_bytes(path)
        for path in root.glob("*.results*")
        if path.is_dir() and not path.is_symlink()
    )
    scratch_bytes = sum(
        allocated_bytes(path)
        for path in root.rglob("*")
        if path.is_dir()
        and not path.is_symlink()
        and (path.name.endswith(".partial") or path.name == "scratch")
    )
    retry_bytes = sum(
        allocated_bytes(path)
        for path in root.rglob("*")
        if path.is_dir()
        and not path.is_symlink()
        and path.name in {"retry", "quarantine", "wal"}
    )
    buckets = {
        "ephemeral_dataset": dataset_bytes,
        "durable_result_staging": durable_bytes,
        "scratch_partial": scratch_bytes,
        "retry_quarantine_wal": retry_bytes,
        "emergency_reserve": 0,
    }
    fake_buckets = getattr(args, "fake_capacity_buckets", None)
    if fake_buckets is not None:
        buckets = {name: int(fake_buckets[name]) for name in buckets}
    filesystem_delta = max(0, usage.used - int(getattr(args, "filesystem_used_baseline", usage.used)))
    owned_external = int(getattr(args, "owned_external_layers_bytes", 0))
    open_deleted = int(getattr(args, "open_deleted_bytes", 0))
    capacity_peak = max(project_allocated, filesystem_delta + owned_external + open_deleted)
    subbudget_breach = any(
        buckets[name] > CAPACITY_CONTRACT["subbudgets_bytes"][name]
        for name in buckets
    )
    if subbudget_breach:
        capacity_state = "SUBBUDGET_BREACH"
    elif capacity_peak > HARD_PEAK_BYTES:
        capacity_state = "SAFE_HALT_CAP_BREACH"
    elif capacity_peak >= DRAIN_THRESHOLD_BYTES:
        capacity_state = "DRAIN_AND_SEAL"
    elif capacity_peak > PLANNED_PEAK_BYTES:
        capacity_state = "PLANNED_CAP_EXCEEDED"
    else:
        capacity_state = "PLANNED"
    return {
        "collected_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "monotonic_ns": time.monotonic_ns(),
        "boot_id": boot_id,
        "root": str(root),
        "approved_remote_parent": str(root.parent),
        "remote_run_root": str(root),
        "hostname": socket.gethostname(),
        "python_version": sys.version.split()[0],
        "source_tree_sha256": args.runtime_source_sha256,
        "package_inventory_sha256": digest({
            "implementation": sys.implementation.name,
            "version": sys.version,
            "stdlib": sorted(sys.stdlib_module_names),
        }),
        "config_sha256": digest({"runtime_manifest": args.runtime_manifest_sha256}),
        "input_manifest_sha256": args.manifest_sha256,
        "owned_process_snapshot_sha256": owned,
        "foreign_process_snapshot_sha256": foreign,
        "mount_identity": f"device={stat.st_dev}:anchor={root.anchor}",
        "mountinfo_sha256": mountinfo_hash,
        "filesystem_total_bytes": usage.total,
        "filesystem_used_bytes": usage.used,
        "filesystem_free_bytes": observed_free,
        "project_tree_allocated_bytes": project_allocated,
        "filesystem_used_delta_bytes": filesystem_delta,
        "owned_external_layers_bytes": owned_external,
        "open_deleted_bytes": open_deleted,
        "capacity_peak_bytes": capacity_peak,
        "capacity_state": capacity_state,
        "capacity_buckets_bytes": buckets,
        "capacity_available": observed_free >= SEGMENT_START_FREE_MIN_BYTES,
        "remote_reserve_available": observed_free >= REMOTE_RESERVE_FLOOR_BYTES,
        "dataset_manifest_sha256": dataset_hash,
        "dataset_manifest_verified": dataset_verified,
        "dataset_probe_status": dataset_status,
        "dataset_probe_reason": dataset_reason,
        "gpu_policy": "cpu_only",
        **gpu_evidence(),
        "prepared_manifest_sha256": args.manifest_sha256,
        "controller_nonce": args.controller_nonce,
        "formal_snapshot_sha256": args.formal_snapshot_sha256,
        "runtime_file_sha256": args.runtime_file_sha256,
        "runtime_source_sha256": args.runtime_source_sha256,
        "runtime_manifest_sha256": args.runtime_manifest_sha256,
        "runtime_dependency_profile": args.runtime_dependency_profile,
        "runtime_path": str(Path(args.runtime_path).resolve()),
        "runtime_format": "python_zipapp_stdlib_v1",
    }

IMMUTABLE_PROBE_FIELDS = (
    "boot_id", "root", "approved_remote_parent", "remote_run_root",
    "hostname", "python_version", "source_tree_sha256",
    "package_inventory_sha256", "config_sha256", "input_manifest_sha256",
    "mount_identity", "mountinfo_sha256",
    "filesystem_total_bytes", "dataset_manifest_sha256",
    "dataset_manifest_verified", "dataset_probe_status",
    "gpu_policy", "gpu_identity", "gpu_inventory_sha256",
    "prepared_manifest_sha256",
    "controller_nonce", "formal_snapshot_sha256", "runtime_file_sha256",
    "runtime_source_sha256", "runtime_manifest_sha256",
    "runtime_dependency_profile", "runtime_path", "runtime_format",
)

def validate_probe_freshness(probe, max_age_seconds, previous=None):
    collected = datetime.fromisoformat(probe["collected_at_utc"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - collected).total_seconds()
    if age < -5 or age > max_age_seconds + 5:
        raise ValueError("PREFLIGHT_STALE:wall_clock")
    if int(probe.get("monotonic_ns", -1)) < 0:
        raise ValueError("PREFLIGHT_STALE:monotonic")
    if not probe.get("capacity_available") or not probe.get("remote_reserve_available"):
        raise ValueError("PREFLIGHT_STALE:capacity")
    capacity_state = probe.get("capacity_state")
    if capacity_state == "SAFE_HALT_CAP_BREACH":
        raise ValueError("SAFE_HALT_CAP_BREACH")
    if capacity_state == "SUBBUDGET_BREACH":
        raise ValueError("SUBBUDGET_BORROWING")
    if previous is None and capacity_state == "PLANNED_CAP_EXCEEDED":
        raise ValueError("CAPACITY_PLANNING_INVALID")
    if previous is not None:
        if int(probe["monotonic_ns"]) < int(previous["monotonic_ns"]):
            raise ValueError("PREFLIGHT_DRIFT:monotonic")
        for field in IMMUTABLE_PROBE_FIELDS:
            if probe.get(field) != previous.get(field):
                raise ValueError("PREFLIGHT_DRIFT:" + field)
    return probe

def runtime_binding(args):
    runtime_path = Path(args.runtime_path).resolve()
    if file_digest(runtime_path) != args.runtime_file_sha256:
        raise ValueError("RUNTIME_HASH_MISMATCH")
    if runtime_path.name != args.runtime_file_sha256 + ".pyz":
        raise ValueError("RUNTIME_PATH_MISMATCH")
    runtime_manifest_path = runtime_path.with_suffix(".manifest.json")
    runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    unsigned = {k: v for k, v in runtime_manifest.items() if k != "manifest_sha256"}
    if (
        runtime_manifest.get("adapter_id") != "tep_fixture"
        or runtime_manifest.get("dependency_profile") != "stdlib_only"
        or args.runtime_dependency_profile != "stdlib_only"
        or runtime_manifest.get("file_sha256") != args.runtime_file_sha256
        or runtime_manifest.get("source_sha256") != args.runtime_source_sha256
        or runtime_manifest.get("manifest_sha256") != args.runtime_manifest_sha256
        or digest(unsigned) != args.runtime_manifest_sha256
    ):
        raise ValueError("RUNTIME_MANIFEST_MISMATCH")
    with zipfile.ZipFile(runtime_path) as archive:
        if digest(archive.read("__main__.py")) != args.runtime_source_sha256:
            raise ValueError("RUNTIME_SOURCE_MISMATCH")
    return runtime_path

def preflight(args):
    runtime_path = runtime_binding(args)
    root = Path(args.root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("PREFLIGHT_ROOT_INVALID")
    evidence = collect_probe(root, args)
    evidence["runtime_path"] = str(runtime_path)
    print(canonical(evidence).decode("utf-8"))

def stage_seal(args):
    partial = Path(args.partial)
    final = Path(args.final)
    if (not partial.is_absolute() or not final.is_absolute()
            or ".." in partial.parts or ".." in final.parts
            or partial.parent != final.parent):
        raise ValueError("STAGE_VERIFY_FAILED")
    try:
        partial_stat = os.lstat(partial)
    except OSError:
        raise ValueError("STAGE_VERIFY_FAILED")
    if not stat.S_ISREG(partial_stat.st_mode):
        raise ValueError("STAGE_VERIFY_FAILED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(partial, flags)
    try:
        digest_value = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest_value.update(chunk)
    finally:
        os.close(fd)
    if digest_value.hexdigest() != args.sha256:
        raise ValueError("STAGE_VERIFY_FAILED")
    try:
        os.lstat(final)
    except FileNotFoundError:
        pass
    else:
        raise ValueError("STAGE_VERIFY_FAILED")
    os.link(partial, final, follow_symlinks=False)
    _fsync(final.parent)
    _fsync(final.parent.parent)
    os.unlink(partial)
    _fsync(final.parent)
    _fsync(final.parent.parent)
    print(canonical({"sealed": args.sha256}).decode("utf-8"))

def validate_execution_manifest(manifest, args, runtime_path):
    if manifest.get("adapter_id") != "tep_fixture":
        raise ValueError("RUNTIME_DEPENDENCY_CLOSURE_UNAVAILABLE")
    if manifest.get("resource_limits") != CAPACITY_CONTRACT:
        raise ValueError("CAPACITY_CONTRACT_MISMATCH")
    for field, expected in CLASSIFICATION.items():
        if manifest.get(field) != expected:
            raise ValueError("CLASSIFICATION_MISMATCH:" + field)
    for field in (
        "runtime_file_sha256",
        "runtime_source_sha256",
        "runtime_manifest_sha256",
        "runtime_dependency_profile",
    ):
        if manifest.get(field) != getattr(args, field):
            raise ValueError("RUNTIME_BINDING_MISMATCH:" + field)
    if manifest.get("runtime_format") == "python_zipapp_v1":
        raise ValueError("RUNTIME_FORMAT_LEGACY_REJECTED")
    if manifest.get("runtime_format") != "python_zipapp_stdlib_v1":
        raise ValueError("RUNTIME_BINDING_MISMATCH:runtime_format")
    if Path(manifest.get("runtime_path", "")).resolve() != runtime_path:
        raise ValueError("RUNTIME_BINDING_MISMATCH:runtime_path")
    preflight = manifest.get("preflight_evidence")
    if not isinstance(preflight, dict):
        raise ValueError("PREFLIGHT_EVIDENCE_MISSING")
    if digest(preflight) != manifest.get("preflight_evidence_sha256"):
        raise ValueError("PREFLIGHT_EVIDENCE_HASH_MISMATCH")
    for field in (
        "prepared_manifest_sha256",
        "controller_nonce",
        "formal_snapshot_sha256",
        "approved_remote_parent",
        "remote_run_root",
    ):
        if not manifest.get(field) or preflight.get(field) != manifest.get(field):
            raise ValueError("PREFLIGHT_BINDING_MISMATCH:" + field)
    for field in (
        "runtime_format",
        "runtime_path",
        "runtime_file_sha256",
        "runtime_source_sha256",
        "runtime_manifest_sha256",
        "runtime_dependency_profile",
    ):
        if preflight.get(field) != manifest.get(field):
            raise ValueError("PREFLIGHT_RUNTIME_BINDING_MISMATCH:" + field)

def scan_closed_result(root):
    forbidden = (b"truth", b"password", b"secret", b"api_key", b"raw dataset")
    for path in Path(root).rglob("*"):
        if path.is_symlink():
            raise ValueError("RESULT_SYMLINK_REJECTED")
        if path.is_file():
            if ".partial" in path.name:
                raise ValueError("PARTIAL_ARTIFACT_REJECTED")
            data = path.read_bytes()
            lowered = data.lower()
            if b"\x00" in data or any(token in lowered for token in forbidden):
                raise ValueError("CLOSED_RESULT_REJECTED")
            data.decode("utf-8")

def validate_receipt(receipt, result_root=None):
    for field, expected in CLASSIFICATION.items():
        if receipt.get(field) != expected:
            raise ValueError("RECEIPT_CLASSIFICATION_MISMATCH:" + field)
    body = {k: v for k, v in receipt.items() if k != "self_hash"}
    if receipt.get("self_hash") != digest(body):
        raise ValueError("RECEIPT_SELF_HASH_MISMATCH")
    for field in (
        "runtime_file_sha256",
        "runtime_source_sha256",
        "runtime_manifest_sha256",
        "runtime_dependency_profile",
        "runtime_path",
        "runtime_format",
    ):
        if not receipt.get(field):
            raise ValueError("RECEIPT_RUNTIME_BINDING_MISSING:" + field)
    if receipt.get("terminal_state") == "RESULT_SEALED_REMOTE":
        required = (
            "execution_manifest_sha256",
            "prepared_manifest_sha256",
            "preflight_evidence_sha256",
            "preflight_after_sha256",
            "formal_snapshot_sha256",
            "controller_nonce",
            "started_at_utc",
            "ended_at_utc",
            "exit_code",
            "hostname",
            "root_identity",
            "mount_identity",
            "gpu_policy",
            "gpu_identity",
            "resource_peaks",
            "pre_post_hashes",
            "result_path",
            "remote_result_tree_sha256",
            "result_tree_sha256",
            "receipt_self_hash",
            "directory_durable",
            "formal_artifacts_created",
            "shk001b_started",
            "gate_checklist_mutated",
        )
        for field in required:
            if field not in receipt:
                raise ValueError("RECEIPT_SUCCESS_FIELD_MISSING:" + field)
        if (
            receipt["directory_durable"] is not True
            or receipt["formal_artifacts_created"] != []
            or receipt["shk001b_started"] is not False
            or receipt["gate_checklist_mutated"] is not False
        ):
            raise ValueError("RECEIPT_SUCCESS_INVARIANT_MISMATCH")
        inner = {
            k: v
            for k, v in receipt.items()
            if k not in {"self_hash", "receipt_self_hash", *CLASSIFICATION}
        }
        if receipt["receipt_self_hash"] != digest(inner):
            raise ValueError("RECEIPT_INNER_HASH_MISMATCH")
    if result_root is not None:
        entries = tree_manifest(result_root)
        if digest(entries) != receipt.get("result_tree_sha256"):
            raise ValueError("RECEIPT_RESULT_HASH_MISMATCH")

def seal_receipt(body):
    receipt = dict(body)
    receipt.update(CLASSIFICATION)
    receipt["self_hash"] = digest(receipt)
    return receipt

def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"

def start_ticks(pid):
    try:
        return Path("/proc/" + str(pid) + "/stat").read_text().split()[21]
    except (OSError, IndexError):
        return "unknown"

def process_alive(record):
    if record.get("boot_id") != boot_id():
        return False
    pid = int(record.get("pid", -1))
    if start_ticks(pid) != str(record.get("start_ticks")):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if hasattr(os, "killpg"):
        try:
            os.killpg(int(record.get("process_group", -1)), 0)
        except OSError:
            return False
    return True

def wall_time():
    override = os.environ.get("RFB_RESEARCH_FAKE_WALL_TIME")
    return float(override) if override is not None else time.time()

def stale_second_observation(lock, first):
    advance = os.environ.get("RFB_RESEARCH_STALE_RECHECK_ADVANCE_SECONDS")
    if advance is None:
        time.sleep(10.0)
        observed_at = wall_time()
    else:
        observed_at = wall_time() + float(advance)
    second = json.loads(lock.read_text(encoding="utf-8"))
    if observed_at - wall_time() < 10 and advance is not None:
        raise ValueError("LOCK_STALE_RECHECK_TOO_SOON")
    if (second.get("nonce") != first.get("nonce")
            or second.get("heartbeat_at") != first.get("heartbeat_at")):
        raise ValueError("LOCK_CHANGED_DURING_STALE_RECHECK")
    return second

def write_lock_record(path, record):
    partial = path.with_name("." + path.name + ".heartbeat.partial")
    publish_new(partial, record)
    os.replace(partial, path)
    _fsync(path.parent)

def acquire_lock(parent, root, run_id, manifest_sha256, controller_nonce):
    lock = Path(parent) / ".rfb-research-run.lock"
    nonce = secrets.token_hex(16)
    now = wall_time()
    record = {
        "run_id": run_id,
        "approved_remote_parent": str(Path(parent).resolve()),
        "remote_run_root": str(Path(root).resolve()),
        "execution_manifest_sha256": manifest_sha256,
        "controller_nonce": controller_nonce,
        "pid": os.getpid(),
        "boot_id": boot_id(),
        "start_ticks": start_ticks(os.getpid()),
        "process_group": os.getpgrp() if hasattr(os, "getpgrp") else os.getpid(),
        "nonce": nonce,
        "heartbeat_at": now,
        "created_at": now,
    }
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = json.loads(lock.read_text(encoding="utf-8"))
        if wall_time() - float(existing.get("heartbeat_at", 0)) < 60:
            raise ValueError("LOCK_BUSY")
        second = stale_second_observation(lock, existing)
        if process_alive(second):
            raise ValueError("LOCK_STALE_CANDIDATE_OWNER_ALIVE")
        tomb = lock.with_name(lock.name + "." + str(existing.get("nonce")) + ".tombstone")
        if tomb.exists():
            raise ValueError("LOCK_TOMBSTONE_EXISTS")
        current = json.loads(lock.read_text(encoding="utf-8"))
        if current.get("nonce") != second.get("nonce"):
            raise ValueError("LOCK_CHANGED_DURING_TOMBSTONE")
        os.rename(lock, tomb)
        _fsync(Path(parent))
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(record))
        stream.flush()
        os.fsync(stream.fileno())
    _fsync(Path(parent))
    stop = threading.Event()
    def heartbeat_loop():
        while not stop.wait(10.0):
            current = json.loads(lock.read_text(encoding="utf-8"))
            if current.get("nonce") != nonce:
                return
            record["heartbeat_at"] = wall_time()
            write_lock_record(lock, record)
    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    return {"path": lock, "nonce": nonce, "record": record, "stop": stop, "thread": thread}

def release_lock(lock_state):
    lock_state["stop"].set()
    lock_state["thread"].join(timeout=11.0)
    if lock_state["thread"].is_alive():
        raise ValueError("LOCK_HEARTBEAT_STOP_FAILED")
    lock = lock_state["path"]
    current = json.loads(lock.read_text(encoding="utf-8"))
    if current.get("nonce") != lock_state["nonce"]:
        raise ValueError("LOCK_CHANGED_DURING_RELEASE")
    tomb = lock.with_name(lock.name + "." + lock_state["nonce"] + ".tombstone")
    if tomb.exists():
        raise ValueError("LOCK_TOMBSTONE_EXISTS")
    os.rename(lock, tomb)
    _fsync(lock.parent)
    persisted = json.loads(tomb.read_text(encoding="utf-8"))
    if persisted.get("nonce") != lock_state["nonce"]:
        raise ValueError("LOCK_TOMBSTONE_VERIFY_FAILED")
    return digest(persisted)

def worker(args):
    runtime_path = runtime_binding(args)
    raw_manifest_path = Path(args.manifest)
    if (
        not raw_manifest_path.is_absolute()
        or ".." in raw_manifest_path.parts
        or raw_manifest_path.is_symlink()
    ):
        raise ValueError("EXECUTION_MANIFEST_SYMLINK_REJECTED")
    manifest_path = raw_manifest_path.resolve()
    manifest_fd = os.open(
        raw_manifest_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        if not stat.S_ISREG(os.fstat(manifest_fd).st_mode):
            raise ValueError("EXECUTION_MANIFEST_SYMLINK_REJECTED")
        chunks = []
        while True:
            chunk = os.read(manifest_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(manifest_fd)
    manifest_bytes = b"".join(chunks)
    if hashlib.sha256(manifest_bytes).hexdigest() != args.execution_manifest_sha256:
        raise ValueError("EXECUTION_MANIFEST_HASH_MISMATCH")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    validate_execution_manifest(manifest, args, runtime_path)
    for key in (
        "run_id",
        "approved_remote_parent",
        "remote_run_root",
        "execution_lane",
        "classification",
        "formal_gate_effect",
        "formal_admission_eligible",
        "shk001b_eligible",
        "contains_formal_claims",
    ):
        setattr(args, key, manifest[key])
    trace_prefix, trace_records = load_trace_prefix(args)
    append_trace(
        trace_records,
        trace_prefix,
        {"staged_execution_manifest": args.execution_manifest_sha256},
        {"verified_manifest_bytes": hashlib.sha256(manifest_bytes).hexdigest()},
    )
    approved_parent = Path(manifest["approved_remote_parent"]).resolve()
    root = Path(manifest["remote_run_root"]).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("RUN_ROOT_INVALID")
    confined(manifest_path, root)
    run_id = manifest["run_id"]
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("MANIFEST_INVALID")
    if root != approved_parent / run_id or approved_parent.is_symlink():
        raise ValueError("RUN_ROOT_BINDING_MISMATCH")
    sealed = root / (run_id + ".remote-result")
    partial = root / ("." + run_id + ".remote-result.partial")
    receipt_path = root / (run_id + ".REMOTE_EXECUTION_RECEIPT.json")
    if any(p.exists() or p.is_symlink() for p in (sealed, partial, receipt_path)):
        raise ValueError("IMMUTABLE_RECEIPT_EXISTS")
    args.manifest_sha256 = manifest["prepared_manifest_sha256"]
    args.controller_nonce = manifest["controller_nonce"]
    args.formal_snapshot_sha256 = manifest["formal_snapshot_sha256"]
    args.dataset_root = manifest.get("dataset_root")
    args.fixture_only = True
    lock = acquire_lock(
        approved_parent,
        root,
        run_id,
        args.execution_manifest_sha256,
        manifest["controller_nonce"],
    )
    append_trace(
        trace_records,
        trace_prefix,
        {"execution_manifest": args.execution_manifest_sha256},
        {"lock_owner": digest(lock["record"])},
    )
    receipt_published = False
    try:
        full_preflight = validate_probe_freshness(
            manifest["preflight_evidence"], 300
        )
        before = collect_probe(root, args)
        validate_probe_freshness(before, 30, previous=full_preflight)
        append_trace(
            trace_records,
            trace_prefix,
            {"full_preflight": digest(full_preflight)},
            {"launch_recheck": digest(before)},
        )
        partial.mkdir()
        adapter_payload = {
            "adapter_id": manifest["adapter_id"],
            "run_id": run_id,
            "panel": PANEL,
            "bundle_complete": True,
            "effect_peeking": False,
            "segment_boundary_frozen": True,
            "capacity_state": "FIXTURE_ONLY",
        }
        result_file = partial / "adapter_result.json"
        result_file.write_bytes(canonical(adapter_payload))
        with result_file.open("rb+") as stream:
            os.fsync(stream.fileno())
        _fsync(partial)
        scan_closed_result(partial)
        rename_dir_new(partial, sealed)
        _fsync(root)
        tree_hash = digest(tree_manifest(sealed))
        after = collect_probe(root, args)
        validate_probe_freshness(after, 10, previous=before)
        append_trace(
            trace_records,
            trace_prefix,
            {"launch_recheck": digest(before)},
            {"post_recheck": digest(after)},
        )
        append_trace(
            trace_records,
            trace_prefix,
            {"post_recheck": digest(after)},
            {"result_tree": tree_hash},
        )
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        body = {
            "run_id": run_id,
            "execution_manifest_sha256": args.execution_manifest_sha256,
            "prepared_manifest_sha256": manifest["prepared_manifest_sha256"],
            "preflight_evidence_sha256": manifest["preflight_evidence_sha256"],
            "preflight_after_sha256": digest(after),
            "formal_snapshot_sha256": manifest["formal_snapshot_sha256"],
            "controller_nonce": manifest["controller_nonce"],
            "started_at_utc": before["collected_at_utc"],
            "ended_at_utc": now,
            "exit_code": 0,
            "hostname": after["hostname"],
            "root_identity": str(root),
            "approved_remote_parent": str(approved_parent),
            "remote_run_root": str(root),
            "mount_identity": after["mount_identity"],
            "gpu_policy": "cpu_only",
            "gpu_identity": after["gpu_identity"],
            "resource_peaks": {
                "filesystem_used_bytes": max(before["filesystem_used_bytes"], after["filesystem_used_bytes"]),
            },
            "pre_post_hashes": {
                key: {"before": before[field], "after": after[field]}
                for key, field in (
                    ("source_tree", "source_tree_sha256"),
                    ("package_inventory", "package_inventory_sha256"),
                    ("config", "config_sha256"),
                    ("input_manifest", "input_manifest_sha256"),
                    ("owned_process_snapshot", "owned_process_snapshot_sha256"),
                    ("foreign_process_snapshot", "foreign_process_snapshot_sha256"),
                    ("mount_identity", "mount_identity"),
                    ("dataset_manifest", "dataset_manifest_sha256"),
                    ("gpu_inventory", "gpu_inventory_sha256"),
                    ("gpu_process_snapshot", "gpu_process_snapshot_sha256"),
                )
            },
            "terminal_state": "RESULT_SEALED_REMOTE",
            "failure_code": None,
            "adapter_id": manifest["adapter_id"],
            "adapter_implementation_sha256": digest(manifest["adapter_id"] + ":1"),
            "fixed_argv_digest": digest(sys.argv),
            "minimal_environment_digest": digest({k: os.environ.get(k) for k in ("PATH", "PYTHONUTF8", "PYTHONUNBUFFERED", "RFB_RESEARCH_ROOT")}),
            "runtime_file_sha256": args.runtime_file_sha256,
            "runtime_source_sha256": args.runtime_source_sha256,
            "runtime_manifest_sha256": args.runtime_manifest_sha256,
            "runtime_dependency_profile": args.runtime_dependency_profile,
            "runtime_path": str(runtime_path),
            "runtime_format": "python_zipapp_stdlib_v1",
            "result_path": str(sealed),
            "remote_result_tree_sha256": tree_hash,
            "result_tree_sha256": tree_hash,
            "receipt_self_hash": "0" * 64,
            "directory_durable": True,
            "formal_artifacts_created": [],
            "shk001b_started": False,
            "gate_checklist_mutated": False,
            "events": [{"kind": "RECEIPT_PUBLISHED_BEFORE_LOCK_RELEASE"}],
        }
        receipt_body_proof = digest(
            {k: v for k, v in body.items() if k != "receipt_self_hash"}
        )
        append_trace(
            trace_records,
            trace_prefix,
            {"result_tree": tree_hash},
            {"authoritative_remote_receipt_body": receipt_body_proof},
        )
        body["lifecycle_trace_records"] = trace_records
        body["lifecycle_trace_head_sha256"] = trace_records[-1]["trace_hash"]
        body["receipt_self_hash"] = digest(
            {k: v for k, v in body.items() if k != "receipt_self_hash"}
        )
        receipt = seal_receipt(body)
        validate_receipt(receipt, sealed)
        publish_new(receipt_path, receipt)
        persisted_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validate_receipt(persisted_receipt, sealed)
        if digest(persisted_receipt) != digest(receipt):
            raise ValueError("REMOTE_RECEIPT_READBACK_MISMATCH")
        receipt_hash = digest(persisted_receipt)
        receipt_published = True
        lock_release_hash = release_lock(lock)
        lock = None
        append_trace(
            trace_records,
            trace_prefix,
            {"authoritative_remote_receipt": receipt_hash},
            {"lock_release_tombstone": lock_release_hash},
        )
        release_proof = {
            "schema_version": "r005-lock-release-proof.v1",
            "run_id": run_id,
            "authoritative_remote_receipt_sha256": receipt_hash,
            "lock_release_tombstone_sha256": lock_release_hash,
            "lifecycle_trace_record": trace_records[-1],
        }
        release_proof["self_hash"] = digest(release_proof)
        release_path = root / (run_id + ".LOCK_RELEASE_PROOF.json")
        publish_new(release_path, release_proof)
        persisted_release = json.loads(release_path.read_text(encoding="utf-8"))
        if persisted_release != release_proof:
            raise ValueError("LOCK_RELEASE_PROOF_READBACK_MISMATCH")
        print(canonical(persisted_receipt).decode("utf-8"))
    except Exception as exc:
        if not receipt_path.exists():
            failure_message = str(exc)
            stable_failure_code = type(exc).__name__
            if failure_message and all(
                character.isalnum() or character in "_:-."
                for character in failure_message
            ):
                stable_failure_code = failure_message
            failure = seal_receipt({
                "run_id": run_id,
                "terminal_state": "FAILED",
                "failure_code": stable_failure_code,
                "error": "worker failure",
                "attempted_execution_manifest_sha256": args.execution_manifest_sha256,
                "runtime_file_sha256": args.runtime_file_sha256,
                "runtime_source_sha256": args.runtime_source_sha256,
                "runtime_manifest_sha256": args.runtime_manifest_sha256,
                "runtime_dependency_profile": args.runtime_dependency_profile,
                "runtime_path": str(runtime_path),
                "runtime_format": "python_zipapp_stdlib_v1",
                "approved_remote_parent": str(approved_parent),
                "remote_run_root": str(root),
            })
            validate_receipt(failure)
            publish_new(receipt_path, failure)
            receipt_published = True
        raise
    finally:
        if receipt_published and lock is not None:
            release_lock(lock)

def verify_remote(args):
    runtime_path = runtime_binding(args)
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    for field in (
        "runtime_file_sha256",
        "runtime_source_sha256",
        "runtime_manifest_sha256",
        "runtime_dependency_profile",
    ):
        if receipt.get(field) != getattr(args, field):
            raise ValueError("RUNTIME_BINDING_MISMATCH:" + field)
    if Path(receipt.get("runtime_path", "")).resolve() != runtime_path:
        raise ValueError("RUNTIME_BINDING_MISMATCH:runtime_path")
    result = Path(receipt["result_path"]).resolve()
    validate_receipt(receipt, result)
    if digest(tree_manifest(result)) != receipt.get("remote_result_tree_sha256"):
        raise ValueError("REMOTE_RECEIPT_INVALID")
    print(canonical(receipt).decode("utf-8"))

def parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    pf = sub.add_parser("preflight")
    pf.add_argument("--root", required=True)
    pf.add_argument("--manifest-sha256", required=True)
    pf.add_argument("--controller-nonce", required=True)
    pf.add_argument("--formal-snapshot-sha256", required=True)
    pf.add_argument("--runtime-file-sha256", required=True)
    pf.add_argument("--runtime-source-sha256", required=True)
    pf.add_argument("--runtime-manifest-sha256", required=True)
    pf.add_argument("--runtime-dependency-profile", required=True)
    pf.add_argument("--runtime-path", required=True)
    pf.add_argument("--dataset-root")
    pf.add_argument("--fixture-only", action="store_true")
    pf.add_argument("--filesystem-baseline-bytes", type=int)
    pf.add_argument("--owned-external-layers-bytes", type=int)
    pf.add_argument("--trusted-open-deleted-bytes", type=int)
    seal = sub.add_parser("stage-seal")
    seal.add_argument("--partial", required=True)
    seal.add_argument("--final", required=True)
    seal.add_argument("--sha256", required=True)
    work = sub.add_parser("worker")
    work.add_argument("--manifest", required=True)
    work.add_argument("--execution-manifest-sha256", required=True)
    work.add_argument("--runtime-file-sha256", required=True)
    work.add_argument("--runtime-source-sha256", required=True)
    work.add_argument("--runtime-manifest-sha256", required=True)
    work.add_argument("--runtime-dependency-profile", required=True)
    work.add_argument("--runtime-path", required=True)
    work.add_argument("--trace-prefix", required=True)
    work.add_argument("--trace-prefix-sha256", required=True)
    verify = sub.add_parser("verify-remote")
    verify.add_argument("--receipt", required=True)
    verify.add_argument("--runtime-file-sha256", required=True)
    verify.add_argument("--runtime-source-sha256", required=True)
    verify.add_argument("--runtime-manifest-sha256", required=True)
    verify.add_argument("--runtime-dependency-profile", required=True)
    verify.add_argument("--runtime-path", required=True)
    return p

def main():
    args = parser().parse_args()
    commands = {
        "preflight": preflight,
        "stage-seal": stage_seal,
        "worker": worker,
        "verify-remote": verify_remote,
    }
    commands[args.command](args)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
"""


def _render_main_source() -> str:
    rendered = canonical_bytes(shared_source_inventory()).decode("utf-8")
    return _MAIN_SOURCE.replace(
        "CLASSIFICATION = {",
        f"SHARED_SOURCE_INVENTORY = {rendered}\nCLASSIFICATION = {{",
        1,
    )


def runtime_bytes(adapter_id: str) -> bytes:
    """Return byte-identical zipapp bytes for an approved adapter."""

    if adapter_id not in _PORTABLE_ADAPTERS:
        raise RuntimeBundleError(f"RUNTIME_DEPENDENCY_CLOSURE_UNAVAILABLE:{adapter_id}")
    buffer = io.BytesIO()
    info = zipfile.ZipInfo("__main__.py", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(buffer, "w", strict_timestamps=True) as archive:
        archive.writestr(info, _render_main_source().encode("utf-8"))
    return buffer.getvalue()


def _publish_new_bytes(destination: Path, data: bytes) -> None:
    """Durably publish bytes via an atomic create-new hard link."""

    expected = hashlib.sha256(data).hexdigest()
    fd, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=str(destination.parent)
    )
    partial = Path(name)
    linked = False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(partial.read_bytes()).hexdigest() != expected:
            raise RuntimeBundleError("RUNTIME_PARTIAL_VERIFY_FAILED")
        _fsync_dir(destination.parent)
        try:
            os.link(partial, destination)
            linked = True
        except FileExistsError as exc:
            raise RuntimeBundleError("RUNTIME_DESTINATION_EXISTS") from exc
        _fsync_dir(destination.parent)
    finally:
        if partial.exists():
            partial.unlink()
            if linked:
                _fsync_dir(destination.parent)


def build_runtime_bundle(adapter_id: str, output_dir: str | Path) -> RuntimeBundle:
    """Build/publish a content-addressed runtime without overwriting content."""

    data = runtime_bytes(adapter_id)
    file_sha256 = hashlib.sha256(data).hexdigest()
    source_sha256 = hashlib.sha256(_render_main_source().encode("utf-8")).hexdigest()
    source_inventory = shared_source_inventory()
    source_inventory_sha256 = hashlib.sha256(
        canonical_bytes(source_inventory)
    ).hexdigest()
    unsigned_manifest = {
        "adapter_id": adapter_id,
        "runtime_format": "python_zipapp_stdlib_v1",
        "entrypoint": "__main__.py",
        "dependency_profile": "stdlib_only",
        "source_sha256": source_sha256,
        "file_sha256": file_sha256,
        "shared_source_inventory": source_inventory,
        "shared_source_inventory_sha256": source_inventory_sha256,
    }
    manifest_sha256 = hashlib.sha256(canonical_bytes(unsigned_manifest)).hexdigest()
    manifest = {**unsigned_manifest, "manifest_sha256": manifest_sha256}
    directory = Path(output_dir).resolve()
    directory_preexisting = directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if not directory_preexisting:
        _fsync_dir(directory.parent)
    _fsync_dir(directory)
    final = directory / f"{file_sha256}.pyz"
    manifest_path = directory / f"{file_sha256}.manifest.json"
    manifest_bytes = canonical_bytes(manifest)
    if final.exists() and (
        final.is_symlink()
        or not final.is_file()
        or hashlib.sha256(final.read_bytes()).hexdigest() != file_sha256
    ):
        raise RuntimeBundleError("RUNTIME_CACHE_CORRUPT")
    if manifest_path.exists() and (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or manifest_path.read_bytes() != manifest_bytes
    ):
        raise RuntimeBundleError("RUNTIME_CACHE_CORRUPT")
    if not manifest_path.exists():
        _publish_new_bytes(manifest_path, manifest_bytes)
    if not final.exists():
        _publish_new_bytes(final, data)
    if (
        final.is_symlink()
        or hashlib.sha256(final.read_bytes()).hexdigest() != file_sha256
        or not manifest_path.is_file()
        or manifest_path.is_symlink()
        or manifest_path.read_bytes() != manifest_bytes
    ):
        raise RuntimeBundleError("RUNTIME_CACHE_CORRUPT")
    _fsync_dir(directory)
    return RuntimeBundle(
        adapter_id,
        final,
        manifest_path,
        file_sha256,
        source_sha256,
        manifest_sha256,
        source_inventory,
        source_inventory_sha256,
    )


def runtime_bundle_for_adapter(
    adapter_id: str, output_dir: str | Path
) -> RuntimeBundle:
    """Compatibility alias with an explicit adapter-oriented name."""

    return build_runtime_bundle(adapter_id, output_dir)
