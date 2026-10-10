"""Local controller API and two-copy verification for research runs."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

from .adapters import resolve_adapter, validate_adapter_contract
from .files import _fsync_dir, publish_json_new
from .lock import _rename_noreplace
from .manifest import validate_manifest
from .preflight import manifest_hashes
from .receipts import (
    _tree_digest,
    reopen_validate_final_receipt,
    reopen_validate_remote_receipt,
    require_remote_scorer_ready_for_final,
    result_tree_manifest,
    seal_receipt,
    validate_copy_verification,
    validate_final_receipt,
    validate_remote_receipt,
)
from .runtime_binding import pinned_runtime_binding, runtime_binding_args
from .runtime_bundle import build_pinned_runtime_bundle, build_runtime_bundle
from .trace import LifecycleTraceRecorder, validate_trace, validate_trace_prefix
from .transport import FakeTransport, OpenSSHTransport
from .worker import durable_tree_sync


@dataclass(frozen=True)
class PreparedResearchRun:
    manifest: dict[str, Any]
    path: Path
    manifest_sha256: str

    @property
    def prepared_manifest_sha256(self) -> str:
        return self.manifest_sha256


def guard_mme_controller_entry(
    workspace_root: str | Path,
    *,
    operation: str,
    independent_blocks: int,
    dataset_split: str,
) -> None:
    if operation != "LOCAL_MME_V2":
        raise ValueError("MME_NONLOCAL_OPERATION")
    if dataset_split not in {"D_impl_unit", "D_development", "MME_v2"}:
        raise ValueError("MME_RUN_CLASS_INVALID")
    if type(independent_blocks) is not int or not 1 <= independent_blocks <= 27:
        raise ValueError("MME_BLOCK_COUNT_INVALID")
    if dataset_split == "MME_v2" and independent_blocks != 27:
        raise ValueError("MME_BLOCK_COUNT_INVALID")
    workspace = Path(workspace_root)
    if not workspace.is_dir():
        raise ValueError("MME_WORKSPACE_UNAVAILABLE")
    for parent in (workspace, *workspace.parents):
        if parent.is_symlink() or bool(
            getattr(parent.stat(), "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("MME_WORKSPACE_REPARSE_POINT")


def _reject_symlink_chain(path: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise ValueError("symlink/reparse path rejected")
        if current == current.parent:
            break
        current = current.parent


def _is_reparse_point(path: Path) -> bool:
    """Reject Windows junctions/reparse points in addition to symlinks."""
    if path.is_symlink():
        return True
    try:
        return bool(path.stat().st_file_attributes & 0x400)
    except (FileNotFoundError, OSError, AttributeError):
        return False


def _require_confined(path: Path, root: Path) -> Path:
    _reject_symlink_chain(path.absolute())
    _reject_symlink_chain(root.absolute())
    resolved = path.resolve()
    base = root.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("path outside controller-owned root")
    return resolved


def _normalize_remote_capability(value: str, approved: str | Path) -> str:
    raw = str(value)
    approved_raw = str(approved)
    raw_windows_absolute = PureWindowsPath(raw).is_absolute()
    approved_windows_absolute = PureWindowsPath(approved_raw).is_absolute()
    if raw_windows_absolute and approved_raw.startswith("/"):
        raise ValueError("mixed-platform remote capability rejected")
    if raw.startswith("/") and approved_windows_absolute:
        raise ValueError("mixed-platform remote capability rejected")
    if raw.startswith("/") or approved_raw.startswith("/"):
        candidate = PurePosixPath(raw)
        base = PurePosixPath(approved_raw)
        resolved = candidate if candidate.is_absolute() else base / candidate
        if (
            not base.is_absolute()
            or not resolved.is_absolute()
            or ".." in resolved.parts
        ):
            raise ValueError("remote capability must be absolute and confined")
        if resolved != base and base not in resolved.parents:
            raise ValueError("remote capability outside approved root")
        return str(resolved)
    if (
        PureWindowsPath(raw).is_absolute()
        or PureWindowsPath(approved_raw).is_absolute()
    ):
        candidate = Path(raw)
        base = Path(approved_raw).resolve()
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (base / candidate).resolve()
        )
        if resolved != base and base not in resolved.parents:
            raise ValueError("remote capability outside approved root")
        _reject_symlink_chain(resolved)
        return str(resolved)
    raise ValueError("remote capability must be absolute and confined")


def _derive_remote_run_root(
    approved_remote_parent: str | Path, run_id: str
) -> tuple[str, str]:
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("invalid run_id")
    raw = str(approved_remote_parent)
    if raw.startswith("/"):
        parent = PurePosixPath(raw)
        if not parent.is_absolute() or ".." in parent.parts:
            raise ValueError("approved remote parent must be absolute and confined")
        return str(parent), str(parent / run_id)
    if PureWindowsPath(raw).is_absolute():
        parent_path = Path(raw).absolute()
        _reject_symlink_chain(parent_path)
        parent = parent_path.resolve()
        return str(parent), str(parent / run_id)
    raise ValueError("approved remote parent must be absolute and confined")


def _formal_snapshot() -> dict[str, str | bool]:
    workspace = Path(__file__).resolve().parents[4]
    bench = Path(__file__).resolve().parents[3]
    named = [
        workspace / "GateChecklist-v6.13.json",
        workspace / "ExecutionPlan-Gates-v6.13.md",
        workspace / "FORMAL_STAGE_ADMISSION-v6.13.json",
        workspace / "CURRENT",
        bench / "CURRENT",
    ]
    snapshot: dict[str, str | bool] = {}
    for path in named:
        key = str(path.relative_to(workspace)).replace("\\", "/")
        snapshot[f"{key}:exists"] = path.exists()
        if path.is_file():
            snapshot[f"{key}:sha256"] = _file_sha256(path)
    outputs = bench / "outputs"
    if outputs.is_dir():
        for path in sorted(item for item in outputs.rglob("*") if item.is_file()):
            key = str(path.relative_to(workspace)).replace("\\", "/")
            snapshot[f"{key}:sha256"] = _file_sha256(path)
    return snapshot


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _formal_snapshot_sha256() -> str:
    return sha256_hex(canonical_bytes(_formal_snapshot()))


def _prepare_run_impl(
    manifest_path: str | Path,
    output: str | Path | None = None,
    *,
    approved_local_root: str | Path | None = None,
    approved_remote_parent: str | Path | None = None,
    approved_remote_root: str | Path | None = None,
    approved_dataset_root: str | Path | None = None,
    approved_pinned_runtime_root: str | Path | None = None,
    approved_pinned_runtime_manifest: str | Path | None = None,
    approved_expected_fingerprint: str | None = None,
    _legacy_entry: bool = False,
) -> PreparedResearchRun:
    raw_path = Path(manifest_path)
    if raw_path.is_symlink():
        raise ValueError("MANIFEST_SYMLINK_REJECTED")
    path = raw_path.resolve()
    raw_manifest = json.loads(path.read_text(encoding="utf-8"))
    protocol = raw_manifest.get("execution_protocol_id")
    if _legacy_entry:
        mme_fields = {
            "authorization_id",
            "authorization_request_id",
            "block_id",
            "attempt_id",
            "checkpoint_id",
            "execution_plan",
            "independent_blocks",
            "method_panel",
            "run_family",
        }
        if protocol not in {None, "RFB_RESEARCH_LEGACY_R006"} or mme_fields & set(
            raw_manifest
        ):
            raise RuntimeError("BLOCKED_MME_REQUIRES_DEDICATED_CONTROLLER")
        raw_manifest["execution_protocol_id"] = "RFB_RESEARCH_LEGACY_R006"
    elif protocol is None:
        raise ValueError("EXECUTION_PROTOCOL_REQUIRED")
    if raw_manifest["execution_protocol_id"] == "RFB_MME_V1_EXACT27_LOCAL":
        raise RuntimeError("BLOCKED_MME_REQUIRES_DEDICATED_CONTROLLER")
    if raw_manifest["execution_protocol_id"] != "RFB_RESEARCH_LEGACY_R006":
        raise ValueError("EXECUTION_PROTOCOL_UNSUPPORTED")
    validate_manifest(raw_manifest, phase="user_manifest")
    raw_manifest.setdefault("controller_nonce", secrets.token_hex(16))
    raw_manifest.setdefault("gpu_policy", "cpu_only")
    raw_manifest.setdefault("formal_snapshot_sha256", _formal_snapshot_sha256())
    exact_capacity_contract = {
        "planned_peak_bytes": 22_000_000_000,
        "drain_threshold_bytes": 24_000_000_000,
        "hard_peak_bytes": 25_000_000_000,
        "segment_start_free_min_bytes": 265_853_007_872,
        "remote_reserve_floor_bytes": 235_853_007_872,
        "subbudgets_bytes": {
            "ephemeral_dataset": 16_000_000_000,
            "durable_result_staging": 3_000_000_000,
            "scratch_partial": 2_000_000_000,
            "retry_quarantine_wal": 1_000_000_000,
            "emergency_reserve": 3_000_000_000,
        },
    }
    supplied_capacity = raw_manifest.get("resource_limits")
    if supplied_capacity not in (None, exact_capacity_contract):
        raise ValueError("CAPACITY_CONTRACT_MISMATCH")
    raw_manifest["resource_limits"] = exact_capacity_contract
    manifest = dict(raw_manifest)
    if Path(manifest["run_id"]).name != manifest["run_id"]:
        raise ValueError("invalid run_id")
    if approved_remote_parent is None and approved_remote_root is not None:
        approved_remote_parent = approved_remote_root
    if approved_remote_parent is not None:
        parent, run_root = _derive_remote_run_root(
            approved_remote_parent, manifest["run_id"]
        )
        manifest["approved_remote_parent"] = parent
        manifest["remote_run_root"] = run_root
    if approved_expected_fingerprint is not None:
        manifest["expected_fingerprint"] = approved_expected_fingerprint
    if (approved_pinned_runtime_root is None) != (
        approved_pinned_runtime_manifest is None
    ):
        raise ValueError("pinned runtime root and manifest must be supplied together")
    if approved_pinned_runtime_root is not None:
        root = Path(approved_pinned_runtime_root).resolve()
        _reject_symlink_chain(root)
        if not root.is_dir():
            raise ValueError("approved pinned runtime root required")
        manifest_path = Path(approved_pinned_runtime_manifest).resolve()
        _reject_symlink_chain(manifest_path)
        if not manifest_path.is_file():
            raise ValueError("approved pinned runtime manifest required")
        pinned_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        from .pinned_runtime import verify_controller_staging

        verify_controller_staging(pinned_manifest, root)
        manifest["pinned_runtime_root"] = str(root)
        manifest["pinned_runtime_manifest"] = pinned_manifest
        manifest["runtime_format"] = "python_pinned_venv_v1"
        manifest["runtime_dependency_profile"] = "tep_nonconfirmatory_v1"
        manifest["pinned_runtime_manifest_sha256"] = sha256_hex(
            canonical_bytes(pinned_manifest)
        )
        manifest["pinned_runtime_closure_fingerprint"] = pinned_manifest[
            "closure_fingerprint"
        ]
    manifest["manifest_phase"] = "prepared_manifest"
    for key in ("local_root", "local_results", "dataset_root"):
        if manifest.get(key):
            candidate = Path(manifest[key])
            if key == "dataset_root":
                approved = approved_dataset_root
            else:
                approved = approved_local_root
            if key == "dataset_root":
                if approved is None:
                    raise ValueError("controller-owned root required")
                manifest[key] = _normalize_remote_capability(
                    str(manifest[key]), approved
                )
                continue
            if approved is None and candidate.is_absolute():
                raise ValueError("controller-owned root required")
            if approved is not None:
                base = Path(approved).resolve()
                resolved = (
                    (base / candidate).resolve()
                    if not candidate.is_absolute()
                    else candidate.resolve()
                )
                if base not in resolved.parents and resolved != base:
                    raise ValueError("root outside approved controller root")
                _reject_symlink_chain(resolved)
                manifest[key] = str(resolved)
            elif candidate.exists():
                _reject_symlink_chain(candidate.resolve())
            if any(part in {".", ".."} for part in candidate.parts):
                raise ValueError("root path escape")
    if manifest.get("known_hosts"):
        known_hosts = Path(manifest["known_hosts"])
        if not known_hosts.is_absolute() or not known_hosts.is_file():
            raise ValueError("controller-owned known_hosts file required")
        _reject_symlink_chain(known_hosts.absolute())
        manifest["known_hosts"] = str(known_hosts.resolve())
    manifest = validate_manifest(manifest, phase="prepared_manifest")
    validate_adapter_contract(manifest)
    prepared_path = path
    if output or manifest != raw_manifest:
        output_path = (
            Path(output)
            if output is not None
            else path.parent / f".{manifest['run_id']}.prepared.manifest.json"
        )
        output_root = (
            Path(approved_local_root).resolve()
            if approved_local_root is not None
            else path.parent.resolve()
        )
        output_path = _require_confined(output_path, output_root)
        publish_json_new(output_path, manifest)
        prepared_path = output_path.resolve()
    digest = hashlib.sha256(prepared_path.read_bytes()).hexdigest()
    return PreparedResearchRun(manifest, prepared_path, digest)


def prepare_run(*args: Any, **kwargs: Any) -> PreparedResearchRun:
    """Strict entry for newly authored manifests; protocol is mandatory."""
    return _prepare_run_impl(*args, **kwargs)


def prepare_legacy_r006(*args: Any, **kwargs: Any) -> PreparedResearchRun:
    """Compatibility entry for frozen pre-protocol R006 research manifests."""
    return _prepare_run_impl(*args, **kwargs, _legacy_entry=True)


def _copy_tree(src: Path, dst: Path) -> str:
    if not src.is_dir() or dst.exists():
        raise ValueError("RESULT_COPY_INCOMPLETE")
    if _is_reparse_point(src) or any(
        _is_reparse_point(path) for path in src.rglob("*")
    ):
        raise ValueError("RESULT_COPY_SYMLINK_REJECTED")
    staging = dst.parent / f".{dst.name}.partial"
    if staging.exists():
        raise ValueError("RESULT_COPY_INCOMPLETE")
    shutil.copytree(src, staging)
    durable_tree_sync(staging)
    _rename_dir_new(staging, dst)
    durable_tree_sync(dst)
    h = hashlib.sha256()
    for path in sorted(x for x in dst.rglob("*") if x.is_file()):
        h.update(path.relative_to(dst).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def _publish_new_json(destination: Path, value: Any) -> str:
    return publish_json_new(destination, value)


def _proof_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def _confine_remote_artifact(
    value: str | Path | PurePosixPath,
    *,
    remote_run_root: Path | PurePosixPath,
    expected_relative: PurePosixPath,
    local_transport: bool,
) -> str:
    if local_transport:
        root = Path(remote_run_root).resolve()
        candidate = Path(value)
        if candidate.is_symlink():
            raise RuntimeError("REMOTE_ARTIFACT_SYMLINK_REJECTED")
        resolved = candidate.resolve()
        expected = (root / Path(*expected_relative.parts)).resolve()
        if resolved != expected or root not in resolved.parents:
            raise RuntimeError("REMOTE_ARTIFACT_CONFINEMENT_MISMATCH")
        return str(resolved)
    root = PurePosixPath(remote_run_root)
    candidate = PurePosixPath(value)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError("REMOTE_ARTIFACT_CONFINEMENT_MISMATCH")
    expected = root / expected_relative
    if candidate != expected or root not in candidate.parents:
        raise RuntimeError("REMOTE_ARTIFACT_CONFINEMENT_MISMATCH")
    return str(candidate)


def _rename_dir_new(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing an existing target."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("IMMUTABLE_RECEIPT_EXISTS")
    try:
        _rename_noreplace(source, destination)
    except FileExistsError as exc:
        raise ValueError("IMMUTABLE_RECEIPT_EXISTS") from exc


def _load_remote_receipt(result: Any, receipt_path: Path) -> dict[str, Any]:
    # The downloaded file is the authoritative remote publication.  Never
    # accept a symlink, directory, or a substitute stdout-only receipt here.
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("REMOTE_RECEIPT_PUBLICATION_INVALID")
    durable = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(durable, dict):
        raise ValueError("REMOTE_RECEIPT_PUBLICATION_INVALID")
    stdout = result.get("stdout", "")
    if isinstance(stdout, str) and stdout.startswith("{"):
        try:
            candidate = json.loads(stdout)
            if sha256_hex(canonical_bytes(candidate)) != sha256_hex(
                canonical_bytes(durable)
            ):
                raise ValueError("REMOTE_RECEIPT_STDOUT_MISMATCH")
        except json.JSONDecodeError:
            pass
    return durable


def execute_remote(
    prepared: PreparedResearchRun, transport: Any | None = None
) -> dict[str, Any]:
    if prepared.manifest.get("execution_protocol_id") == "RFB_MME_V1_EXACT27_LOCAL":
        raise RuntimeError("BLOCKED_MME_V1_REMOTE_FORBIDDEN")
    formal_before = _formal_snapshot()
    if sha256_hex(canonical_bytes(formal_before)) != prepared.manifest.get(
        "formal_snapshot_sha256"
    ):
        raise RuntimeError("FORMAL_SNAPSHOT_DRIFT")
    transport = transport or OpenSSHTransport(
        prepared.manifest["ssh_host"],
        Path(prepared.manifest["known_hosts"]),
        prepared.manifest.get("expected_fingerprint"),
        port=int(prepared.manifest.get("ssh_port", 22)),
    )
    if not hasattr(transport, "preflight"):
        raise RuntimeError("PREFLIGHT_UNSUPPORTED")
    if not prepared.manifest.get("approved_remote_parent") or not prepared.manifest.get(
        "remote_run_root"
    ):
        raise RuntimeError("CONTROLLER_CAPABILITY_BINDING_MISSING")
    approved_parent_value = str(prepared.manifest["approved_remote_parent"])
    expected_run_root_value = str(prepared.manifest["remote_run_root"])
    approved_remote_parent = (
        Path(approved_parent_value).resolve()
        if isinstance(transport, FakeTransport)
        else PurePosixPath(approved_parent_value)
    )
    expected_run_root = (
        Path(expected_run_root_value).resolve()
        if isinstance(transport, FakeTransport)
        else PurePosixPath(expected_run_root_value)
    )
    trace_recorder = LifecycleTraceRecorder(
        run_id=prepared.manifest["run_id"],
        approved_remote_parent=str(approved_remote_parent),
        remote_run_root=str(expected_run_root),
    )
    trace_recorder.append(
        input_hashes={"user_manifest": prepared.manifest_sha256},
        output_hashes={"prepared_manifest": prepared.manifest_sha256},
    )
    adapter = resolve_adapter(prepared.manifest["adapter_id"])
    pinned_binding = pinned_runtime_binding(prepared.manifest)
    if prepared.manifest.get("runtime_format") == "python_pinned_venv_v1":
        bundle = build_pinned_runtime_bundle(
            prepared.manifest["pinned_runtime_root"],
            prepared.manifest["pinned_runtime_manifest"],
            prepared.path.parent / ".runtime",
        )
    else:
        bundle = build_runtime_bundle(
            adapter.adapter_id, prepared.path.parent / ".runtime"
        )
    prepared_sha256 = prepared.manifest_sha256
    trace_recorder.append(
        input_hashes={"adapter": _proof_hash(adapter.adapter_id)},
        output_hashes={"runtime_bundle": bundle.file_sha256},
    )
    if not hasattr(transport, "bootstrap_parent_preflight"):
        raise RuntimeError("BOOTSTRAP_PREFLIGHT_UNSUPPORTED")
    bootstrap = transport.bootstrap_parent_preflight(
        approved_remote_parent=approved_remote_parent
    )
    bootstrap_hash = _proof_hash(bootstrap)
    trace_recorder.append(
        input_hashes={
            "expected_fingerprint": _proof_hash(
                prepared.manifest.get("expected_fingerprint")
            )
        },
        output_hashes={"host_key_verification": bootstrap_hash},
    )
    trace_recorder.append(
        input_hashes={"approved_parent": _proof_hash(str(approved_remote_parent))},
        output_hashes={"bootstrap_preflight": bootstrap_hash},
    )
    if (
        not bootstrap.get("capacity_available")
        or not bootstrap.get("remote_reserve_available")
        or not bootstrap.get("fingerprint_verified")
        or str(bootstrap.get("approved_remote_parent")) != str(approved_remote_parent)
    ):
        raise RuntimeError("BOOTSTRAP_PREFLIGHT_BLOCKED")
    if not hasattr(transport, "create_run_root"):
        raise RuntimeError("RUN_ROOT_CREATE_UNSUPPORTED")
    creation = transport.create_run_root(
        approved_remote_parent=approved_remote_parent,
        run_id=prepared.manifest["run_id"],
    )
    creation_hash = _proof_hash(creation.as_dict())
    trace_recorder.append(
        input_hashes={"bootstrap_preflight": bootstrap_hash},
        output_hashes={"run_root_creation": creation_hash},
    )
    remote_root_value = str(creation.remote_run_root)
    remote_root = (
        Path(remote_root_value).resolve()
        if isinstance(transport, FakeTransport)
        else PurePosixPath(remote_root_value)
    )
    if remote_root != expected_run_root:
        raise RuntimeError("RUN_ROOT_BINDING_MISMATCH")
    if (
        creation.parent_device != bootstrap.get("parent_device")
        or creation.parent_inode != bootstrap.get("parent_inode")
        or creation.mount_identity != bootstrap.get("mount_identity")
    ):
        raise RuntimeError("RUN_ROOT_PARENT_IDENTITY_DRIFT")
    if not hasattr(transport, "stage_runtime"):
        raise RuntimeError("RUNTIME_STAGE_UNSUPPORTED")
    runtime_path = transport.stage_runtime(bundle=bundle, remote_run_root=remote_root)
    if bundle.format == "python_pinned_venv_v1":
        relative_parts = PurePosixPath(bundle.interpreter_relative_path).parts
        if isinstance(transport, FakeTransport):
            materialized_root = (
                Path(runtime_path).resolve().parents[len(relative_parts) - 1]
            )
            expected_materialized = (
                Path(remote_root).resolve()
                / ".runtime"
                / f"{bundle.file_sha256}.pinned"
            )
        else:
            runtime_posix = PurePosixPath(str(runtime_path))
            materialized_root = runtime_posix.parents[len(relative_parts) - 1]
            expected_materialized = (
                PurePosixPath(str(remote_root))
                / ".runtime"
                / f"{bundle.file_sha256}.pinned"
            )
        if materialized_root != expected_materialized:
            raise RuntimeError("PINNED_RUNTIME_PATH_BINDING_MISMATCH")
    else:
        runtime_path = _confine_remote_artifact(
            runtime_path,
            remote_run_root=remote_root,
            expected_relative=PurePosixPath(".runtime") / bundle.remote_name,
            local_transport=isinstance(transport, FakeTransport),
        )
    trace_recorder.append(
        input_hashes={"runtime_bundle": bundle.file_sha256},
        output_hashes={"runtime_partial_upload": _proof_hash(str(runtime_path))},
    )
    trace_recorder.append(
        input_hashes={"runtime_partial_upload": _proof_hash(str(runtime_path))},
        output_hashes={"runtime_seal": bundle.file_sha256},
    )
    runtime_binding = {
        "runtime_format": bundle.format,
        "runtime_path": str(runtime_path),
        "runtime_file_sha256": bundle.file_sha256,
        "runtime_source_sha256": bundle.source_sha256,
        "runtime_manifest_sha256": bundle.manifest_sha256,
        "runtime_dependency_profile": (
            "tep_nonconfirmatory_v1"
            if bundle.format == "python_pinned_venv_v1"
            else "stdlib_only"
        ),
    }
    # Preserve the verified pinned closure hashes in every downstream object.
    # A pinned profile still cannot use the fixture zipapp and therefore never
    # reaches this branch; this guard prevents accidental silent downgrade if
    # a transport is changed in the future.
    if pinned_binding:
        runtime_binding.update(pinned_binding)
    pf = transport.preflight(
        root=remote_root,
        manifest_sha256=prepared.manifest_sha256,
        controller_nonce=prepared.manifest["controller_nonce"],
        formal_snapshot_sha256=prepared.manifest["formal_snapshot_sha256"],
        dataset_root=prepared.manifest.get("dataset_root"),
        fixture_only=adapter.fixture_only or not prepared.manifest.get("dataset_root"),
    )
    pf = {**pf, **runtime_binding}
    if pinned_binding:
        # The installed pinned worker re-probes against the research manifest.
        # Bind the controller's initial evidence to that same semantic input;
        # the portable zipapp uses its frozen runtime-manifest probe contract.
        pf.update(manifest_hashes(prepared.manifest))
    pf["fingerprint_verified"] = bool(bootstrap["fingerprint_verified"])
    if (
        not pf.get("capacity_available")
        or not pf.get("remote_reserve_available")
        or not pf.get("fingerprint_verified")
    ):
        raise RuntimeError("PREFLIGHT_BLOCKED")
    expected_bindings = {
        "prepared_manifest_sha256": prepared.manifest_sha256,
        "controller_nonce": prepared.manifest["controller_nonce"],
        "formal_snapshot_sha256": prepared.manifest["formal_snapshot_sha256"],
        "gpu_policy": prepared.manifest["gpu_policy"],
        "approved_remote_parent": str(approved_remote_parent),
        "remote_run_root": str(remote_root),
        **runtime_binding,
    }
    if any(pf.get(key) != value for key, value in expected_bindings.items()):
        raise RuntimeError("PREFLIGHT_BINDING_MISMATCH")
    observed_preflight_root = (
        Path(str(pf.get("root", ""))).resolve()
        if isinstance(transport, FakeTransport)
        else PurePosixPath(str(pf.get("root", "")))
    )
    if observed_preflight_root != remote_root:
        raise RuntimeError("PREFLIGHT_BINDING_MISMATCH")
    preflight_hash = sha256_hex(canonical_bytes(dict(pf)))
    trace_recorder.append(
        input_hashes={"runtime_seal": bundle.file_sha256},
        output_hashes={"full_preflight": preflight_hash},
    )
    execution_manifest = {
        **prepared.manifest,
        **runtime_binding,
        "manifest_phase": "execution_manifest",
        "prepared_manifest_sha256": prepared_sha256,
        "preflight_evidence": dict(pf),
        "preflight_evidence_sha256": preflight_hash,
        "run_root_creation_evidence": creation.as_dict(),
    }
    if pinned_binding:
        execution_manifest["pinned_runtime_root"] = str(materialized_root)
    validate_manifest(execution_manifest, phase="execution_manifest")
    execution_path = prepared.path.with_name(
        f".{prepared.manifest['run_id']}.execution.manifest.json"
    )
    publish_json_new(execution_path, execution_manifest)
    execution_sha256 = hashlib.sha256(execution_path.read_bytes()).hexdigest()
    trace_recorder.append(
        input_hashes={"full_preflight": preflight_hash},
        output_hashes={"execution_manifest": execution_sha256},
    )
    prepared = PreparedResearchRun(
        manifest=execution_manifest,
        path=execution_path.resolve(),
        manifest_sha256=execution_sha256,
    )
    if not hasattr(transport, "stage"):
        raise RuntimeError("STAGE_UNSUPPORTED")
    try:
        staged_manifest = transport.stage(
            manifest=prepared.path,
            remote_root=remote_root,
        )
    except Exception as exc:
        raise RuntimeError("EXECUTION_FAILED") from exc
    staged_manifest = _confine_remote_artifact(
        staged_manifest,
        remote_run_root=remote_root,
        expected_relative=PurePosixPath(execution_path.name),
        local_transport=isinstance(transport, FakeTransport),
    )
    trace_recorder.append(
        input_hashes={"execution_manifest": execution_sha256},
        output_hashes={"staged_execution_manifest": _proof_hash(staged_manifest)},
    )
    runtime_launch = (
        [str(runtime_path), "-B", "-I", "-m", "rfb.research", "worker"]
        if bundle.format == "python_pinned_venv_v1"
        else ["python3", "-I", "-S", str(runtime_path), "worker"]
    )
    fixed_argv = [
        *runtime_launch,
        "--manifest",
        str(staged_manifest),
        "--execution-manifest-sha256",
        prepared.manifest_sha256,
        "--runtime-file-sha256",
        bundle.file_sha256,
        "--runtime-source-sha256",
        bundle.source_sha256,
        "--runtime-manifest-sha256",
        bundle.manifest_sha256,
        "--runtime-dependency-profile",
        runtime_binding["runtime_dependency_profile"],
        "--runtime-path",
        str(runtime_path),
    ]
    if pinned_binding:
        fixed_argv.extend(
            runtime_binding_args({**runtime_binding, **pinned_binding})[10:]
        )
    if isinstance(transport, FakeTransport):
        launch_contract = fixed_argv
    else:
        remote_env = adapter.minimal_environment(root=remote_root)
        remote_env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        env_argv = ["env", "-i", *[f"{k}={v}" for k, v in sorted(remote_env.items())]]
        launch_contract = [*env_argv, *fixed_argv]
    trace_recorder.append(
        input_hashes={"staged_execution_manifest": execution_sha256},
        output_hashes={"fixed_argv": _proof_hash(launch_contract)},
    )
    trace_prefix = {
        "schema_version": "1.0.0-prefix",
        "run_id": prepared.manifest["run_id"],
        "approved_remote_parent": str(approved_remote_parent),
        "remote_run_root": str(remote_root),
        "execution_manifest_sha256": prepared.manifest_sha256,
        **{
            key: prepared.manifest[key]
            for key in (
                "execution_lane",
                "classification",
                "formal_gate_effect",
                "formal_admission_eligible",
                "shk001b_eligible",
                "contains_formal_claims",
            )
        },
        "records": trace_recorder.records,
        "trace_head_sha256": trace_recorder.records[-1]["trace_hash"],
    }
    trace_prefix_path = prepared.path.with_name(
        f".{prepared.manifest['run_id']}.lifecycle-trace-prefix.json"
    )
    trace_prefix_sha256 = publish_json_new(trace_prefix_path, trace_prefix)
    staged_trace_prefix = transport.stage(
        manifest=trace_prefix_path,
        remote_root=remote_root,
    )
    staged_trace_prefix = _confine_remote_artifact(
        staged_trace_prefix,
        remote_run_root=remote_root,
        expected_relative=PurePosixPath(trace_prefix_path.name),
        local_transport=isinstance(transport, FakeTransport),
    )
    fixed_argv.extend(
        [
            "--trace-prefix",
            str(staged_trace_prefix),
            "--trace-prefix-sha256",
            trace_prefix_sha256,
        ]
    )
    if isinstance(transport, FakeTransport):
        result = transport.run(fixed_argv)
    else:
        result = transport.run([*env_argv, *fixed_argv])
    if result.get("returncode") != 0:
        stderr_lines = str(result.get("stderr", "")).strip().splitlines()
        detail = stderr_lines[-1][:512] if stderr_lines else "NO_WORKER_STDERR"
        raise RuntimeError(f"EXECUTION_FAILED:{detail}")
    local_root = Path(
        prepared.manifest.get("local_results", prepared.path.parent / "local-results")
    ).resolve()
    _reject_symlink_chain(local_root)
    local_root.mkdir(parents=True, exist_ok=True)
    local_result = local_root / prepared.manifest["run_id"]
    evidence_root = local_root / f"{prepared.manifest['run_id']}.receipts"
    evidence_partial = local_root / f".{prepared.manifest['run_id']}.receipts.partial"
    if any(
        candidate.exists() or candidate.is_symlink()
        for candidate in (local_result, evidence_root, evidence_partial)
    ):
        raise ValueError("IMMUTABLE_RECEIPT_EXISTS")
    evidence_partial.mkdir(parents=False, exist_ok=False)
    _fsync_dir(local_root)
    if not hasattr(transport, "download_file"):
        raise RuntimeError("REMOTE_RECEIPT_DOWNLOAD_UNSUPPORTED")
    remote_receipt_path = remote_root / (
        f"{prepared.manifest['run_id']}.REMOTE_EXECUTION_RECEIPT.json"
    )
    local_remote_receipt = evidence_partial / "REMOTE_EXECUTION_RECEIPT.json"
    transport.download_file(
        remote_path=remote_receipt_path,
        local_path=local_remote_receipt,
    )
    remote = _load_remote_receipt(result, local_remote_receipt)
    validate_remote_receipt(remote)
    require_remote_scorer_ready_for_final(remote)
    # Bind the validated bytes to the exact content-addressed run root and
    # run identity requested by the controller.  A valid receipt from another
    # run is not an acceptable surrogate for this execution.
    if remote.get("run_id") != prepared.manifest["run_id"]:
        raise ValueError("REMOTE_RECEIPT_BINDING_MISMATCH:run_id")
    if remote.get("remote_run_root") != str(remote_root):
        raise ValueError("REMOTE_RECEIPT_BINDING_MISMATCH:remote_run_root")
    if remote.get("approved_remote_parent") != str(approved_remote_parent):
        raise ValueError("REMOTE_RECEIPT_BINDING_MISMATCH:approved_remote_parent")
    reopen_validate_remote_receipt(
        local_remote_receipt,
        expected_hash=sha256_hex(canonical_bytes(remote)),
    )
    remote_receipt_hash = sha256_hex(canonical_bytes(remote))
    remote_release_path = remote_root / (
        f"{prepared.manifest['run_id']}.LOCK_RELEASE_PROOF.json"
    )
    local_release_proof = evidence_partial / "LOCK_RELEASE_PROOF.json"
    if not hasattr(transport, "download_evidence_file"):
        raise RuntimeError("LOCK_RELEASE_PROOF_DOWNLOAD_UNSUPPORTED")
    transport.download_evidence_file(
        remote_path=remote_release_path,
        local_path=local_release_proof,
    )
    if not local_release_proof.is_file() or local_release_proof.is_symlink():
        raise ValueError("LOCK_RELEASE_PROOF_INVALID")
    release_proof = json.loads(local_release_proof.read_text(encoding="utf-8"))
    release_body = {k: v for k, v in release_proof.items() if k != "self_hash"}
    if (
        release_proof.get("schema_version") != "r005-lock-release-proof.v1"
        or release_proof.get("run_id") != prepared.manifest["run_id"]
        or release_proof.get("authoritative_remote_receipt_sha256")
        != remote_receipt_hash
        or release_proof.get("self_hash") != sha256_hex(canonical_bytes(release_body))
    ):
        raise ValueError("LOCK_RELEASE_PROOF_INVALID")
    for field, expected in {
        "run_id": prepared.manifest["run_id"],
        "execution_manifest_sha256": prepared.manifest_sha256,
        "prepared_manifest_sha256": prepared_sha256,
        "controller_nonce": prepared.manifest["controller_nonce"],
        "formal_snapshot_sha256": prepared.manifest["formal_snapshot_sha256"],
        "preflight_evidence_sha256": prepared.manifest["preflight_evidence_sha256"],
        "runtime_format": prepared.manifest["runtime_format"],
        "runtime_path": prepared.manifest["runtime_path"],
        "runtime_file_sha256": prepared.manifest["runtime_file_sha256"],
        "runtime_source_sha256": prepared.manifest["runtime_source_sha256"],
        "runtime_manifest_sha256": prepared.manifest["runtime_manifest_sha256"],
        "runtime_dependency_profile": prepared.manifest["runtime_dependency_profile"],
    }.items():
        if remote.get(field) != expected:
            raise ValueError(f"REMOTE_RECEIPT_BINDING_MISMATCH:{field}")
    remote_trace_records = remote.get("lifecycle_trace_records")
    if not isinstance(remote_trace_records, list) or len(remote_trace_records) != 17:
        raise ValueError("REMOTE_TRACE_INCOMPLETE")
    release_record = release_proof.get("lifecycle_trace_record")
    if not isinstance(release_record, dict):
        raise ValueError("LOCK_RELEASE_PROOF_INVALID")
    remote_trace_records = [*remote_trace_records, release_record]
    validate_trace_prefix(
        remote_trace_records,
        run_id=prepared.manifest["run_id"],
        approved_remote_parent=str(approved_remote_parent),
        remote_run_root=str(remote_root),
    )
    if remote_trace_records[:11] != trace_recorder.records:
        raise ValueError("REMOTE_TRACE_PREFIX_MISMATCH")
    if remote.get("lifecycle_trace_head_sha256") != remote_trace_records[-2].get(
        "trace_hash"
    ):
        raise ValueError("REMOTE_TRACE_HEAD_MISMATCH")
    trace_recorder = LifecycleTraceRecorder.from_records(
        run_id=prepared.manifest["run_id"],
        approved_remote_parent=str(approved_remote_parent),
        remote_run_root=str(remote_root),
        records=remote_trace_records,
    )
    if isinstance(transport, FakeTransport):
        remote_result = Path(remote["result_path"]).resolve()
        _require_confined(remote_result, Path(remote_root))
    else:
        remote_result = PurePosixPath(str(remote["result_path"]))
        if not remote_result.is_absolute() or (
            remote_result != remote_root and remote_root not in remote_result.parents
        ):
            raise ValueError("remote result outside approved root")
    if not hasattr(transport, "download"):
        raise RuntimeError("DOWNLOAD_UNSUPPORTED")
    downloaded = transport.download(remote_path=remote_result, local_path=local_result)
    downloaded_path = Path(downloaded)
    if _is_reparse_point(downloaded_path) or (
        downloaded_path.is_dir()
        and any(_is_reparse_point(path) for path in downloaded_path.rglob("*"))
    ):
        raise ValueError("RESULT_COPY_REPARSE_REJECTED")
    if downloaded_path.is_dir() and downloaded_path.resolve() != local_result.resolve():
        _copy_tree(Path(downloaded), local_result)
    if (
        _is_reparse_point(local_result)
        or any(_is_reparse_point(path) for path in local_result.rglob("*"))
        or not local_result.is_dir()
    ):
        raise ValueError("RESULT_COPY_INCOMPLETE")
    try:
        durable_tree_sync(local_result)
    except RuntimeError as exc:
        raise RuntimeError("RESULT_COPY_DURABILITY_UNPROVEN") from exc
    local_hash = _tree_digest(result_tree_manifest(local_result))
    if local_hash != remote["remote_result_tree_sha256"]:
        raise ValueError("RESULT_COPY_INCOMPLETE")
    runtime_fields = {
        field: remote[field]
        for field in (
            "runtime_format",
            "runtime_path",
            "runtime_file_sha256",
            "runtime_source_sha256",
            "runtime_manifest_sha256",
            "runtime_dependency_profile",
        )
    }
    copy_body = {
        "schema_version": "copy-verification.v6",
        "run_id": prepared.manifest["run_id"],
        **runtime_fields,
        "prepared_manifest_sha256": prepared_sha256,
        "execution_manifest_sha256": prepared.manifest_sha256,
        "preflight_evidence_sha256": prepared.manifest["preflight_evidence_sha256"],
        "remote_receipt_hash": remote_receipt_hash,
        "remote_receipt_self_hash": remote["self_hash"],
        "remote_result_tree_sha256": remote["remote_result_tree_sha256"],
        "local_result_tree_sha256": local_hash,
        "equal_tree": True,
        "remote_result_path": str(remote_result),
        "local_result_path": str(local_result.resolve()),
        "verified_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "directory_durable": True,
    }
    copy_body.update(pinned_binding)
    copy_value = seal_receipt(copy_body)
    validate_copy_verification(
        copy_value, remote_receipt=remote, local_result_path=local_result
    )
    copy_hash = copy_value["self_hash"]
    copy_final = evidence_partial / "COPY_VERIFICATION.json"
    _publish_new_json(copy_final, copy_value)
    persisted_copy = json.loads(copy_final.read_text(encoding="utf-8"))
    if persisted_copy.get("self_hash") != copy_hash:
        raise RuntimeError("COPY_VERIFICATION_DURABILITY_UNPROVEN")
    trace_recorder.append(
        input_hashes={"remote_receipt": remote_receipt_hash},
        output_hashes={"local_copy": local_hash},
    )
    if _formal_snapshot() != formal_before:
        raise RuntimeError("FORMAL_SIDE_EFFECT_DETECTED")
    trace_recorder.append(
        input_hashes={"copy_verification": copy_hash},
        output_hashes={
            "final_receipt_body": _proof_hash(
                {
                    "execution_manifest_sha256": prepared.manifest_sha256,
                    "remote_receipt_hash": remote_receipt_hash,
                    "copy_verification_hash": copy_hash,
                }
            )
        },
    )
    lifecycle_trace = trace_recorder.seal()
    validate_trace(lifecycle_trace)
    lifecycle_trace_sha256 = sha256_hex(canonical_bytes(lifecycle_trace))
    final = seal_receipt(
        {
            "run_id": prepared.manifest["run_id"],
            "execution_manifest_sha256": prepared.manifest_sha256,
            "prepared_manifest_sha256": prepared_sha256,
            "controller_nonce": prepared.manifest["controller_nonce"],
            "formal_snapshot_sha256": prepared.manifest["formal_snapshot_sha256"],
            "preflight_evidence_sha256": prepared.manifest["preflight_evidence_sha256"],
            "runtime_format": prepared.manifest["runtime_format"],
            "runtime_path": prepared.manifest["runtime_path"],
            "runtime_file_sha256": prepared.manifest["runtime_file_sha256"],
            "runtime_source_sha256": prepared.manifest["runtime_source_sha256"],
            "runtime_manifest_sha256": prepared.manifest["runtime_manifest_sha256"],
            "runtime_dependency_profile": prepared.manifest[
                "runtime_dependency_profile"
            ],
            "terminal_state": "SUCCEEDED",
            "remote_result_tree_sha256": remote["remote_result_tree_sha256"],
            "local_result_tree_sha256": local_hash,
            "remote_receipt_hash": remote_receipt_hash,
            "copy_verification_hash": copy_hash,
            "local_result_path": str(local_result.resolve()),
            "directory_durable": True,
            "formal_side_effect_recheck": True,
            "copy_verification": copy_value,
            "lifecycle_trace": lifecycle_trace,
            "lifecycle_trace_sha256": lifecycle_trace_sha256,
            **pinned_binding,
        }
    )
    validate_final_receipt(final)
    final_receipt_name = "FINAL_RUN_RECEIPT.json"
    final_publication_hash = _publish_new_json(
        evidence_partial / final_receipt_name, final
    )
    reopen_validate_final_receipt(
        evidence_partial / final_receipt_name,
        expected_hash=final_publication_hash,
    )
    # Fresh end-to-end verification of the exact receipt tree before publish.
    verify_final_receipt(
        evidence_partial / final_receipt_name,
        local_copy=local_result,
    )
    durable_tree_sync(evidence_partial)
    _rename_dir_new(evidence_partial, evidence_root)
    durable_tree_sync(evidence_root)
    persisted_final = reopen_validate_final_receipt(
        evidence_root / final_receipt_name,
        expected_hash=final_publication_hash,
    )
    return dict(persisted_final)


def verify_remote_receipt(receipt_path: str | Path) -> dict[str, Any]:
    path = Path(receipt_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("REMOTE_RECEIPT_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_remote_receipt(value)
    return dict(value)


def bind_downloaded_result(
    prepared: PreparedResearchRun,
    *,
    remote_receipt_path: str | Path,
    lock_release_proof_path: str | Path,
    local_result: str | Path,
    evidence_root: str | Path,
) -> dict[str, Any]:
    """Bind a controller-side download to an already sealed remote receipt.

    This is the recovery/hand-off path for a result sealed by another process:
    the controller reopens the authoritative receipt, hashes the downloaded
    tree, and seals fresh controller-owned COPY_VERIFICATION and FINAL receipts.
    The lock-release proof is independently reopened and supplies the only
    accepted step-18 record; steps 19-20 are appended by this controller.
    """
    receipt_path = Path(remote_receipt_path)
    remote = reopen_validate_remote_receipt(receipt_path)
    require_remote_scorer_ready_for_final(remote)
    remote_hash = sha256_hex(canonical_bytes(remote))
    proof_path = Path(lock_release_proof_path)
    if not proof_path.is_file() or proof_path.is_symlink():
        raise ValueError("LOCK_RELEASE_PROOF_INVALID")
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("LOCK_RELEASE_PROOF_INVALID") from exc
    proof_body = {k: v for k, v in proof.items() if k != "self_hash"}
    if (
        proof.get("schema_version") != "r005-lock-release-proof.v1"
        or proof.get("run_id") != remote.get("run_id")
        or proof.get("authoritative_remote_receipt_sha256") != remote_hash
        or proof.get("self_hash") != sha256_hex(canonical_bytes(proof_body))
    ):
        raise ValueError("LOCK_RELEASE_PROOF_INVALID")
    release_record = proof.get("lifecycle_trace_record")
    remote_trace_records = remote.get("lifecycle_trace_records")
    if not isinstance(remote_trace_records, list) or len(remote_trace_records) != 17:
        raise ValueError("REMOTE_TRACE_INCOMPLETE")
    if (
        not isinstance(release_record, dict)
        or release_record.get("step_id") != 18
        or release_record.get("run_id") != remote.get("run_id")
        or release_record.get("previous_trace_hash")
        != remote_trace_records[-1].get("trace_hash")
    ):
        raise ValueError("LOCK_RELEASE_PROOF_INVALID")
    remote_trace_records = [*remote_trace_records, release_record]
    run_id = prepared.manifest["run_id"]
    if remote.get("run_id") != run_id:
        raise ValueError("REMOTE_RECEIPT_BINDING_MISMATCH:run_id")
    for field in (
        "execution_manifest_sha256",
        "prepared_manifest_sha256",
        "preflight_evidence_sha256",
        "runtime_format",
        "runtime_path",
        "runtime_file_sha256",
        "runtime_source_sha256",
        "runtime_manifest_sha256",
        "runtime_dependency_profile",
    ):
        expected = prepared.manifest.get(field)
        if expected is not None and remote.get(field) != expected:
            raise ValueError(f"REMOTE_RECEIPT_BINDING_MISMATCH:{field}")
    result_path = Path(local_result).resolve()
    _reject_symlink_chain(result_path)
    if (
        _is_reparse_point(result_path)
        or not result_path.is_dir()
        or any(_is_reparse_point(path) for path in result_path.rglob("*"))
    ):
        raise ValueError("RESULT_COPY_INCOMPLETE")
    try:
        durable_tree_sync(result_path)
    except RuntimeError as exc:
        raise RuntimeError("RESULT_COPY_DURABILITY_UNPROVEN") from exc
    local_hash = _tree_digest(result_tree_manifest(result_path))
    if local_hash != remote.get("remote_result_tree_sha256"):
        raise ValueError("RESULT_COPY_INCOMPLETE")
    remote_root = str(remote.get("remote_run_root", ""))
    approved_parent = str(remote.get("approved_remote_parent", ""))
    trace_recorder = LifecycleTraceRecorder.from_records(
        run_id=run_id,
        approved_remote_parent=approved_parent,
        remote_run_root=remote_root,
        records=remote_trace_records,
    )
    result_ref = str(remote.get("result_path", ""))
    if remote_root.startswith("/"):
        root_ref = PurePosixPath(remote_root)
        result_ref_path = PurePosixPath(result_ref)
        if (
            not result_ref_path.is_absolute()
            or ".." in result_ref_path.parts
            or result_ref_path != root_ref / f"{run_id}.remote-result"
        ):
            raise ValueError("REMOTE_RESULT_PATH_INVALID")
    else:
        root_ref = Path(remote_root).resolve()
        result_ref_path = Path(result_ref).resolve()
        if (
            result_ref_path.name != f"{run_id}.remote-result"
            or root_ref not in result_ref_path.parents
            or len(result_ref_path.relative_to(root_ref).parts) != 1
        ):
            raise ValueError("REMOTE_RESULT_PATH_INVALID")
    formal_before = _formal_snapshot_sha256()
    expected_formal = prepared.manifest.get("formal_snapshot_sha256")
    if expected_formal is not None and formal_before != expected_formal:
        raise ValueError("FORMAL_SNAPSHOT_DRIFT")
    pinned_binding = pinned_runtime_binding(prepared.manifest)
    runtime_fields = {
        field: remote[field]
        for field in (
            "runtime_format",
            "runtime_path",
            "runtime_file_sha256",
            "runtime_source_sha256",
            "runtime_manifest_sha256",
            "runtime_dependency_profile",
        )
    }
    copy_body = {
        "schema_version": "copy-verification.v6",
        "run_id": run_id,
        **runtime_fields,
        "prepared_manifest_sha256": remote["prepared_manifest_sha256"],
        "execution_manifest_sha256": remote["execution_manifest_sha256"],
        "preflight_evidence_sha256": remote["preflight_evidence_sha256"],
        "remote_receipt_hash": remote_hash,
        "remote_receipt_self_hash": remote["self_hash"],
        "remote_result_tree_sha256": remote["remote_result_tree_sha256"],
        "local_result_tree_sha256": local_hash,
        "equal_tree": True,
        "remote_result_path": result_ref,
        "local_result_path": str(result_path),
        "verified_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "directory_durable": True,
    }
    copy_body.update(pinned_binding)
    copy_value = seal_receipt(copy_body)
    validate_copy_verification(
        copy_value, remote_receipt=remote, local_result_path=result_path
    )
    destination = Path(evidence_root)
    if destination.exists() or destination.is_symlink():
        raise ValueError("IMMUTABLE_RECEIPT_EXISTS")
    staging = destination.parent / f".{destination.name}.partial"
    if staging.exists():
        raise ValueError("IMMUTABLE_RECEIPT_EXISTS")
    staging.mkdir(parents=True)
    _publish_new_json(staging / "REMOTE_EXECUTION_RECEIPT.json", remote)
    _publish_new_json(staging / "LOCK_RELEASE_PROOF.json", proof)
    _publish_new_json(staging / "COPY_VERIFICATION.json", copy_value)
    copy_hash = copy_value["self_hash"]
    trace_recorder.append(
        input_hashes={"remote_receipt": remote_hash},
        output_hashes={"local_copy": local_hash},
    )
    if _formal_snapshot_sha256() != formal_before:
        raise ValueError("FORMAL_SIDE_EFFECT_DETECTED")
    trace_recorder.append(
        input_hashes={"copy_verification": copy_hash},
        output_hashes={
            "final_receipt_body": _proof_hash(
                {
                    "execution_manifest_sha256": prepared.manifest_sha256,
                    "remote_receipt_hash": remote_hash,
                    "copy_verification_hash": copy_hash,
                }
            )
        },
    )
    lifecycle_trace = trace_recorder.seal()
    lifecycle_trace_sha256 = sha256_hex(canonical_bytes(lifecycle_trace))
    final = seal_receipt(
        {
            "run_id": run_id,
            "execution_manifest_sha256": remote["execution_manifest_sha256"],
            "prepared_manifest_sha256": remote["prepared_manifest_sha256"],
            "controller_nonce": prepared.manifest["controller_nonce"],
            "formal_snapshot_sha256": prepared.manifest["formal_snapshot_sha256"],
            "preflight_evidence_sha256": remote["preflight_evidence_sha256"],
            **runtime_fields,
            "terminal_state": "SUCCEEDED",
            "remote_result_tree_sha256": remote["remote_result_tree_sha256"],
            "local_result_tree_sha256": local_hash,
            "remote_receipt_hash": remote_hash,
            "copy_verification_hash": copy_hash,
            "local_result_path": str(result_path),
            "directory_durable": True,
            "formal_side_effect_recheck": _formal_snapshot_sha256() == formal_before,
            "copy_verification": copy_value,
            "lifecycle_trace": lifecycle_trace,
            "lifecycle_trace_sha256": lifecycle_trace_sha256,
            **pinned_binding,
        }
    )
    validate_final_receipt(final)
    publication_hash = _publish_new_json(staging / "FINAL_RUN_RECEIPT.json", final)
    reopen_validate_final_receipt(
        staging / "FINAL_RUN_RECEIPT.json", expected_hash=publication_hash
    )
    verify_final_receipt(staging / "FINAL_RUN_RECEIPT.json", local_copy=result_path)
    durable_tree_sync(staging)
    _rename_dir_new(staging, destination)
    durable_tree_sync(destination)
    return reopen_validate_final_receipt(
        destination / "FINAL_RUN_RECEIPT.json", expected_hash=publication_hash
    )


def verify_final_receipt(
    receipt_path: str | Path, *, local_copy: str | Path
) -> dict[str, Any]:
    value = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    validate_final_receipt(value)
    copy_path = Path(receipt_path).resolve().parent / "COPY_VERIFICATION.json"
    if not copy_path.is_file() or copy_path.is_symlink():
        raise ValueError("COPY_VERIFICATION_MISSING")
    copy_value = json.loads(copy_path.read_text(encoding="utf-8"))
    if copy_value.get("self_hash") != value.get("copy_verification_hash"):
        raise ValueError("COPY_VERIFICATION_HASH_MISMATCH")
    remote_path = Path(receipt_path).resolve().parent / "REMOTE_EXECUTION_RECEIPT.json"
    if not remote_path.is_file() or remote_path.is_symlink():
        raise ValueError("REMOTE_RECEIPT_MISSING")
    remote_value = json.loads(remote_path.read_text(encoding="utf-8"))
    validate_remote_receipt(remote_value)
    remote_hash = sha256_hex(canonical_bytes(remote_value))
    if remote_hash != value.get("remote_receipt_hash"):
        raise ValueError("REMOTE_RECEIPT_HASH_MISMATCH")
    if copy_value.get("remote_receipt_hash") != remote_hash:
        raise ValueError("COPY_REMOTE_RECEIPT_HASH_MISMATCH")
    validate_copy_verification(copy_value, remote_receipt=remote_value)
    for field in (
        "execution_manifest_sha256",
        "prepared_manifest_sha256",
        "controller_nonce",
        "formal_snapshot_sha256",
        "preflight_evidence_sha256",
        "runtime_format",
        "runtime_path",
        "runtime_file_sha256",
        "runtime_source_sha256",
        "runtime_manifest_sha256",
        "runtime_dependency_profile",
    ):
        if remote_value.get(field) != value.get(field):
            raise ValueError(f"REMOTE_RECEIPT_BINDING_MISMATCH:{field}")
    local = Path(local_copy).resolve()
    recorded_local = Path(value.get("local_result_path", "")).resolve()
    if local != recorded_local:
        raise ValueError("LOCAL_RESULT_PATH_MISMATCH")
    if (
        not local.is_dir()
        or _is_reparse_point(local)
        or any(_is_reparse_point(path) for path in local.rglob("*"))
    ):
        raise ValueError("RESULT_COPY_INCOMPLETE")
    actual = _tree_digest(result_tree_manifest(local))
    if actual != value.get("local_result_tree_sha256"):
        raise ValueError("RESULT_COPY_INCOMPLETE")
    return {"valid": True, "terminal_state": value["terminal_state"]}


def release_stale_lock(root: str | Path, *, run_id: str, manifest_sha256: str) -> Path:
    from .lock import ResearchLock

    return ResearchLock.verified_tombstone(
        root, expected_manifest_hash=manifest_sha256, run_id=run_id
    )
