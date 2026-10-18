"""Remote worker entry point for a prepared research manifest."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

from .adapters import resolve_adapter, validate_adapter_contract
from .files import _fsync_dir, publish_json_new
from .lock import ResearchLock, _rename_noreplace
from .manifest import validate_manifest
from .models import CLASSIFICATION, emit_event
from .pinned_runtime import verify_after_run
from .preflight import HARD_PEAK_BYTES, collect_preflight
from .receipts import (
    _tree_digest,
    result_tree_manifest,
    scan_closed_result,
    seal_receipt,
)
from .runtime_binding import validate_pinned_receipt_binding
from .scorer_owner import (
    audit_d_test_namespace,
    seal_prediction_result,
    tep_scorer_owner_from_manifest,
)
from .trace import LifecycleTraceRecorder, validate_trace_prefix


def durable_tree_sync(root: Path) -> None:
    """Fsync every regular file and directory in a tree, failing closed."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("TREE_DURABILITY_UNPROVEN")
    directories: list[Path] = []

    def walk(directory: Path) -> None:
        try:
            directory_stat = os.lstat(directory)
        except OSError as exc:
            raise RuntimeError("TREE_DURABILITY_UNPROVEN") from exc
        if not stat.S_ISDIR(directory_stat.st_mode) or (
            getattr(directory_stat, "st_file_attributes", 0) & 0x400
        ):
            raise RuntimeError("TREE_DURABILITY_UNPROVEN")
        directories.append(directory)
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise RuntimeError("TREE_DURABILITY_UNPROVEN") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError("TREE_DURABILITY_UNPROVEN") from exc
            if entry.is_symlink() or (
                getattr(entry_stat, "st_file_attributes", 0) & 0x400
            ):
                raise RuntimeError("TREE_DURABILITY_UNPROVEN")
            if stat.S_ISDIR(entry_stat.st_mode):
                walk(path)
            elif stat.S_ISREG(entry_stat.st_mode):
                try:
                    access = os.O_RDWR if os.name == "nt" else os.O_RDONLY
                    flags = access | getattr(os, "O_NOFOLLOW", 0)
                    fd = os.open(path, flags | getattr(os, "O_BINARY", 0))
                    try:
                        _fsync_regular_file(fd)
                    finally:
                        os.close(fd)
                except OSError as exc:
                    raise RuntimeError("TREE_DURABILITY_UNPROVEN") from exc
            else:
                raise RuntimeError("TREE_DURABILITY_UNPROVEN")

    walk(root)
    try:
        for directory in reversed(directories):
            _fsync_dir(directory)
        _fsync_dir(root.parent)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("TREE_DURABILITY_UNPROVEN") from exc


def _fsync_regular_file(fd: int) -> None:
    if os.name != "nt":
        os.fsync(fd)
        return
    import ctypes
    import msvcrt

    handle = msvcrt.get_osfhandle(fd)
    if handle == -1:
        raise OSError("invalid file handle")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel32.FlushFileBuffers(handle):
        raise OSError(ctypes.get_last_error(), "FlushFileBuffers failed")


def _seal_result_directory(source: Path, destination: Path, lock: ResearchLock) -> None:
    if not lock._owns():
        raise RuntimeError("RESULT_SEAL_LOCK_NOT_OWNED")
    _rename_noreplace(source, destination)


