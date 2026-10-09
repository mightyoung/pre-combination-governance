from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from rfb.contracts.canonical_json import canonical_bytes
from rfb.research.runtime_bundle import (
    _MAIN_SOURCE,
    RuntimeBundleError,
    build_runtime_bundle,
    runtime_bytes,
    shared_source_inventory,
)
from rfb.research.trace import LifecycleTraceRecorder
from rfb.research.models import CLASSIFICATION as SHARED_CLASSIFICATION
from rfb.research.models import validate_classification
from rfb.research.files import publish_json_new
from rfb.research.receipts import scan_closed_result as shared_scan_closed_result
from rfb.research.trace import validate_trace_prefix, TraceValidationError
from rfb.research.adapters import capacity_state, SUBBUDGETS


def _embedded_namespace() -> dict:
    namespace = {"__name__": "embedded_runtime_test"}
    exec(_MAIN_SOURCE, namespace)
    return namespace


def _embedded_worker_case(tmp_path: Path):
    namespace = _embedded_namespace()
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "embedded"
    root.mkdir()
    bundle = build_runtime_bundle("tep_fixture", root / ".runtime")
    runtime = {
        "runtime_format": bundle.format,
        "runtime_path": str(bundle.path.resolve()),
        "runtime_file_sha256": bundle.file_sha256,
        "runtime_source_sha256": bundle.source_sha256,
        "runtime_manifest_sha256": bundle.manifest_sha256,
        "runtime_dependency_profile": "stdlib_only",
    }
    probe_args = SimpleNamespace(
        manifest_sha256="a" * 64,
        controller_nonce="c" * 32,
        formal_snapshot_sha256="d" * 64,
        runtime_file_sha256=bundle.file_sha256,
        runtime_source_sha256=bundle.source_sha256,
        runtime_manifest_sha256=bundle.manifest_sha256,
        runtime_dependency_profile="stdlib_only",
        runtime_path=str(bundle.path),
        dataset_root=None,
        fixture_only=True,
        fake_available_bytes=300_000_000_000,
    )
    preflight = namespace["collect_probe"](root, probe_args)
    manifest = {
        "run_id": "embedded",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
        "approved_remote_parent": str(parent.resolve()),
        "remote_run_root": str(root.resolve()),
        "prepared_manifest_sha256": "a" * 64,
        "preflight_evidence_sha256": namespace["digest"](preflight),
        "controller_nonce": "c" * 32,
        "formal_snapshot_sha256": "d" * 64,
        "preflight_evidence": preflight,
        "resource_limits": namespace["CAPACITY_CONTRACT"],
        **runtime,
    }
    manifest_path = root / ".embedded.execution.manifest.json"
    manifest_path.write_bytes(namespace["canonical"](manifest))
    manifest_sha256 = namespace["file_digest"](manifest_path)
    recorder = LifecycleTraceRecorder(
        run_id="embedded",
        approved_remote_parent=str(parent.resolve()),
        remote_run_root=str(root.resolve()),
    )
    for step in range(11):
        recorder.append(
            input_hashes={
                f"input_{step}": hashlib.sha256(f"i{step}".encode()).hexdigest()
            },
            output_hashes={
                f"output_{step}": hashlib.sha256(f"o{step}".encode()).hexdigest()
            },
        )
    trace_prefix = {
        "schema_version": "1.0.0-prefix",
        "run_id": "embedded",
        "approved_remote_parent": str(parent.resolve()),
        "remote_run_root": str(root.resolve()),
        "execution_manifest_sha256": manifest_sha256,
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "records": recorder.records,
        "trace_head_sha256": recorder.records[-1]["trace_hash"],
    }
    trace_prefix_path = root / ".embedded.trace-prefix.json"
    trace_prefix_path.write_bytes(namespace["canonical"](trace_prefix))
    args = SimpleNamespace(
        manifest=str(manifest_path),
        execution_manifest_sha256=manifest_sha256,
        runtime_file_sha256=bundle.file_sha256,
        runtime_source_sha256=bundle.source_sha256,
        runtime_manifest_sha256=bundle.manifest_sha256,
        runtime_dependency_profile="stdlib_only",
        runtime_path=str(bundle.path),
        manifest_sha256="a" * 64,
        controller_nonce="c" * 32,
        formal_snapshot_sha256="d" * 64,
        dataset_root=None,
        fixture_only=True,
        trace_prefix=str(trace_prefix_path),
        trace_prefix_sha256=hashlib.sha256(trace_prefix_path.read_bytes()).hexdigest(),
        fake_available_bytes=300_000_000_000,
    )
    return namespace, root, args