def _validate_preflight_binding(manifest: dict[str, Any]) -> None:
    validate_pinned_receipt_binding(manifest)
    evidence = manifest.get("preflight_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("PREFLIGHT_BINDING_MISSING")
    if sha256_hex(canonical_bytes(evidence)) != manifest.get(
        "preflight_evidence_sha256"
    ):
        raise ValueError("PREFLIGHT_BINDING_MISMATCH")
    bindings = {
        "prepared_manifest_sha256": manifest.get("prepared_manifest_sha256"),
        "controller_nonce": manifest.get("controller_nonce"),
        "formal_snapshot_sha256": manifest.get("formal_snapshot_sha256"),
        "gpu_policy": manifest.get("gpu_policy"),
    }
    if any(evidence.get(key) != value for key, value in bindings.items()):
        raise ValueError("PREFLIGHT_BINDING_MISMATCH")


def _publish_receipt_new(path: Path, receipt: dict[str, Any]) -> None:
    publish_json_new(path, receipt)


def _capacity_probe_kwargs(
    evidence: dict[str, Any], *, fixture_only: bool
) -> dict[str, int]:
    """Recover sealed capacity inputs without resetting the segment baseline."""
    if fixture_only:
        return {}
    if evidence.get("capacity_measurement_status") != "MEASURED":
        raise ValueError("PREFLIGHT_CAPACITY_UNAVAILABLE")
    unavailable = evidence.get("capacity_unavailable_fields", [])
    if unavailable:
        raise ValueError("PREFLIGHT_CAPACITY_UNAVAILABLE")
    baseline = evidence.get("filesystem_baseline_bytes")
    owned_external = evidence.get("owned_external_layers_bytes")
    trusted_open_deleted = evidence.get("open_deleted_bytes")
    values = (baseline, owned_external, trusted_open_deleted)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in values
    ):
        raise ValueError("PREFLIGHT_CAPACITY_UNAVAILABLE")
    return {
        "filesystem_baseline_bytes": baseline,
        "owned_external_layers_bytes": owned_external,
        "trusted_open_deleted_bytes": trusted_open_deleted,
    }


CAPACITY_SAMPLE_INTERVAL_SECONDS = 5.0


def _run_post_prediction_scorer(
    *,
    manifest: dict[str, Any],
    output: Path,
    remote_run_root: Path,
    adapter_id: str,
) -> tuple[dict[str, Any], Any | None]:
    """Seal method output, then write truth outside the archivable result tree."""
    if adapter_id != "tep_nonconfirmatory_v1":
        return (
            {
                "status": "NOT_APPLICABLE",
                "scientific_eligible": False,
                "failure_code": None,
                "excluded_from_result_tree": True,
                "ephemeral": True,
                "d_test_namespace_touched": False,
            },
            None,
        )
    method_result_path = output / "tep_result.json"
    prediction_receipt = seal_prediction_result(
        bundle_id=manifest["run_id"],
        method_result_path=method_result_path,
    )
    method_result = json.loads(method_result_path.read_text(encoding="utf-8"))
    expected_count = method_result.get("method_event_count")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 1
    ):
        raise ValueError("METHOD_EVENT_COUNT_UNAVAILABLE")
    namespace = (
        remote_run_root / ".scorer-only-ephemeral" / manifest["run_id"]
    ).resolve()
    d_test_namespace_touched = audit_d_test_namespace(
        output, remote_run_root, namespace
    )
    namespace.mkdir(parents=True, exist_ok=False)
    status: dict[str, Any]
    try:
        owner = tep_scorer_owner_from_manifest(manifest)
        truth_bundle = owner.seal_after_prediction(
            prediction_receipt=prediction_receipt,
            method_result_path=method_result_path,
            expected_count=expected_count,
        )
        publish_json_new(
            namespace / "scorer_truth_bundle.json",
            {
                "prediction_seal_receipt": prediction_receipt.to_canonical_payload(),
                "truth_bundle": truth_bundle.to_canonical_payload(),
                "excluded_from_result_tree": True,
                "ephemeral": True,
                "d_test_namespace_touched": d_test_namespace_touched,
            },
        )
        status = {
            "status": "SEALED",
            "scientific_eligible": True,
            "failure_code": None,
            "truth_content_sha256": truth_bundle.content_sha256,
            "prediction_seal_self_hash": prediction_receipt.self_hash,
            "excluded_from_result_tree": True,
            "ephemeral": True,
            "d_test_namespace_touched": d_test_namespace_touched,
        }
    except (OSError, TypeError, ValueError) as exc:
        failure_code = (
            "SCORER_TRUTH_ALIGNMENT_INVALID"
            if str(exc) == "SCORER_TRUTH_BUNDLE_ALIGNMENT_INVALID"
            else "SCORER_TRUTH_SEAL_FAILED"
        )
        failure = {
            "bundle_id": manifest["run_id"],
            "status": "SCORER_FAILED",
            "failure_code": failure_code,
            "prediction_seal_self_hash": prediction_receipt.self_hash,
            "prediction_seal_receipt": prediction_receipt.to_canonical_payload(),
            "excluded_from_result_tree": True,
            "ephemeral": True,
            "d_test_namespace_touched": d_test_namespace_touched,
        }
        publish_json_new(namespace / "scorer_failure.json", failure)
        status = {
            key: failure[key]
            for key in (
                "status",
                "failure_code",
                "prediction_seal_self_hash",
                "excluded_from_result_tree",
                "ephemeral",
                "d_test_namespace_touched",
            )
        }
        status["scientific_eligible"] = False
    prediction_receipt.validate(method_result_path)
    return status, prediction_receipt