def test_tep_fixture_runtime_is_deterministic_and_content_addressed(tmp_path: Path):
    first = build_runtime_bundle("tep_fixture", tmp_path / "first")
    second = build_runtime_bundle("tep_fixture", tmp_path / "second")

    assert (
        first.path.read_bytes()
        == second.path.read_bytes()
        == runtime_bytes("tep_fixture")
    )
    assert first.file_sha256 == second.file_sha256
    assert first.source_sha256 == second.source_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.path.name == f"{first.file_sha256}.pyz"
    assert hashlib.sha256(first.path.read_bytes()).hexdigest() == first.file_sha256

    with zipfile.ZipFile(first.path) as archive:
        assert archive.namelist() == ["__main__.py"]
        info = archive.getinfo("__main__.py")
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert hashlib.sha256(archive.read(info)).hexdigest() == first.source_sha256


def test_runtime_manifest_binds_source_file_and_own_unsigned_hash(tmp_path: Path):
    bundle = build_runtime_bundle("tep_fixture", tmp_path)
    persisted = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))

    assert persisted == bundle.manifest
    unsigned = {k: v for k, v in persisted.items() if k != "manifest_sha256"}
    assert (
        hashlib.sha256(canonical_bytes(unsigned)).hexdigest() == bundle.manifest_sha256
    )
    assert persisted["source_sha256"] == bundle.source_sha256
    assert persisted["file_sha256"] == bundle.file_sha256

    repeated = build_runtime_bundle("tep_fixture", tmp_path)
    assert repeated == bundle