def _gpu_allocation_verdict(
    before: dict[str, Any],
    post: dict[str, Any],
    *,
    fixture_only: bool,
    samples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prove execution did not add a GPU process or the worker itself."""
    if fixture_only:
        return {"status": "NOT_APPLICABLE", "new_pids": [], "worker_pid": os.getpid()}
    before_rows = before.get("gpu_process_snapshot")
    post_rows = post.get("gpu_process_snapshot")
    if before_rows is None and post_rows is None and "gpu_probe_status" not in post:
        return {"status": "LEGACY_FIXTURE", "new_pids": [], "worker_pid": os.getpid()}
    if not isinstance(before_rows, list) or not isinstance(post_rows, list):
        raise ValueError("PREFLIGHT_GPU_PROCESS_SNAPSHOT_UNAVAILABLE")

    def pids(rows: list[Any]) -> set[int]:
        result: set[int] = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("pid"), int):
                raise ValueError("PREFLIGHT_GPU_PROCESS_SNAPSHOT_INVALID")
            result.add(row["pid"])
        return result

    before_pids = pids(before_rows)
    snapshots = [post, *(samples or [])]
    observed_pids = [pids(item["gpu_process_snapshot"]) for item in snapshots]
    new_pids = sorted(
        set().union(*(current - before_pids for current in observed_pids))
    )
    worker_pid = os.getpid()
    if new_pids or any(worker_pid in current for current in observed_pids):
        raise ValueError("SAFE_HALT_GPU_ALLOCATION")
    return {
        "status": "PASS",
        "new_pids": new_pids,
        "worker_pid": worker_pid,
        "before_pids": sorted(before_pids),
        "after_pids": sorted(observed_pids[-1]),
        "sample_count": len(observed_pids),
    }


def run_worker(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str | None = None,
    expected_runtime_binding: dict[str, str] | None = None,
    trace_prefix: str | Path | None = None,
    trace_prefix_sha256: str | None = None,
) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    manifest_bytes = path.read_bytes()
    prefix_payload: dict[str, Any] | None = None
    trace_recorder: LifecycleTraceRecorder | None = None
    if (trace_prefix is None) != (trace_prefix_sha256 is None):
        raise ValueError("TRACE_PREFIX_BINDING_MISSING")
    if trace_prefix is not None:
        prefix_path = Path(trace_prefix).resolve()
        prefix_bytes = prefix_path.read_bytes()
        if hashlib.sha256(prefix_bytes).hexdigest() != trace_prefix_sha256:
            raise ValueError("TRACE_PREFIX_HASH_MISMATCH")
        prefix_payload = json.loads(prefix_bytes.decode("utf-8"))
        validate_trace_prefix(
            prefix_payload["records"],
            run_id=prefix_payload["run_id"],
            approved_remote_parent=prefix_payload["approved_remote_parent"],
            remote_run_root=prefix_payload["remote_run_root"],
        )
    if (
        expected_manifest_sha256 is not None
        and hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256
    ):
        raise ValueError("EXECUTION_MANIFEST_HASH_MISMATCH")
    raw = json.loads(manifest_bytes.decode("utf-8"))
    if raw.get("execution_protocol_id") == "RFB_MME_V1_EXACT27_LOCAL":
        raise ValueError("BLOCKED_MME_V1_WORKER_ENTRY_FORBIDDEN")
    try:
        manifest = validate_manifest(raw)
    except Exception:
        run_id = ""
        try:
            candidate = json.loads(path.read_text(encoding="utf-8")).get("run_id", "")
            if (
                isinstance(candidate, str)
                and candidate
                and Path(candidate).name == candidate
            ):
                run_id = candidate
        except Exception:
            pass
        if run_id:
            receipt = seal_receipt(
                {
                    "run_id": run_id,
                    "terminal_state": "FAILED",
                    "failure_code": "MANIFEST_INVALID",
                    "directory_durable": True,
                    "formal_artifacts_created": [],
                    "shk001b_started": False,
                    "result_tree_sha256": "0" * 64,
                    "receipt_self_hash": "0" * 64,
                }
            )
            _publish_receipt_new(
                path.parent / f"{run_id}.REMOTE_EXECUTION_RECEIPT.json", receipt
            )
            return receipt
        raise ValueError("MANIFEST_INVALID") from None
    if prefix_payload is not None and any(
        prefix_payload.get(key) != manifest.get(key)
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
        )
    ):
        raise ValueError("TRACE_PREFIX_BINDING_MISMATCH")
    if prefix_payload is not None:
        trace_recorder = LifecycleTraceRecorder.from_records(
            run_id=prefix_payload["run_id"],
            approved_remote_parent=prefix_payload["approved_remote_parent"],
            remote_run_root=prefix_payload["remote_run_root"],
            records=prefix_payload["records"],
        )
        trace_recorder.append(
            input_hashes={
                "staged_execution_manifest": hashlib.sha256(manifest_bytes).hexdigest()
            },
            output_hashes={
                "verified_manifest_bytes": hashlib.sha256(manifest_bytes).hexdigest()
            },
        )
    if expected_runtime_binding is not None and any(
        manifest.get(key) != value for key, value in expected_runtime_binding.items()
    ):
        raise ValueError("RUNTIME_ARGV_BINDING_MISMATCH")
    run_id = manifest.get("run_id", "")
    if (
        not isinstance(run_id, str)
        or not run_id
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
    ):
        raise ValueError("invalid run_id")
    remote_root = manifest.get("remote_run_root")
    if (
        not isinstance(remote_root, str)
        or not Path(remote_root).is_absolute()
        or ".." in Path(remote_root).parts
        or (os.name != "nt" and PureWindowsPath(remote_root).is_absolute())
    ):
        raise ValueError("controller-bound absolute remote_root required")
    if Path(remote_root).is_symlink():
        raise ValueError("controller-bound absolute remote_root required")
    approved_parent = manifest.get("approved_remote_parent")
    if (
        not isinstance(approved_parent, str)
        or not Path(approved_parent).is_absolute()
        or ".." in Path(approved_parent).parts
        or (os.name != "nt" and PureWindowsPath(approved_parent).is_absolute())
    ):
        raise ValueError("controller-bound absolute approved_remote_parent required")
    if Path(approved_parent).is_symlink():
        raise ValueError("controller-bound absolute approved_remote_parent required")
    parent = Path(approved_parent).resolve()
    root = Path(remote_root).resolve()
    if parent != root and parent not in root.parents:
        raise ValueError("remote_run_root outside approved_remote_parent")
    manifest_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    started_at = datetime.now(UTC).isoformat()
    sealed = root / f"{run_id}.results"
    output = root / f"{run_id}.results.partial"
    receipt_path = root / f"{run_id}.REMOTE_EXECUTION_RECEIPT.json"
    if any(
        candidate.exists() or candidate.is_symlink()
        for candidate in (sealed, output, receipt_path)
    ):
        raise ValueError("RUN_ID_REPLAY")
    lock = ResearchLock(
        parent,
        manifest_sha256,
        run_id=run_id,
        remote_run_root=root,
        controller_nonce=manifest.get("controller_nonce"),
    ).acquire()
    if trace_recorder is not None:
        trace_recorder.append(
            input_hashes={"execution_manifest": manifest_sha256},
            output_hashes={
                "parent_wide_lock": sha256_hex(canonical_bytes(lock.record or {}))
            },
        )
    lock.start_heartbeat()
    try:
        validate_adapter_contract(manifest)
        _validate_preflight_binding(manifest)
        spec = resolve_adapter(manifest["adapter_id"])
        before = manifest["preflight_evidence"]
        if Path(before.get("root", "")).resolve() != root:
            raise ValueError("PREFLIGHT_STALE:root")
        capacity_probe_kwargs = _capacity_probe_kwargs(
            before, fixture_only=spec.fixture_only
        )
        launch = collect_preflight(
            root,
            dataset_root=manifest.get("dataset_root"),
            fixture_only=spec.fixture_only or not manifest.get("dataset_root"),
            manifest=manifest,
            **capacity_probe_kwargs,
        )
        if (
            not spec.fixture_only
            and "gpu_probe_status" in launch
            and launch.get("gpu_probe_status") != "OBSERVED_NOT_USED"
        ):
            raise ValueError("PREFLIGHT_GPU_PROBE_UNAVAILABLE")
        for field in (
            "hostname",
            "mount_identity",
            "source_tree_sha256",
            "package_inventory_sha256",
            "config_sha256",
            "input_manifest_sha256",
            "dataset_manifest_sha256",
            "dataset_manifest_verified",
            "gpu_policy",
            "gpu_identity",
        ):
            if launch.get(field) != before.get(field):
                raise ValueError(f"PREFLIGHT_STALE:{field}")
        if trace_recorder is not None:
            trace_recorder.append(
                input_hashes={"full_preflight": manifest["preflight_evidence_sha256"]},
                output_hashes={"launch_recheck": sha256_hex(canonical_bytes(launch))},
            )
        if not spec.fixture_only and (
            not launch.get("capacity_available")
            or not launch.get("dataset_manifest_verified")
            or launch.get("capacity_state") != "PLANNED"
        ):
            raise ValueError("PREFLIGHT_STALE:critical_state")
        capacity_samples: list[dict[str, Any]] = []
        capacity_failure: list[str] = []
        stop_sampling = threading.Event()

        def sample_capacity() -> None:
            while not stop_sampling.wait(CAPACITY_SAMPLE_INTERVAL_SECONDS):
                try:
                    sample = collect_preflight(
                        root,
                        dataset_root=manifest.get("dataset_root"),
                        fixture_only=False,
                        manifest=manifest,
                        **{**capacity_probe_kwargs, "trusted_open_deleted_bytes": None},
                    )
                    if sample.get("capacity_measurement_status") != "MEASURED":
                        raise ValueError("PREFLIGHT_CAPACITY_UNAVAILABLE")
                    peak = sample.get("capacity_peak_bytes")
                    if sample.get("capacity_state") != "PLANNED":
                        raise ValueError("CAPACITY_STATE_NOT_SAFE")
                    if not isinstance(peak, int) or peak > HARD_PEAK_BYTES:
                        raise ValueError("SAFE_HALT_CAP_BREACH")
                    capacity_samples.append(sample)
                except Exception as exc:  # fail closed; surfaced by owner thread
                    capacity_failure.append(str(exc))
                    stop_sampling.set()
                    return

        sampler = threading.Thread(
            target=sample_capacity,
            name=f"rfb-capacity-sampler-{run_id}",
            daemon=False,
        )
        sampler.start()
        execution_error: list[BaseException] = []

        def execute_adapter() -> None:
            try:
                spec.execute(manifest, output)
            except BaseException as exc:  # preserve adapter failure semantics
                execution_error.append(exc)

        # Enforce CPU-only policy for the actual adapter, including transports
        # that invoke this worker in-process rather than through a shell.
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        executor = threading.Thread(
            target=execute_adapter,
            name=f"rfb-adapter-{run_id}",
            daemon=False,
        )
        executor.start()
        executor.join()
        stop_sampling.set()
        sampler.join()
        if execution_error:
            raise execution_error[0]
        if capacity_failure:
            raise ValueError(capacity_failure[0])
        scorer_status, prediction_seal_receipt = _run_post_prediction_scorer(
            manifest=manifest,
            output=output,
            remote_run_root=root,
            adapter_id=spec.adapter_id,
        )
        post = collect_preflight(
            root,
            dataset_root=manifest.get("dataset_root"),
            fixture_only=spec.fixture_only or not manifest.get("dataset_root"),
            manifest=manifest,
            **{**capacity_probe_kwargs, "trusted_open_deleted_bytes": None},
        )
        gpu_allocation = _gpu_allocation_verdict(
            launch,
            post,
            fixture_only=spec.fixture_only,
            samples=capacity_samples,
        )
        if (
            not spec.fixture_only
            and post.get("capacity_measurement_status") != "MEASURED"
        ):
            raise ValueError("PREFLIGHT_CAPACITY_UNAVAILABLE")
        if not spec.fixture_only and post.get("capacity_state") != "PLANNED":
            raise ValueError("CAPACITY_STATE_NOT_SAFE")
        if (
            post.get("capacity_peak_bytes") is not None
            and post["capacity_peak_bytes"] > HARD_PEAK_BYTES
        ):
            raise ValueError("SAFE_HALT_CAP_BREACH")
        if manifest.get("runtime_dependency_profile") == "tep_nonconfirmatory_v1":
            pinned = manifest.get("pinned_runtime_manifest")
            pinned_root = manifest.get("pinned_runtime_root")
            if not isinstance(pinned, dict) or not isinstance(pinned_root, str):
                raise ValueError("PINNED_RUNTIME_BINDING_MISSING")
            verify_after_run(pinned, pinned_root)
        for field in (
            "hostname",
            "mount_identity",
            "source_tree_sha256",
            "package_inventory_sha256",
            "config_sha256",
            "input_manifest_sha256",
            "dataset_manifest_sha256",
            "dataset_manifest_verified",
            "gpu_policy",
            "gpu_identity",
        ):
            if post.get(field) != launch.get(field):
                raise ValueError(f"PREFLIGHT_POST_DRIFT:{field}")
        if not spec.fixture_only and (
            not post.get("capacity_available")
            or not post.get("dataset_manifest_verified")
        ):
            raise ValueError("PREFLIGHT_POST_DRIFT:critical_state")
        post_hash = sha256_hex(canonical_bytes(post))
        peak_fields = (
            "capacity_peak_bytes",
            "project_tree_allocated_bytes",
            "filesystem_used_delta_bytes",
            "owned_external_layers_bytes",
            "open_deleted_bytes",
        )
        if not all(field in launch and field in post for field in peak_fields):
            if not spec.fixture_only:
                raise ValueError("PREFLIGHT_CAPACITY_UNAVAILABLE")
            measured_resource_peaks = None
        else:
            observations = [launch, *capacity_samples, post]
            measured_peak = max(
                int(item["capacity_peak_bytes"]) for item in observations
            )
            measured_resource_peaks = {
                "project_tree_allocated_bytes": max(
                    item["project_tree_allocated_bytes"] for item in observations
                ),
                "filesystem_used_delta_bytes": max(
                    item["filesystem_used_delta_bytes"] for item in observations
                ),
                "owned_external_layers_bytes": max(
                    item["owned_external_layers_bytes"] for item in observations
                ),
                "open_deleted_bytes": max(
                    item["open_deleted_bytes"] for item in observations
                ),
                "observed_peak_bytes": measured_peak,
                "measurement_source": "worker_launch_samples_post_preflight",
            }
        if trace_recorder is not None:
            trace_recorder.append(
                input_hashes={"launch_recheck": sha256_hex(canonical_bytes(launch))},
                output_hashes={"adapter_post_recheck": post_hash},
            )
        if prediction_seal_receipt is not None:
            prediction_seal_receipt.validate(output / "tep_result.json")
        scan_closed_result(output)
        expected = (
            {"tep_result.json"}
            if spec.adapter_id == "tep_nonconfirmatory_v1"
            else {"adapter_result.json"}
        )
        entries = result_tree_manifest(output, allowlist=expected)
        if set(entries) != expected:
            raise ValueError("RESULT_ALLOWLIST_MISMATCH")
        if sealed.exists() or sealed.is_symlink():
            raise ValueError("RUN_ID_REPLAY")
        try:
            _seal_result_directory(output, sealed, lock)
        except OSError as exc:
            if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise ValueError("RUN_ID_REPLAY") from exc
            raise RuntimeError("RESULT_SEAL_ATOMICITY_UNSUPPORTED") from exc
        try:
            durable_tree_sync(sealed)
        except RuntimeError as exc:
            raise RuntimeError("RESULT_SEAL_DURABILITY_UNPROVEN") from exc
        tree_hash = _tree_digest(result_tree_manifest(sealed))
        if trace_recorder is not None:
            trace_recorder.append(
                input_hashes={"adapter_post_recheck": post_hash},
                output_hashes={"sealed_result_tree": tree_hash},
            )
        emitted = emit_event(kind="RESULT_SEALED_REMOTE", payload={"run_id": run_id})
        serializable_event = {
            **{key: emitted[key] for key in emitted if key != "payload"},
            "payload": dict(emitted["payload"]),
        }
        argv_digest = hashlib.sha256(
            json.dumps(spec.fixed_argv(path), separators=(",", ":")).encode()
        ).hexdigest()
        base = {
            "run_id": run_id,
            "execution_manifest_sha256": manifest_sha256,
            "prepared_manifest_sha256": manifest.get(
                "prepared_manifest_sha256", manifest_sha256
            ),
            "preflight_evidence_sha256": manifest.get("preflight_evidence_sha256"),
            "preflight_after_sha256": post_hash,
            "formal_snapshot_sha256": manifest.get("formal_snapshot_sha256"),
            "controller_nonce": manifest.get("controller_nonce"),
            "started_at_utc": started_at,
            "ended_at_utc": datetime.now(UTC).isoformat(),
            "exit_code": 0,
            "hostname": os.uname().nodename
            if hasattr(os, "uname")
            else os.environ.get("COMPUTERNAME", "unknown"),
            "root_identity": str(root),
            "approved_remote_parent": manifest["approved_remote_parent"],
            "remote_run_root": manifest["remote_run_root"],
            "mount_identity": manifest.get("preflight_evidence", {}).get(
                "mount_identity", "unknown"
            ),
            "gpu_policy": manifest.get("gpu_policy", "cpu_only"),
            "gpu_identity": manifest.get("preflight_evidence", {}).get(
                "gpu_identity", "CPU_ONLY"
            ),
            "resource_peaks": {
                **(measured_resource_peaks or {}),
                "sample_count": len(capacity_samples) + 2,
                "sample_peak_bytes": max(
                    [
                        int(launch["capacity_peak_bytes"]),
                        int(post["capacity_peak_bytes"]),
                        *(
                            int(item["capacity_peak_bytes"])
                            for item in capacity_samples
                        ),
                    ]
                    if measured_resource_peaks is not None
                    else [0]
                ),
                "filesystem_used_bytes_before": before["filesystem_used_bytes"],
                "filesystem_used_bytes_after": post["filesystem_used_bytes"],
                "filesystem_free_bytes_min": min(
                    before["filesystem_free_bytes"], post["filesystem_free_bytes"]
                ),
            },
            "pre_post_hashes": {
                "source": {
                    "before": before["source_tree_sha256"],
                    "after": post["source_tree_sha256"],
                },
                "config": {
                    "before": before["config_sha256"],
                    "after": post["config_sha256"],
                },
                "input_manifest": {
                    "before": before["input_manifest_sha256"],
                    "after": post["input_manifest_sha256"],
                },
                "dataset_manifest": {
                    "before": before["dataset_manifest_sha256"],
                    "after": post["dataset_manifest_sha256"],
                },
                "packages": {
                    "before": before["package_inventory_sha256"],
                    "after": post["package_inventory_sha256"],
                },
                "owned_processes": {
                    "before": before["owned_process_snapshot_sha256"],
                    "after": post["owned_process_snapshot_sha256"],
                },
                "foreign_processes": {
                    "before": before["foreign_process_snapshot_sha256"],
                    "after": post["foreign_process_snapshot_sha256"],
                },
                "gpu_inventory": {
                    "before": before["gpu_inventory_sha256"],
                    "after": post["gpu_inventory_sha256"],
                },
                "gpu_processes": {
                    "before": before["gpu_process_snapshot_sha256"],
                    "after": post["gpu_process_snapshot_sha256"],
                },
                "adapter": {
                    "before": spec.implementation_sha256,
                    "after": spec.implementation_sha256,
                },
                "argv": {"before": argv_digest, "after": argv_digest},
                "result_manifest": {"after": tree_hash},
            },
            "terminal_state": "RESULT_SEALED_REMOTE",
            "failure_code": None,
            "gpu_allocation": gpu_allocation,
            "adapter_id": spec.adapter_id,
            "adapter_implementation_sha256": spec.implementation_sha256,
            "fixed_argv_digest": argv_digest,
            "minimal_environment_digest": hashlib.sha256(
                json.dumps(spec.minimal_environment(root=root), sort_keys=True).encode()
            ).hexdigest(),
            "remote_result_tree_sha256": tree_hash,
            "result_tree_sha256": tree_hash,
            "receipt_self_hash": "0" * 64,
            "directory_durable": True,
            "shk001b_started": False,
            "result_path": str(sealed),
            "formal_artifacts_created": [],
            "gate_checklist_mutated": False,
            "scorer_artifact": scorer_status,
            "events": [serializable_event],
        }
        for key in (
            "runtime_format",
            "runtime_path",
            "runtime_file_sha256",
            "runtime_source_sha256",
            "runtime_manifest_sha256",
            "runtime_dependency_profile",
            "pinned_runtime_manifest_sha256",
            "pinned_runtime_closure_fingerprint",
        ):
            if key in manifest:
                base[key] = manifest[key]
        if trace_recorder is not None:
            receipt_body_proof = sha256_hex(
                canonical_bytes(
                    {k: v for k, v in base.items() if k != "receipt_self_hash"}
                )
            )
            trace_recorder.append(
                input_hashes={"sealed_result_tree": tree_hash},
                output_hashes={"authoritative_remote_receipt_body": receipt_body_proof},
            )
            base["lifecycle_trace_records"] = trace_recorder.records
            base["lifecycle_trace_head_sha256"] = trace_recorder.records[-1][
                "trace_hash"
            ]
        base["receipt_self_hash"] = sha256_hex(
            canonical_bytes(
                {
                    k: v
                    for k, v in base.items()
                    if k not in {"receipt_self_hash", *CLASSIFICATION}
                }
            )
        )
        receipt = seal_receipt(base)
        _publish_receipt_new(receipt_path, receipt)
        persisted_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if persisted_receipt != receipt:
            raise RuntimeError("REMOTE_RECEIPT_READBACK_MISMATCH")
        receipt_hash = sha256_hex(canonical_bytes(persisted_receipt))
        tomb = lock.release_owned()
        tomb_hash = hashlib.sha256(tomb.read_bytes()).hexdigest()
        release_proof = {
            "schema_version": "r005-lock-release-proof.v1",
            "run_id": run_id,
            "authoritative_remote_receipt_sha256": receipt_hash,
            "lock_release_tombstone_sha256": tomb_hash,
        }
        if trace_recorder is not None:
            release_record = trace_recorder.append(
                input_hashes={"authoritative_remote_receipt": receipt_hash},
                output_hashes={"lock_release_tombstone": tomb_hash},
            )
            release_proof["lifecycle_trace_record"] = release_record
        release_proof["self_hash"] = sha256_hex(canonical_bytes(release_proof))
        publish_json_new(root / f"{run_id}.LOCK_RELEASE_PROOF.json", release_proof)
        persisted_proof = json.loads(
            (root / f"{run_id}.LOCK_RELEASE_PROOF.json").read_text(encoding="utf-8")
        )
        if persisted_proof != release_proof:
            raise RuntimeError("LOCK_RELEASE_PROOF_READBACK_MISMATCH")
        return persisted_receipt
    except Exception as exc:
        receipt = seal_receipt(
            {
                "run_id": run_id,
                "terminal_state": "FAILED",
                "failure_code": type(exc).__name__,
                "error": "worker failure",
                "adapter_id": manifest.get("adapter_id"),
            }
        )
        if not receipt_path.exists():
            _publish_receipt_new(receipt_path, receipt)
        raise
    finally:
        lock.stop_heartbeat()
        if lock._owns():
            try:
                lock.release_owned()
            except Exception as cleanup_exc:
                # Never turn a nominal success into an unverified success.  If
                # an execution exception is already active, retain it as the
                # primary cause. Never rewrite an already sealed receipt.
                if sys.exc_info()[0] is None:
                    raise RuntimeError(
                        "LOCK_RELEASE_DURABILITY_UNPROVEN"
                    ) from cleanup_exc
                # A primary execution exception is already propagating; retain
                # it and leave the lock for verified stale-proof handling.