def test_runtime_zipapp_starts_without_site_or_installed_rfb(tmp_path: Path):
    bundle = build_runtime_bundle("tep_fixture", tmp_path)
    proc = subprocess.run(
        [sys.executable, "-I", "-S", str(bundle.path), "--help"],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "preflight" in proc.stdout and "worker" in proc.stdout


@pytest.mark.parametrize(
    "adapter_id", ["tep_nonconfirmatory_v1", "local_fixture_nonconfirmatory", "unknown"]
)
def test_runtime_rejects_unclosed_dependency_surfaces(tmp_path: Path, adapter_id: str):
    with pytest.raises(
        RuntimeBundleError,
        match=f"RUNTIME_DEPENDENCY_CLOSURE_UNAVAILABLE:{adapter_id}",
    ):
        build_runtime_bundle(adapter_id, tmp_path)


@pytest.mark.parametrize("force_failure", [False, True])
def test_embedded_worker_publishes_receipt_before_lock_release(
    tmp_path: Path, force_failure: bool
):
    namespace, root, args = _embedded_worker_case(tmp_path)
    receipt_path = root / "embedded.REMOTE_EXECUTION_RECEIPT.json"
    original_release = namespace["release_lock"]
    observed = []

    def checked_release(lock):
        observed.append(receipt_path.is_file())
        return original_release(lock)

    namespace["release_lock"] = checked_release
    if force_failure:
        namespace["scan_closed_result"] = lambda _: (_ for _ in ()).throw(
            ValueError("forced closed-result failure")
        )
        with pytest.raises(ValueError, match="forced closed-result failure"):
            namespace["worker"](args)
    else:
        namespace["worker"](args)

    assert observed == [True]
    assert not (root / ".embedded.REMOTE_EXECUTION_RECEIPT.json.pre-release").exists()
    if force_failure:
        assert not (root / "embedded.LOCK_RELEASE_PROOF.json").exists()
    else:
        assert (root / "embedded.LOCK_RELEASE_PROOF.json").is_file()
    assert not (root.parent / ".rfb-research-run.lock").exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["terminal_state"] == (
        "FAILED" if force_failure else "RESULT_SEALED_REMOTE"
    )


def test_embedded_lock_collision_preserves_existing_owner(tmp_path: Path):
    namespace = _embedded_namespace()
    root = tmp_path / "root"
    root.mkdir()
    lock = namespace["acquire_lock"](root, root / "first", "first", "a" * 64, "c" * 32)
    lock_path = lock["path"]
    owner = lock_path.read_bytes()

    with pytest.raises(ValueError, match="LOCK_BUSY"):
        namespace["acquire_lock"](root, root / "second", "second", "b" * 64, "d" * 32)

    assert lock_path.read_bytes() == owner
    namespace["release_lock"](lock)


def test_embedded_directory_fsync_failure_cannot_claim_success(tmp_path: Path):
    namespace, root, args = _embedded_worker_case(tmp_path)
    namespace["_fsync"] = lambda _: (_ for _ in ()).throw(
        RuntimeError("forced durability failure")
    )

    with pytest.raises(RuntimeError, match="forced durability failure"):
        namespace["worker"](args)

    assert not (root / "embedded.REMOTE_EXECUTION_RECEIPT.json").exists()
    assert not (root / "embedded.remote-result").exists()


def test_embedded_probe_reflects_actual_root_mount_and_filesystem(tmp_path: Path):
    namespace, root, args = _embedded_worker_case(tmp_path)
    args.manifest_sha256 = "a" * 64
    args.controller_nonce = "c" * 32
    args.formal_snapshot_sha256 = "d" * 64
    args.dataset_root = None
    args.fixture_only = True
    probe = namespace["collect_probe"](root, args)

    assert probe["root"] == str(root.resolve())
    assert f"device={root.stat().st_dev}" in probe["mount_identity"]
    assert (
        probe["filesystem_total_bytes"] == __import__("shutil").disk_usage(root).total
    )
    assert probe["hostname"]
    assert len(probe["owned_process_snapshot_sha256"]) == 64


def test_embedded_success_receipt_rejects_incomplete_runtime_binding(tmp_path: Path):
    namespace, root, args = _embedded_worker_case(tmp_path)
    namespace["worker"](args)
    receipt_path = root / "embedded.REMOTE_EXECUTION_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    body = {k: v for k, v in receipt.items() if k != "self_hash"}
    body.pop("runtime_source_sha256")
    incomplete = namespace["seal_receipt"](body)

    with pytest.raises(ValueError, match="RECEIPT_RUNTIME_BINDING_MISSING"):
        namespace["validate_receipt"](incomplete)


def test_runtime_parity_inventory_is_source_hashed_and_behavioral():
    inventory = json.loads(
        (
            Path(__file__).parents[1]
            / "src"
            / "rfb"
            / "contracts"
            / "research_runtime_parity_inventory.json"
        ).read_text(encoding="utf-8")
    )
    required = {
        "models",
        "events",
        "lock",
        "probes",
        "classification",
        "result",
        "receipt",
        "publication",
        "capacity",
    }
    assert set(inventory["components"]) == required
    assert inventory["schema_version"] == "r005-runtime-parity.v2"
    observed = shared_source_inventory()
    assert set(observed) == required
    for component, contract in inventory["components"].items():
        path = Path(__file__).parents[1] / contract["shared_source_file"]
        assert observed[component] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert contract["behavior_vectors"]
    bundle = build_runtime_bundle(
        "tep_fixture", Path(__file__).parent / ".runtime-parity"
    )
    with zipfile.ZipFile(bundle.path) as archive:
        source = archive.read("__main__.py").decode("utf-8")
    assert canonical_bytes(observed).decode("utf-8") in source
    assert bundle.shared_source_inventory == observed


def test_shared_source_drift_changes_runtime_source_hash(tmp_path: Path, monkeypatch):
    before = build_runtime_bundle("tep_fixture", tmp_path / "before")
    original = shared_source_inventory()
    mutated = {**original, "capacity": "f" * 64}
    monkeypatch.setattr(
        "rfb.research.runtime_bundle.shared_source_inventory", lambda: mutated
    )
    after = build_runtime_bundle("tep_fixture", tmp_path / "after")
    assert after.source_sha256 != before.source_sha256
    assert after.file_sha256 != before.file_sha256
    assert after.manifest_sha256 != before.manifest_sha256


def test_embedded_behavioral_classification_parity_and_negative_mismatch():
    namespace = _embedded_namespace()
    assert namespace["CLASSIFICATION"] == SHARED_CLASSIFICATION
    validate_classification(SHARED_CLASSIFICATION)
    mutated = {**namespace["CLASSIFICATION"], "formal_gate_effect": "PASS"}
    with pytest.raises(ValueError, match="immutable classification mismatch"):
        validate_classification(mutated)
    manifest = {
        **mutated,
        "adapter_id": "tep_fixture",
        "resource_limits": namespace["CAPACITY_CONTRACT"],
    }
    with pytest.raises(ValueError, match="CLASSIFICATION_MISMATCH"):
        namespace["validate_execution_manifest"](
            manifest,
            SimpleNamespace(
                manifest_sha256="a" * 64,
                controller_nonce="c" * 32,
                formal_snapshot_sha256="d" * 64,
                runtime_file_sha256="e" * 64,
                runtime_source_sha256="f" * 64,
                runtime_manifest_sha256="1" * 64,
                runtime_dependency_profile="stdlib_only",
            ),
            Path("runtime.pyz"),
        )


def test_real_embedded_probe_freshness_positive_and_negative(tmp_path: Path):
    embedded, root, args = _embedded_worker_case(tmp_path)
    fresh = embedded["collect_probe"](root, args)
    embedded["validate_probe_freshness"](fresh, 300)
    stale = {**fresh, "collected_at_utc": "2000-01-01T00:00:00Z"}
    with pytest.raises(ValueError, match="PREFLIGHT_STALE:wall_clock"):
        embedded["validate_probe_freshness"](stale, 300)


def test_embedded_nfs_atomic_rename_fallback_is_lock_scoped(tmp_path: Path):
    import ctypes as real_ctypes
    import os as real_os

    embedded = _embedded_namespace()
    source = tmp_path / "partial"
    destination = tmp_path / "sealed"
    source.mkdir()
    (source / "result.json").write_text("{}", encoding="utf-8")

    class FakeRenameAt2:
        argtypes = None
        restype = None

        def __call__(self, *_args):
            real_ctypes.set_errno(22)
            return -1

    class FakeLibc:
        renameat2 = FakeRenameAt2()

    class FakeCtypes:
        c_int = real_ctypes.c_int
        c_char_p = real_ctypes.c_char_p
        c_uint = real_ctypes.c_uint

        @staticmethod
        def CDLL(*_args, **_kwargs):
            return FakeLibc()

        get_errno = staticmethod(real_ctypes.get_errno)

    class PosixOsProxy:
        name = "posix"
        fsencode = staticmethod(real_os.fsencode)
        rename = staticmethod(real_os.rename)
        strerror = staticmethod(real_os.strerror)

    embedded["ctypes"] = FakeCtypes
    embedded["os"] = PosixOsProxy
    embedded["rename_dir_new"](source, destination)
    assert not source.exists()
    assert (destination / "result.json").is_file()


def test_embedded_recheck_records_dynamic_processes_without_false_drift(
    tmp_path: Path,
):
    embedded, root, args = _embedded_worker_case(tmp_path)
    before = embedded["collect_probe"](root, args)
    after = {
        **before,
        "monotonic_ns": before["monotonic_ns"] + 1,
        "foreign_process_snapshot_sha256": "a" * 64,
        "gpu_process_snapshot_sha256": "b" * 64,
    }
    embedded["validate_probe_freshness"](after, 300, previous=before)
    with pytest.raises(ValueError, match="PREFLIGHT_DRIFT:source_tree_sha256"):
        embedded["validate_probe_freshness"](
            {**after, "source_tree_sha256": "c" * 64},
            300,
            previous=before,
        )


def test_real_shared_and_embedded_publication_and_closed_result_paths(tmp_path: Path):
    embedded = _embedded_namespace()
    shared_path = tmp_path / "shared.json"
    embedded_path = tmp_path / "embedded.json"
    publish_json_new(shared_path, {"v": 1})
    embedded["publish_new"](embedded_path, {"v": 1})
    for call, path in (
        (lambda: publish_json_new(shared_path, {"v": 2}), shared_path),
        (lambda: embedded["publish_new"](embedded_path, {"v": 2}), embedded_path),
    ):
        with pytest.raises((ValueError, FileExistsError)):
            call()
        assert json.loads(path.read_text(encoding="utf-8")) == {"v": 1}
    closed = tmp_path / "closed"
    closed.mkdir()
    (closed / "adapter_result.json").write_text("{}", encoding="utf-8")
    shared_scan_closed_result(closed)
    embedded["scan_closed_result"](closed)
    (closed / "raw.bin").write_bytes(b"raw")
    shared_error = embedded_error = None
    try:
        shared_scan_closed_result(closed)
    except ValueError as exc:
        shared_error = str(exc)
    try:
        embedded["scan_closed_result"](closed)
    except ValueError as exc:
        embedded_error = str(exc)
    assert shared_error == embedded_error


def _shared_capacity(peak: int, *, borrow: bool = False) -> dict:
    telemetry = {
        "project_tree_allocated_bytes": peak,
        "filesystem_used_delta_bytes": 0,
        "owned_external_layers_bytes": 0,
        "open_deleted_bytes": 0,
        "observed_peak_bytes": peak,
    }
    return {
        "planned_bytes": 22_000_000_000,
        "drain_bytes": 24_000_000_000,
        **{
            **SUBBUDGETS,
            "dataset": 16_000_000_001 if borrow else SUBBUDGETS["dataset"],
        },
        "telemetry": telemetry,
    }


@pytest.mark.parametrize(
    "peak",
    [21_999_999_999, 22_000_000_000, 22_000_000_001, 24_000_000_000, 25_000_000_001],
)
def test_real_shared_and_embedded_capacity_paths(tmp_path: Path, peak: int):
    embedded, root, args = _embedded_worker_case(tmp_path)
    args.owned_external_layers_bytes = peak
    probe = embedded["collect_probe"](root, args)
    shared_result = embedded_result = None
    try:
        shared_result = capacity_state(_shared_capacity(peak))
    except ValueError as exc:
        shared_result = str(exc)
    try:
        embedded["validate_probe_freshness"](probe, 300)
        embedded_result = probe["capacity_state"]
    except ValueError as exc:
        embedded_result = str(exc)
    assert embedded_result == shared_result


def test_real_shared_and_embedded_trace_prefix_paths(tmp_path: Path):
    embedded, _root, args = _embedded_worker_case(tmp_path)
    prefix = json.loads(Path(args.trace_prefix).read_text(encoding="utf-8"))
    records = prefix["records"]
    validate_trace_prefix(
        records,
        run_id=prefix["run_id"],
        approved_remote_parent=prefix["approved_remote_parent"],
        remote_run_root=prefix["remote_run_root"],
    )
    embedded["load_trace_prefix"](args)
    shared_error = embedded_error = None
    try:
        validate_trace_prefix(
            records,
            run_id="wrong",
            approved_remote_parent=prefix["approved_remote_parent"],
            remote_run_root=prefix["remote_run_root"],
        )
    except TraceValidationError as exc:
        shared_error = str(exc)
    args.run_id = "wrong"
    try:
        embedded["load_trace_prefix"](args)
    except ValueError as exc:
        embedded_error = str(exc)
    assert shared_error == embedded_error == "run_id mismatch"


@pytest.mark.parametrize(
    ("peak", "expected"),
    [
        (21_999_999_999, "PLANNED"),
        (22_000_000_000, "PLANNED"),
        (22_000_000_001, "PLANNED_CAP_EXCEEDED"),
        (23_999_999_999, "PLANNED_CAP_EXCEEDED"),
        (24_000_000_000, "DRAIN_AND_SEAL"),
        (24_999_999_999, "DRAIN_AND_SEAL"),
        (25_000_000_000, "DRAIN_AND_SEAL"),
        (25_000_000_001, "SAFE_HALT_CAP_BREACH"),
    ],
)
def test_embedded_capacity_boundary_vectors(tmp_path: Path, peak: int, expected: str):
    namespace, root, args = _embedded_worker_case(tmp_path)
    args.owned_external_layers_bytes = peak
    probe = namespace["collect_probe"](root, args)
    assert probe["capacity_peak_bytes"] >= peak
    assert probe["capacity_state"] == expected


def test_embedded_capacity_subbudget_is_non_borrowable(tmp_path: Path):
    namespace, root, args = _embedded_worker_case(tmp_path)
    dataset = root / "dataset"
    dataset.mkdir()
    args.dataset_root = str(dataset)
    args.fake_capacity_buckets = {
        "ephemeral_dataset": 16_000_000_001,
        "durable_result_staging": 0,
        "scratch_partial": 0,
        "retry_quarantine_wal": 0,
        "emergency_reserve": 0,
    }
    probe = namespace["collect_probe"](root, args)
    assert probe["capacity_peak_bytes"] < 22_000_000_000
    assert probe["capacity_state"] == "SUBBUDGET_BREACH"


def test_embedded_lock_requires_two_stale_observations_without_sleep(
    tmp_path: Path, monkeypatch
):
    namespace = _embedded_namespace()
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "run"
    root.mkdir()
    lock_path = parent / ".rfb-research-run.lock"
    stale = {
        "run_id": "old",
        "nonce": "old-nonce",
        "heartbeat_at": 0.0,
        "boot_id": namespace["boot_id"](),
        "pid": 999999,
        "start_ticks": "unknown",
        "process_group": 999999,
    }
    lock_path.write_bytes(namespace["canonical"](stale))
    monkeypatch.setenv("RFB_RESEARCH_FAKE_WALL_TIME", "1000")
    monkeypatch.setenv("RFB_RESEARCH_STALE_RECHECK_ADVANCE_SECONDS", "10")

    acquired = namespace["acquire_lock"](parent, root, "run", "a" * 64, "c" * 32)

    assert acquired["record"]["run_id"] == "run"
    assert list(parent.glob("*.tombstone"))
    namespace["release_lock"](acquired)


def test_embedded_lock_ttl_never_unlocks_live_identity(tmp_path: Path, monkeypatch):
    namespace = _embedded_namespace()
    namespace["process_alive"] = lambda record: True
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "run"
    root.mkdir()
    lock_path = parent / ".rfb-research-run.lock"
    live = {
        "run_id": "live",
        "nonce": "live-nonce",
        "heartbeat_at": 0.0,
        "boot_id": "live-boot",
        "pid": 12345,
        "start_ticks": "live-start",
        "process_group": 12345,
    }
    lock_path.write_bytes(namespace["canonical"](live))
    monkeypatch.setenv("RFB_RESEARCH_FAKE_WALL_TIME", "1000")
    monkeypatch.setenv("RFB_RESEARCH_STALE_RECHECK_ADVANCE_SECONDS", "10")

    with pytest.raises(ValueError, match="LOCK_STALE_CANDIDATE_OWNER_ALIVE"):
        namespace["acquire_lock"](parent, root, "run", "a" * 64, "c" * 32)
